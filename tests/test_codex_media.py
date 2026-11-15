"""Bounded Codex media, cost choices and no live provider calls."""
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from PIL import Image
from tools.ytbot import assets, codex_media, config
from tools.ytbot.accounts_store import private_directory, write_private


class CodexMediaContracts(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        scoped = patch.object(config, 'ROOT', self.root)
        scoped.start()
        self.addCleanup(scoped.stop)
        self.run = private_directory(self.root / 'run')
        channel = patch.object(config, 'CHANNEL', SimpleNamespace(slug='fallem-prince'))
        channel.start()
        self.addCleanup(channel.stop)
        theme = patch.object(config, 'THUMBNAIL_THEME', 'fallem_prince')
        theme.start()
        self.addCleanup(theme.stop)
        references = self.root/'assets/styles/fallem_prince'
        references.mkdir(parents=True)
        for index in (1,2):
            Image.new('RGB', (640,360), 'gray').save(references/f'reference-{index:02d}.jpg')
        (self.run / 'article.txt').write_text('The complete saved narrative. ' * 300)

    def fake_result(self, task, value):
        directory = private_directory(self.run / '.codex-media' / task)
        write_private(directory / 'state.json', {'state': 'complete', 'model': 'gpt-6.1-terra'})
        return value

    def test_cost_allowlist_and_scoped_cli_never_change_global_model_settings(self):
        codex_media.configure('gpt-6-luna')
        command = codex_media._command('/safe/codex', self.run, self.run/'schema', self.run/'result', images=True, model=codex_media.settings()['model'])
        self.assertEqual(command[command.index('--model')+1], 'gpt-6-luna')
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertIn('--ignore-user-config', command)
        self.assertEqual(command.count('--image'), 0)
        self.assertEqual(command[command.index('--sandbox')+1], 'read-only')
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', command)
        with self.assertRaises(ValueError):
            codex_media.configure('more-expensive-unapproved-model')
        self.assertEqual(codex_media.settings()['model'], 'gpt-6-luna')

    def test_completed_media_request_is_reused_without_another_model_call(self):
        def complete(command, **kwargs):
            output = Path(command[command.index('--output-last-message')+1])
            write_private(output, {'image_path': '/fixture/generated.png'})
            self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
            self.assertNotIn('ZATURO_WORKER_TOKEN', kwargs['env'])
            return subprocess.CompletedProcess(command, 0, stderr='')
        with patch.object(codex_media.shutil, 'which', return_value='/safe/codex'), patch.object(codex_media.subprocess, 'run', side_effect=complete) as launch, patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic', 'ZATURO_WORKER_TOKEN':'synthetic'}):
            first = codex_media._execute(self.run, 'thumbnail', 'fixed request', {}, images=True)
            second = codex_media._execute(self.run, 'thumbnail', 'fixed request', {}, images=True)
        self.assertEqual(first, second)
        launch.assert_called_once()

    def test_interrupted_generation_is_fenced_instead_of_silently_repeated(self):
        with patch.object(codex_media.shutil, 'which', return_value='/safe/codex'), patch.object(codex_media.subprocess, 'run', side_effect=subprocess.TimeoutExpired('codex', 900)) as launch:
            with self.assertRaises(subprocess.TimeoutExpired):
                codex_media._execute(self.run, 'thumbnail', 'fixed request', {}, images=True)
            with self.assertRaisesRegex(RuntimeError, 'fenced'):
                codex_media._execute(self.run, 'thumbnail', 'fixed request', {}, images=True)
        launch.assert_called_once()

    def test_metadata_preserves_channel_format_and_first_title_with_bounded_tags(self):
        value = {'title_options':['First Actual Title','Second Title','Third Title'], 'description':' '.join(['Narrative']*110), 'hashtags':['#mind','#identity','#thoughts','#philosophy','#psychology'], 'tags':['a long relevant tag '+str(i) for i in range(50)]}
        with patch.object(codex_media, '_execute', return_value=self.fake_result('metadata', value)) as execute:
            result = codex_media.generate_metadata(self.run, 'Exact topic')
        self.assertEqual(result['title'], 'First Actual Title')
        self.assertLessEqual(len(result['tags']), 425)
        self.assertIn('#mind #identity', result['description'])
        self.assertFalse(execute.call_args.kwargs['images'])
        self.assertIn((self.run/'article.txt').read_text(), execute.call_args.args[2])

    def test_thumbnail_cannot_read_an_arbitrary_returned_file_path(self):
        outside = self.root / 'private-owner-file'
        outside.write_text('must not be treated as an image')
        with patch.object(codex_media, '_execute', return_value={'image_path':str(outside)}):
            with self.assertRaises(ValueError):
                codex_media.generate_thumbnail(self.run)
        self.assertFalse((self.run/'thumbnail.png').exists())

    def test_generated_thumbnail_preserves_reference_engraving_tones(self):
        source = self.root/'.codex/generated_images/fixture.png'
        source.parent.mkdir(parents=True)
        image = Image.new('RGB', (640,360), 'white')
        image.paste('black', (0,0,320,360))
        image.paste((128,128,128), (250,0,390,360))
        image.save(source)
        with patch.object(codex_media.Path, 'home', return_value=self.root), patch.object(codex_media, '_execute', return_value=self.fake_result('thumbnail', {'image_path':str(source)})):
            destination = codex_media.generate_thumbnail(self.run)
        exported = Image.open(destination).convert('RGB')
        self.assertEqual(exported.size, (1280,720))
        colors = {color for _count,color in exported.getcolors(1280*720)}
        self.assertIn((128,128,128), colors)
        self.assertTrue(all(red == green == blue for red,green,blue in colors))
        self.assertTrue(source.exists())

    def test_installed_codex_routes_both_media_stages_without_opening_chatgpt(self):
        from unittest.mock import Mock
        context = Mock()
        with patch.object(codex_media, 'available', return_value=True), patch.object(codex_media, 'generate_metadata', return_value={'title':'Prepared'}) as metadata, patch.object(codex_media, 'generate_thumbnail', return_value=self.run/'thumbnail.png') as thumbnail:
            assets.generate_metadata(context, self.run, 'Topic')
            assets.generate_thumbnail(context, self.run)
        metadata.assert_called_once_with(self.run, 'Topic')
        thumbnail.assert_called_once_with(self.run)
        context.new_page.assert_not_called()

    def test_metadata_normalizes_hashtags_with_leading_space(self):
        value = {'title_options':['First Actual Title','Second Title','Third Title'], 'description':' '.join(['Narrative']*120), 'hashtags':['#faith',' #hope','#jesus','#bible','#prayer'], 'tags':['faith','hope']}
        with patch.object(config, 'CHANNEL', SimpleNamespace(slug='fallem-prince')), patch.object(codex_media, '_execute', return_value=self.fake_result('metadata', value)):
            result = codex_media.generate_metadata(self.run, 'Topic')
        self.assertIn('#faith #hope', result['description'])

    def test_zaflas_keeps_fixed_links_and_its_own_paragraph_and_hashtag_rules(self):
        prefix = "🌱 Conheça o Zaflas:  https://zaflas.com.br/\n\n" + "Fixed social prefix words "*25 + "\nGitHub: https://github.com/zaflas"
        rules = "DESCRIPTION:\n" + prefix + "\n\n[topic paragraph]"
        value = {'title_options':['Título um','Título dois','Título três'], 'description':prefix+'\n\n'+' '.join(['Narrativa']*140), 'hashtags':['#agro','#zaflas','#campo','#solo','#safra','#dados','#tecnologia'], 'tags':['agro','tecnologia']}
        with patch.object(config, 'CHANNEL', SimpleNamespace(slug='zaflas')), patch.object(config, 'prompt', return_value=rules), patch.object(codex_media, '_execute', return_value=self.fake_result('metadata', value)):
            result = codex_media.generate_metadata(self.run, 'Tema agrícola')
        self.assertIn('https://zaflas.com.br/', result['description'])
        self.assertIn('https://github.com/zaflas', result['description'])
        self.assertEqual(len(result['hashtags'].split()), 7)

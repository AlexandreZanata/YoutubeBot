"""Non-NVIDIA rendering keeps the channel's media settings and fails safely."""
import subprocess
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from src.engine import video_composer
from tools.ytbot import logic


class CpuVideoFallback(TestCase):
    def test_missing_nvenc_retries_cpu_with_same_filters_fps_audio_and_timing(self):
        results = [subprocess.CompletedProcess([], 1, stderr='Cannot load libcuda.so.1'),
                   subprocess.CompletedProcess([], 0, stderr='')]
        with patch.object(video_composer.subprocess, 'run', side_effect=results) as encode:
            ok = video_composer.render_single_pass_video(
                Path('background.mp4'), Path('voice.aac'), None, None, Path('video.mp4'),
                width=1920, height=1080, fps=30, total_duration=4775, background_is_video=True)
        self.assertTrue(ok)
        gpu, cpu = [call.args[0] for call in encode.call_args_list]
        self.assertIn('h264_nvenc', gpu)
        self.assertIn('libx264', cpu)
        self.assertEqual(cpu[cpu.index('-crf') + 1], '18')
        for option in ['-filter_complex', '-af', '-r', '-g', '-t', '-b:a']:
            self.assertEqual(gpu[gpu.index(option) + 1], cpu[cpu.index(option) + 1])
        self.assertEqual(cpu[-1], 'video.mp4')

    def test_unrelated_encoding_failure_is_not_retried_as_a_gpu_problem(self):
        with patch.object(video_composer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stderr='Permission denied')) as encode:
            self.assertFalse(video_composer.render_single_pass_video(
                Path('background.png'), Path('voice.aac'), None, None, Path('video.mp4')))
        encode.assert_called_once()

    def test_browser_rendered_title_options_do_not_become_untitled(self):
        raw = ('TITLE OPTIONS:\n\nFirst Actual Title\n\nSecond Actual Title\n\nThird Actual Title\n\n'
               'DESCRIPTION:\nA real description.\n\n#mind #identity\n\nTAGS: mind, identity')
        parsed = logic.parse_metadata(raw)
        self.assertEqual(parsed['title'], 'First Actual Title')
        self.assertIn('#mind #identity', parsed['description'])
        with self.assertRaises(ValueError):
            logic.parse_metadata('An unrelated page without generated metadata')

    def test_empty_transcription_cannot_start_rendering_without_subtitles(self):
        from tools.ytbot import render
        with patch.object(render, 'fit_narration', return_value=Path('voice.aac')), patch.object(render, 'transcribe_narration', return_value=[]), patch('src.engine.audio_mixer.get_audio_duration', return_value=4770), patch('src.engine.standard_backgrounds.resolve_standard_background', return_value=('background.mp4', True)), patch.object(video_composer, 'render_single_pass_video') as encode:
            with self.assertRaisesRegex(RuntimeError, 'subtitle transcription'):
                render._render_video(Path('run'))
        encode.assert_not_called()

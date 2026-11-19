import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.ytbot import documentary


class DocumentaryTests(unittest.TestCase):
    def test_license_allowlist_keeps_public_domain_and_open_licenses(self):
        self.assertTrue(documentary.license_allowed("Public domain"))
        self.assertTrue(documentary.license_allowed("CC BY-SA 4.0"))
        self.assertTrue(documentary.license_allowed("CC0"))
        self.assertFalse(documentary.license_allowed("All rights reserved"))
        self.assertFalse(documentary.license_allowed(""))

    def test_timeline_covers_the_audio_without_gaps(self):
        sources = [{"file": "a.jpg"}, {"file": "b.jpg"}, {"file": "c.jpg"}]
        rows = documentary.timeline("one two three four five six seven eight nine ten", 30.0, sources)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["start"], 0.0)
        self.assertAlmostEqual(rows[-1]["end"], 30.0)
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous["end"], current["start"], places=2)

    def test_aligned_timeline_puts_each_photo_where_it_is_narrated(self):
        article = ("Mulberry Street crowded with immigrants. "
                   "The tenement kitchen was small. "
                   "The steel mill roared with workers.")
        sources = [
            {"file": "a.jpg", "title": "Mulberry Street New York",
             "narration_segment": "A crowded immigrant street", "place": "New York"},
            {"file": "b.jpg", "title": "Tenement kitchen interior",
             "narration_segment": "A tenement kitchen", "place": "New York"},
            {"file": "c.jpg", "title": "Steel mill workers",
             "narration_segment": "Steel mill", "place": "United States"},
        ]
        rows = documentary.timeline_aligned(article, 90.0, sources)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["start"], 0.0)
        self.assertAlmostEqual(rows[-1]["end"], 90.0)
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous["end"], current["start"], places=2)
            self.assertLess(previous["start"], current["start"])
        # The mill photo must not cover the opening street passage.
        self.assertGreater(rows[2]["start"], 30.0)

    def test_generic_subjects_share_dense_passages_evenly(self):
        article = " ".join(["street"] * 40 + ["market"] * 40 + ["school"] * 40)
        sources = [
            {"file": f"{name}.jpg", "title": name, "narration_segment": name,
             "place": "United States"}
            for name in ("street", "market", "school")
        ]
        rows = documentary.timeline_aligned(article, 90.0, sources, min_seconds=6.0)
        for row in rows:
            self.assertGreaterEqual(row["end"] - row["start"], 6.0)
        for previous, current in zip(rows, rows[1:]):
            self.assertAlmostEqual(previous["end"], current["start"], places=2)

    def test_aligned_timeline_resists_outlier_drift(self):
        article = ("Mulberry Street crowded with immigrants. "
                   + " ".join(["city"] * 30) + " "
                   + "Electric streetcar wires crossed the avenue. "
                   + " ".join(["work"] * 30) + " "
                   + "Baseball drew crowds to the park.")
        sources = [
            {"file": "a.jpg", "title": "Mulberry Street", "narration_segment": "Mulberry Street", "place": "New York"},
            {"file": "b.jpg", "title": "Unknown alley", "narration_segment": "Unmentioned alley", "place": "Boston"},
            {"file": "c.jpg", "title": "Streetcar", "narration_segment": "Electric streetcar", "place": "Chicago"},
            {"file": "d.jpg", "title": "Baseball", "narration_segment": "Baseball", "place": "United States"},
        ]
        rows = documentary.timeline_aligned(article, 100.0, sources, min_seconds=5.0)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0]["start"], 0.0)
        self.assertAlmostEqual(rows[-1]["end"], 100.0)
        # Baseball is near the end (~90%+ of article), must not be dragged earlier.
        self.assertGreater(rows[3]["start"], 60.0)

    def test_render_with_crossfade_and_analog_texture(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            photos = []
            for name, color in (("p1.jpg", "red"), ("p2.jpg", "blue")):
                p = run / name
                Image.new("RGB", (640, 360), color).save(p)
                photos.append(p)
            narration = run / "narration.aac"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "sine=frequency=440:duration=10", "-c:a", "aac", str(narration)],
                check=True,
            )
            rows = [
                {"photo": str(photos[0]), "start": 0.0, "end": 5.0},
                {"photo": str(photos[1]), "start": 5.0, "end": 10.0},
            ]
            out = documentary.render(run, rows, narration=narration, output_name="out.mp4",
                                     crossfade=1.0, analog_texture=True, voice_filter=True, workers=2)
            self.assertTrue(out.is_file())
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(out)],
                capture_output=True, text=True, check=True,
            )
            dur = float(probe.stdout.strip())
            self.assertAlmostEqual(dur, 10.0, delta=0.5)
            # Re-mux with voice filter only via mux_audio (-c:v copy)
            remuxed = documentary.mux_audio(
                run / "silent.mp4", narration, run / "out-voice-only.mp4", 10.0,
                voice_filter=True, analog_texture=False,
            )
            self.assertTrue(remuxed.is_file())

    def test_sepia_atlas_defaults_lock_speed_voice_filter_and_duration_bounds(self):
        import inspect
        from tools.ytbot import channels

        self.assertEqual(inspect.signature(documentary.slow_narration).parameters["factor"].default, 0.9)
        render_params = inspect.signature(documentary.render).parameters
        self.assertTrue(render_params["voice_filter"].default)
        self.assertTrue(render_params["analog_texture"].default)
        for slug in ("sepia-atlas", "bathylora"):
            channel = channels.CHANNELS[slug]
            self.assertEqual(channel.min_article_chars, 13000)
            self.assertEqual(channel.max_article_chars, 36000)

    def test_abyssal_thumbnails_and_ocean_credits(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            photo = run / "ocean.jpg"
            Image.new("RGB", (1920, 1080), (10, 45, 70)).save(photo)
            for tmpl in ("encounter", "discovery", "unknown"):
                dest = documentary.thumbnail(
                    run, photo, "WHAT LIVES\nBELOW?", style="abyssal", template=tmpl,
                    subtitle="DEEP OCEAN", output_name=f"thumb-{tmpl}.png",
                )
                with Image.open(dest) as img:
                    self.assertEqual(img.size, (1280, 720))
            credits = documentary.write_credits(run, [{
                "id": "001", "narration_segment": "Dumbo octopus",
                "title": "File:Dumbo-hires.jpg", "institution": "NOAA",
                "expedition": "Okeanos Explorer", "species": "Grimpoteuthis",
                "place": "Atlantic", "depth": "2,000 m", "license": "Public domain",
                "commercial_status": "public domain / commercial use permitted",
                "attribution": "NOAA OER", "resolution": "1920x1080",
                "source_page": "https://commons.wikimedia.org/wiki/File:Dumbo-hires.jpg",
            }])
            text = credits.read_text(encoding="utf-8")
            self.assertIn("Grimpoteuthis", text)
            self.assertIn("Public domain", text)

    def test_documentary_cli_init_and_audit_gates(self):
        from unittest import mock
        from tools.ytbot import cli, documentary_commands

        parser = cli.build_parser()
        args = parser.parse_args(["documentary", "init", "--channel", "bathylora", "--title", "Bigfin Squid"])
        self.assertEqual(args.doc_command, "init")
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "bigfin-squid"
            with mock.patch.object(documentary_commands, "_run_dir", return_value=run):
                documentary_commands.cmd_init(args)
                self.assertTrue((run / "scenes.json").is_file())
                self.assertTrue((run / "metadata.json").is_file())
                meta = (run / "metadata.json").read_text(encoding="utf-8")
                self.assertIn("not affiliated with NOAA", meta)

                # Audit rejects markdown headings and unaligned scripts
                (run / "sources.json").write_text(
                    '[{"id":"001","file":"a.jpg","narration_segment":"Bigfin squid Magnapinna"}]',
                    encoding="utf-8",
                )
                (run / "article.txt").write_text("# Heading\nBigfin squid Magnapinna.", encoding="utf-8")
                bad = parser.parse_args(["documentary", "audit", "--channel", "bathylora", "--run", "bigfin-squid", "--allow-length"])
                with self.assertRaises(SystemExit):
                    documentary_commands.cmd_audit(bad)

                # Clean aligned prose passes audit and writes article.md
                (run / "article.txt").write_text("The bigfin squid Magnapinna glides through deep dark water.", encoding="utf-8")
                documentary_commands.cmd_audit(bad)
                self.assertTrue((run / "article.md").is_file())

    def test_generated_flag_flows_from_sources_to_timeline_rows(self):
        sources = [
            {'file': 'a.jpg', 'title': 'Real photo', 'narration_segment': 'a street',
             'place': 'New York'},
            {'file': 'b.jpg', 'title': 'Illustration', 'narration_segment': 'a vessel',
             'place': 'Ocean', 'generated': True},
        ]
        rows = documentary.timeline_aligned('a street then a vessel', 20.0, sources)
        self.assertFalse(rows[0]['generated'])
        self.assertTrue(rows[1]['generated'])
        summary = documentary.summarize_sources(sources)
        self.assertEqual(summary["real"], 1)
        self.assertEqual(summary["generated"], 1)
        self.assertEqual(summary["generated_ids"], ["?"])

    def test_thumbnail_title_never_leaves_the_canvas(self):
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            photo = run / 'photo.jpg'
            Image.new('RGB', (1600, 900), 'navy').save(photo)
            dest = documentary.thumbnail(run, photo, 'The Strange World of the Bigfin Squid',
                                         style='abyssal', template='encounter')
            with Image.open(dest) as image:
                self.assertEqual(image.size, (1280, 720))
                px = image.convert('RGB').load()
                right = [px[x, y] for x in range(1220, 1280, 4) for y in range(420, 700, 8)]
                bright = sum(1 for r, g, b in right if r + g + b > 540)
                self.assertEqual(bright, 0, 'title text reaches the right edge')

    def test_illustration_label_is_channel_voiced_and_empty_when_absent(self):
        self.assertIn('historical photograph', documentary.illustration_label_for('sepia-atlas'))
        self.assertIn('real observation', documentary.illustration_label_for('bathylora'))
        self.assertTrue(documentary.illustration_label_for('unknown-slug'))
        self.assertEqual(documentary._illustration_filter(''), '')
        self.assertIn('drawtext', documentary._illustration_filter('AI illustration - test'))

    def test_thumbnail_is_a_1280x720_episode_specific_title(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            photo = run / "photo.jpg"
            Image.new("RGB", (1200, 800), "gray").save(photo)
            destination = documentary.thumbnail(run, photo, "AMERICA IN 1900")
            with Image.open(destination) as image:
                self.assertEqual(image.size, (1280, 720))


    def test_chapters_merge_short_windows_and_name_sources(self):
        rows = [
            {'photo': 'a.jpg', 'start': 0.0, 'end': 30.0, 'caption': 'Mulberry Street'},
            {'photo': 'b.jpg', 'start': 30.0, 'end': 34.0, 'caption': 'A kitchen'},
            {'photo': 'c.jpg', 'start': 34.0, 'end': 90.0, 'caption': 'A mill'},
        ]
        sources = [
            {'file': 'a.jpg', 'institution': 'Library of Congress'},
            {'file': 'b.jpg', 'institution': 'Wikimedia Commons'},
            {'file': 'c.jpg', 'institution': '', 'generated': True},
        ]
        block = documentary.chapters_block(rows, sources)
        lines = block.splitlines()
        self.assertTrue(lines[0].startswith('0:00 Mulberry Street'))
        self.assertIn('Library of Congress', lines[0])
        self.assertIn('AI illustration', block)
        # short 4s window merged: every chapter start is >=10s apart
        starts = [line.split(' ')[0] for line in lines]
        self.assertEqual(len(starts), 2)

    def test_description_chapters_fit_youtube_limit(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            rows = [{'photo': f'p{i}.jpg', 'start': float(i * 30), 'end': float(i * 30 + 30),
                     'caption': f'Scene number {i} with a very long descriptive title here'}
                    for i in range(40)]
            sources = [{'file': f'p{i}.jpg', 'institution': 'Wikimedia Commons'} for i in range(40)]
            (run / 'metadata.json').write_text(json.dumps({'description': 'Base paragraph. ' * 20}), encoding='utf-8')
            (run / 'sources.json').write_text(json.dumps(sources), encoding='utf-8')
            text = documentary.apply_description_chapters(run, rows, 'sepia-atlas')
            self.assertLessEqual(len(text), 4900)
            self.assertIn('0:00', text)
            self.assertIn('VIDEO CHAPTERS', text)


if __name__ == "__main__":
    unittest.main()

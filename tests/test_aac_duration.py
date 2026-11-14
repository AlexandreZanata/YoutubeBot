"""ADTS packet timelines must win over misleading bitrate duration estimates."""
import subprocess
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from src.engine.audio_mixer import get_audio_duration


class AacDuration(TestCase):
    def test_variable_bitrate_aac_uses_actual_timeline_not_estimated_container_length(self):
        def probe(command, **_kwargs):
            if command[0] == 'ffprobe':
                return subprocess.CompletedProcess(command,0,stdout='600.0',stderr='')
            return subprocess.CompletedProcess(command,0,stdout='',stderr='time=00:03:00.25 bitrate=N/A')
        with patch('src.engine.audio_mixer.subprocess.run', side_effect=probe):
            self.assertEqual(get_audio_duration(Path('variable.aac')),180.25)

    def test_failed_packet_scan_cannot_report_a_partial_clip_as_complete(self):
        with patch('src.engine.audio_mixer.subprocess.run', return_value=subprocess.CompletedProcess([],1,stdout='',stderr='time=00:00:15.00 decoding failed')):
            self.assertEqual(get_audio_duration(Path('damaged.aac')),0)

"""Real dependency compatibility without loading a speech model or any network."""
import io
import wave
from unittest import TestCase
from faster_whisper.audio import decode_audio


class AudioDecodeCompatibility(TestCase):
    def test_faster_whisper_decodes_pcm_with_supported_pyav(self):
        source = io.BytesIO()
        with wave.open(source, 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b'\0\0'*1600)
        source.seek(0)
        samples = decode_audio(source)
        self.assertEqual(len(samples), 1600)

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from parser_serve.schema.media import MediaStreamType
from parser_serve.utils.ffmpeg import (
    FFmpegExecutionError,
    extract_audio_track,
    probe_media,
)


class FFmpegUtilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "media.mp4"
        self.source.write_bytes(b"media")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("parser_serve.utils.ffmpeg.subprocess.run")
    def test_probe_parses_typed_metadata(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "format": {
                        "format_name": "mov,mp4",
                        "duration": "12.5",
                        "size": "1024",
                        "bit_rate": "8000",
                        "tags": {"title": "demo"},
                    },
                    "streams": [
                        {
                            "index": 0,
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 1080,
                            "avg_frame_rate": "30000/1001",
                        },
                        {
                            "index": 1,
                            "codec_type": "audio",
                            "codec_name": "aac",
                            "sample_rate": "48000",
                            "channels": 2,
                            "tags": {"language": "zho"},
                        },
                    ],
                }
            ),
            stderr="",
        )

        result = probe_media(self.source, executable="/usr/bin/ffprobe")

        self.assertEqual(result.duration_seconds, 12.5)
        self.assertEqual(result.size_bytes, 1024)
        self.assertEqual(result.streams[0].type, MediaStreamType.VIDEO)
        self.assertAlmostEqual(result.streams[0].frame_rate or 0, 29.970, places=3)
        self.assertEqual(result.streams[1].sample_rate, 48_000)
        self.assertEqual(result.streams[1].language, "zho")
        self.assertEqual(run.call_args.args[0][-1], str(self.source.resolve()))

    @patch("parser_serve.utils.ffmpeg.subprocess.run")
    def test_probe_rejects_invalid_json_and_failures(
        self,
        run: Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="not-json",
            stderr="",
        )
        with self.assertRaises(FFmpegExecutionError):
            probe_media(self.source, executable="ffprobe")

        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="invalid media",
        )
        with self.assertRaisesRegex(FFmpegExecutionError, "invalid media"):
            probe_media(self.source, executable="ffprobe")

    @patch("parser_serve.utils.ffmpeg.subprocess.run")
    def test_extract_audio_uses_safe_arguments_and_checks_output(
        self,
        run: Mock,
    ) -> None:
        output = self.root / "audio.wav"

        def execute(
            command: list[str], **_: object
        ) -> subprocess.CompletedProcess[str]:
            Path(command[-1]).write_bytes(b"wave")
            return subprocess.CompletedProcess(command, 0, "", "")

        run.side_effect = execute
        converted = extract_audio_track(
            self.source,
            output,
            sample_rate=16_000,
            channels=1,
            executable="/usr/bin/ffmpeg",
        )

        self.assertEqual(converted, output.resolve())
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/ffmpeg")
        self.assertIn("-nostdin", command)
        self.assertEqual(command[command.index("-ar") + 1], "16000")
        self.assertEqual(command[command.index("-ac") + 1], "1")


if __name__ == "__main__":
    unittest.main()

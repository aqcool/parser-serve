from __future__ import annotations

import unittest
from unittest.mock import patch

from parser_serve.utils.process_limits import (
    ProcessResourceLimitError,
    ProcessResourceLimits,
)


class ProcessResourceLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limits = ProcessResourceLimits(
            maximum_memory_bytes=4_294_967_296,
            maximum_cpu_seconds=900,
            maximum_output_file_bytes=1_073_741_824,
            maximum_processes=64,
            required=True,
        )

    def test_builds_argument_only_prlimit_command(self) -> None:
        command = self.limits.command(
            ["/usr/bin/ffmpeg", "-i", "source.mp4", "output.wav"],
            executable="/usr/bin/prlimit",
        )

        self.assertEqual(command[0], "/usr/bin/prlimit")
        self.assertIn("--as=4294967296", command)
        self.assertIn("--cpu=900", command)
        self.assertIn("--fsize=1073741824", command)
        self.assertIn("--nproc=64", command)
        self.assertEqual(
            command[command.index("--") + 1 :],
            ["/usr/bin/ffmpeg", "-i", "source.mp4", "output.wav"],
        )

    @patch("parser_serve.utils.process_limits.shutil.which", return_value=None)
    def test_required_limits_fail_closed(self, _which: object) -> None:
        with self.assertRaises(ProcessResourceLimitError):
            self.limits.command(["ffmpeg", "-version"])

    @patch("parser_serve.utils.process_limits.shutil.which", return_value=None)
    def test_optional_limits_allow_local_development_fallback(
        self,
        _which: object,
    ) -> None:
        limits = ProcessResourceLimits(
            maximum_memory_bytes=1,
            maximum_cpu_seconds=1,
            maximum_output_file_bytes=1,
            maximum_processes=1,
            required=False,
        )

        self.assertEqual(
            limits.command(["ffprobe", "-version"]), ["ffprobe", "-version"]
        )

    def test_rejects_nonpositive_limits(self) -> None:
        with self.assertRaises(ValueError):
            ProcessResourceLimits(
                maximum_memory_bytes=0,
                maximum_cpu_seconds=1,
                maximum_output_file_bytes=1,
                maximum_processes=1,
            )

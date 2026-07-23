from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parser_serve.utils.libreoffice import (
    LibreOfficeConversionError,
    LibreOfficeNotFoundError,
    convert_with_libreoffice,
)


class ConvertWithLibreOfficeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "example document.docx"
        self.source.write_bytes(b"test document")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_converts_document_and_returns_output_path(self, run_mock) -> None:
        output_dir = self.root / "converted"

        def create_output(command, **kwargs):
            (output_dir / "example document.pdf").write_bytes(b"%PDF")
            return subprocess.CompletedProcess(command, 0, "converted", "")

        run_mock.side_effect = create_output

        result = convert_with_libreoffice(
            self.source,
            output_dir=output_dir,
            executable="/usr/bin/libreoffice",
        )

        self.assertEqual(result, (output_dir / "example document.pdf").resolve())
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/libreoffice")
        self.assertIn("--headless", command)
        self.assertEqual(command[command.index("--convert-to") + 1], "pdf")
        self.assertEqual(
            command[command.index("--outdir") + 1],
            str(output_dir.resolve()),
        )
        self.assertEqual(command[-1], str(self.source.resolve()))
        self.assertTrue(command[1].startswith("-env:UserInstallation=file://"))
        run_mock.assert_called_once()

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_supports_libreoffice_filter_format(self, run_mock) -> None:
        source = self.root / "example document.odt"
        source.write_bytes(b"test document")

        def create_output(command, **kwargs):
            (self.root / "example document.docx").write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_output

        result = convert_with_libreoffice(
            source,
            output_format="docx:Office Open XML Text",
            executable="soffice",
        )

        self.assertEqual(result.suffix, ".docx")
        command = run_mock.call_args.args[0]
        self.assertEqual(
            command[command.index("--convert-to") + 1],
            "docx:Office Open XML Text",
        )

    @patch(
        "parser_serve.utils.libreoffice.shutil.which",
        side_effect=[None, "/usr/local/bin/soffice"],
    )
    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_falls_back_to_soffice(self, run_mock, which_mock) -> None:
        def create_output(command, **kwargs):
            (self.root / "example document.pdf").write_bytes(b"%PDF")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_output

        convert_with_libreoffice(self.source)

        self.assertEqual(run_mock.call_args.args[0][0], "/usr/local/bin/soffice")
        self.assertEqual(
            [call.args[0] for call in which_mock.call_args_list],
            ["libreoffice", "soffice"],
        )

    def test_rejects_missing_source(self) -> None:
        with self.assertRaises(FileNotFoundError):
            convert_with_libreoffice(
                self.root / "missing.docx",
                executable="libreoffice",
            )

    @patch("parser_serve.utils.libreoffice.shutil.which", return_value=None)
    def test_reports_missing_libreoffice(self, which_mock) -> None:
        with self.assertRaises(LibreOfficeNotFoundError):
            convert_with_libreoffice(self.source)

        self.assertEqual(which_mock.call_count, 2)

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_reports_nonzero_exit(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            ["libreoffice"],
            1,
            "",
            "source format could not be loaded",
        )

        with self.assertRaisesRegex(
            LibreOfficeConversionError,
            "source format could not be loaded",
        ):
            convert_with_libreoffice(self.source, executable="libreoffice")

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_reports_timeout(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired(
            ["libreoffice"],
            timeout=1,
        )

        with self.assertRaisesRegex(
            LibreOfficeConversionError,
            "timed out",
        ):
            convert_with_libreoffice(
                self.source,
                executable="libreoffice",
                timeout=1,
            )

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_reports_missing_output_file(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            ["libreoffice"],
            0,
            "convert completed",
            "",
        )

        with self.assertRaisesRegex(
            LibreOfficeConversionError,
            "did not create",
        ):
            convert_with_libreoffice(self.source, executable="libreoffice")

    def test_validates_arguments(self) -> None:
        with self.assertRaises(ValueError):
            convert_with_libreoffice(
                self.source,
                output_format=" ",
                executable="libreoffice",
            )

        with self.assertRaises(ValueError):
            convert_with_libreoffice(
                self.source,
                timeout=0,
                executable="libreoffice",
            )


if __name__ == "__main__":
    unittest.main()

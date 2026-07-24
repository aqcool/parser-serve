from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from parser_serve.utils.libreoffice import (
    LibreOfficeConversionError,
    LibreOfficeNotFoundError,
    UnsupportedLegacyOfficeFormatError,
    convert_legacy_office,
)


class ConvertLegacyOfficeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "example document.doc"
        self.source.write_bytes(b"test document")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_converts_doc_to_docx_and_returns_output_path(self, run_mock) -> None:
        output_dir = self.root / "converted"

        def create_output(command, **kwargs):
            (output_dir / "example document.docx").write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "converted", "")

        run_mock.side_effect = create_output

        result = convert_legacy_office(
            self.source,
            output_dir=output_dir,
            executable="/usr/bin/libreoffice",
        )

        self.assertEqual(result, (output_dir / "example document.docx").resolve())
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/libreoffice")
        self.assertIn("--headless", command)
        self.assertEqual(command[command.index("--convert-to") + 1], "docx")
        self.assertEqual(
            command[command.index("--outdir") + 1],
            str(output_dir.resolve()),
        )
        self.assertEqual(command[-1], str(self.source.resolve()))
        self.assertTrue(command[1].startswith("-env:UserInstallation=file://"))
        run_mock.assert_called_once()

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_converts_ppt_to_pptx_case_insensitively(self, run_mock) -> None:
        source = self.root / "slides.PPT"
        source.write_bytes(b"test presentation")

        def create_output(command, **kwargs):
            (self.root / "slides.pptx").write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_output

        result = convert_legacy_office(
            source,
            executable="soffice",
        )

        self.assertEqual(result, (self.root / "slides.pptx").resolve())
        command = run_mock.call_args.args[0]
        self.assertEqual(command[command.index("--convert-to") + 1], "pptx")

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_converts_xls_to_xlsx(self, run_mock) -> None:
        source = self.root / "workbook.xls"
        source.write_bytes(b"test workbook")

        def create_output(command, **kwargs):
            (self.root / "workbook.xlsx").write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_output

        result = convert_legacy_office(source, executable="soffice")

        self.assertEqual(result, (self.root / "workbook.xlsx").resolve())
        command = run_mock.call_args.args[0]
        self.assertEqual(command[command.index("--convert-to") + 1], "xlsx")

    @patch(
        "parser_serve.utils.libreoffice.shutil.which",
        side_effect=[None, "/usr/local/bin/soffice"],
    )
    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_falls_back_to_soffice(self, run_mock, which_mock) -> None:
        def create_output(command, **kwargs):
            (self.root / "example document.docx").write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_output

        convert_legacy_office(self.source)

        self.assertEqual(run_mock.call_args.args[0][0], "/usr/local/bin/soffice")
        self.assertEqual(
            [call.args[0] for call in which_mock.call_args_list],
            ["libreoffice", "soffice"],
        )

    def test_rejects_missing_source(self) -> None:
        with self.assertRaises(FileNotFoundError):
            convert_legacy_office(
                self.root / "missing.doc",
                executable="libreoffice",
            )

    @patch("parser_serve.utils.libreoffice.subprocess.run")
    def test_rejects_non_legacy_office_formats(self, run_mock) -> None:
        for suffix in (".docx", ".pptx", ".xlsx", ".pdf", ""):
            with self.subTest(suffix=suffix):
                source = self.root / f"unsupported{suffix}"
                source.write_bytes(b"unsupported")

                with self.assertRaises(UnsupportedLegacyOfficeFormatError):
                    convert_legacy_office(source, executable="libreoffice")

        run_mock.assert_not_called()

    @patch("parser_serve.utils.libreoffice.shutil.which", return_value=None)
    def test_reports_missing_libreoffice(self, which_mock) -> None:
        with self.assertRaises(LibreOfficeNotFoundError):
            convert_legacy_office(self.source)

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
            convert_legacy_office(self.source, executable="libreoffice")

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
            convert_legacy_office(
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
            convert_legacy_office(self.source, executable="libreoffice")

    def test_rejects_nonpositive_timeout(self) -> None:
        with self.assertRaises(ValueError):
            convert_legacy_office(
                self.source,
                timeout=0,
                executable="libreoffice",
            )


if __name__ == "__main__":
    unittest.main()

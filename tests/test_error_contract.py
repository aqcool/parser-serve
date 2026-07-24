"""Error-code documentation contract tests."""

from __future__ import annotations

import re
from pathlib import Path
from unittest import TestCase

from parser_serve.schema.error import ErrorCode

_ROOT = Path(__file__).resolve().parents[1]
_ERROR_CODE_ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]*)` \|", re.MULTILINE)


class ErrorCodeDocumentationTests(TestCase):
    def test_every_error_code_is_documented_exactly_once(self) -> None:
        documentation = (_ROOT / "docs" / "error-codes.md").read_text(encoding="utf-8")
        documented_codes = _ERROR_CODE_ROW.findall(documentation)

        self.assertEqual(len(documented_codes), len(set(documented_codes)))
        self.assertEqual(set(documented_codes), {code.value for code in ErrorCode})

    def test_reserved_codes_are_explicitly_documented(self) -> None:
        documentation = (_ROOT / "docs" / "error-codes.md").read_text(encoding="utf-8")

        for code in (ErrorCode.API_KEY_EXPIRED, ErrorCode.RATE_LIMITED):
            matching_row = next(
                line
                for line in documentation.splitlines()
                if line.startswith(f"| `{code.value}` |")
            )
            self.assertIn("预留", matching_row)

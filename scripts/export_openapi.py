"""Export the canonical HTTP contract for the Web UI type generator."""

from __future__ import annotations

import json
from pathlib import Path

from parser_serve.api import create_app


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "web" / "openapi.json"
    payload = json.dumps(
        create_app().openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    target.write_text(f"{payload}\n", encoding="utf-8")


if __name__ == "__main__":
    main()

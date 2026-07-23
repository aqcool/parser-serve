"""Convert documents with LibreOffice in headless mode."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final


DEFAULT_TIMEOUT_SECONDS: Final = 120.0


class LibreOfficeConversionError(RuntimeError):
    """Raised when LibreOffice cannot convert a document."""


class LibreOfficeNotFoundError(LibreOfficeConversionError):
    """Raised when a LibreOffice executable cannot be found."""


def _find_executable() -> str:
    """Return the first LibreOffice command available on PATH."""
    for command in ("libreoffice", "soffice"):
        if executable := shutil.which(command):
            return executable

    raise LibreOfficeNotFoundError(
        "LibreOffice executable was not found. Install LibreOffice and make "
        "'libreoffice' or 'soffice' available on PATH."
    )


def _validate_output_format(output_format: str) -> str:
    normalized = output_format.strip().removeprefix(".")
    if not normalized:
        raise ValueError("output_format must not be empty")

    file_extension = normalized.partition(":")[0]
    if not file_extension.isalnum():
        raise ValueError(
            "output_format must start with an alphanumeric file extension"
        )

    return normalized


def _find_output_file(
    output_dir: Path,
    source_stem: str,
    output_extension: str,
) -> Path | None:
    expected = output_dir / f"{source_stem}.{output_extension}"
    if expected.is_file():
        return expected

    expected_name = expected.name.casefold()
    return next(
        (
            candidate
            for candidate in output_dir.iterdir()
            if candidate.is_file() and candidate.name.casefold() == expected_name
        ),
        None,
    )


def convert_with_libreoffice(
    source: str | Path,
    *,
    output_format: str = "pdf",
    output_dir: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executable: str | Path | None = None,
) -> Path:
    """Convert a document using LibreOffice's headless CLI.

    Args:
        source: File to convert.
        output_format: LibreOffice output format, such as ``pdf`` or
            ``docx:Office Open XML Text``.
        output_dir: Destination directory. Defaults to the source directory.
        timeout: Maximum conversion time in seconds.
        executable: Optional path or command name for LibreOffice. When omitted,
            ``libreoffice`` and ``soffice`` are searched on PATH.

    Returns:
        The absolute path of the converted file.

    Raises:
        FileNotFoundError: If ``source`` does not exist.
        IsADirectoryError: If ``source`` is not a regular file.
        ValueError: If the output format or timeout is invalid.
        LibreOfficeNotFoundError: If LibreOffice cannot be found.
        LibreOfficeConversionError: If conversion fails or produces no output.
    """
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")
    if not source_path.is_file():
        raise IsADirectoryError(f"Source path is not a file: {source_path}")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    normalized_format = _validate_output_format(output_format)
    output_extension = normalized_format.partition(":")[0]

    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else source_path.parent
    )
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise NotADirectoryError(f"Output path is not a directory: {destination}")

    libreoffice = str(executable) if executable is not None else _find_executable()

    # Each invocation gets an isolated profile so parallel workers do not attach
    # to an existing LibreOffice process or contend for the same profile lock.
    with tempfile.TemporaryDirectory(prefix="parser-serve-libreoffice-") as profile:
        profile_uri = Path(profile).resolve().as_uri()
        command = [
            libreoffice,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--nofirststartwizard",
            "--convert-to",
            normalized_format,
            "--outdir",
            str(destination),
            str(source_path),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise LibreOfficeNotFoundError(
                f"LibreOffice executable was not found: {libreoffice}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LibreOfficeConversionError(
                f"LibreOffice conversion timed out after {timeout} seconds: "
                f"{source_path}"
            ) from exc

    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise LibreOfficeConversionError(
            f"LibreOffice conversion failed with exit code "
            f"{result.returncode}: {details}"
        )

    converted_path = _find_output_file(
        destination,
        source_path.stem,
        output_extension,
    )
    if converted_path is None:
        details = result.stderr.strip() or result.stdout.strip() or "no output"
        raise LibreOfficeConversionError(
            f"LibreOffice reported success but did not create "
            f"{source_path.stem}.{output_extension}: {details}"
        )

    return converted_path.resolve()

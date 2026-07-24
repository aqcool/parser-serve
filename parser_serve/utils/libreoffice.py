"""Upgrade legacy Word, PowerPoint, and Excel files with LibreOffice."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

from .process_limits import ProcessResourceLimitError, ProcessResourceLimits


DEFAULT_TIMEOUT_SECONDS: Final = 120.0
LEGACY_OFFICE_FORMATS: Final = {
    ".doc": "docx",
    ".ppt": "pptx",
    ".xls": "xlsx",
}


class LibreOfficeConversionError(RuntimeError):
    """Raised when LibreOffice cannot convert a document."""


class LibreOfficeNotFoundError(LibreOfficeConversionError):
    """Raised when a LibreOffice executable cannot be found."""


class UnsupportedLegacyOfficeFormatError(ValueError):
    """Raised when a file is not a supported legacy Office document."""


def _find_executable() -> str:
    """Return the first LibreOffice command available on PATH."""
    for command in ("libreoffice", "soffice"):
        if executable := shutil.which(command):
            return executable

    raise LibreOfficeNotFoundError(
        "LibreOffice executable was not found. Install LibreOffice and make "
        "'libreoffice' or 'soffice' available on PATH."
    )


def libreoffice_available() -> bool:
    return any(
        shutil.which(command) is not None for command in ("libreoffice", "soffice")
    )


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


def convert_legacy_office(
    source: str | Path,
    *,
    output_dir: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    executable: str | Path | None = None,
    resource_limits: ProcessResourceLimits | None = None,
) -> Path:
    """Upgrade a legacy Word, PowerPoint, or Excel file.

    Supported conversions are ``.doc`` to ``.docx``, ``.ppt`` to ``.pptx``,
    and ``.xls`` to ``.xlsx``.

    Args:
        source: Legacy Word, PowerPoint, or Excel file to convert.
        output_dir: Destination directory. Defaults to the source directory.
        timeout: Maximum conversion time in seconds.
        executable: Optional path or command name for LibreOffice. When omitted,
            ``libreoffice`` and ``soffice`` are searched on PATH.
        resource_limits: Optional Linux process limits enforced through ``prlimit``.

    Returns:
        The absolute path of the converted file.

    Raises:
        FileNotFoundError: If ``source`` does not exist.
        IsADirectoryError: If ``source`` is not a regular file.
        UnsupportedLegacyOfficeFormatError: If the source is not ``.doc``,
            ``.ppt``, or ``.xls``.
        ValueError: If the timeout is invalid.
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

    try:
        output_extension = LEGACY_OFFICE_FORMATS[source_path.suffix.casefold()]
    except KeyError as exc:
        supported = ", ".join(sorted(LEGACY_OFFICE_FORMATS))
        raise UnsupportedLegacyOfficeFormatError(
            f"Unsupported legacy Office format {source_path.suffix or '<none>'!r}; "
            f"expected one of: {supported}"
        ) from exc

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
            output_extension,
            "--outdir",
            str(destination),
            str(source_path),
        ]
        if resource_limits is not None:
            try:
                command = resource_limits.command(command)
            except ProcessResourceLimitError as exc:
                raise LibreOfficeConversionError(str(exc)) from exc

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


# Backward-compatible name retained while callers move to the more explicit API.
convert_with_libreoffice = convert_legacy_office


__all__ = [
    "LibreOfficeConversionError",
    "LibreOfficeNotFoundError",
    "UnsupportedLegacyOfficeFormatError",
    "convert_legacy_office",
    "convert_with_libreoffice",
    "libreoffice_available",
]

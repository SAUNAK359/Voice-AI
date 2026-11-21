"""Opt-in V26 bounded disk-streamed Work uploads.

This module solves transport memory pressure, file integrity and archive safety.
It does not claim the existing 10,000-row analytical specialist can process
every 200 MB dataset; downstream capacity is separately qualified.
"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import re
import stat
import zipfile

LEGACY_LIMIT = 8_000_000
HARD_LIMIT = 200_000_000
OWNER_TOTAL_LIMIT = 600_000_000
XLSX_INFLATED_LIMIT = 400_000_000
MAX_ARCHIVE_ENTRIES = 1_000
DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")


class UploadTooLarge(ValueError):
    """Request exceeds the configured Work upload byte budget."""


def upload_limit() -> int:
    from .v26_flags import enabled
    if not enabled("RIZZLER_V26_LARGE_UPLOADS"):
        return LEGACY_LIMIT
    value = os.environ.get("RIZZLER_V26_MAX_UPLOAD_BYTES", str(HARD_LIMIT))
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Invalid Work upload size policy")
    count = int(value)
    if not LEGACY_LIMIT <= count <= HARD_LIMIT:
        raise ValueError("V26 upload size policy outside approved bounds")
    return count


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_uploaded_file(path: Path, name: str, *, maximum: int) -> int:
    """Validate format without materializing the entire file in memory."""
    from .security import safe_upload_name
    safe_upload_name(name)
    path = Path(path)
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise ValueError("Unsafe upload staging object")
    size = path.stat().st_size
    if size > maximum:
        raise UploadTooLarge("Upload exceeds approved size")
    if size < 10:
        raise ValueError("Upload is too small")
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                header = next(reader, None)
            if (not header or len(header) > 50 or
                    any(not h.strip() or len(h)>200 for h in header) or
                    len(set(header)) != len(header)):
                raise ValueError("Invalid CSV header")
        except (UnicodeError, csv.Error) as exc:
            raise ValueError("Invalid CSV structure") from exc
    elif suffix == ".xlsx":
        if not zipfile.is_zipfile(path):
            raise ValueError("Invalid XLSX container")
        try:
            with zipfile.ZipFile(path, "r") as archive:
                entries = archive.infolist()
                names = set(archive.namelist())
                if ("xl/workbook.xml" not in names or
                        len(entries) > MAX_ARCHIVE_ENTRIES or
                        not entries or
                        len(names) != len(entries)):
                    raise ValueError("Invalid XLSX structure")
                expanded = 0
                for item in entries:
                    key = item.filename.replace("\\", "/")
                    parts = key.split("/")
                    expanded += item.file_size
                    if (key.startswith("/") or any(p in ("", ".", "..") for p in parts[:-1]) or
                            ".." in parts or item.flag_bits & 1 or
                            (item.external_attr >> 16) & 0o170000 in (0o120000, 0o10000) or
                            key.lower().endswith(("vbaproject.bin", ".exe", ".dll")) or
                            key.lower().startswith("xl/externallinks/") or
                            item.file_size > XLSX_INFLATED_LIMIT or
                            expanded > XLSX_INFLATED_LIMIT or
                            (item.file_size > 1_000_000 and
                             item.file_size > 250 * max(1, item.compress_size))):
                        raise ValueError("Unsafe or excessive XLSX archive")
                if archive.testzip() is not None:
                    raise ValueError("XLSX failed CRC validation")
        except (zipfile.BadZipFile, RuntimeError, EOFError, OSError) as exc:
            raise ValueError("Unreadable XLSX archive") from exc
    else:
        raise ValueError("Only CSV or XLSX Work uploads are supported")
    return size


async def spool_request(stream, path: Path, *, maximum: int) -> tuple[int, str]:
    """Stream request bytes to an exclusive 0600 file; unlink on any failure."""
    path = Path(path)
    if not LEGACY_LIMIT <= maximum <= HARD_LIMIT:
        raise ValueError("Invalid upload budget")
    total = 0
    sha = hashlib.sha256()
    try:
        with path.open("xb") as handle:
            path.chmod(0o600)
            async for chunk in stream:
                if not isinstance(chunk, bytes):
                    raise ValueError("Invalid streamed upload chunk")
                total += len(chunk)
                if total > maximum:
                    raise UploadTooLarge("Upload exceeds approved size")
                sha.update(chunk)
                handle.write(chunk)
        if total < 10:
            raise ValueError("Upload is too small")
        return total, sha.hexdigest()
    except BaseException:
        path.unlink(missing_ok=True)
        raise

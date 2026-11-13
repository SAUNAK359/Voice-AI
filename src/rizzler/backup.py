"""Verified offline backup/restore of Rizzler's single-host persistent state.

Stop API and workers before backup or restore. Archives are streamed, checked,
and restored into a private staging directory before atomic rename. A backup
does NOT export PostgreSQL data, external S3, or encryption secrets; back those
up separately using their provider-native snapshot facilities.

No artificial total-byte or PDF page-count cap. Physical disk/free space,
tar archive size, file-count protection and user-configured resources still
apply. Not a live, cross-host consistency guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import tarfile
import tempfile

MAX_FILES = 1_000_000
PATHS = ("jobs.sqlite3", "identity.sqlite3", "uploads", "artifacts",
         "private_memory", "visuals", "memory", "pdfs")
BLOCK = 1024 * 1024


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_member_path(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Invalid backup file name")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value or ".." in path.parts
            or "." in path.parts or path.parts[0] not in PATHS
            or (len(path.parts) == 1 and path.parts[0] not in (
                "jobs.sqlite3", "identity.sqlite3"))):
        raise ValueError("Unsafe backup member path")
    return path.parts


def _collect(root: Path):
    results = []
    for prefix in PATHS:
        candidate = root / prefix
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.is_symlink():
            raise ValueError("Backup source symlink is forbidden")
        items = [candidate] if candidate.is_file() else candidate.rglob("*")
        for path in items:
            if path.is_symlink():
                raise ValueError("Backup source symlink is forbidden")
            if not path.is_file():
                continue
            if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise ValueError("Nonregular backup member")
            relative = path.relative_to(root).as_posix()
            _validate_member_path(relative)
            results.append((relative, path))
            if len(results) > MAX_FILES:
                raise ValueError("Backup exceeds file count safety bound")
    return sorted(results)


def backup(root: Path, destination: Path):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if not root.is_dir() or destination.is_relative_to(root):
        raise ValueError("Backup destination must be outside existing work root")
    # Exclusive offline backup: no API/worker may write while the snapshot runs.
    for db_name in ("jobs.sqlite3", "identity.sqlite3"):
        db_file = root / db_name
        if db_file.is_file():
            with sqlite3.connect(db_file, timeout=15) as con:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    entries = _collect(root)
    if not entries:
        raise ValueError("Nothing to back up")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 2, "files": []}
    for name, path in entries:
        st = path.stat()
        manifest["files"].append({
            "path": name, "bytes": st.st_size, "sha256": _sha_file(path)
        })
    with tempfile.NamedTemporaryFile(dir=destination.parent,
                                     suffix=".tmp", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        temporary.chmod(0o600)
        with tarfile.open(temporary, "w:gz") as archive:
            for entry, (_, path) in zip(manifest["files"], entries):
                before = path.stat()
                if before.st_size != entry["bytes"]:
                    raise RuntimeError("Source changed during offline backup")
                meta = tarfile.TarInfo("data/" + entry["path"])
                meta.size, meta.mode, meta.mtime = entry["bytes"], 0o600, 0
                with path.open("rb") as stream:
                    archive.addfile(meta, stream)
                if path.stat().st_size != before.st_size or (
                        _sha_file(path) != entry["sha256"]):
                    raise RuntimeError("Source changed during offline backup")
            data = (json.dumps(manifest, sort_keys=True,
                     separators=(",", ":")) + "\n").encode()
            meta = tarfile.TarInfo("MANIFEST.json")
            meta.size, meta.mode, meta.mtime = len(data), 0o600, 0
            archive.addfile(meta, io.BytesIO(data))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def restore(source: Path, destination: Path):
    source, destination = Path(source), Path(destination).resolve()
    if not source.is_file() or destination.exists():
        raise ValueError("Restore requires an existing archive and absent destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage on destination filesystem; no incomplete final directory appears.
    with tempfile.TemporaryDirectory(dir=destination.parent,
                                     prefix=".rizzler-restore-") as temp:
        staged = Path(temp) / "data"
        staged.mkdir(mode=0o700)
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            if (len(members) < 2 or len(members) > MAX_FILES + 1
                    or any(not item.isfile() for item in members)):
                raise ValueError("Unsafe backup archive")
            if len({m.name for m in members}) != len(members):
                raise ValueError("Duplicate backup members")
            manifest_member = archive.getmember("MANIFEST.json")
            if manifest_member.size > 100_000_000:
                raise ValueError("Backup manifest too large")
            mf = archive.extractfile(manifest_member)
            if mf is None:
                raise ValueError("Missing backup manifest")
            manifest = json.loads(mf.read())
            if (manifest.get("schema_version") not in (1, 2)
                    or not isinstance(manifest.get("files"), list)):
                raise ValueError("Invalid backup manifest")
            files = manifest["files"]
            if len(files) != len(members) - 1:
                raise ValueError("Backup member count differs from manifest")
            seen = set()
            for item in files:
                if not isinstance(item, dict) or set(item) != {"path","bytes","sha256"}:
                    raise ValueError("Invalid backup manifest entry")
                name, size, digest = item["path"], item["bytes"], item["sha256"]
                parts = _validate_member_path(name)
                if (name in seen or type(size) is not int or size < 0
                        or not isinstance(digest, str) or len(digest) != 64
                        or any(c not in "0123456789abcdef" for c in digest)):
                    raise ValueError("Invalid or duplicated backup file entry")
                seen.add(name)
                member = archive.getmember("data/" + name)
                if not member.isfile() or member.size != size:
                    raise ValueError("Archive file size mismatch")
                target = staged.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                reader = archive.extractfile(member)
                if reader is None:
                    raise ValueError("Backup content unavailable")
                checksum = hashlib.sha256()
                remaining = size
                with target.open("xb") as output:
                    while remaining:
                        block = reader.read(min(BLOCK, remaining))
                        if not block:
                            raise ValueError("Truncated backup member")
                        output.write(block)
                        checksum.update(block)
                        remaining -= len(block)
                target.chmod(0o600)
                if checksum.hexdigest() != digest:
                    raise ValueError("Backup checksum mismatch")
            expected_members = {"MANIFEST.json", *("data/" + n for n in seen)}
            if {m.name for m in members} != expected_members:
                raise ValueError("Undeclared backup member")
        if destination.exists():
            raise ValueError("Restore destination appeared during validation")
        staged.rename(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (backup(args.root, args.archive) if args.action == "backup" else
                  restore(args.archive, args.root))
    except (ValueError, RuntimeError, OSError, tarfile.TarError, KeyError,
            TypeError, sqlite3.Error):
        parser.exit(2, "Backup/restore verification failed; inspect offline state.\n")
    print(f"{args.action}: {len(result['files'])} files verified")


if __name__ == "__main__":
    main()

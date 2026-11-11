"""Offline verified backup/restore for single-host Rizzler state.

Stop both API and worker before invoking. A backup isn't atomic with live
artifact writes. This tool rejects symlinks and unsafe archive members.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

MAX_FILES = 100_000
MAX_BYTES = 20_000_000_000
PATHS = ("jobs.sqlite3", "identity.sqlite3", "uploads", "artifacts")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def backup(root: Path, destination: Path):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if not root.is_dir() or destination.is_relative_to(root):
        raise ValueError("Backup destination must be outside work root")
    # This command requires the web API and worker to be stopped.
    # Merge any leftover SQLite WAL pages into the main database first.
    for db_name in ("jobs.sqlite3", "identity.sqlite3"):
        db_file = root / db_name
        if db_file.is_file():
            with sqlite3.connect(db_file, timeout=15) as con:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    entries = []
    for item in PATHS:
        candidate = root / item
        if not candidate.exists():
            continue
        paths = [candidate] if candidate.is_file() else sorted(candidate.rglob("*"))
        for path in paths:
            if path.is_symlink():
                raise ValueError("Symlink found in work tree")
            if path.is_file():
                size = path.stat().st_size
                entries.append((path.relative_to(root).as_posix(), path, size))
    if not entries or len(entries) > MAX_FILES or sum(x[2] for x in entries) > MAX_BYTES:
        raise ValueError("Missing or excessive backup data")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "files": []}
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with tarfile.open(temp_path, "w:gz") as archive:
            for name, path, expected in entries:
                data = path.read_bytes()
                if len(data) != expected:
                    raise RuntimeError("File modified during offline backup")
                manifest["files"].append({"path": name, "bytes": len(data), "sha256": _sha(data)})
                info = tarfile.TarInfo("data/" + name)
                info.size, info.mode, info.mtime = len(data), 0o600, 0
                archive.addfile(info, io.BytesIO(data))
            raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
            info = tarfile.TarInfo("MANIFEST.json")
            info.size, info.mode, info.mtime = len(raw), 0o600, 0
            archive.addfile(info, io.BytesIO(raw))
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)
    return manifest


def restore(source: Path, destination: Path):
    source, destination = Path(source), Path(destination).resolve()
    if not source.is_file() or destination.exists():
        raise ValueError("Restore requires a valid archive and absent destination")
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > MAX_FILES + 1 or any(not m.isfile() or m.issym() or m.islnk() for m in members):
            raise ValueError("Unsafe backup archive")
        manifest_file = archive.extractfile("MANIFEST.json")
        if manifest_file is None:
            raise ValueError("Manifest absent")
        manifest = json.loads(manifest_file.read())
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
            raise ValueError("Invalid manifest")
        expected = {f["path"]: f for f in manifest["files"]}
        if len(expected) != len(manifest["files"]) or len(expected) + 1 != len(members):
            raise ValueError("Missing or duplicate entries")
        if sum(f["bytes"] for f in expected.values()) > MAX_BYTES:
            raise ValueError("Backup too large")
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, entry in expected.items():
            parts = PurePosixPath(name)
            if (parts.is_absolute() or ".." in parts.parts or
                    parts.parts[0] not in PATHS or not name or "\\" in name):
                raise ValueError("Unsafe backup path")
            member = archive.getmember("data/" + name)
            if not member.isfile() or member.size != entry["bytes"]:
                raise ValueError("Backup size mismatch")
            reader = archive.extractfile(member)
            if reader is None:
                raise ValueError("Backup file missing")
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest = hashlib.sha256()
            remaining = entry["bytes"]
            with path.open("wb") as target:
                while remaining:
                    chunk = reader.read(min(1024*1024, remaining))
                    if not chunk:
                        raise ValueError("Backup truncated")
                    target.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError("Backup checksum mismatch")
            path.chmod(0o600)
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
    except (ValueError, RuntimeError, OSError, tarfile.TarError, KeyError, TypeError):
        parser.exit(2, "Backup/restore verification failed. Inspect storage offline.\n")
    print(f"{args.action}: {len(result['files'])} files verified")


if __name__ == "__main__":
    main()

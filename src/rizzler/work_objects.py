"""Private S3-compatible object storage with verified checksums and SSE.

Used for Work Agent uploads/artifacts when RIZZLER_S3_BUCKET is configured.
Object keys are server-generated; no user-controlled bucket or paths.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


class StorageUnavailable(RuntimeError):
    pass


class S3Objects:
    def __init__(self, bucket: str, *, region: str | None = None,
                 endpoint: str | None = None, client=None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{2,62}", bucket):
            raise ValueError("Invalid S3 bucket")
        if endpoint:
            uri = urlparse(endpoint)
            if uri.scheme != "https" or not uri.hostname or uri.username or uri.password:
                raise ValueError("S3 endpoint must be HTTPS and operator controlled")
        self.bucket = bucket
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("Install boto3 for S3-backed work storage") from exc
            client = boto3.client("s3", region_name=region or None, endpoint_url=endpoint or None)
        self.client = client

    @staticmethod
    def _key(name: str) -> str:
        if (not isinstance(name, str) or len(name) > 250 or
                not re.fullmatch(r"[A-Za-z0-9_./-]+", name) or
                any(part in ("", ".", "..") for part in PurePosixPath(name).parts) or
                PurePosixPath(name).is_absolute()):
            raise ValueError("Invalid object key")
        return "rizzler-v10/" + name

    @staticmethod
    def _check_bytes(path: Path, digest: str, size: int):
        if not path.is_file() or path.stat().st_size != size:
            raise StorageUnavailable("Object length mismatch")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise StorageUnavailable("Object integrity mismatch")

    def put(self, key: str, path: Path, digest: str, size: int):
        path = Path(path)
        if size < 1 or size > 50_000_000:
            raise ValueError("Object outside size policy")
        self._check_bytes(path, digest, size)
        name = self._key(key)
        try:
            with path.open("rb") as handle:
                self.client.upload_fileobj(handle, self.bucket, name, ExtraArgs={
                    "ServerSideEncryption": "AES256", "Metadata": {"sha256": digest}})
            result = self.client.head_object(Bucket=self.bucket, Key=name)
            if (result.get("ContentLength") != size or
                    (result.get("Metadata") or {}).get("sha256") != digest):
                raise StorageUnavailable("Remote object verification failed")
        except Exception as exc:
            raise StorageUnavailable("Object publication unavailable") from None

    def get(self, key: str, path: Path, digest: str, size: int):
        name, path = self._key(key), Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            info = self.client.head_object(Bucket=self.bucket, Key=name)
            if (info.get("ContentLength") != size or
                    (info.get("Metadata") or {}).get("sha256") != digest):
                raise StorageUnavailable("Remote metadata mismatch")
            self.client.download_file(self.bucket, name, str(temp))
            self._check_bytes(temp, digest, size)
            temp.replace(path)
            path.chmod(0o600)
        except Exception:
            raise StorageUnavailable("Object download unavailable") from None
        finally:
            temp.unlink(missing_ok=True)
        return path


def from_environment():
    bucket = os.environ.get("RIZZLER_S3_BUCKET", "").strip()
    if not bucket:
        return None
    return S3Objects(bucket, region=os.environ.get("RIZZLER_S3_REGION"),
                     endpoint=os.environ.get("RIZZLER_S3_ENDPOINT_URL"))

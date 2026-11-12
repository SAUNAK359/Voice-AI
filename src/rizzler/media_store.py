"""Owner-scoped, encrypted visual attachments; bounded validation before persistence.

Only user-submitted PNG/JPEG/WebP and PDF are accepted. Never follow links
or interpret document contents as instructions. SQLite is local to this host;
a Kaggle ephemeral filesystem is not a durable multi-node media backend.
"""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time

MAX_UPLOAD = 8_000_000
MAX_FILES = 6
TTL = 24 * 3600
_ID = re.compile(r"^[A-Za-z0-9_-]{12,48}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,99}$")


class MediaMissing(LookupError):
    pass


def normalize(name: str, data: bytes) -> tuple[str, bytes, dict]:
    """Sniff content independently from the extension; remove image metadata."""
    if not isinstance(name, str) or not _NAME.fullmatch(name) or (
            not isinstance(data, bytes) or not 32 <= len(data) <= MAX_UPLOAD):
        raise ValueError("Invalid visual upload name or size")
    ext = Path(name).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".pdf"):
        raise ValueError("Visual upload type is not supported")
    if ext == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("File is not a PDF")
        import fitz
        try:
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass or not 1 <= pdf.page_count <= 24:
                    raise ValueError("Encrypted or excessive PDF pages")
                if getattr(pdf, "get_javascript", lambda: [])():
                    raise ValueError("PDF JavaScript is not supported")
                for page in pdf:
                    if not 36 <= page.rect.width <= 20000 or not 36 <= page.rect.height <= 20000:
                        raise ValueError("PDF page dimensions outside bounds")
                pages = pdf.page_count
        except ValueError:
            raise
        except Exception:
            raise ValueError("Malformed PDF upload") from None
        return "application/pdf", data, {"pages": pages}
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(BytesIO(data)) as img:
            if img.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Unsupported image encoding")
            if ((img.format == "PNG" and ext != ".png") or
                    (img.format == "JPEG" and ext not in (".jpg", ".jpeg")) or
                    (img.format == "WEBP" and ext != ".webp")):
                raise ValueError("Image extension and contents disagree")
            if img.width * img.height > 20_000_000 or min(img.size) < 16:
                raise ValueError("Image dimensions outside bounds")
            image = ImageOps.exif_transpose(img).convert("RGB")
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=83, optimize=True)
            normalized = output.getvalue()
            return "image/jpeg", normalized, {"width": image.width, "height": image.height}
    except (OSError, UnidentifiedImageError, OverflowError, Image.DecompressionBombError):
        raise ValueError("Unreadable or decompression-bomb image") from None


class MediaStore:
    def __init__(self, root: str | Path, key: str, scanner=None):
        if not isinstance(key, str) or len(key.encode()) < 32:
            raise ValueError("Media encryption needs an independent 32-byte secret")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        location = Path(root)
        if not location.is_absolute() or location.is_symlink():
            raise ValueError("Media root must be absolute and not a symlink")
        location.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = location / "visual_v11.sqlite3"
        if self.path.is_symlink():
            raise ValueError("Media database cannot be a symlink")
        self._crypto = AESGCM(hashlib.sha256(b"rizzler-visual-v11\0" + key.encode()).digest())
        self.scanner = scanner
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS visuals(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
              mime TEXT NOT NULL, sha TEXT NOT NULL, encrypted BLOB NOT NULL,
              info TEXT NOT NULL, size INTEGER NOT NULL,
              created INTEGER NOT NULL, expires INTEGER NOT NULL,
              UNIQUE(owner, sha))""")
            db.execute("CREATE INDEX IF NOT EXISTS visual_owner ON visuals(owner, created)")
            db.execute("CREATE INDEX IF NOT EXISTS visual_expiry ON visuals(expires)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _owner(owner):
        if (not isinstance(owner, str) or not 1 <= len(owner) <= 120 or
                any(ord(c) < 33 or ord(c) == 127 for c in owner)):
            raise ValueError("Invalid visual owner")
        return owner

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError("Invalid visual attachment ID")
        return value

    def save(self, owner: str, name: str, raw: bytes) -> dict:
        owner = self._owner(owner)
        if self.scanner is not None:
            self.scanner(raw)  # production scan before parsing or DB insertion
        mime, cleaned, info = normalize(name, raw)
        import json
        now = int(time.time())
        digest = hashlib.sha256(cleaned).hexdigest()
        with self._db() as db:
            db.execute("DELETE FROM visuals WHERE expires<=?", (now,))
            previous = db.execute(
                "SELECT * FROM visuals WHERE owner=? AND sha=?", (owner, digest)).fetchone()
            if previous:
                return self._public(previous)
            count, bytes_used = db.execute(
                "SELECT count(*),coalesce(sum(size),0) FROM visuals WHERE owner=?",
                (owner,)).fetchone()
            if count >= MAX_FILES or bytes_used + len(cleaned) > 25_000_000:
                raise OverflowError("Visual attachment quota exceeded")
            uid = secrets.token_urlsafe(18)
            aad = (owner + "\0" + uid + "\0" + mime).encode()
            nonce = secrets.token_bytes(12)
            encrypted = nonce + self._crypto.encrypt(nonce, cleaned, aad)
            db.execute("""INSERT INTO visuals
                (id,owner,name,mime,sha,encrypted,info,size,created,expires)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (uid, owner, name, mime, digest, encrypted, json.dumps(info),
                 len(cleaned), now, now+TTL))
            saved = db.execute("SELECT * FROM visuals WHERE owner=? AND id=?",
                               (owner, uid)).fetchone()
            return self._public(saved)

    @staticmethod
    def _public(row) -> dict:
        import json
        return {"id": row["id"], "name": row["name"], "mime": row["mime"],
                "bytes": row["size"], "info": json.loads(row["info"]),
                "expires": row["expires"]}

    def list(self, owner: str) -> list[dict]:
        owner = self._owner(owner)
        with self._db() as db:
            records = db.execute("""SELECT * FROM visuals
              WHERE owner=? AND expires>? ORDER BY created DESC,id DESC LIMIT ?""",
              (owner, int(time.time()), MAX_FILES)).fetchall()
        return [self._public(row) for row in records]

    def read(self, owner: str, uid: str) -> tuple[dict, bytes]:
        owner, uid = self._owner(owner), self._id(uid)
        with self._db() as db:
            row = db.execute("""SELECT * FROM visuals WHERE owner=? AND id=? AND expires>?""",
                             (owner, uid, int(time.time()))).fetchone()
        if row is None:
            raise MediaMissing("Visual attachment unavailable")
        aad = (owner + "\0" + uid + "\0" + row["mime"]).encode()
        try:
            payload = self._crypto.decrypt(row["encrypted"][:12],
                                           row["encrypted"][12:], aad)
            if hashlib.sha256(payload).hexdigest() != row["sha"]:
                raise ValueError("Visual attachment checksum mismatch")
        except Exception:
            raise ValueError("Visual attachment integrity failure") from None
        return self._public(row), payload

    def delete(self, owner: str, uid: str) -> bool:
        owner, uid = self._owner(owner), self._id(uid)
        with self._db() as db:
            result = db.execute("DELETE FROM visuals WHERE owner=? AND id=?",
                                (owner, uid))
            return bool(result.rowcount)

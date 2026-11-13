"""Fail-closed ClamAV INSTREAM upload scanning for production uploads.

ClamAV runs as an external supervised daemon. This client does not execute
uploaded content or shell commands and does not trust a suspicious scanner error.
"""
from __future__ import annotations
import socket
import struct


class ScanUnavailable(RuntimeError):
    pass


def scan_clamd(data: bytes, host: str, port: int = 3310, timeout: float = 8.0):
    if not isinstance(data, bytes) or not 1 <= len(data) <= 8_000_000:
        raise ValueError("Upload outside allowed scan size")
    if not host or not 1 <= port <= 65535 or not 1 <= timeout <= 30:
        raise ValueError("Invalid scanner configuration")
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"zINSTREAM\x00")
            for start in range(0, len(data), 32768):
                block = data[start:start+32768]
                sock.sendall(struct.pack("!I", len(block)))
                sock.sendall(block)
            sock.sendall(b"\x00\x00\x00\x00")
            result = bytearray()
            while len(result) <= 1024:
                part = sock.recv(512)
                if not part:
                    break
                result.extend(part)
                if b"\x00" in part or b"\n" in part:
                    break
    except (OSError, TimeoutError) as exc:
        raise ScanUnavailable("Malware scanning unavailable") from None
    if not result or len(result) > 1024:
        raise ScanUnavailable("Malware scanner returned invalid response")
    text = bytes(result).split(b"\x00", 1)[0].strip()
    # Accept exactly a clean scanner result; infected/errors are rejected.
    if text not in (b"stream: OK", b"stream: OK\n"):
        raise ScanUnavailable("Upload rejected by malware scanner")



def scan_clamd_file(path, host: str, port: int = 3310, timeout: float = 30.0):
    """Scan entire disk-backed PDF in INSTREAM chunks, without a local file cap.

    ClamAV daemon policy (StreamMaxLength) must be configured for the expected
    workload. A daemon refusal or scan failure rejects finalization.
    """
    from pathlib import Path
    path=Path(path)
    if not path.is_file() or not host or not 1 <= port <= 65535 or not 1 <= timeout <= 120:
        raise ValueError("Invalid file scan request")
    try:
        with socket.create_connection((host,port),timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"zINSTREAM\x00")
            with path.open("rb") as handle:
                for block in iter(lambda:handle.read(256*1024),b""):
                    sock.sendall(struct.pack("!I",len(block)))
                    sock.sendall(block)
            sock.sendall(b"\x00\x00\x00\x00")
            response=bytearray()
            while len(response)<=1024:
                chunk=sock.recv(256)
                if not chunk:break
                response.extend(chunk)
                if b"\x00" in chunk or b"\n" in chunk:break
    except (OSError,TimeoutError):
        raise ScanUnavailable("Full PDF malware scanner unavailable") from None
    if (len(response)>1024 or
        bytes(response).split(b"\x00",1)[0].strip()!=b"stream: OK"):
        raise ScanUnavailable("Full PDF rejected by malware scanner")

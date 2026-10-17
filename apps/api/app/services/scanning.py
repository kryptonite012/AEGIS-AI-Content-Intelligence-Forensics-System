"""Malware scanning via ClamAV's clamd INSTREAM protocol, when configured."""

from __future__ import annotations

import socket
import struct
from pathlib import Path

from app.core.config import get_settings


def scanner_configured() -> bool:
    return bool(get_settings().clamav_host)


def scan_file(path: Path) -> tuple[str, str]:
    """Returns (status, detail): clean | infected | error | not_scanned."""
    s = get_settings()
    if not s.clamav_host:
        return "not_scanned", "No malware scanner configured (AEGIS_CLAMAV_HOST)."
    try:
        with socket.create_connection((s.clamav_host, s.clamav_port), timeout=30) as sock:
            sock.sendall(b"zINSTREAM\0")
            with path.open("rb") as f:
                while chunk := f.read(1 << 16):
                    sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
            reply = sock.recv(4096).decode(errors="replace").strip("\0\n ")
    except OSError as exc:
        return "error", f"Scanner unreachable: {exc.__class__.__name__}"
    if reply.endswith("OK"):
        return "clean", "clamd: OK"
    if "FOUND" in reply:
        return "infected", reply.split(":", 1)[-1].strip()[:200]
    return "error", reply[:200]

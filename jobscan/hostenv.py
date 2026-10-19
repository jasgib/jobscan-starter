"""Host differences in one place, so the rest of the code need not care.

Where Chrome lives, how to stop the machine sleeping mid-run, how to test
that DNS is up, and the install path differ between macOS, Linux and Windows.
"""
from __future__ import annotations

import shutil
import socket
import sys
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",   # macOS
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",        # Linux
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",     # Windows
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def chrome() -> str | None:
    """Path to a Chrome/Chromium that can print to PDF."""
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def keep_awake_prefix() -> list[str]:
    """Command prefix that stops the host sleeping during a long run.

    macOS idles into sleep and takes the network with it. A Linux server
    normally does not, and systemd-inhibit covers the case where it might.
    """
    if sys.platform == "darwin" and Path("/usr/bin/caffeinate").exists():
        return ["/usr/bin/caffeinate", "-i"]
    inhibit = shutil.which("systemd-inhibit")
    if inhibit:
        return [inhibit, "--what=idle:sleep", "--why=jobscan scan"]
    return []


def dns_ready(host: str = "boards-api.greenhouse.io") -> bool:
    """True when name resolution works. Portable; no nslookup dependency."""
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def root() -> Path:
    """The jobscan install directory, derived rather than hardcoded."""
    return Path(__file__).resolve().parent.parent

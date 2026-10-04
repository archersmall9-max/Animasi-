"""Optional source fetcher (thin, honest wrapper around yt-dlp).

Scope, deliberately narrow: pulling down the highest-quality copy of material
**you own or are licensed to use** so it can be finished by this pipeline.

It does not bypass any technical protection measure, does not touch
paywalled or DRM-protected content, and does not bulk-scrape. yt-dlp is an
optional dependency and is never vendored here. See docs/COMPLIANCE.md.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("viralcut.fetch")

RIGHTS_NOTICE = """\
──────────────────────────────────────────────────────────────────────────
 RIGHTS CHECK
 Only fetch material you own, created, commissioned, or are licensed to
 reuse (including clearly licensed Creative Commons work, with credit).
 Re-uploading someone else's video without permission gets the *upload*
 taken down and the account struck — no edit quality can fix that.
──────────────────────────────────────────────────────────────────────────"""

# Highest-quality progressive-friendly selection, capped at 4K.
DEFAULT_FORMAT = "bv*[height<=2160][vcodec!*=av01]+ba/bv*[height<=2160]+ba/b"


def have_yt_dlp() -> bool:
    return shutil.which("yt-dlp") is not None or _module_available()


def _module_available() -> bool:
    try:
        import yt_dlp  # type: ignore[import-not-found]  # noqa: F401

        return True
    except Exception:
        return False


def fetch(
    url: str,
    out_dir: str | Path = "sources",
    *,
    fmt: str = DEFAULT_FORMAT,
    filename: str | None = None,
    quiet: bool = False,
) -> Path:
    """Download ``url`` into ``out_dir`` and return the resulting file path."""
    if not have_yt_dlp():
        raise RuntimeError(
            "yt-dlp is not installed. Install it with `pip install yt-dlp` "
            "(it is an optional dependency of this project)."
        )
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    template = filename or "%(title).80s [%(id)s].%(ext)s"

    if not quiet:
        print(RIGHTS_NOTICE, file=sys.stderr)

    base = [shutil.which("yt-dlp")] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]
    cmd = [
        *base, "--no-playlist", "--no-warnings", "--newline",
        "-f", fmt, "--merge-output-format", "mp4",
        "-o", str(out / template), url,
    ]
    log.info("fetching %s", url)
    before = set(out.iterdir()) if out.exists() else set()
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"yt-dlp exited with {proc.returncode}. The source may be private, "
            "region-locked, or require sign-in — in that case export the file "
            "yourself and pass the local path to `viralcut edit`."
        )
    created = sorted(
        (p for p in out.iterdir() if p not in before and p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    if not created:
        raise RuntimeError("Download finished but no new file appeared in the output folder.")
    return created[-1]

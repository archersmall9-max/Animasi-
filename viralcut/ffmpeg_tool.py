"""Locating and running FFmpeg/FFprobe.

Resolution order for both binaries:
1. Explicit environment variable (``VIRALCUT_FFMPEG`` / ``VIRALCUT_FFPROBE``)
2. Anything already on ``PATH``
3. The portable build shipped by the optional ``imageio-ffmpeg`` package

FFmpeg itself is never vendored into this repository (see LICENSE).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

log = logging.getLogger("viralcut.ffmpeg")


class FFmpegNotFound(RuntimeError):
    """Raised when no usable FFmpeg binary can be located."""


class FFmpegError(RuntimeError):
    """Raised when an FFmpeg invocation exits non-zero."""

    def __init__(self, cmd: Sequence[str], returncode: int, stderr: str) -> None:
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stderr = stderr
        tail = "\n".join(stderr.strip().splitlines()[-25:])
        super().__init__(f"FFmpeg exited with {returncode}.\n--- stderr tail ---\n{tail}")


def _from_imageio() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]

        path = imageio_ffmpeg.get_ffmpeg_exe()
        return path if path and os.path.exists(path) else None
    except Exception:  # pragma: no cover - optional dependency
        return None


def find_ffmpeg() -> str:
    """Return a path to an ffmpeg binary or raise :class:`FFmpegNotFound`."""
    explicit = os.environ.get("VIRALCUT_FFMPEG")
    if explicit and (os.path.exists(explicit) or shutil.which(explicit)):
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    portable = _from_imageio()
    if portable:
        return portable
    raise FFmpegNotFound(
        "FFmpeg not found. Install it (https://ffmpeg.org/download.html), "
        "or run `pip install imageio-ffmpeg` for a portable build, "
        "or set VIRALCUT_FFMPEG=/path/to/ffmpeg"
    )


def find_ffprobe() -> str | None:
    """Return a path to ffprobe, or ``None`` when unavailable.

    ffprobe is a convenience, not a requirement: :mod:`viralcut.probe` falls
    back to parsing ``ffmpeg -i`` output when it is missing.
    """
    explicit = os.environ.get("VIRALCUT_FFPROBE")
    if explicit and (os.path.exists(explicit) or shutil.which(explicit)):
        return explicit
    found = shutil.which("ffprobe")
    if found:
        return found
    # Some portable distributions place ffprobe next to ffmpeg.
    try:
        sibling = os.path.join(os.path.dirname(find_ffmpeg()), "ffprobe")
        if os.path.exists(sibling):
            return sibling
    except FFmpegNotFound:
        pass
    return None


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str


def run(cmd: Sequence[str], *, check: bool = True, quiet: bool = False) -> RunResult:
    """Run a command, capturing output. Raises :class:`FFmpegError` on failure."""
    if not quiet:
        log.debug("exec: %s", " ".join(_quote(part) for part in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if check and proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, proc.stderr)
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def run_ffmpeg(args: Iterable[str], *, quiet: bool = False) -> RunResult:
    """Run ffmpeg with sane global flags prepended."""
    cmd = [find_ffmpeg(), "-hide_banner", "-nostdin", "-y", *args]
    return run(cmd, quiet=quiet)


def _quote(part: str) -> str:
    return f'"{part}"' if " " in part else part


def describe_environment() -> dict[str, str]:
    """Human-readable environment report used by the ``doctor`` command."""
    report: dict[str, str] = {}
    try:
        ffmpeg = find_ffmpeg()
        report["ffmpeg"] = ffmpeg
        out = run([ffmpeg, "-hide_banner", "-version"], check=False).stdout
        report["ffmpeg_version"] = out.splitlines()[0] if out else "unknown"
        filters = run([ffmpeg, "-hide_banner", "-filters"], check=False).stdout
        required = ["scale", "crop", "pad", "gblur", "overlay", "zoompan", "fade", "loudnorm", "unsharp"]
        missing = [f for f in required if f" {f} " not in filters]
        report["filters"] = "all required filters present" if not missing else f"MISSING: {', '.join(missing)}"
        encoders = run([ffmpeg, "-hide_banner", "-encoders"], check=False).stdout
        report["libx264"] = "available" if "libx264" in encoders else "MISSING (required)"
        report["aac"] = "available" if " aac " in encoders else "MISSING (required)"
    except FFmpegNotFound as exc:
        report["ffmpeg"] = f"NOT FOUND — {exc}"
    report["ffprobe"] = find_ffprobe() or "not found (using ffmpeg fallback)"
    try:
        import PIL  # type: ignore[import-not-found]

        report["pillow"] = getattr(PIL, "__version__", "installed")
    except Exception:
        report["pillow"] = "MISSING (required: pip install Pillow)"
    try:
        import yt_dlp  # type: ignore[import-not-found]  # noqa: F401

        report["yt-dlp"] = "available (optional)"
    except Exception:
        report["yt-dlp"] = "not installed (optional)"
    return report

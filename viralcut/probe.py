"""Source inspection: resolution, frame rate, duration, rotation, audio."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .ffmpeg_tool import find_ffmpeg, find_ffprobe, run

log = logging.getLogger("viralcut.probe")


@dataclass
class MediaInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool
    rotation: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    bitrate: int = 0
    pix_fmt: str = ""

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def orientation(self) -> str:
        if self.aspect > 1.05:
            return "landscape"
        if self.aspect < 0.95:
            return "portrait"
        return "square"

    def summary(self) -> str:
        return (
            f"{self.width}x{self.height} ({self.orientation}, AR {self.aspect:.3f}) "
            f"{self.fps:g}fps  {self.duration:.2f}s  "
            f"audio={'yes' if self.has_audio else 'NO'}  codec={self.video_codec or '?'}"
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["aspect"] = round(self.aspect, 4)
        data["orientation"] = self.orientation
        return data


def _parse_rate(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            n, d = float(num), float(den)
        except ValueError:
            return 0.0
        return n / d if d else 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _probe_with_ffprobe(path: Path, ffprobe: str) -> MediaInfo | None:
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    res = run(cmd, check=False, quiet=True)
    if res.returncode != 0 or not res.stdout.strip():
        return None
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return None

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    rotation = 0
    for side in video.get("side_data_list", []) or []:
        if "rotation" in side:
            rotation = int(round(float(side["rotation"]))) % 360
    tag_rotate = (video.get("tags") or {}).get("rotate")
    if tag_rotate:
        try:
            rotation = int(round(float(tag_rotate))) % 360
        except ValueError:
            pass
    if rotation in (90, 270):
        width, height = height, width

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    duration = 0.0
    for candidate in (video.get("duration"), (data.get("format") or {}).get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue

    return MediaInfo(
        path=str(path),
        width=width,
        height=height,
        fps=round(fps, 6) if fps else 0.0,
        duration=duration,
        has_audio=audio is not None,
        rotation=rotation,
        video_codec=video.get("codec_name", ""),
        audio_codec=(audio or {}).get("codec_name", ""),
        bitrate=int(float((data.get("format") or {}).get("bit_rate") or 0)),
        pix_fmt=video.get("pix_fmt", ""),
    )


_RE_SIZE = re.compile(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})")
_RE_FPS = re.compile(r"(\d+(?:\.\d+)?)\s+fps")
_RE_TBR = re.compile(r"(\d+(?:\.\d+)?)\s+tbr")
_RE_DUR = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_RE_VCODEC = re.compile(r"Video:\s*([A-Za-z0-9_]+)")
_RE_ACODEC = re.compile(r"Audio:\s*([A-Za-z0-9_]+)")
_RE_ROT = re.compile(r"rotate\s*:\s*(-?\d+)")
_RE_DISPROT = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees")


def _probe_with_ffmpeg(path: Path) -> MediaInfo:
    """Fallback parser for environments without ffprobe."""
    res = run([find_ffmpeg(), "-hide_banner", "-i", str(path)], check=False, quiet=True)
    text = res.stderr
    size = _RE_SIZE.search(text)
    if not size:
        raise ValueError(f"Could not read video stream from {path}")
    width, height = int(size.group(1)), int(size.group(2))

    rotation = 0
    rot = _RE_ROT.search(text) or _RE_DISPROT.search(text)
    if rot:
        rotation = int(round(float(rot.group(1)))) % 360
    if rotation in (90, 270):
        width, height = height, width

    fps_m = _RE_FPS.search(text) or _RE_TBR.search(text)
    fps = float(fps_m.group(1)) if fps_m else 30.0

    duration = 0.0
    dur = _RE_DUR.search(text)
    if dur:
        duration = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))

    vcodec = _RE_VCODEC.search(text)
    acodec = _RE_ACODEC.search(text)
    return MediaInfo(
        path=str(path),
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        has_audio=acodec is not None,
        rotation=rotation,
        video_codec=vcodec.group(1) if vcodec else "",
        audio_codec=acodec.group(1) if acodec else "",
    )


def probe(path: str | Path) -> MediaInfo:
    """Inspect a media file and return a :class:`MediaInfo`."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Source not found: {p}")

    ffprobe = find_ffprobe()
    info: MediaInfo | None = None
    if ffprobe:
        try:
            info = _probe_with_ffprobe(p, ffprobe)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("ffprobe failed (%s), falling back to ffmpeg parser", exc)
    if info is None:
        info = _probe_with_ffmpeg(p)

    if not info.fps or math.isnan(info.fps) or info.fps <= 0:
        info.fps = 30.0
    if info.duration <= 0:
        info.duration = _duration_by_decode(p)
    log.info("source: %s", info.summary())
    return info


def _duration_by_decode(path: Path) -> float:
    """Last-resort duration measurement by decoding the file (null muxer)."""
    res = run(
        [find_ffmpeg(), "-hide_banner", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
        check=False,
        quiet=True,
    )
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
    if not times:
        return 0.0
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)

"""The render orchestrator — source in, platform master out.

Pipeline (a single encode of the body, so nothing is generation-lossed):

    probe  ->  plan timings  ->  build the body filter graph
           ->  pull the exact first/last framed+graded frames
           ->  synthesise intro/outro plates from them (Pillow)
           ->  concat [intro][body][outro], composite the watermark,
               normalise audio, encode 1080x1920 @ 60 fps H.264/AAC
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import __version__
from .audio import build_audio_chain, measure_loudness
from .config import EditConfig
from .ffmpeg_tool import FFmpegError, find_ffmpeg
from .framing import build_framing, framing_report
from .grade import build_grade
from .plates import build_plate
from .probe import MediaInfo, probe
from .watermark import overlay_position, render_watermark

log = logging.getLogger("viralcut.render")


@dataclass
class RenderResult:
    output: Path
    duration: float
    width: int
    height: int
    fps: int
    size_bytes: int
    fill_mode: str
    report: dict = field(default_factory=dict)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def _even(value: float) -> int:
    return max(2, int(round(value / 2) * 2))


def _plan_timing(info: MediaInfo, cfg: EditConfig) -> tuple[float, float, float]:
    """Return ``(src_start, src_duration, body_out_duration)``.

    ``max_duration`` caps the *delivered* runtime, intro and outro included —
    that is what platform limits (and attention spans) actually measure.
    """
    src_start = max(0.0, cfg.start or 0.0)
    src_end = cfg.end if cfg.end is not None else info.duration
    if info.duration > 0:
        src_end = min(src_end, info.duration)
    src_dur = max(0.05, src_end - src_start)
    if cfg.max_duration:
        overhead = 0.0
        if cfg.intro != "none":
            overhead += max(0.0, cfg.intro_duration)
        if cfg.outro != "none":
            overhead += max(0.0, cfg.outro_duration)
        body_budget = max(0.5, cfg.max_duration - overhead)
        src_dur = min(src_dur, body_budget * cfg.speed)
    return src_start, src_dur, src_dur / cfg.speed


def _zoom_bounds(cfg: EditConfig) -> tuple[float, float, float]:
    """Return ``(work_scale, zoom_at_start, zoom_at_end)``."""
    if cfg.zoom == "off":
        return 1.0, 1.0, 1.0
    z = 1.0 + max(0.0, cfg.zoom_amount)
    if cfg.zoom == "push":
        return z, 1.0, z
    return z, z, 1.0  # 'hook': punch in, then settle


def _build_body_graph(
    info: MediaInfo, cfg: EditConfig, body_duration: float,
    work_w: int, work_h: int, out_label: str,
    transforms: Path | None = None,
    still: bool = False,
) -> tuple[list[str], str]:
    """Filter graph for the main body, consuming ``[0:v]``.

    With ``still=True`` every time-dependent filter (speed, fps conversion,
    motion interpolation, zoompan) is dropped: the graph then renders exactly
    one framed + graded frame on the final canvas, which is what the intro and
    outro plates are built from.
    """
    segments: list[str] = []
    pre: list[str] = []

    if abs(cfg.speed - 1.0) > 1e-3 and not still:
        pre.append(f"setpts=PTS/{cfg.speed:.6f}")
    if cfg.stabilize and transforms is not None:
        pre.append(
            f"vidstabtransform=input={_escape_path(transforms)}:zoom=1:smoothing=30:"
            "optalgo=gauss:interpol=bicubic,unsharp=5:5:0.2:3:3:0.0"
        )
    label_in = "0:v"
    if pre:
        segments.append(f"[0:v]{','.join(pre)}[pre0]")
        label_in = "pre0"

    frame_segments, mode = build_framing(info, cfg, work_w, work_h, label_in, "framed")
    segments.extend(frame_segments)

    tail: list[str] = build_grade(cfg)
    if still:
        if (work_w, work_h) != (cfg.width, cfg.height):
            tail.append(f"scale={cfg.width}:{cfg.height}:flags=lanczos")
        tail += ["setsar=1", "format=yuv420p"]
        segments.append(f"[framed]{','.join(tail)}[{out_label}]")
        return segments, mode

    if cfg.interpolate and info.fps and info.fps < cfg.fps - 1:
        tail.append(
            f"minterpolate=fps={cfg.fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        )
    else:
        tail.append(f"fps={cfg.fps}")

    work_scale, _, _ = _zoom_bounds(cfg)
    if work_scale > 1.0:
        nframes = max(2, int(round(body_duration * cfg.fps)))
        if cfg.zoom == "push":
            expr = f"1+{work_scale - 1:.5f}*min(on/{nframes - 1},1)"
        else:  # hook
            hook_frames = max(2, int(round(cfg.hook_seconds * cfg.fps)))
            expr = f"{work_scale:.5f}-{work_scale - 1:.5f}*min(on/{hook_frames},1)"
        tail.append(
            f"zoompan=z='{expr}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
            f"d=1:s={cfg.width}x{cfg.height}:fps={cfg.fps}"
        )
    elif (work_w, work_h) != (cfg.width, cfg.height):
        tail.append(f"scale={cfg.width}:{cfg.height}:flags=lanczos")

    tail += ["setsar=1", "format=yuv420p", "setpts=PTS-STARTPTS", "settb=AVTB"]
    segments.append(f"[framed]{','.join(tail)}[{out_label}]")
    return segments, mode


def _escape_path(path: Path) -> str:
    """Escape a path for use inside an FFmpeg filter argument."""
    return str(path).replace("\\", "/").replace(":", r"\:").replace(",", r"\,")


def _extract_frame(
    source: Path, cfg: EditConfig, info: MediaInfo, timestamp: float,
    work_w: int, work_h: int, out_png: Path, *, from_end: bool = False,
) -> Image.Image:
    """Render one fully framed + graded frame (no zoom) to PNG and load it.

    Seeking near the very end of a file can land past the last decodable
    frame, so several fallbacks are attempted before giving up.
    """
    segments, _ = _build_body_graph(info, cfg, 1.0, work_w, work_h, "still", still=True)
    graph = ";".join(segments)

    seeks: list[list[str]] = [["-ss", f"{max(0.0, timestamp):.3f}"]]
    if from_end:
        for back in (0.15, 0.40, 1.00):
            ts = timestamp - back
            if ts > 0:
                seeks.append(["-ss", f"{ts:.3f}"])
        seeks.append(["-sseof", "-0.35"])
    else:
        seeks.append(["-ss", f"{timestamp + 0.08:.3f}"])
    seeks.append([])  # first frame of the file

    last_error: FFmpegError | None = None
    for seek in seeks:
        out_png.unlink(missing_ok=True)
        args = [
            find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            *seek, "-i", str(source),
            "-filter_complex", graph, "-map", "[still]",
            "-frames:v", "1", "-update", "1", "-q:v", "1", str(out_png),
        ]
        proc = subprocess.run(args, capture_output=True, text=True, errors="replace")
        if proc.returncode == 0 and out_png.exists() and out_png.stat().st_size > 0:
            img = Image.open(out_png).convert("RGB")
            if img.size != (cfg.width, cfg.height):
                img = img.resize((cfg.width, cfg.height), Image.LANCZOS)
            return img
        last_error = FFmpegError(args, proc.returncode, proc.stderr or "no frame was produced")
        log.debug("still extraction at %s produced nothing; retrying", seek or "start")
    raise last_error or RuntimeError("frame extraction failed")


def _stabilize_pass(source: Path, cfg: EditConfig, start: float, dur: float, workdir: Path) -> Path:
    transforms = workdir / "vidstab.trf"
    args = [
        find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source),
        "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result={_escape_path(transforms)}",
        "-f", "null", "-",
    ]
    log.info("analysing camera shake (stabilisation pass 1/2)...")
    proc = subprocess.run(args, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(args, proc.returncode, proc.stderr)
    return transforms


def _run_with_progress(args: list[str], total_duration: float, label: str = "render") -> None:
    """Run FFmpeg, printing a single-line progress bar."""
    cmd = [find_ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", *args]
    started = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    is_tty = sys.stderr.isatty()
    last = 0.0
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                seconds = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            pct = min(100.0, 100.0 * seconds / total_duration) if total_duration else 0.0
            if is_tty or pct - last >= 10:
                last = pct
                bar = "#" * int(pct / 4) + "." * (25 - int(pct / 4))
                end = "\r" if is_tty else "\n"
                print(f"  {label} [{bar}] {pct:5.1f}%  {seconds:6.2f}s", end=end, file=sys.stderr, flush=True)
    stderr = proc.stderr.read() if proc.stderr else ""
    code = proc.wait()
    if is_tty:
        print(file=sys.stderr)
    if code != 0:
        raise FFmpegError(cmd, code, stderr)
    log.info("%s finished in %.1fs", label, time.time() - started)


def render(
    source: str | Path,
    output: str | Path,
    cfg: EditConfig,
    *,
    workdir: str | Path | None = None,
    keep_work: bool = False,
    write_report: bool = True,
) -> RenderResult:
    """Render ``source`` into a platform-ready master at ``output``."""
    src = Path(source).expanduser().resolve()
    out = Path(output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    info = probe(src)
    cfg.validate()

    tmp_parent = Path(workdir).expanduser() if workdir else Path(tempfile.mkdtemp(prefix="viralcut-"))
    tmp_parent.mkdir(parents=True, exist_ok=True)
    work = tmp_parent if workdir else tmp_parent

    try:
        src_start, src_dur, body_dur = _plan_timing(info, cfg)
        work_scale, z_start, z_end = _zoom_bounds(cfg)
        work_w, work_h = _even(cfg.width * work_scale), _even(cfg.height * work_scale)

        transforms = None
        if cfg.stabilize:
            transforms = _stabilize_pass(src, cfg, src_start, src_dur, work)

        body_segments, fill_mode = _build_body_graph(
            info, cfg, body_dur, work_w, work_h, "body", transforms
        )
        log.info("framing: %s", framing_report(info, cfg, fill_mode))

        # --- intro / outro plates -----------------------------------------
        plates: dict[str, tuple[Path, float]] = {}
        if cfg.intro != "none" and cfg.intro_duration > 0:
            first = _extract_frame(src, cfg, info, src_start, work_w, work_h, work / "first.png")
            built = build_plate(first, cfg, "intro", cfg.intro_duration, z_start, work / "intro.mp4")
            if built:
                plates["intro"] = built
        if cfg.outro != "none" and cfg.outro_duration > 0:
            tail_ts = max(src_start, src_start + src_dur - max(0.08, 2.0 / max(info.fps, 1)))
            last = _extract_frame(src, cfg, info, tail_ts, work_w, work_h, work / "last.png",
                                  from_end=True)
            built = build_plate(last, cfg, "outro", cfg.outro_duration, z_end, work / "outro.mp4")
            if built:
                plates["outro"] = built

        intro_dur = plates.get("intro", (None, 0.0))[1]
        outro_dur = plates.get("outro", (None, 0.0))[1]
        total_dur = intro_dur + body_dur + outro_dur

        # --- watermark ------------------------------------------------------
        wm_path = None
        if cfg.watermark_text or cfg.watermark_image:
            wm_path = render_watermark(cfg, work / "watermark.png")

        # --- assemble the final command --------------------------------------
        args: list[str] = ["-ss", f"{src_start:.3f}", "-t", f"{src_dur:.3f}", "-i", str(src)]
        idx = 1
        input_index: dict[str, int] = {}
        for key in ("intro", "outro"):
            if key in plates:
                args += ["-i", str(plates[key][0])]
                input_index[key] = idx
                idx += 1
        if wm_path:
            args += ["-i", str(wm_path)]
            input_index["wm"] = idx
            idx += 1

        use_audio = cfg.keep_audio and info.has_audio
        if not use_audio and cfg.silent_track_if_missing:
            args += ["-f", "lavfi", "-t", f"{total_dur:.3f}",
                     "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            input_index["silence"] = idx
            idx += 1

        graph: list[str] = list(body_segments)
        for key in ("intro", "outro"):
            if key in plates:
                i = input_index[key]
                graph.append(
                    f"[{i}:v]fps={cfg.fps},scale={cfg.width}:{cfg.height}:flags=lanczos,"
                    f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS,settb=AVTB[{key}v]"
                )
        order = [lbl for lbl in (
            "[introv]" if "intro" in plates else None,
            "[body]",
            "[outrov]" if "outro" in plates else None,
        ) if lbl]
        if len(order) > 1:
            graph.append(f"{''.join(order)}concat=n={len(order)}:v=1:a=0[cat]")
            video_label = "cat"
        else:
            video_label = "body"

        if wm_path:
            x, y = overlay_position(cfg)
            graph.append(
                f"[{input_index['wm']}:v]format=rgba[wmk];"
                f"[{video_label}][wmk]overlay=x={x}:y={y}:format=auto:eof_action=repeat[vout]"
            )
        else:
            graph.append(f"[{video_label}]null[vout]")

        measured = None
        if use_audio and cfg.loudnorm_passes >= 2:
            log.info("measuring loudness (pass 1/2)...")
            measured = measure_loudness(src, cfg, src_start, src_dur)
        if use_audio:
            achain = build_audio_chain(cfg, measured, body_dur, intro_dur, total_dur)
            graph.append(f"[0:a]{','.join(achain)}[aout]")
            audio_map = "[aout]"
        elif "silence" in input_index:
            audio_map = f"{input_index['silence']}:a"
        else:
            audio_map = ""

        args += ["-filter_complex", ";".join(graph), "-map", "[vout]"]
        if audio_map:
            args += ["-map", audio_map]
        args += [
            "-c:v", "libx264", "-preset", cfg.x264_preset, "-crf", str(cfg.crf),
            "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
            "-x264-params",
            f"keyint={cfg.fps * 2}:min-keyint={cfg.fps}:scenecut=40:ref=4:bframes=3:"
            "aq-mode=3:rc-lookahead=60:psy-rd=1.0,0.15",
            "-maxrate", cfg.max_bitrate, "-bufsize", cfg.bufsize,
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-fps_mode", "cfr", "-r", str(cfg.fps),
        ]
        if audio_map:
            args += ["-c:a", "aac", "-b:a", cfg.audio_bitrate, "-ar", "48000", "-ac", "2"]
        else:
            args += ["-an"]
        if cfg.faststart:
            args += ["-movflags", "+faststart"]
        args += ["-t", f"{total_dur:.3f}", str(out)]

        log.info("encoding %dx%d @ %dfps, %.2fs total", cfg.width, cfg.height, cfg.fps, total_dur)
        _run_with_progress(args, total_dur, label="encode")

        final = probe(out)
        result = RenderResult(
            output=out,
            duration=final.duration or total_dur,
            width=final.width,
            height=final.height,
            fps=round(final.fps) if final.fps else cfg.fps,
            size_bytes=out.stat().st_size,
            fill_mode=fill_mode,
            report={
                "viralcut_version": __version__,
                "source": info.to_dict(),
                "output": final.to_dict(),
                "config": cfg.to_dict(),
                "timeline": {
                    "source_start": round(src_start, 3),
                    "source_duration": round(src_dur, 3),
                    "intro": round(intro_dur, 3),
                    "body": round(body_dur, 3),
                    "outro": round(outro_dur, 3),
                    "total": round(total_dur, 3),
                },
                "framing": framing_report(info, cfg, fill_mode),
                "loudness": {"measured": measured, "target_lufs": cfg.loudness_target},
            },
        )
        if write_report:
            report_path = out.with_suffix(out.suffix + ".report.json")
            report_path.write_text(json.dumps(result.report, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        if not keep_work and workdir is None:
            shutil.rmtree(tmp_parent, ignore_errors=True)

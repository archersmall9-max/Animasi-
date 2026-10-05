"""Audio finishing: streaming-loudness normalisation, fades, timing.

Short-form platforms all normalise to roughly -14 LUFS integrated with a
-1 dBTP ceiling. Delivering a master that already sits there means the
platform's own normaliser does nothing — no pumping, no surprise volume drop
against competing videos in the feed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import EditConfig
from .ffmpeg_tool import find_ffmpeg, run

log = logging.getLogger("viralcut.audio")

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)

# Below this integrated loudness the track is effectively silent; normalising
# it would just amplify the noise floor.
SILENCE_FLOOR_LUFS = -45.0


def atempo_chain(speed: float) -> list[str]:
    """FFmpeg's atempo only accepts 0.5–2.0 per instance; chain as needed."""
    if abs(speed - 1.0) < 1e-3:
        return []
    remaining = speed
    parts: list[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.6f}")
    return parts


def measure_loudness(
    source: str | Path,
    cfg: EditConfig,
    start: float | None = None,
    duration: float | None = None,
) -> dict | None:
    """First loudnorm pass. Returns measured values, or ``None`` on failure."""
    args: list[str] = [find_ffmpeg(), "-hide_banner", "-nostdin"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(source)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    filters = atempo_chain(cfg.speed) + [
        f"loudnorm=I={cfg.loudness_target}:TP={cfg.true_peak}:LRA=11:print_format=json"
    ]
    args += ["-map", "0:a:0", "-af", ",".join(filters), "-f", "null", "-"]

    res = run(args, check=False, quiet=True)
    blocks = _JSON_BLOCK.findall(res.stderr)
    match = blocks[-1] if blocks else None
    if not match:
        log.warning("loudness measurement failed; falling back to single-pass loudnorm")
        return None
    try:
        data = json.loads(match)
    except json.JSONDecodeError:
        return None

    try:
        measured_i = float(data["input_i"])
    except (KeyError, TypeError, ValueError):
        return None
    if measured_i < SILENCE_FLOOR_LUFS:
        log.warning("source audio is effectively silent (%.1f LUFS) — skipping normalisation",
                    measured_i)
        return {"silent": True}
    log.info("measured loudness: %.1f LUFS, true peak %s dBTP, LRA %s",
             measured_i, data.get("input_tp"), data.get("input_lra"))
    return data


def build_audio_chain(
    cfg: EditConfig,
    measured: dict | None,
    body_duration: float,
    intro_duration: float,
    total_duration: float,
) -> list[str]:
    """Filters applied to the source audio before it is muxed."""
    chain: list[str] = ["aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"]
    chain += atempo_chain(cfg.speed)

    if measured and not measured.get("silent"):
        chain.append(
            "loudnorm=I={i}:TP={tp}:LRA=11:measured_I={mi}:measured_TP={mtp}:"
            "measured_LRA={mlra}:measured_thresh={mth}:offset={off}:linear=true:print_format=summary".format(
                i=cfg.loudness_target, tp=cfg.true_peak,
                mi=measured.get("input_i"), mtp=measured.get("input_tp"),
                mlra=measured.get("input_lra"), mth=measured.get("input_thresh"),
                off=measured.get("target_offset", 0.0),
            )
        )
    elif measured is None:
        chain.append(f"loudnorm=I={cfg.loudness_target}:TP={cfg.true_peak}:LRA=11")
    # measured["silent"] -> leave the track untouched

    chain.append("aresample=48000:resampler=soxr:precision=28")

    fade = max(0.0, min(cfg.audio_fade, body_duration / 4 if body_duration else 0.0))
    if fade > 0.01:
        chain.append(f"afade=t=in:st=0:d={fade:.3f}")
        fade_out_start = max(0.0, body_duration - fade)
        chain.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade:.3f}")

    if intro_duration > 0.001:
        delay_ms = int(round(intro_duration * 1000))
        chain.append(f"adelay={delay_ms}:all=1")
    chain.append(f"apad=whole_dur={total_duration:.3f}")
    chain.append("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
    return chain


def build_music_chain(cfg: EditConfig, total_duration: float,
                      measured: dict | None = None) -> list[str]:
    """Filters that turn an external track into the bed for this cut.

    The track is looped rather than allowed to run out. A montage planned
    against a beat grid is often a little longer than the excerpt that was
    analysed, and silence at the end of an edit reads as a mistake; a loop
    at least keeps the rhythm going. ``aloop`` counts in samples, hence the
    multiplication by the sample rate.

    Normalisation is two-pass when ``measured`` is supplied, and it matters
    more than it looks. Single-pass ``loudnorm`` is a dynamic normaliser
    that aims at the target rather than hitting it: on a test render it
    landed at -18.7 LUFS against a -14 target, nearly 5 dB quiet. Every
    platform normalises on playback, so a quiet master is not made louder,
    it simply plays quieter than everything around it.
    """
    fade_in = max(0.0, min(cfg.music_fade_in, total_duration / 2))
    fade_out = max(0.0, min(cfg.music_fade_out, total_duration / 2))

    chain = ["aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"]
    if cfg.music_start > 0:
        chain.append(f"atrim=start={cfg.music_start:.3f}")
        chain.append("asetpts=PTS-STARTPTS")
    chain.append(f"aloop=loop=-1:size={int(48000 * 600)}")
    chain.append(f"atrim=end={total_duration:.3f}")
    chain.append("asetpts=PTS-STARTPTS")
    if abs(cfg.music_gain) > 0.01:
        chain.append(f"volume={cfg.music_gain:.2f}dB")
    if fade_in > 0:
        chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        chain.append(f"afade=t=out:st={total_duration - fade_out:.3f}:d={fade_out:.3f}")
    if measured and not measured.get("silent"):
        # The gain above is a linear scaling, so the measured figures move
        # with it exactly - no need to re-measure after applying it.
        shift = cfg.music_gain
        chain.append(
            "loudnorm=I={i}:TP={tp}:LRA=11:measured_I={mi}:measured_TP={mtp}:"
            "measured_LRA={mlra}:measured_thresh={mth}:offset={off}:"
            "linear=true:print_format=summary".format(
                i=cfg.loudness_target, tp=cfg.true_peak,
                mi=float(measured.get("input_i", -24.0)) + shift,
                mtp=float(measured.get("input_tp", -6.0)) + shift,
                mlra=measured.get("input_lra"),
                mth=float(measured.get("input_thresh", -34.0)) + shift,
                off=measured.get("target_offset", 0.0),
            )
        )
    else:
        chain.append(f"loudnorm=I={cfg.loudness_target}:TP={cfg.true_peak}:LRA=11")
    chain.append("aresample=48000:resampler=soxr:precision=28")
    return chain

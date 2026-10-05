"""Command-line interface.

    viralcut doctor
    viralcut probe   SOURCE
    viralcut analyze SOURCE [--window 30]
    viralcut edit    SOURCE [-o OUT] [--preset shorts] [...]
    viralcut meta    BRIEF.json [-o metadata/]
    viralcut fetch   URL [-o sources/]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import (
    FILL_MODES,
    GRADE_PRESETS,
    INTRO_STYLES,
    OUTRO_STYLES,
    PRESETS,
    RATIOS,
    WATERMARK_POSITIONS,
    WATERMARK_STYLES,
    ZOOM_MODES,
    build_config,
)


def _add_edit_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", help="input video file")
    p.add_argument("-o", "--output", default=None, help="output file (default: exports/<name>_<preset>.mp4)")
    p.add_argument("--preset", default="shorts", choices=sorted(PRESETS), help="platform preset")
    p.add_argument("--config", default=None, help="JSON config file (overrides the preset)")

    g = p.add_argument_group("canvas")
    g.add_argument("--ratio", default=None, help=f"target aspect ratio ({', '.join(RATIOS)} or W:H)")
    g.add_argument("--fps", type=int, default=None, help="output frame rate (default 60)")
    g.add_argument("--interpolate", action="store_true", default=None,
                   help="motion-interpolate up to the target fps instead of duplicating frames")

    g = p.add_argument_group("framing")
    g.add_argument("--fill", default=None, choices=FILL_MODES, help="how to fit the source into the canvas")
    g.add_argument("--focus-x", type=float, default=None, help="horizontal crop focus, 0..1 (default 0.5)")
    g.add_argument("--focus-y", type=float, default=None, help="vertical crop focus, 0..1 (default 0.5)")
    g.add_argument("--blur-strength", type=float, default=None, help="background blur multiplier")
    g.add_argument("--smart-max-aspect", type=float, default=None,
                   help="'smart' fill trims a wide source to this aspect first (default 1.30; "
                        "1.0 makes the subject bigger, 1.78 keeps the whole frame)")

    g = p.add_argument_group("motion & look")
    g.add_argument("--zoom", default=None, choices=ZOOM_MODES, help="camera move across the clip")
    g.add_argument("--zoom-amount", type=float, default=None, help="zoom travel, e.g. 0.06 = 6%%")
    g.add_argument("--grade", default=None, choices=GRADE_PRESETS, help="colour grade preset")
    g.add_argument("--sharpen", type=float, default=None, help="sharpening multiplier (0 disables)")
    g.add_argument("--denoise", action="store_true", default=None, help="clean up a noisy/compressed source")
    g.add_argument("--stabilize", action="store_true", default=None, help="two-pass camera stabilisation")

    g = p.add_argument_group("timing")
    g.add_argument("--start", type=float, default=None, help="trim in-point, seconds")
    g.add_argument("--end", type=float, default=None, help="trim out-point, seconds")
    g.add_argument("--max-duration", type=float, default=None, help="cap the output length, seconds")
    g.add_argument("--speed", type=float, default=None, help="playback speed, 1.0 = original")

    g = p.add_argument_group("intro / outro")
    g.add_argument("--intro", default=None, choices=INTRO_STYLES)
    g.add_argument("--intro-duration", type=float, default=None)
    g.add_argument("--outro", default=None, choices=OUTRO_STYLES)
    g.add_argument("--outro-duration", type=float, default=None)

    g = p.add_argument_group("watermark")
    g.add_argument("--watermark-text", default=None, help='handle to burn in (default "@Lowk67Tuff")')
    g.add_argument("--watermark-image", default=None, help="PNG logo instead of text")
    g.add_argument("--watermark-position", default=None, choices=WATERMARK_POSITIONS)
    g.add_argument("--watermark-style", default=None, choices=WATERMARK_STYLES)
    g.add_argument("--watermark-opacity", type=float, default=None)
    g.add_argument("--watermark-scale", type=float, default=None)
    g.add_argument("--no-watermark", action="store_true", help="render without any watermark")

    g = p.add_argument_group("captions")
    g.add_argument("--captions", default=None, metavar="FILE",
                   help="JSON file of timed on-screen captions (emoji supported)")
    g.add_argument("--caption-size", type=float, default=None,
                   help="type height as a fraction of canvas height (default 0.0345)")
    g.add_argument("--no-captions", action="store_true",
                   help="ignore any captions the config carries")

    g = p.add_argument_group("audio & encode")
    g.add_argument("--mute", action="store_true", help="drop the source audio (silent track kept)")
    g.add_argument("--loudness-target", type=float, default=None, help="LUFS target (default -14)")
    g.add_argument("--crf", type=int, default=None, help="x264 quality, lower = better (default 18)")
    g.add_argument("--x264-preset", default=None, help="x264 speed preset (default slow)")

    p.add_argument("--keep-work", action="store_true", help="keep the temporary working folder")
    p.add_argument("--dry-run", action="store_true", help="plan and print, but do not encode")


def _config_from_args(args: argparse.Namespace):
    from .config import EditConfig

    overrides = {
        "ratio": args.ratio, "fps": args.fps, "interpolate": args.interpolate,
        "fill": args.fill, "focus_x": args.focus_x, "focus_y": args.focus_y,
        "blur_strength": args.blur_strength, "smart_max_aspect": args.smart_max_aspect,
        "zoom": args.zoom, "zoom_amount": args.zoom_amount,
        "grade": args.grade, "sharpen": args.sharpen,
        "denoise": args.denoise, "stabilize": args.stabilize,
        "start": args.start, "end": args.end,
        "max_duration": args.max_duration, "speed": args.speed,
        "intro": args.intro, "intro_duration": args.intro_duration,
        "outro": args.outro, "outro_duration": args.outro_duration,
        "watermark_text": args.watermark_text, "watermark_image": args.watermark_image,
        "watermark_position": args.watermark_position, "watermark_style": args.watermark_style,
        "watermark_opacity": args.watermark_opacity, "watermark_scale": args.watermark_scale,
        "loudness_target": args.loudness_target,
        "crf": args.crf, "x264_preset": args.x264_preset,
    }
    if args.config:
        cfg = EditConfig.load(args.config)
        for key, value in overrides.items():
            if value is not None:
                setattr(cfg, key, value)
        if args.ratio:
            cfg.apply_ratio(args.ratio)
        cfg.validate()
    else:
        cfg = build_config(args.preset, **overrides)
    if args.caption_size is not None:
        cfg.caption_size = args.caption_size
    if args.captions:
        import json as _json
        from pathlib import Path as _Path
        data = _json.loads(_Path(args.captions).read_text(encoding="utf-8"))
        cfg.captions = data.get("captions", data) if isinstance(data, dict) else data
    if args.no_captions:
        cfg.captions = []
    if args.no_watermark:
        cfg.watermark_text, cfg.watermark_image = "", None
    if args.mute:
        cfg.keep_audio = False
    return cfg


def cmd_edit(args: argparse.Namespace) -> int:
    from .render import render

    cfg = _config_from_args(args)
    src = Path(args.source).expanduser()
    if not src.exists():
        print(f"error: source not found: {src}", file=sys.stderr)
        return 2
    out = Path(args.output) if args.output else Path("exports") / f"{src.stem}_{args.preset}_{cfg.ratio.replace(':', 'x')}.mp4"

    if args.dry_run:
        from .framing import framing_report, resolve_fill
        from .probe import probe as _probe

        info = _probe(src)
        mode = resolve_fill(info, cfg, cfg.width / cfg.height)
        print(f"source : {info.summary()}")
        print(f"plan   : {framing_report(info, cfg, mode)}")
        print(f"output : {out}  ({cfg.width}x{cfg.height} @ {cfg.fps}fps, CRF {cfg.crf})")
        print(f"intro  : {cfg.intro} {cfg.intro_duration}s   outro: {cfg.outro} {cfg.outro_duration}s")
        print(f"brand  : {cfg.watermark_text or cfg.watermark_image or 'none'} @ {cfg.watermark_position}")
        return 0

    result = render(src, out, cfg, keep_work=args.keep_work)
    print()
    print(f"✓ {result.output}")
    print(f"  {result.width}x{result.height} @ {result.fps}fps · "
          f"{result.duration:.2f}s · {result.size_mb:.1f} MB · fill={result.fill_mode}")
    print(f"  report: {result.output}.report.json")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    from .probe import probe

    info = probe(args.source)
    print(info.summary())
    for key, value in info.to_dict().items():
        print(f"  {key:>12}: {value}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from .analyze import analyze

    result = analyze(args.source, args.window)
    print(result.summary())
    return 0


def cmd_meta(args: argparse.Namespace) -> int:
    from .metadata import build

    md, js, pack = build(args.brief, args.output)
    print(f"✓ {md}")
    print(f"✓ {js}")
    for issue in pack.issues:
        print(f"  {issue}")
    return 0 if pack.ok else 1


def cmd_fetch(args: argparse.Namespace) -> int:
    from .fetch import fetch

    path = fetch(args.url, args.output)
    print(f"✓ {path}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    from .ffmpeg_tool import describe_environment

    print(f"ViralCut {__version__}")
    report = describe_environment()
    width = max(len(k) for k in report)
    problems = 0
    for key, value in report.items():
        flag = "MISSING" in str(value) or "NOT FOUND" in str(value)
        problems += int(flag)
        print(f"  {key:>{width}} : {value}")
    print()
    print("All good — ready to render." if not problems else f"{problems} problem(s) to fix above.")
    return 0 if not problems else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viralcut",
        description="Short-form video finishing pipeline: 1080x1920 · 60 fps · branded.",
    )
    parser.add_argument("--version", action="version", version=f"viralcut {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_edit = sub.add_parser("edit", help="render a platform master")
    _add_edit_arguments(p_edit)
    p_edit.set_defaults(func=cmd_edit)

    p_probe = sub.add_parser("probe", help="inspect a source file")
    p_probe.add_argument("source")
    p_probe.set_defaults(func=cmd_probe)

    p_an = sub.add_parser("analyze", help="find the strongest window to cut from")
    p_an.add_argument("source")
    p_an.add_argument("--window", type=float, default=None, help="window length in seconds")
    p_an.set_defaults(func=cmd_analyze)

    p_meta = sub.add_parser("meta", help="build title/description/hashtag/tag packs from a brief")
    p_meta.add_argument("brief", help="research brief JSON")
    p_meta.add_argument("-o", "--output", default="metadata", help="output folder")
    p_meta.set_defaults(func=cmd_meta)

    p_fetch = sub.add_parser("fetch", help="download a source you own (requires yt-dlp)")
    p_fetch.add_argument("url")
    p_fetch.add_argument("-o", "--output", default="sources")
    p_fetch.set_defaults(func=cmd_fetch)

    p_doc = sub.add_parser("doctor", help="check the local toolchain")
    p_doc.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s" if not args.verbose else "%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

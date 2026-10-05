"""Build the Namakura Gatana (1917) AMV-style Short.

Source  : work/anime_full.mp4 - public-domain film at its full 1350x1060,
          so each shot can crop its own 9:16 window and punch in.
Music   : sources/music_raw.mp3 - "Ishikari Lore", Kevin MacLeod, CC-BY 4.0.
Grid    : 82.03 BPM, period 0.7314397 s, downbeat at 43.9322 s.

Structure (output clock, 60 fps):
    0.000 - 0.733   intro plate      1 beat
    0.733 - 26.336  montage          35 beats / 17 shots
   26.336 - 27.069  outro plate      1 beat

The music starts on the downbeat at 43.9322 s so that the +3.4 dB section
change at 46.8579 s lands exactly on the first hard cut of the montage.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from viralcut.beats import track_beats
from viralcut.config import EditConfig
from viralcut.montage import Shot, check_sources, plan_shots, render_montage
from viralcut.render import render

ROOT = Path(__file__).resolve().parent
PROXY = ROOT / "work" / "anime_full.mp4"
MUSIC = ROOT / "sources" / "music_raw.mp3"
BODY = ROOT / "work" / "anime" / "montage_body.mp4"
FINAL = ROOT / "exports" / "NamakuraGatana_Shorts_MASTER.mp4"

FPS = 60
MUSIC_START = 43.9322          # a measured downbeat
INTRO_BEATS = 1
OUTRO_BEATS = 1

# (source in-point, beats, zoom, focus_x, focus_y, label)
#
# The film only has five locations, so cutting between two shots of the same
# master at the same framing reads as a glitch rather than as an edit. Every
# neighbouring pair therefore changes either location or framing scale, and
# two close-ups of one master are aimed at opposite sides of the frame.
#
# focus_x is capped at 0.70: the archive's "NFC" logo sits at the bottom
# right of the full frame and panning further would bring it into shot.
SHOTS: list[tuple[float, int, float, float, float, str]] = [
    #  --- act 1: the reveal -------------------------------------------------
    (8.0,   3, 1.00, 0.42, 0.50, "iris portrait: the ronin and his blade"),
    (46.0,  4, 1.00, 0.46, 0.50, "the sword shop, wide"),
    (78.0,  4, 1.35, 0.62, 0.42, "close: the merchant"),
    #  --- act 2: the build --------------------------------------------------
    (100.0, 2, 1.25, 0.30, 0.45, "close: the ronin, other side of frame"),
    (118.0, 2, 1.00, 0.48, 0.50, "the night street, wide"),
    (136.0, 2, 1.40, 0.56, 0.40, "close: drawing the sword"),
    (10.5,  2, 1.20, 0.40, 0.45, "cut back to the portrait"),
    #  --- act 3: rapid fire, one beat each ----------------------------------
    (160.0, 1, 1.30, 0.46, 0.45, "stalking, close"),
    (178.0, 1, 1.00, 0.42, 0.50, "the willow, wide"),
    (186.0, 1, 1.35, 0.30, 0.48, "close: the passer-by"),
    (196.0, 1, 1.10, 0.38, 0.50, "the two meet"),
    (214.0, 1, 1.00, 0.52, 0.50, "silhouette: the duel, wide"),
    (218.4, 1, 1.25, 0.50, 0.45, "silhouette: close on the blade"),
    (222.0, 1, 1.00, 0.45, 0.50, "silhouette: wide again"),
    (232.0, 1, 1.35, 0.52, 0.48, "silhouette: down"),
    #  --- act 4: the pay-off ------------------------------------------------
    (241.0, 4, 1.00, 0.45, 0.50, "silhouette duel under the tree"),
    (248.0, 4, 1.20, 0.48, 0.45, "last man standing"),
]

CAPTIONS = [
    {"text": "this anime is 109 years old 🎬",          "start": 0.95,  "end": 2.85},
    {"text": "Japan, 1917. cut from paper by hand",     "start": 3.00,  "end": 6.50},
    {"text": "a broke samurai buys a cheap sword ⚔",    "start": 6.65,  "end": 10.20},
    {"text": "it could not cut a single thing 💀",      "start": 10.40, "end": 14.50},
    {"text": "so the whole street beat him up 😭",      "start": 14.75, "end": 19.50},
    {"text": "lost for 91 years, found in a junk shop 📦", "start": 20.00, "end": 25.60},
]


def main() -> None:
    grid = track_beats(str(MUSIC))
    beat = grid.period
    print(f"grid: {grid.tempo:.2f} BPM  period {beat:.7f}s  confidence {grid.confidence:.2f}")

    intro_d = round(INTRO_BEATS * beat * FPS) / FPS
    outro_d = round(OUTRO_BEATS * beat * FPS) / FPS

    shots = [
        Shot(source=PROXY, start=t, duration=n * beat,
             zoom=z, focus_x=fx, focus_y=fy, label=label)
        for t, n, z, fx, fy, label in SHOTS
    ]
    notes = check_sources(shots)
    if notes:
        raise SystemExit("source problems: " + "; ".join(notes))

    plan = plan_shots(shots, grid, transition_duration=0.10, fps=FPS)
    plan.transition = "fade"
    total_beats = sum(n for _, n, *_ in SHOTS)
    print(f"montage: {len(plan.shots)} shots, {total_beats} beats, {plan.duration:.3f}s")
    print("cuts   :", ", ".join(f"{c:.2f}" for c in plan.cut_times))

    cfg = replace(
        EditConfig.load(ROOT / "config" / "lowk67tuff-shorts.json"),
        fps=FPS,
        zoom="off",
        speed=1.0,
        grade="clean",
        intro_duration=intro_d,
        outro_duration=outro_d,
        music=str(MUSIC),
        music_mode="replace",
        music_start=MUSIC_START,
        captions=CAPTIONS,
        caption_emoji_font="/home/user/fonts/NotoColorEmoji.ttf",
    )

    BODY.parent.mkdir(parents=True, exist_ok=True)
    render_montage(plan, cfg, BODY, fps=FPS)

    total = intro_d + plan.duration + outro_d
    print(f"intro {intro_d:.3f}s + body {plan.duration:.3f}s + outro {outro_d:.3f}s = {total:.3f}s")

    result = render(BODY, FINAL, cfg)
    print("written:", FINAL)
    print(json.dumps(getattr(result, "__dict__", {}), default=str, indent=2)[:1200])


if __name__ == "__main__":
    main()

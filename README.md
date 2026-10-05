# ViralCut

**A reproducible finishing pipeline for short-form video.** One command turns
any source clip into a platform-ready vertical master: **1080 × 1920, 60 fps**,
branded watermark, intro and outro transition, broadcast-safe loudness.

No timeline, no templates, no guesswork — the same input always produces the
same output, and every decision is written to a JSON report next to the file.

```bash
viralcut edit raw.mp4 --preset shorts
# -> exports/raw_shorts_9x16.mp4   1080x1920 @ 60fps
# -> exports/raw_shorts_9x16.mp4.report.json
```

---

## What it does

| Stage | What happens | Why it matters |
|---|---|---|
| **Framing** | Converts any aspect ratio to the target canvas — full-bleed crop, blurred-background fill, smart fill or letterbox | A 16:9 source cropped to 9:16 loses 68 % of the picture. ViralCut measures that loss and picks the strategy that keeps the subject on screen |
| **Motion** | Slow push-in, or a "hook" punch that settles in the first 1.2 s | Constant subtle movement measurably holds attention in a scrolling feed |
| **Intro** | Blur-zoom reveal, flash, fade or whip — generated from the clip's own first frame | Reads as one continuous move instead of a bolted-on template |
| **Outro** | Blur-out, fade or zoom-out that resolves to black | A clean ending beats an abrupt cut for loop/replay behaviour |
| **Grade** | Conservative contrast / saturation / micro-contrast presets | Survives aggressive platform re-encoding instead of banding |
| **Brand** | Pillow-rendered watermark, pixel-identical on every machine | Attribution travels with every re-upload |
| **Audio** | Two-pass EBU R128 loudness normalisation to −14 LUFS / −1 dBTP, with fades | The platform's own normaliser then does nothing — no volume drop against competing videos |
| **Encode** | x264 CRF 18, high profile, CFR 60, bt709, `+faststart` | Maximum quality inside what the platforms actually accept |

Everything beyond the cut is **opt-in**: captions are off unless you pass
`--captions`, and there is **no voice-over and no stock music** at all. What
you ask for is what gets rendered.

---

## Install

```bash
git clone https://github.com/archersmall9-max/Animasi-.git
cd Animasi-
pip install -r requirements.txt           # Pillow
pip install -r requirements-optional.txt  # portable FFmpeg + yt-dlp (optional)
python -m viralcut doctor                 # verify the toolchain
```

FFmpeg is the only external requirement. Install it from
[ffmpeg.org](https://ffmpeg.org/download.html), or let
`pip install imageio-ffmpeg` provide a portable build. It is never vendored
into this repository.

Optionally install the CLI itself:

```bash
pip install -e .        # provides the `viralcut` command
```

---

## Usage

```bash
# Inspect a source
viralcut probe raw.mp4

# Find the strongest window to cut from (scene changes + loudness)
viralcut analyze raw.mp4 --window 30

# Render a master
viralcut edit raw.mp4 --preset tiktok -o exports/clip.mp4

# Same source, deliberate choices
viralcut edit raw.mp4 \
  --preset shorts \
  --fill smart --focus-x 0.45 \
  --zoom hook --grade vivid \
  --start 12.5 --max-duration 45 \
  --watermark-text "@Lowk67Tuff" --watermark-position top-left \
  --intro blurzoom --outro blurout

# Build the publishing pack from a research brief
viralcut meta briefs/my-video.brief.json -o metadata/
```

`--dry-run` prints the full plan — framing decision, timeline, encode
settings — without touching the encoder.

### Presets

| Preset | Look | Intro / outro | CRF |
|---|---|---|---|
| `shorts` | clean | blur-zoom 0.45 s / blur-out 0.70 s | 17 |
| `tiktok` | vivid | blur-zoom 0.40 s / blur-out 0.65 s | 18 |
| `reels` | vivid | flash 0.35 s / fade 0.60 s | 18 |
| `master` | neutral, no camera move | fade / fade | 15 |

All four render 1080 × 1920 at 60 fps. Override anything on the command line,
or keep a project config:

```bash
viralcut edit raw.mp4 --config config/my-channel.json
```

### Aspect ratios

`--ratio` accepts `9:16` (default), `4:5`, `1:1`, `16:9`, `2:3` or any `W:H`.
`--fill` controls how the source is fitted:

* `auto` — measures how much a full-bleed crop would discard and chooses
  (crop under 32 % loss, otherwise keep the whole frame)
* `crop` — fill the canvas edge to edge, nothing left over
* `blur` — whole frame visible, gaps filled with a blurred copy of itself
* `smart` — trim an ultra-wide source toward 1.3:1 first, then blur-fill
* `fit` — whole frame visible, flat colour bars

---

## Metadata

Titles, descriptions, hashtags and tags come from research, not from a
template. The research lives in a JSON brief
(`briefs/example.brief.json`); `viralcut meta` assembles per-platform packs
and validates them against the real limits — YouTube's 100-character title and
500-character tag budget, TikTok's and Instagram's 2 200-character captions,
hashtag counts and formatting.

See [docs/METADATA_PLAYBOOK.md](docs/METADATA_PLAYBOOK.md).

---

## Repository policy

This repository contains **code only**. Source footage, renders, exports,
fonts, music and sound effects are all git-ignored and stay on your machine.
That keeps the project small, fast to clone, and clear of the copyright
complaints that get repositories flagged.

Read [docs/COMPLIANCE.md](docs/COMPLIANCE.md) before you push anything here, and
[docs/WORKFLOW.md](docs/WORKFLOW.md) for the production sequence used on every delivery.

---

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest                       # 72 tests, all media generated locally
```

Licensed under the [MIT License](LICENSE).

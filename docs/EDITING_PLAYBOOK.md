# Editing playbook

The reasoning behind every default in `viralcut`. Short-form distribution is
driven by a small number of measurable signals — watch time, completion,
replays, shares — so each decision below is tied to one of them rather than to
taste.

---

## 1. The first second decides everything

Feeds judge a video on the first 1–2 seconds. Two defaults exist for that
window:

* **Intro plate (0.40–0.45 s).** Generated from the clip's *own* first frame:
  blurred, slightly over-zoomed and dimmed, resolving to the exact frame the
  body starts on. It reads as a camera finding focus, not as a template, and
  because the last plate frame is the body's first frame the join is
  invisible. It is short on purpose — anything approaching a second is dead
  air in a feed.
* **Camera move.** `--zoom push` adds a 5–6 % travel across the clip;
  `--zoom hook` starts 6 % in and settles within 1.2 s. Continuous subtle
  motion keeps the eye engaged on otherwise static footage.

Where the clip starts matters more than either: `viralcut analyze` scores
every candidate window by scene-change density and momentary loudness, then
snaps the suggested in-point to the nearest cut.

```bash
viralcut analyze raw.mp4 --window 30
# best window : 18.5s -> 48.5s  (use --start 18.5 --end 48.5)
```

## 2. Framing: crop only when it is cheap

Full-bleed vertical always feels more native than bars — but not at any price.
`crop_loss()` computes the fraction of the source a full-bleed crop would
discard:

| Source | Loss cropping to 9:16 | Auto decision |
|---|---|---|
| 9:16 (1080×1920) | 0 % | crop |
| 9:19.5 (1080×2340) | 18 % | crop |
| 4:5 (1080×1350) | 30 % | crop |
| 1:1 | 44 % | smart fill |
| 16:9 | 68 % | smart fill |
| 21:9 | 76 % | smart fill |

Above 32 % loss the whole frame is kept and the gaps are filled with a
blurred, slightly darkened and desaturated copy of the frame itself —
CapCut's "blur background", which readers parse as intentional rather than as
a letterboxed TV clip. **Smart fill** goes one step further for ultra-wide
sources: the sides are trimmed toward 1.3:1 *first*, so the subject lands
noticeably larger before the blur fill is applied.

Use `--focus-x` / `--focus-y` when the subject is not centred (`0.0` = left /
top edge, `1.0` = right / bottom edge).

## 3. 60 fps, and what it costs

60 fps is the house standard: it is smoother in-feed, and both YouTube and
TikTok accept it natively.

* A 24/30 fps source is **duplicated** to 60 by default — zero artefacts,
  identical motion.
* `--interpolate` synthesises intermediate frames (`minterpolate`, motion
  compensated). It genuinely smooths slow camera moves, and it can smear fast
  action or anything with text and particles. It is opt-in for that reason.

## 4. Grading for compressed delivery

Platforms re-encode everything, hard. Heavy grades turn into banding; subtle
ones survive:

| Preset | Contrast | Saturation | Micro-contrast |
|---|---|---|---|
| `clean` | +5 % | +8 % | +0.32 |
| `vivid` | +11 % | +22 % | +0.48 |
| `cinematic` | medium S-curve | −2 % | +0.30 |
| `warm` | +6 % | +14 % | +0.35 |

Sharpening is applied **after** scaling (where it belongs) and is tuned to
survive re-encoding without ringing. `--denoise` is worth it on an already
compressed source: cleaner input means the platform's encoder spends its bits
on detail instead of noise.

## 5. Loudness is a retention feature

Every platform normalises to roughly −14 LUFS integrated. Deliver quieter and
your video is quieter than the next one in the feed; deliver louder and it
gets turned down, often with audible pumping. ViralCut measures the source
(EBU R128, pass 1) and applies a linear correction (pass 2) to land on
−14 LUFS / −1 dBTP.

Safety rails: a source measuring below −45 LUFS is treated as silent and left
alone rather than amplified into noise; sources without audio get a silent
AAC track so no platform rejects the upload.

## 6. The outro

0.65–0.70 s of blur-out resolving to black. Long enough to feel finished,
short enough that it does not eat completion rate. No end cards, no
subscribe animations — on a loop-based feed they are watched-time overhead.

## 7. Watermark placement

Top-left by default, at 5 % / 4.5 % margins: that corner is clear of TikTok's
caption and action rail, of Instagram's caption block, and of the Shorts
title and progress bar. The watermark is rasterised by Pillow and composited
*after* the intro and outro, so it is never blurred and is readable from the
very first frame.

## 8. Encoder settings

```
x264  CRF 18 · preset slow · high profile · level 4.2
      keyint 120 / min-keyint 60 · ref 4 · bframes 3 · aq-mode 3
      maxrate 24M · bufsize 48M · yuv420p · bt709 · CFR 60
AAC   320 kb/s · 48 kHz · stereo
MP4   +faststart
```

CRF 18 at 1080×1920/60 is visually transparent on phone screens while staying
inside the bitrate the platforms accept. `+faststart` puts the index at the
head of the file so upload-side processing starts immediately. The master is
BT.709-tagged, which stops washed-out or over-saturated colour after
transcoding.

## 9. What is deliberately absent

* **Captions / subtitles** — added only on request.
* **Voice-over / TTS** — added only on request.
* **Music and sound effects** — a licensing liability, and platform-native
  audio features (trending sounds added *at upload*) outperform baked-in beds.
* **Stock transitions and sting templates** — recognisably generic, and most
  "free" packs are not actually licensed for commercial use.

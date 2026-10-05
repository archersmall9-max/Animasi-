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

## 8. Comment captions

Off unless `--captions FILE` is passed. The file is a JSON list of
`{text, start, end}` in **output seconds** — the clock of the finished file,
intro included — with optional `position`, `scale`, `fade` and `align`.

```bash
python3 -m viralcut edit SRC --captions captions/orange-earless-cat.json -o OUT.mp4
```

**Where they go.** Anchored at 70 % of frame height, centred, wrapped to two
lines at most. Two bands are off limits: 11–22.5 % crosses the subject's face
on a vertical crop, and anything below 82 % collides with the Shorts title,
the progress bar and the action rail. `validate_captions` warns about lines
that overrun the cut, flash for under half a second, or overlap each other.

**How they are drawn.** This ffmpeg build has no `drawtext`, so each line is
rasterised by Pillow to an RGBA PNG — white fill, dark stroke, blurred drop
shadow — and composited with `overlay`. Captions chain *before* the
watermark, so branding always sits on top.

**Timing without `enable=`.** Every caption PNG is looped into a full-length
stream and gated by a pair of alpha fades:

```
format=rgba,loop=loop=-1:size=1,fps=FPS,trim=end=TOTAL,setpts=PTS-STARTPTS,
fade=t=in:st=START:d=F:alpha=1,fade=t=out:st=END-F:d=F:alpha=1
```

The fades *are* the gate: the stream is fully transparent outside the window.
The fade is clamped to half the caption's duration. Only when a caption asks
for `fade: 0` does the overlay take `enable='between(t,…)'` instead.

**Emoji.** `NotoColorEmoji.ttf` is a CBDT bitmap font: it rasterises at
exactly 109 px and nothing else. Each glyph is drawn at 109 px, cropped to
its bounding box and resampled to 0.98 × the line height, with
`embedded_color=True`. The shadow pass gets a black silhouette of the same
glyph so pale emoji keep their halo over pale footage. There is no `raqm`
shaper in this build, so **single-codepoint emoji only** — ZWJ sequences,
flags and skin-tone modifiers fall apart. Verified: 👀 🧡 😐 🍦 💀. With no
colour-emoji font installed the emoji is dropped with a warning rather than
rendered as tofu.

## 9. Montage and music

A montage is assembled by `viralcut/montage.py` into one intermediate video,
which the normal pipeline then treats as its source. That keeps framing,
grading, captions, watermark and the intro/outro in one place rather than
reimplemented twice. It costs one extra encode, so the intermediate is
written at CRF 10 — far above the delivery bitrate, where the loss is not
measurable in the final file.

**Cuts land on the beat.** `viralcut/beats.py` returns a beat grid;
`plan_shots(..., beats_per_shot=N)` gives each shot N beats. Four is one bar,
two is twice as fast, eight lets a moment breathe.

**Cut points are quantised to whole frames**, and this is not cosmetic.
ffmpeg rounds each shot's length up to a frame independently, so without it
the rounding accumulates: four shots at 30 fps drifted 82 ms by the end.
Quantising the cut times and deriving durations as the gaps between them
holds the error to half a frame and stops it compounding.

**Hard cuts and cross-fades are built differently.** `xfade` cannot do a
zero-length transition, so hard cuts — the more common shape — use `concat`
and skip the overlap arithmetic. A cross-fade needs one extra transition's
worth of footage from every shot *except the last*, which has nothing to
blend into; padding that one too runs the montage a transition long.

Two ffmpeg traps are handled in `_shot_chain`. Trimming happens by frame
count inside the graph, never with `-t` on the input, which cuts at the
first frame past the limit and rounds up. And `fps=` is reapplied after the
final `setpts`, because resetting timestamps leaves the stream with no
declared rate and `xfade` rejects it outright: *"current rate of 1/0 is
invalid"*.

```bash
python3 -m viralcut edit MONTAGE.mp4 --music track.mp3 -o OUT.mp4
```

**Music** is off unless `--music` is given. The track is looped rather than
allowed to run out, then trimmed, faded and normalised. Normalisation is
two-pass: single-pass `loudnorm` aims at the target rather than hitting it,
and landed 4.7 dB quiet on a test render. Since every platform normalises on
playback, a quiet master is not made louder — it just plays quieter than
everything around it.

One caveat worth recognising: if a track's true peak is already near the
ceiling while its integrated loudness is low — sparse percussion with a big
crest factor — no normaliser can reach −14 LUFS without clipping, and
`loudnorm` will fall back to dynamic mode and come up short. That is the
track, not the pipeline.

## 10. Encoder settings

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

## 11. What is deliberately absent

* **Captions / subtitles** — opt-in per job, see §8.
* **Voice-over / TTS** — added only on request.
* **Music by default** — opt-in per job with `--music`, see §9; a licensing
  liability otherwise, and platform-native
  audio features (trending sounds added *at upload*) outperform baked-in beds.
* **Stock transitions and sting templates** — recognisably generic, and most
  "free" packs are not actually licensed for commercial use.

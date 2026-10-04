# Delivery note — Orange the earless cat / ice cream

**Date:** 2026-10-04 · **Channel:** @Lowk67Tuff · **Primary platform:** YouTube Shorts

## Source as received

| | |
|---|---|
| File | `earlesspotato_1791122713122.mp4` (1.53 MB) |
| Format | 720×1280, 30 fps, H.264 High, ~774 kb/s video |
| Audio | AAC HE-AAC, 44.1 kHz stereo, 52 kb/s |
| Length | 15.53 s |
| sha256 | `e199d4703ecda5acf36d54e3d8ef1c3c9887c2b19852e5b2e335d06299aab713` |

The source is a platform re-encode, not a camera original: low bitrate, visible
blocking in the flat background, chroma smearing around the ice cream.

## Edit decisions, and why

**Trimmed the first 1.3 s.** The clip opens on 1.3 s of a motionless cat before
the ice cream enters at 1.5 s. On Shorts that is the whole hook window spent on
nothing. Starting at 1.30 s puts the ice cream in frame 0.75 s after the video
begins, immediately behind the intro reveal.

**Full-bleed crop, no bars.** Source is already 9:16, so the frame is used
whole and only enlarged 720→1080 (1.5×). Nothing is cropped away, no letterbox,
no blurred side panels.

**Denoise moved ahead of the upscale.** At 774 kb/s the compression artefacts
are the limiting factor, not resolution. Cleaning them at native 720p before
enlarging keeps the upscale from magnifying blocking; the sharpen pass then runs
after, on the clean 1080p frame. This changed `viralcut`'s filter order for all
upscaled sources, not just this job.

**No motion interpolation.** 30→60 fps was tested with `minterpolate`
(mci/aobmc/bidir). It softened fur detail and put wobble on the whiskers,
because the motion vectors are derived from already-artefacted pixels. The
master is true 60 fps CFR by frame conform instead — the spec is met and the
source detail survives. Interpolation would be worth revisiting on a
higher-bitrate original.

**Watermark style changed to `outline`.** Measured the top-left patch across the
clip: it swings from luma 109 to luma 191 as the shot opens up onto white
cabinets. A soft-shadow white mark disappears at the bright end. The black
outline reads on both. This is now the house default.

**Intro / outro.** `blurzoom` 0.45 s in, `blurout` 0.70 s out, both built from
the real first and last framed+graded frames, so they inherit the grade rather
than being generic cards. Watermark is composited after the concat, so it is
never blurred by either transition.

**Audio.** Measured −14.2 LUFS / −0.67 dBTP after a two-pass EBU R128 normalise.
The spectrogram shows a continuous mastered music bed with beat transients and
vocal harmonics up to a ~17 kHz codec cutoff — it is a song, not room tone. See
the risk note below.

## Output

| File | Audio | Use |
|---|---|---|
| `exports/CatIceCream_Shorts_MASTER.mp4` | original music, normalised | only if the music is cleared |
| `exports/CatIceCream_Shorts_NOMUSIC.mp4` | silent track | add platform-library audio at upload |

Both: 1080×1920, 60 fps CFR, H.264 High L4.2, CRF 17, yuv420p, bt709,
AAC 320 k 48 kHz, faststart, 15.38 s. No captions, no on-screen text, no
voice-over.

## Risks the uploader has to resolve before publishing

1. **Rights.** The footage belongs to **@earlesspotato** (Orange / "earless
   hachimi"), ~121 K followers on Instagram, ~93 K on TikTok. Written permission
   is needed before this goes anywhere. Credit alone is not a licence.
2. **Music.** The bed is almost certainly a licensed library track from the
   originating platform. Carrying it onto YouTube invites a Content ID claim.
   Use the `NOMUSIC` master and add audio from YouTube's own library.
3. **Reach.** As of 2026-10-01 YouTube's Shorts recommendation system explicitly
   reduces distribution for channels that mainly re-upload other creators' work
   without adding something of their own, and "minor technical edits" are named
   as not counting. The description in this pack carries the ear-surgery context
   and the lactose guidance specifically so the upload has original value
   attached to it — but one description does not make a re-upload original.
   A channel built on this will be throttled.

## Reproduce

```bash
python3 -m viralcut edit sources/raw_instagram.mp4 \
  --config config/lowk67tuff-shorts.json \
  --start 1.3 --denoise --sharpen 1.2 \
  -o exports/CatIceCream_Shorts_MASTER.mp4
# add --mute for the NOMUSIC variant
python3 -m viralcut meta briefs/orange-earless-cat-icecream.brief.json -o metadata/
```

# Production workflow

The exact sequence run for every delivery. House settings:
`config/lowk67tuff-shorts.json` — 1080 × 1920, 60 fps, `@Lowk67Tuff`
top-left, no voice-over, English metadata, YouTube Shorts first. Captions are
off by default and enabled per job with `--captions`.

---

## 1. Get the source

```bash
viralcut fetch "<URL>" -o sources/        # only for material you own/licensed
# or simply drop the file into sources/
```

Highest-quality copy available. Never a screen recording of a player, never a
re-encode of a re-encode — every generation costs detail the final encode
cannot restore.

## 2. Inspect

```bash
viralcut probe sources/clip.mp4
```

Resolution, true frame rate, duration, rotation flag, audio presence. This
decides the framing strategy and whether interpolation or denoising is worth
enabling.

## 3. Find the hook

```bash
viralcut analyze sources/clip.mp4 --window 35
```

Scene-change density plus momentary loudness, scored over a sliding window;
the suggested in-point is snapped to the nearest cut. Short-form lives or
dies in the first second, so the clip starts on the strongest moment rather
than on whatever happened to be first.

## 4. Render

```bash
viralcut edit sources/clip.mp4 \
  --config config/lowk67tuff-shorts.json \
  --start <hook> --max-duration <length> \
  -o "exports/<slug>_shorts_1080x1920_60fps.mp4"
```

Check `--dry-run` first if the framing decision needs confirming. Every
render writes `<output>.report.json`: source properties, framing decision,
timeline, loudness measurement and the full config.

## 5. Research the metadata

Done per video, never templated:

1. What the clip actually shows — subject, action, entities, the hook.
2. What the demand looks like — search phrasing, what the top videos on the
   subject already title themselves, what the comments ask for.
3. Where the gap is — the angle nobody has used yet.

Written into `briefs/<slug>.brief.json`, then:

```bash
viralcut meta briefs/<slug>.brief.json -o metadata/
```

Produces a copy-paste publishing pack plus validation against every platform
limit. See [METADATA_PLAYBOOK.md](METADATA_PLAYBOOK.md).

## 6. Deliver

* `exports/<slug>_shorts_1080x1920_60fps.mp4` — the master
* `exports/<slug>…report.json` — what was done, reproducibly
* `metadata/<slug>.md` — titles, description, hashtags, tags

Nothing from steps 1–6 is committed except the brief and the config.
See [COMPLIANCE.md](COMPLIANCE.md).

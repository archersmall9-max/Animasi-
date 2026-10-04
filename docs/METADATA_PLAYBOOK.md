# Metadata playbook

Titles, descriptions, hashtags and tags are not decoration — they are how a
video gets classified, recommended and found. This document describes the
research process that fills a brief, and the limits `viralcut meta` enforces.

---

## The process

1. **Identify what the video actually is.** Subject, setting, action, visible
   entities (people, products, places, games, songs), language, and the one
   moment that makes someone stop scrolling.
2. **Find the demand.** How do real people search for this? Collect the
   phrasing used in search suggestions, in the titles of the top-performing
   videos on the same subject, and in the comments under them. Note the
   language mix — a global audience usually means English-first with the
   local-language term kept where it is the actual name of the thing.
3. **Separate the layers.**
   * *Primary keyword* — the one phrase the video should rank for.
   * *Secondary keywords* — variants, synonyms, misspellings people type.
   * *Entities* — proper nouns the platform's classifier already understands.
   * *Broad topic* — the category the recommendation engine files it under.
4. **Write titles against the hook, not the summary.** Specific beats clever.
   A number, a stake, or an unexpected pairing earns the click; vague
   superlatives do not.
5. **Write the description for the first two lines.** That is all anyone sees
   before "more". Put the keyword-bearing sentence first, context second,
   call to action third, hashtags last.
6. **Pick hashtags by precision, not volume.** A handful of tags that
   genuinely describe the video outperform thirty generic ones, which read as
   spam to both the classifier and the viewer.
7. **Record the sources** you used in the brief, so the reasoning can be
   audited later instead of re-guessed.

## The brief

`briefs/example.brief.json` is the template. Fill it, then:

```bash
viralcut meta briefs/my-video.brief.json -o metadata/
```

You get `metadata/<slug>.md` (copy-paste ready, per platform) and
`metadata/<slug>.json` (machine readable), plus validation output.

## Limits enforced

| Platform | Title | Description / caption | Hashtags | Tags |
|---|---|---|---|---|
| YouTube | 100 (≈60 shown on mobile) | 5 000 | 3 recommended, 15 max in description | 500 characters total |
| TikTok | 150 | 2 200 | 30 max, 3–5 recommended | — |
| Instagram | 125 | 2 200 | 30 max, 3–8 recommended | — |
| Facebook | 255 | 5 000 | 30 max | — |
| Snapchat | 100 | 250 | 10 max | — |

`viralcut meta` reports:

* `✖ error` — over a hard limit, or malformed (the upload would be truncated
  or rejected)
* `▲ warn` — over a practical recommendation (e.g. a title too long to read
  on a phone)
* `· info` — optional improvement, such as a missing `#Shorts` marker

## Practical rules that survive platform changes

* **One idea per title.** If it needs a comma and a dash, it is two titles.
* **Front-load.** The first 40 characters of a title and the first 70 of a
  caption do the work.
* **No clickbait you do not pay off** in the first three seconds — the
  retention drop is measured and it suppresses the next upload too.
* **Do not recycle one caption across platforms.** YouTube rewards searchable
  phrasing, TikTok rewards conversational phrasing, Instagram rewards a short
  line plus precise tags.
* **Keep the handle in the description**, not only in the burned-in
  watermark: that is what people copy when they re-share.
* **Never put hashtags in the YouTube title** beyond one `#Shorts` — more
  looks like spam and YouTube ignores them anyway.

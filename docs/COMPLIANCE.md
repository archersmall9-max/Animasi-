# Repository & account safety

Everything in this document exists for one reason: **a repository (or a social
account) gets flagged for what it hosts and how it behaves, not for how good
the edit is.** The rules below are cheap to follow and remove almost every
realistic cause of a takedown, a strike or a suspension.

---

## 1. No media in Git — ever

`.gitignore` blocks every common video, audio and image-sequence extension,
plus the `sources/`, `downloads/`, `exports/`, `renders/` and `work/` folders.

Why it matters:

* **Copyright complaints.** A DMCA notice against a file in a public repo is
  handled by GitHub's DMCA process and is attached to the *account*, not just
  the file. Repeated notices end accounts. Code cannot be DMCA'd for
  containing someone else's footage if it never contains footage.
* **Size and history.** Binary files never deduplicate. One 80 MB clip
  committed and deleted still lives in history forever; large pushes get
  rejected and LFS budgets get consumed.
* **Privacy.** Raw footage frequently contains faces, locations, screen
  contents and metadata that were never meant to be public.

If a render must be shared, upload it to the destination platform or to
storage with an explicit link — not to the repository.

## 2. No vendored binaries or third-party assets

FFmpeg is **called**, never bundled: its builds are GPL/LGPL depending on
configuration, and redistributing one inside an MIT repository creates a
licence conflict. Likewise there are no bundled fonts, music beds, sound
effects, LUT packs or "viral template" files — those are the usual source of
licence violations in editing repositories.

Fonts: the watermark renderer looks for an optional
`assets/fonts/VC-Brand-Bold.ttf` that **you** provide, and otherwise falls
back to a font already installed on the system. Only add a font file here if
its licence explicitly allows redistribution (SIL OFL, Apache-2.0), and commit
the licence text next to it.

## 3. No credentials, cookies or tokens

`.gitignore` covers `.env`, `*.pem`, `*.key`, `cookies.txt`, `credentials.json`
and `token*.json`. Secret scanning flags leaked platform tokens, and a leaked
upload token is an account-takeover risk, not just an embarrassment.

Nothing in this project needs an API key.

## 4. Fetching sources: ownership first

`viralcut fetch` is a thin wrapper around [yt-dlp](https://github.com/yt-dlp/yt-dlp),
kept as an **optional** dependency, and it prints a rights notice every run.
It does not bypass DRM, does not touch paywalled content, and does not bulk
scrape.

Use it only for material you own, created, commissioned, or hold a licence to
reuse (including clearly licensed Creative Commons work — credit the author in
the description). Re-uploading someone else's video without permission gets
the *upload* removed and the *account* struck; no edit quality compensates for
that.

If a source cannot be fetched, export it from the platform you own it on and
pass the local path to `viralcut edit`.

## 5. No automation that looks like abuse

This project deliberately contains **no** auto-uploader, no scheduler, no
engagement bot, no view/like automation and no multi-account tooling. Those
features violate every major platform's terms of service and are the fastest
route to a permanent ban. Rendering is local; publishing stays a human action.

## 6. Keep the repository itself legible

Repositories get flagged as spam for keyword-stuffed READMEs, hundreds of
generated files, misleading names and bulk automated commits. This one keeps
a plain description, a real licence, a test suite and human-readable commits.

## 7. Platform-side safety of the output

The renderer also avoids the things that get *uploads* suppressed:

* no third-party music or sound effects are ever added — the audio track is
  the source's own, loudness-normalised;
* no text, captions or subtitles are burned in unless explicitly requested;
* no borrowed intro stingers or template packs — intro and outro are
  generated from the clip's own frames;
* output is a clean H.264/AAC MP4 inside every platform's documented limits,
  so nothing is rejected at upload time.

---

### Quick checklist before pushing

```text
[ ] git status shows no .mp4 / .mov / .wav / .png renders
[ ] no .env, cookies.txt, tokens or API keys
[ ] no vendored ffmpeg / fonts / music / LUTs
[ ] commit message describes a real change
[ ] tests pass:  pytest
```

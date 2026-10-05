# deliverables/

Finished masters, ready to upload. **This is the one place in the repository
where a video file is allowed to live.**

`.gitignore` rule #1 is that source and rendered media never enter git, because
third-party footage in a public repository is the fastest route to a DMCA
notice and a flagged account. That rule still stands everywhere else —
`exports/`, `work/`, `sources/` and `downloads/` stay ignored.

The exception exists because the sandbox cannot hand a file to the user any
other way: `uploads.github.com` is blocked, so `gh release upload` fails, and
anything under an ignored path is invisible in the file browser. A master that
nobody can download is not a deliverable.

A file may only be committed here if **both** are true:

1. The footage is public domain, or licensed for redistribution, or shot by us.
2. Every piece of audio is cleared the same way, and its attribution is
   recorded in the matching `metadata/<slug>.md`.

Anything with ordinary studio footage in it — an anime rip, a reposted clip,
a commercial track — does **not** go here. Render it to `exports/` and hand the
user the file some other way.

## Contents

### `NamakuraGatana_Shorts_MASTER.mp4`

1080x1920 · 60 fps · 27.07 s · −14.1 LUFS · 22.7 MB

A beat-synced montage cut from *Namakura Gatana* (なまくら刀, "The Dull Sword",
1917) by Jun'ichi Kōuchi — one of the oldest surviving Japanese animations.

- **Film:** public domain. Restored by the National Film Center, National
  Museum of Modern Art, Tokyo; the print came from Wikimedia Commons.
- **Music:** "Ishikari Lore" by Kevin MacLeod (incompetech.com), licensed
  under Creative Commons: By Attribution 4.0 —
  <http://creativecommons.org/licenses/by/4.0/>
  **The attribution must appear in the video description.** It is already
  written into `metadata/namakura-gatana-1917.md`; deleting it voids the
  licence.

Rebuild it with `python3 build_anime_montage.py` (needs `work/anime_full.mp4`,
a full-frame 1350x1060 H.264 proxy of the source film).

# inbox/ — temporary source transfer

A drop folder for getting a source file onto a machine that cannot reach the
platform it lives on. **Temporary by definition**: nothing here is meant to
stay in the repository.

## Upload from a browser (works on a phone)

1. Open the repository on github.com.
2. **Add file → Upload files** (on a phone, switch the browser to desktop
   mode if the button is hidden).
3. Drag in the video. Keep the name simple: `raw.mp4`.
   *Browser uploads are capped at 25 MB per file. Larger files need git.*
4. Under *Commit changes*, choose **"Create a new branch for this commit"**
   and name it `inbox-upload`.
5. Commit.

## Upload with git (no size limit below 100 MB)

```bash
git checkout -b inbox-upload
cp /path/to/raw.mp4 inbox/raw.mp4
git add -f inbox/raw.mp4        # -f because .gitignore blocks media
git commit -m "chore: temporary source upload"
git push origin inbox-upload
```

## Afterwards

The file is pulled out of the branch without merging it:

```bash
git fetch origin inbox-upload
git show origin/inbox-upload:inbox/raw.mp4 > sources/raw.mp4
```

Then **delete the `inbox-upload` branch on GitHub**. The blob becomes
unreachable and is garbage-collected; the working branches never carry it.

CI will flag a media file on that branch — that is the compliance check doing
its job, not a failure. The branch is never merged.

See [../docs/COMPLIANCE.md](../docs/COMPLIANCE.md).

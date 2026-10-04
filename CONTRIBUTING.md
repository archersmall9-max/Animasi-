# Contributing

Thanks for taking a look. A few things keep this project predictable.

## Ground rules

1. **No media, no binaries, no third-party assets in commits.**
   See [docs/COMPLIANCE.md](docs/COMPLIANCE.md). CI enforces this.
2. **Tests generate their own footage.** Use the fixtures in
   `tests/conftest.py` or `scripts/make_test_clip.py`; never add a sample file.
3. **Every behaviour change needs a test**, and every new filter chain needs a
   test that asserts the resulting graph, not just that it ran.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m viralcut doctor
```

## Before opening a pull request

```bash
ruff check .
pytest -q
```

Keep commits small and the messages descriptive — `fix: last-frame extraction
returned no frame when seeking past the final keyframe` beats `update`.

## Design principles

* **Deterministic.** The same input and config must always produce the same
  output. No hidden randomness.
* **One encode of the body.** Intermediate re-encodes cost quality; build the
  whole filter graph instead.
* **Quality first, convenience second.** If a feature needs a quality
  trade-off (motion interpolation, aggressive sharpening), it is opt-in and
  documented.
* **Nothing is added to the viewer's video that was not requested** — no
  captions, no voice-over, no music.

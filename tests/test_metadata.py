from __future__ import annotations

import json

from viralcut.metadata import LIMITS, MetadataPack, build

BRIEF = {
    "slug": "demo-clip",
    "topic": "Demo clip",
    "summary": "A short demo.",
    "platforms": ["youtube", "tiktok", "instagram"],
    "titles": {
        "default": ["A clean, specific title that reads well on a phone", "Alt title"],
        "youtube": ["Why this looks so smooth at 60fps #Shorts"],
    },
    "descriptions": {"default": "What you are watching and why it matters."},
    "hashtags": {"core": ["#demo", "#shorts"], "niche": ["#60fps"], "broad": ["#viral"]},
    "tags": ["demo", "short video", "60fps"],
    "cta": "Follow @Lowk67Tuff for more.",
    "research": {"primary_keyword": "demo clip", "competition": "low"},
    "sources": ["https://example.com"],
}


def test_builds_every_requested_platform():
    pack = MetadataPack.from_brief(BRIEF)
    assert set(pack.platforms) == {"youtube", "tiktok", "instagram"}
    assert pack.ok


def test_platform_specific_title_wins():
    pack = MetadataPack.from_brief(BRIEF)
    assert pack.platforms["youtube"]["title"].endswith("#Shorts")
    assert pack.platforms["tiktok"]["title"].startswith("A clean, specific title")


def test_description_contains_cta_and_hashtags():
    desc = MetadataPack.from_brief(BRIEF).platforms["tiktok"]["description"]
    assert "Follow @Lowk67Tuff" in desc
    assert "#demo" in desc


def test_youtube_caps_hashtags_at_three_and_tags_at_500_chars():
    brief = dict(BRIEF)
    brief["hashtags"] = {"core": [f"#tag{i}" for i in range(12)]}
    brief["tags"] = [f"keyword number {i}" for i in range(80)]
    pack = MetadataPack.from_brief(brief)
    yt = pack.platforms["youtube"]
    assert len(yt["hashtags"]) == 3
    assert yt["tags_char_count"] <= LIMITS["youtube"]["tags_total"]
    assert pack.ok


def test_too_long_title_is_an_error():
    brief = dict(BRIEF)
    brief["titles"] = {"default": ["x" * 160]}
    pack = MetadataPack.from_brief(brief)
    assert not pack.ok
    assert any("exceeds" in str(i) for i in pack.issues)


def test_malformed_hashtag_is_rejected():
    brief = dict(BRIEF)
    brief["hashtags"] = {"core": ["#not a tag"]}
    pack = MetadataPack.from_brief(brief)
    assert not pack.ok


def test_missing_title_is_an_error():
    brief = dict(BRIEF)
    brief["titles"] = {}
    assert not MetadataPack.from_brief(brief).ok


def test_markdown_and_json_written(tmp_path):
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(BRIEF), encoding="utf-8")
    md, js, pack = build(brief_path, tmp_path / "out")
    assert md.exists() and js.exists()
    text = md.read_text(encoding="utf-8")
    assert "# Publishing pack" in text
    assert "Youtube" in text and "Tiktok" in text
    assert json.loads(js.read_text())["platforms"]["tiktok"]["hashtags"]
    assert pack.ok

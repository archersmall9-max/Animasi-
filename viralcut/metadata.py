"""Publishing metadata builder.

The *creative* input (what the video is actually about, which keywords real
people search for, which angle the algorithm rewards) comes from research and
lives in a JSON brief. This module turns that brief into per-platform packs
and — just as importantly — validates them against each platform's hard
limits so nothing gets silently truncated at upload time.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Hard platform limits (2026). Soft recommendations in RECOMMENDED.
LIMITS: dict[str, dict[str, int]] = {
    "youtube": {"title": 100, "description": 5000, "tags_total": 500, "hashtags_in_desc": 15},
    "tiktok": {"title": 150, "description": 2200, "hashtags": 30},
    "instagram": {"title": 125, "description": 2200, "hashtags": 30},
    "facebook": {"title": 255, "description": 5000, "hashtags": 30},
    "snapchat": {"title": 100, "description": 250, "hashtags": 10},
}

RECOMMENDED: dict[str, dict[str, Any]] = {
    "youtube": {"title": 60, "hashtags": 3, "note": "First 40-60 chars are what a phone shows."},
    "tiktok": {"title": 90, "hashtags": 5, "note": "Caption competes with UI; front-load the hook."},
    "instagram": {"title": 125, "hashtags": 8, "note": "3-8 precise tags beat 30 generic ones."},
    "facebook": {"title": 80, "hashtags": 3, "note": "Reels inherit the caption; keep it punchy."},
    "snapchat": {"title": 60, "hashtags": 3, "note": "Spotlight favours topics over hashtags."},
}

_HASHTAG_RE = re.compile(r"^#[A-Za-z0-9_]+$")


@dataclass
class Issue:
    level: str   # "error" | "warn" | "info"
    platform: str
    field: str
    message: str

    def __str__(self) -> str:
        icon = {"error": "✖", "warn": "▲", "info": "·"}.get(self.level, "·")
        return f"{icon} [{self.platform}/{self.field}] {self.message}"


@dataclass
class MetadataPack:
    brief: dict[str, Any]
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    # ---------------------------------------------------------------- build
    @classmethod
    def from_brief(cls, brief: dict[str, Any]) -> MetadataPack:
        pack = cls(brief=brief)
        for platform in brief.get("platforms", ["youtube", "tiktok", "instagram"]):
            pack.platforms[platform] = pack._build_platform(platform)
        pack.validate()
        return pack

    def _build_platform(self, platform: str) -> dict[str, Any]:
        brief = self.brief
        titles = (brief.get("titles") or {}).get(platform) or (brief.get("titles") or {}).get("default") or []
        descriptions = brief.get("descriptions") or {}
        body = descriptions.get(platform) or descriptions.get("default") or ""
        hashtags = self._hashtags_for(platform)
        data: dict[str, Any] = {
            "titles": list(titles),
            "title": titles[0] if titles else "",
            "description": self._compose_description(platform, body, hashtags),
            "hashtags": hashtags,
        }
        if platform == "youtube":
            data["tags"] = self._youtube_tags()
            data["tags_char_count"] = len(", ".join(data["tags"]))
        return data

    def _hashtags_for(self, platform: str) -> list[str]:
        groups = self.brief.get("hashtags") or {}
        if platform in groups and isinstance(groups[platform], list):
            tags = list(groups[platform])
        else:
            tags = [*groups.get("core", []), *groups.get("niche", []), *groups.get("broad", [])]
        limit = int(RECOMMENDED.get(platform, {}).get("hashtags", 8))
        if platform == "youtube":
            limit = 3
        seen: list[str] = []
        for tag in tags:
            tag = tag if tag.startswith("#") else f"#{tag}"
            if tag.lower() not in {t.lower() for t in seen}:
                seen.append(tag)
        return seen[:limit] if platform in {"youtube", "tiktok"} else seen[: max(limit, 8)]

    def _compose_description(self, platform: str, body: str, hashtags: list[str]) -> str:
        parts = [body.strip()] if body.strip() else []
        cta = (self.brief.get("cta") or "").strip()
        credit = (self.brief.get("credit") or "").strip()
        if cta:
            parts.append(cta)
        if credit:
            parts.append(credit)
        if hashtags:
            parts.append(" ".join(hashtags))
        return "\n\n".join(parts).strip()

    def _youtube_tags(self) -> list[str]:
        raw: list[str] = list(self.brief.get("tags") or [])
        out: list[str] = []
        budget = LIMITS["youtube"]["tags_total"]
        used = 0
        for tag in raw:
            tag = tag.strip()
            if not tag:
                continue
            cost = len(tag) + (2 if out else 0)
            if used + cost > budget:
                continue
            out.append(tag)
            used += cost
        return out

    # ------------------------------------------------------------- validate
    def validate(self) -> list[Issue]:
        self.issues = []
        for platform, data in self.platforms.items():
            limits = LIMITS.get(platform, {})
            rec = RECOMMENDED.get(platform, {})
            title = data.get("title", "")
            if not title:
                self.issues.append(Issue("error", platform, "title", "missing title"))
            else:
                if "title" in limits and len(title) > limits["title"]:
                    self.issues.append(Issue(
                        "error", platform, "title",
                        f"{len(title)} chars exceeds the {limits['title']} limit"))
                elif "title" in rec and len(title) > rec["title"]:
                    self.issues.append(Issue(
                        "warn", platform, "title",
                        f"{len(title)} chars — over the {rec['title']} recommended for mobile"))
            desc = data.get("description", "")
            if "description" in limits and len(desc) > limits["description"]:
                self.issues.append(Issue(
                    "error", platform, "description",
                    f"{len(desc)} chars exceeds the {limits['description']} limit"))
            tags = data.get("hashtags", [])
            bad = [t for t in tags if not _HASHTAG_RE.match(t)]
            if bad:
                self.issues.append(Issue(
                    "error", platform, "hashtags",
                    f"invalid (letters, digits and _ only): {', '.join(bad)}"))
            max_tags = limits.get("hashtags")
            if max_tags and len(tags) > max_tags:
                self.issues.append(Issue(
                    "error", platform, "hashtags", f"{len(tags)} exceeds the {max_tags} limit"))
            if platform == "youtube":
                count = data.get("tags_char_count", 0)
                if count > LIMITS["youtube"]["tags_total"]:
                    self.issues.append(Issue(
                        "error", platform, "tags",
                        f"{count} chars exceeds YouTube's 500-char tag budget"))
                if "#shorts" not in (title + " " + desc).lower():
                    self.issues.append(Issue(
                        "info", platform, "title",
                        "no #Shorts marker — harmless, but it helps classification"))
        return self.issues

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    # --------------------------------------------------------------- output
    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.brief.get("topic", ""),
            "summary": self.brief.get("summary", ""),
            "research": self.brief.get("research", {}),
            "platforms": self.platforms,
            "issues": [str(i) for i in self.issues],
        }

    def render_markdown(self) -> str:
        b = self.brief
        lines: list[str] = []
        lines.append(f"# Publishing pack — {b.get('topic', 'untitled')}")
        if b.get("summary"):
            lines += ["", b["summary"]]
        research = b.get("research") or {}
        if research:
            lines += ["", "## Research snapshot", ""]
            for key, value in research.items():
                label = key.replace("_", " ").capitalize()
                if isinstance(value, list):
                    lines.append(f"- **{label}:** {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"- **{label}:** {value}")
        for platform, data in self.platforms.items():
            lines += ["", f"## {platform.capitalize()}", ""]
            titles = data.get("titles") or []
            if titles:
                lines.append("**Title options**")
                lines.append("")
                for i, title in enumerate(titles, 1):
                    flag = " ← primary" if i == 1 else ""
                    lines.append(f"{i}. `{title}`  _({len(title)} chars){flag}_")
                lines.append("")
            lines.append("**Description**")
            lines.append("")
            lines.append("```text")
            lines.append(data.get("description", ""))
            lines.append("```")
            if data.get("hashtags"):
                lines += ["", f"**Hashtags ({len(data['hashtags'])}):** " + " ".join(data["hashtags"])]
            if data.get("tags"):
                lines += [
                    "",
                    f"**Tags ({data.get('tags_char_count', 0)}/500 chars):**",
                    "",
                    "```text",
                    ", ".join(data["tags"]),
                    "```",
                ]
        if self.issues:
            lines += ["", "## Validation", ""]
            lines += [f"- {issue}" for issue in self.issues]
        if b.get("sources"):
            lines += ["", "## Sources consulted", ""]
            lines += [f"- {s}" for s in b["sources"]]
        lines.append("")
        return "\n".join(lines)


def load_brief(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build(brief_path: str | Path, out_dir: str | Path) -> tuple[Path, Path, MetadataPack]:
    """Build markdown + JSON packs from a brief. Returns ``(md, json, pack)``."""
    brief = load_brief(brief_path)
    pack = MetadataPack.from_brief(brief)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = _slugify(brief.get("slug") or brief.get("topic") or "publishing-pack")
    md_path = out / f"{slug}.md"
    json_path = out / f"{slug}.json"
    md_path.write_text(pack.render_markdown(), encoding="utf-8")
    json_path.write_text(json.dumps(pack.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return md_path, json_path, pack


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "publishing-pack"


def hashtag_budget(tags: Iterable[str], platform: str) -> str:
    tags = list(tags)
    limit = LIMITS.get(platform, {}).get("hashtags", 30)
    return f"{len(tags)}/{limit}"

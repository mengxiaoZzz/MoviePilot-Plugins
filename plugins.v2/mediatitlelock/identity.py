from dataclasses import dataclass
from typing import Any, Optional


SOURCE_ALIASES = {
    "tmdb": "themoviedb",
    "themoviedb": "themoviedb",
    "douban": "douban",
    "bangumi": "bangumi",
    "anilist": "anilist",
}

@dataclass(frozen=True)
class MediaIdentity:
    """媒体来源内唯一身份。"""

    media_source: str
    media_id: str


def normalize_source(value: Any) -> str:
    """标准化媒体来源名称。"""

    source = str(value or "").strip().casefold()
    return SOURCE_ALIASES.get(source, source)


def extract_media_identity(mediainfo: Any) -> Optional[MediaIdentity]:
    """从 MoviePilot MediaInfo 提取媒体来源和来源内 ID。"""

    if mediainfo is None:
        return None

    source = normalize_source(getattr(mediainfo, "source", None))
    media_id = getattr(mediainfo, "media_id", None)
    source_ids = (
        ("themoviedb", getattr(mediainfo, "tmdb_id", None)),
        ("douban", getattr(mediainfo, "douban_id", None)),
        ("bangumi", getattr(mediainfo, "bangumi_id", None)),
        ("anilist", getattr(mediainfo, "anilist_id", None)),
    )

    if not source:
        source, media_id = next(
            ((item_source, item_id) for item_source, item_id in source_ids if item_id is not None),
            ("", None),
        )
    elif media_id is None:
        media_id = next(
            (item_id for item_source, item_id in source_ids if item_source == source),
            None,
        )

    if not source or media_id is None or not str(media_id).strip():
        return None
    return MediaIdentity(
        media_source=source,
        media_id=str(media_id).strip(),
    )


def apply_locked_title(rename_dict: dict, title: str, year: Optional[str]) -> None:
    """把锁定的标题和年份写入 MoviePilot 重命名上下文。"""

    locked_title = str(title or "").strip()
    locked_year = str(year or "").strip()
    if not locked_title:
        return
    rename_dict["title"] = locked_title
    if locked_year:
        rename_dict["year"] = locked_year
        rename_dict["title_year"] = f"{locked_title} ({locked_year})"
    else:
        rename_dict["title_year"] = locked_title

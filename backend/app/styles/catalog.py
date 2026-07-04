"""視覺風格與色盤目錄：掃描 styles/ 下的 markdown 檔，解析 frontmatter。

styles/ 位於專案根目錄（不在 backend/ 下），故本模組以「相對於本檔案
往上找到含 styles/ 的目錄」定位 repo 根，而非硬編碼路徑。掃描結果快取
於模組層 dict，避免每次呼叫都重新讀檔／解析。
"""

from pathlib import Path

# frontmatter 只有三個固定 key，手寫解析即可，不必引入 pyyaml 依賴。
_FRONTMATTER_KEYS = ("id", "name_zh", "tagline_zh")

_cache: dict[tuple[str, str], dict[str, dict]] = {}


class StyleCatalogError(Exception):
    """風格／色盤目錄讀取或解析失敗（訊息對使用者友善，不洩漏內部細節）。"""


def _default_repo_root() -> Path:
    """從本檔案往上找到第一個含 styles/visual 與 styles/palettes 的祖先目錄。

    注意：backend/app/styles（本模組所在目錄）本身不叫 styles/visual，
    所以用 visual + palettes 兩個子目錄同時存在來判定，避免誤認本模組
    的所在目錄（app/styles）為 repo 根。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "styles" / "visual").is_dir() and (
            parent / "styles" / "palettes"
        ).is_dir():
            return parent
    raise StyleCatalogError("找不到專案根目錄下的 styles/ 目錄")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析檔案開頭 `--- ... ---` 區塊的 `key: value` 行，回傳 (meta, 正文)。

    正文為 frontmatter 區塊（含前後 `---` 分隔線）之後的內容。
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise StyleCatalogError("檔案缺少 frontmatter 區塊（開頭需為 ---）")

    meta: dict[str, str] = {}
    body_start = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = i + 1
            break
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key in _FRONTMATTER_KEYS:
                meta[key] = value

    if body_start is None:
        raise StyleCatalogError("檔案缺少 frontmatter 結束分隔線（---）")

    missing = [k for k in _FRONTMATTER_KEYS if k not in meta]
    if missing:
        raise StyleCatalogError(f"frontmatter 缺少必要欄位：{'、'.join(missing)}")

    body = "".join(lines[body_start:]).lstrip("\n")
    return meta, body


def _scan_dir(directory: Path) -> dict[str, dict]:
    """掃描目錄下所有 .md 檔，回傳 {id: {"meta": ..., "body": ...}}。"""
    entries: dict[str, dict] = {}
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        entries[meta["id"]] = {"meta": meta, "body": body}
    return entries


def _get_entries(kind: str, base_dir: Path | None) -> dict[str, dict]:
    root = base_dir if base_dir is not None else _default_repo_root()
    cache_key = (kind, str(root))
    if cache_key not in _cache:
        _cache[cache_key] = _scan_dir(root / "styles" / kind)
    return _cache[cache_key]


def clear_cache() -> None:
    """清除模組層快取（測試用；亦可在檔案異動後重新載入時呼叫）。"""
    _cache.clear()


def list_styles(base_dir: Path | None = None) -> list[dict[str, str]]:
    """回傳所有視覺風格的 {"id", "name_zh", "tagline_zh"} 清單。"""
    entries = _get_entries("visual", base_dir)
    return [dict(entry["meta"]) for entry in entries.values()]


def load_style(style_id: str, base_dir: Path | None = None) -> str:
    """回傳指定風格的正文（frontmatter 以下的原始內容）。

    不存在的 style_id 會 raise KeyError。
    """
    entries = _get_entries("visual", base_dir)
    if style_id not in entries:
        raise KeyError(f"找不到視覺風格：{style_id}")
    return entries[style_id]["body"]


def list_palettes(base_dir: Path | None = None) -> list[dict[str, str]]:
    """回傳所有色盤的 {"id", "name_zh", "tagline_zh"} 清單。"""
    entries = _get_entries("palettes", base_dir)
    return [dict(entry["meta"]) for entry in entries.values()]


def load_palette(palette_id: str, base_dir: Path | None = None) -> str:
    """回傳指定色盤的正文（frontmatter 以下的原始內容）。

    不存在的 palette_id 會 raise KeyError。
    """
    entries = _get_entries("palettes", base_dir)
    if palette_id not in entries:
        raise KeyError(f"找不到色盤：{palette_id}")
    return entries[palette_id]["body"]

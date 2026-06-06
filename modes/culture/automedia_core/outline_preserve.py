from __future__ import annotations

import json
import shutil
from pathlib import Path


OUTLINE_JSON_NAME = "00_分集解读大纲.json"
PRESERVED_OUTLINE_NAMES = (
    OUTLINE_JSON_NAME,
    "00_分集解读大纲_可读.txt",
    "raw_00_模型返回_大纲.txt",
)
OUTLINE_BACKUP_DIR_NAME = "小猪理工程备份"


def _valid_outline_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    return isinstance(data, dict) and bool(data.get("episodes"))


def outline_backup_root(book_path: Path | None, out_dir: Path) -> Path:
    if book_path:
        try:
            book = Path(book_path).expanduser()
            if book.suffix.lower() == ".pdf":
                return book.parent / OUTLINE_BACKUP_DIR_NAME
        except Exception:
            pass
    return Path(out_dir).expanduser().parent / OUTLINE_BACKUP_DIR_NAME


def backup_outline_files_before_clear(out_dir: Path, book_path: Path | None = None) -> list[Path]:
    out_dir = Path(out_dir).expanduser()
    backup_root = outline_backup_root(book_path, out_dir)
    candidates: list[Path] = []
    for root in (out_dir, out_dir / "短视频素材"):
        for name in PRESERVED_OUTLINE_NAMES:
            path = root / name
            if path.exists() and path.is_file():
                candidates.append(path)
    copied: list[Path] = []
    for source in candidates:
        try:
            backup_root.mkdir(parents=True, exist_ok=True)
            target = backup_root / source.name
            shutil.copy2(source, target)
            copied.append(target)
        except Exception:
            continue
    return copied


def find_existing_outline_for_book_and_output(book_path: Path | None, out_dir: Path) -> Path | None:
    out_dir = Path(out_dir).expanduser()
    roots: list[Path] = [
        out_dir,
        out_dir / "短视频素材",
        out_dir / "outputs",
        out_dir / "output",
        out_dir.parent,
        out_dir.parent / OUTLINE_BACKUP_DIR_NAME,
    ]
    if book_path:
        try:
            book_parent = Path(book_path).expanduser().parent
            roots.extend(
                [
                    book_parent,
                    book_parent / OUTLINE_BACKUP_DIR_NAME,
                    book_parent / "短视频素材",
                    book_parent / "outputs",
                    book_parent / "output",
                ]
            )
        except Exception:
            pass

    seen: set[Path] = set()
    for root in roots:
        try:
            path = (root / OUTLINE_JSON_NAME).resolve()
        except Exception:
            path = root / OUTLINE_JSON_NAME
        if path in seen:
            continue
        seen.add(path)
        if path.exists() and _valid_outline_json(path):
            return path

    for root in roots:
        try:
            for path in root.glob(f"*/{OUTLINE_JSON_NAME}"):
                if path.exists() and _valid_outline_json(path):
                    return path
        except Exception:
            continue
    return None

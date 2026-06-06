from __future__ import annotations

import argparse
import json
from pathlib import Path

from .split_assets import rebuild_split_cover_cards


def main() -> None:
    parser = argparse.ArgumentParser(
        description="只根据分集小标题中间文件重做分集封面，不重跑拆分、台词或正文配图。"
    )
    parser.add_argument("--episode-dir", type=str, default="", help="分集目录，例如 outputs/.../episodes/EP02_xxx")
    parser.add_argument("--split-root", type=str, default="", help="拆分目录，例如 EP02_xxx/07_拆分脚本与配图")
    parser.add_argument("--output-name", type=str, default="07_拆分脚本与配图", help="拆分输出目录名，默认 07_拆分脚本与配图")
    args = parser.parse_args()

    episode_dir = Path(args.episode_dir) if args.episode_dir else None
    split_root = Path(args.split_root) if args.split_root else None
    if episode_dir is None and split_root is None:
        raise SystemExit("请提供 --episode-dir 或 --split-root。")

    result = rebuild_split_cover_cards(episode_dir, split_root=split_root, output_name=args.output_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n已完成：只重做分集封面，并同步更新每个分集 images/001_A1_封面.png。")


if __name__ == "__main__":
    main()

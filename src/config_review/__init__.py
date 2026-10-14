import sys
from pathlib import Path

from config_review.apply import apply_changes
from config_review.diff import diff_trees
from config_review.parser import parse_config


def main() -> None:
    """現行 Config と投入 Config を読み込み、投入後に変わる部分を表示する。"""
    if len(sys.argv) != 3:
        print("使い方: config-review <現行の running-config> <投入する Config>")
        sys.exit(1)

    current = parse_config(Path(sys.argv[1]).read_text(encoding="utf-8"))
    changes = parse_config(Path(sys.argv[2]).read_text(encoding="utf-8"))
    expected = apply_changes(current, changes)

    lines = diff_trees(current, expected)
    if lines:
        print("\n".join(lines))
    else:
        print("差分はありません（投入しても Config は変わりません）")

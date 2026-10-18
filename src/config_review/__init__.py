import sys
from pathlib import Path

from config_review.compare import compare, problem_lines, read_config_file


def main() -> None:
    """現行 Config と投入 Config を読み込み、投入後に変わる部分を表示する。"""
    if len(sys.argv) != 3:
        print("使い方: config-review <現行の running-config> <投入する Config>")
        print("画面で使うとき: config-review-gui")
        sys.exit(1)

    try:
        result = compare(
            read_config_file(Path(sys.argv[1])),
            read_config_file(Path(sys.argv[2])),
        )
    except (OSError, ValueError) as error:  # ファイルがない、「vlan 10-2」のような読めない書き方 など
        print(f"比較できませんでした：{error}")
        sys.exit(1)

    for line in problem_lines(result):
        print(line)

    if result.diff:
        print("\n".join(result.diff))
    else:
        print("差分はありません（投入しても Config は変わりません）")

    if result.notes:
        print()
        for note in result.notes:
            print(f"※ {note}")

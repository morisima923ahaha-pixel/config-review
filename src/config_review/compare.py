"""現行 Config と投入 Config の文字列から、想定 Config と差分を作る（CLI と GUI の共通の入り口）。"""

from dataclasses import dataclass
from pathlib import Path

from config_review.apply import apply_changes
from config_review.diff import diff_trees
from config_review.normalize import parse_changes, parse_running
from config_review.parser import to_text


@dataclass
class CompareResult:
    expected: str  # 投入後の想定 Config
    diff: list[str]  # 差分の行（先頭が "-" "+" " "）
    notes: list[str]  # 投入 Config の書き方をそろえたときのメモ


def read_config_file(path: Path) -> str:
    """Config のファイルを読む。UTF-8 で読めなければ Shift_JIS（Windows の日本語）で読む。

    Tera Term のログなど、Windows で保存したファイルは Shift_JIS のことがあるため。
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932", errors="replace")


def compare(current_text: str, changes_text: str) -> CompareResult:
    current = parse_running(current_text)
    changes, notes = parse_changes(changes_text)
    expected = apply_changes(current, changes)
    return CompareResult(
        expected=to_text(expected),
        diff=diff_trees(current, expected),
        notes=notes,
    )

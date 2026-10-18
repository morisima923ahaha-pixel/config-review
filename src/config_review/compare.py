"""現行 Config と投入 Config の文字列から、想定 Config と差分を作る（CLI と GUI の共通の入り口）。"""

from dataclasses import dataclass
from pathlib import Path

from config_review.apply import apply_changes
from config_review.checks import Problem
from config_review.diff import diff_trees
from config_review.normalize import parse_changes, parse_running
from config_review.parser import to_text


@dataclass
class CompareResult:
    expected: str  # 投入後の想定 Config
    diff: list[str]  # 差分の行（先頭が "-" "+" " "）
    notes: list[str]  # 投入 Config の書き方をそろえたときのメモ
    problems: list[Problem]  # 実機ではエラーになるはずの行・確認してほしい行

    @property
    def errors(self) -> list[Problem]:
        """実機ではエラーで入らないはずの行（想定 Config には入れていない）。"""
        return [p for p in self.problems if p.rejected]

    @property
    def warnings(self) -> list[Problem]:
        """入るかどうかを Config だけでは判断できず、確認してほしい行。"""
        return [p for p in self.problems if not p.rejected]


def read_config_file(path: Path) -> str:
    """Config のファイルを読む。UTF-8 で読めなければ Shift_JIS（Windows の日本語）で読む。

    Tera Term のログなど、Windows で保存したファイルは Shift_JIS のことがあるため。
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932", errors="replace")


def problem_lines(result: CompareResult) -> list[str]:
    """差分の前に出す、エラーになるはずの行と確認してほしい行の一覧（CLI と GUI で共通）。

    見落とされると作業当日に「入っていない！」となるので、差分より先に目立たせて出す。
    """
    lines: list[str] = []
    if result.errors:
        lines.append(f"【エラー】実機ではエラーになって入らないはずの行が {len(result.errors)} 件あります（想定 Config には入れていません）")
        lines += [f"  × {p}" for p in result.errors]
    if result.warnings:
        lines.append(f"【要確認】Config だけでは入るかどうか判断できない行が {len(result.warnings)} 件あります")
        lines += [f"  △ {p}" for p in result.warnings]
    if lines:
        lines.append("")
    return lines


def compare(current_text: str, changes_text: str) -> CompareResult:
    current = parse_running(current_text)
    changes, notes = parse_changes(changes_text)
    problems: list[Problem] = []
    expected = apply_changes(current, changes, problems)
    return CompareResult(
        expected=to_text(expected),
        diff=diff_trees(current, expected),
        notes=notes,
        problems=problems,
    )

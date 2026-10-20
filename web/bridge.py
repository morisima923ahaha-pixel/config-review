"""ブラウザ（Pyodide）の中で、画面（app.js）とツールの本体をつなぐ。

gui.py は tkinter を読み込むので、ブラウザでは使えない（Pyodide に tkinter はない）。
そこで、tkinter 版と同じ表示になるように、gui.py の summarize と _problem_view_lines と同じ考え方で
「出す行」と「色の名前」を作る。同じ結果になることは tests/test_web.py で確かめる。

JavaScript とのやりとりは JSON の文字列にする。Python のオブジェクトをそのまま渡すと、
JavaScript 側で後片付け（destroy）が要るので、文字列にしたほうが簡単でまちがいにくい。
"""

import json
import sys
from pathlib import Path

from config_review.compare import CompareResult, compare, problem_lines, read_config_file

NO_DIFF = "差分はありません（投入しても Config は変わりません）"
DIFF_TAGS = {"-": "removed", "+": "added", " ": "context"}


def summarize(result: CompareResult) -> str:
    """画面に出す「何行変わるか」のまとめ（gui.py の summarize と同じ文章）。"""
    removed = sum(1 for line in result.diff if line.startswith("-"))
    added = sum(1 for line in result.diff if line.startswith("+"))
    alerts = ""
    if result.errors:
        alerts += f"⚠ エラーになるはずの行：{len(result.errors)}　"
    if result.warnings:
        alerts += f"要確認：{len(result.warnings)}　"
    if not result.diff:
        return alerts + NO_DIFF
    text = alerts + f"消える行：{removed}　増える行：{added}"
    if result.notes:
        text += f"　／　読みかえのメモが {len(result.notes)} 件あります（「メモ」タブ）"
    return text


def problem_view_lines(result: CompareResult) -> list[tuple[str, str | None]]:
    """差分タブの一番上に出す、エラー（赤）と要確認（黄）の行（gui.py の _problem_view_lines と同じ）。"""
    lines: list[tuple[str, str | None]] = []
    tag: str | None = None
    for line in problem_lines(result):
        if line.startswith("【エラー】"):
            tag = "error"
        elif line.startswith("【要確認】"):
            tag = "warning"
        lines.append((line, tag if line else None))
    return lines


def view(current_text: str, changes_text: str) -> str:
    """「比較する」を押したときに呼ぶ。画面に出すものを JSON で返す。"""
    try:
        result = compare(current_text, changes_text)
    except ValueError as error:  # 「vlan 10-2」のような、読めない書き方があった
        return json.dumps({"ok": False, "message": f"比較できませんでした。\n\n{error}"}, ensure_ascii=False)
    except Exception as error:  # 想定外のエラーでも、画面が止まらないようにする
        message = f"比較できませんでした。\n\n{type(error).__name__}: {error}"
        return json.dumps({"ok": False, "message": message}, ensure_ascii=False)

    diff = [(line, DIFF_TAGS.get(line[:1])) for line in result.diff] or [(NO_DIFF, None)]
    notes = result.notes or ["読みかえはありません"]
    return json.dumps(
        {
            "ok": True,
            "diff": problem_view_lines(result) + diff,
            "expected": result.expected.splitlines(),
            "notes": ["※ " + note for note in notes],
            "summary": summarize(result),
            "alert": bool(result.problems),
        },
        ensure_ascii=False,
    )


def read_file(path: str) -> str:
    """「ファイルを開く…」で選んだファイルを読む。tkinter 版と同じく、UTF-8 で読めなければ Shift_JIS で読む。"""
    return read_config_file(Path(path))


def python_version() -> str:
    return sys.version.split()[0]

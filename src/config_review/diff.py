"""2 つの Config のツリーを比べて、親の行をつけたまま差分を表示する。"""

from difflib import SequenceMatcher

from config_review.parser import ConfigNode


def diff_trees(before: ConfigNode, after: ConfigNode, indent_width: int = 2) -> list[str]:
    """差分の行の一覧を返す。

    行の先頭が "-" なら消える行、"+" なら増える行、" " なら変わらない親の行。
    変更がない枝は表示しない。
    """
    lines: list[str] = []
    _diff(before, after, 0, indent_width, lines)
    return lines


def _diff(before: ConfigNode, after: ConfigNode, depth: int, width: int, lines: list[str]) -> None:
    indent = " " * (width * depth)

    # 子の行の並びを、上から順に突き合わせる。
    # 「同じ行が続く所（equal）」と「違う行に変わった所」に分けてくれるので、
    # 置き換わった行は「- 古い行」のすぐ下に「+ 新しい行」が並ぶ。
    # 同じ行が 2 回ある Config も、別々の行として数えられる。
    matcher = SequenceMatcher(
        a=[child.text for child in before.children],
        b=[child.text for child in after.children],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # 行は同じでも、中身（子の行）が変わっているかもしれない
            for old, new in zip(before.children[i1:i2], after.children[j1:j2]):
                child_lines: list[str] = []
                _diff(old, new, depth + 1, width, child_lines)
                if child_lines:
                    # どの interface の変更かわかるように、変わらない親の行も表示する
                    lines.append(" " + indent + old.text)
                    lines.extend(child_lines)
            continue

        for old in before.children[i1:i2]:
            _add_subtree("-", old, depth, width, lines)
        for new in after.children[j1:j2]:
            _add_subtree("+", new, depth, width, lines)


def _add_subtree(mark: str, node: ConfigNode, depth: int, width: int, lines: list[str]) -> None:
    """node とその子の行を、すべて同じ印（+ か -）で追加する。"""
    lines.append(mark + " " * (width * depth) + node.text)
    for child in node.children:
        _add_subtree(mark, child, depth + 1, width, lines)

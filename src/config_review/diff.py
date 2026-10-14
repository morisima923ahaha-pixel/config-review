"""2 つの Config のツリーを比べて、親の行をつけたまま差分を表示する。"""

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
    after_by_text = {child.text: child for child in after.children}
    before_texts = {child.text for child in before.children}
    indent = " " * (width * depth)

    # 1. 前からある行：消えたか、中身（子の行）が変わったかを調べる
    for old in before.children:
        new = after_by_text.get(old.text)
        if new is None:
            _add_subtree("-", old, depth, width, lines)
            continue

        child_lines: list[str] = []
        _diff(old, new, depth + 1, width, child_lines)
        if child_lines:
            # どの interface の変更かわかるように、変わらない親の行も表示する
            lines.append(" " + indent + old.text)
            lines.extend(child_lines)

    # 2. 新しく増えた行
    for new in after.children:
        if new.text not in before_texts:
            _add_subtree("+", new, depth, width, lines)


def _add_subtree(mark: str, node: ConfigNode, depth: int, width: int, lines: list[str]) -> None:
    """node とその子の行を、すべて同じ印（+ か -）で追加する。"""
    lines.append(mark + " " * (width * depth) + node.text)
    for child in node.children:
        _add_subtree(mark, child, depth + 1, width, lines)

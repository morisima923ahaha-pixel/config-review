"""NX-OS の running-config を、インデントをもとに親子関係のツリーにする。"""

from dataclasses import dataclass, field


@dataclass
class ConfigNode:
    """Config の 1 行を表す。子の行（1 段深いインデントの行）を children に持つ。"""

    text: str
    children: list["ConfigNode"] = field(default_factory=list)


def parse_config(config_text: str) -> ConfigNode:
    """Config の文字列を読み込み、ツリーの根（root）を返す。

    root 自体は Config の行ではなく、最上位の行（hostname や interface など）を
    まとめるための入れ物。root.text は空文字にしている。
    """
    root = ConfigNode(text="")

    # 「いま開いている親」を、インデントの深さと一緒に積んでおく。
    # root はどの行よりも浅いので、深さを -1 にしておく。
    stack: list[tuple[int, ConfigNode]] = [(-1, root)]

    for line in config_text.splitlines():
        text = line.strip()

        # 空行と「!」で始まるコメント行は設定ではないので読み飛ばす。
        if text == "" or text.startswith("!"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        # 自分と同じ深さか、より深い行は「親ではない」ので取り除く。
        # 残った一番上が、この行の親になる。
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]

        node = ConfigNode(text=text)
        parent.children.append(node)
        stack.append((indent, node))

    return root


def to_text(root: ConfigNode, indent_width: int = 2) -> str:
    """ツリーを Config の文字列に戻す。深さ 1 段ごとに indent_width 個の空白を付ける。"""
    lines: list[str] = []

    def walk(node: ConfigNode, depth: int) -> None:
        for child in node.children:
            lines.append(" " * (indent_width * depth) + child.text)
            walk(child, depth + 1)

    walk(root, 0)
    return "\n".join(lines)

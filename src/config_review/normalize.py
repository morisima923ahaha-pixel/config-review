"""投入 Config の書き方のゆれを、running-config と同じ書き方にそろえてからツリーにする。

そろえるもの：
  - 「conf t」「end」「copy run start」などの、設定ではない行（読み飛ばす）
  - インデントのない投入 Config（conf t で打つそのままの形。exit で 1 段戻る）
  - 「int e1/1」のような省略形（interface の行だけ）
  - 「interface Ethernet1/1-4」「interface e1/1, e1/3」のような複数の interface の指定
"""

import re

from config_review.parser import ConfigNode, parse_config

# interface の種類。（show run での書き方, 省略できる最短の文字数）
# 「e1/1」「eth1/1」「ethernet1/1」は、どれも「Ethernet1/1」になる。
INTERFACE_TYPES = (
    ("Ethernet", 1),
    ("port-channel", 2),
    ("Vlan", 2),
    ("loopback", 2),
    ("mgmt", 1),
    ("Tunnel", 2),
    ("nve", 2),
)

# インデントのない投入 Config で、「ここから新しいブロックが始まる」とわかる行
MODE_COMMANDS = (
    "interface ",
    "router ",
    "vrf context ",
    "ip access-list ",
    "ipv6 access-list ",
    "route-map ",
    "class-map ",
    "policy-map ",
    "object-group ",
    "key chain ",
    "line ",
    "vpc domain ",
    "role name ",
    "port-profile ",
)

# インデントのない投入 Config で、ブロックの中に書かれていても最上位の設定とみなす行
GLOBAL_COMMANDS = (
    "hostname ",
    "feature ",
    "ip route ",
    "ipv6 route ",
    "username ",
    "ntp ",
    "snmp-server ",
    "ip domain-name ",
    "ip name-server ",
    "boot ",
    "clock ",
)

VLAN_LINE = re.compile(r"vlan \d[\d,\-]*")
INTERFACE_PART = re.compile(r"([A-Za-z][A-Za-z\-]*?)\s*(\d[\d/.]*?)(?:-(\d+))?")


def parse_changes(text: str) -> tuple[ConfigNode, list[str]]:
    """投入 Config をツリーにする。書き方をそろえた内容のメモ（notes）も一緒に返す。"""
    notes: list[str] = []
    lines: list[str] = []

    for raw in text.expandtabs(4).splitlines():
        stripped = raw.strip()
        if stripped == "" or stripped.startswith("!"):
            continue
        if _is_not_config(stripped):
            _note(notes, f"「{stripped}」は設定ではないので読み飛ばしました")
            continue
        indent = raw[: len(raw) - len(raw.lstrip(" "))]
        lines.append(indent + normalize_interface_line(stripped, notes))

    if any(line.startswith(" ") for line in lines):
        # インデントがあるときは、インデントで親子がわかるので exit はいらない
        kept = [line for line in lines if line.strip() != "exit"]
        if len(kept) != len(lines):
            _note(notes, "インデントがあるので、「exit」の行は読み飛ばしました")
        root = parse_config("\n".join(kept))
    else:
        root = _parse_flat(lines, notes)

    _split_interface_lists(root)
    return root, notes


def parse_running(text: str) -> ConfigNode:
    """running-config をツリーにする（interface の名前の書き方だけそろえる）。"""
    root = parse_config(text.expandtabs(4))
    for node in root.children:
        node.text = normalize_interface_line(node.text, [])
    _split_interface_lists(root)
    return root


def normalize_interface_line(line: str, notes: list[str]) -> str:
    """「int e1/1」のような interface の行を、「interface Ethernet1/1」にそろえる。

    複数の interface が指定されていたら「interface Ethernet1/1,Ethernet1/2」のように
    カンマでつないで返す（あとで _split_interface_lists が 1 つずつのブロックに分ける）。
    interface の行でなければ、そのまま返す。
    """
    no = "no " if line.startswith("no ") else ""
    words = line.removeprefix("no ").split(maxsplit=1)

    if len(words) != 2 or len(words[0]) < 3 or not "interface".startswith(words[0].lower()):
        return line

    names = expand_interface_names(words[1])
    if names is None:
        return line

    result = f"{no}interface {','.join(names)}"
    if result != line:
        _note(notes, f"「{line}」を「{no}interface {', '.join(names)}」と読みかえました")
    return result


def expand_interface_names(text: str) -> list[str] | None:
    """「e1/1-3, po10」を ["Ethernet1/1", "Ethernet1/2", "Ethernet1/3", "port-channel10"] にする。

    知らない種類の interface や、読めない書き方があれば None を返す。
    """
    names: list[str] = []
    for part in text.split(","):
        m = INTERFACE_PART.fullmatch(part.strip())
        if m is None:
            return None
        kind = _interface_type(m.group(1))
        if kind is None:
            return None

        number, end = m.group(2), m.group(3)
        if end is None:
            names.append(kind + number)
            continue

        # 「1/1-3」の、最後の番号（1）から end（3）までを順に作る
        prefix, _, start = number.rpartition("/")
        prefix = prefix + "/" if prefix else ""
        if not start.isdigit() or int(start) > int(end):
            return None
        names.extend(f"{kind}{prefix}{n}" for n in range(int(start), int(end) + 1))
    return names


def _interface_type(word: str) -> str | None:
    """「eth」「Po」などを、show run での書き方（Ethernet・port-channel）にする。"""
    for name, min_length in INTERFACE_TYPES:
        if len(word) >= min_length and name.lower().startswith(word.lower()):
            return name
    return None


def _parse_flat(lines: list[str], notes: list[str]) -> ConfigNode:
    """インデントのない投入 Config を、ブロックの始まりの行（interface など）をもとにツリーにする。

    「exit」でブロックを抜ける。ブロックの中のさらに深いブロック（router の下の vrf など）は
    見分けられないので、その場合はインデントをつけて書いてもらう。
    """
    root = ConfigNode(text="")
    parent = root
    used_blocks = False

    for line in lines:
        if line == "exit":
            parent = root
            continue

        base = line.removeprefix("no ")
        is_block = base.startswith(MODE_COMMANDS) or VLAN_LINE.fullmatch(base)

        if is_block and not line.startswith("no "):
            node = ConfigNode(text=line)
            root.children.append(node)
            parent = node
            used_blocks = True
        elif is_block or base.startswith(GLOBAL_COMMANDS):
            root.children.append(ConfigNode(text=line))
            parent = root
        else:
            parent.children.append(ConfigNode(text=line))

    if used_blocks:
        _note(
            notes,
            "インデントのない投入 Config として読みました。interface などの次の行から、"
            "exit か次のブロックまでを、そのブロックの中の設定とみなしています",
        )
    return root


def _split_interface_lists(root: ConfigNode) -> None:
    """「interface Ethernet1/1,Ethernet1/2」のブロックを、interface 1 つずつのブロックに分ける。"""
    result: list[ConfigNode] = []
    for node in root.children:
        no = "no " if node.text.startswith("no ") else ""
        body = node.text.removeprefix("no ")
        if body.startswith("interface ") and "," in body:
            for name in body.removeprefix("interface ").split(","):
                result.append(ConfigNode(text=f"{no}interface {name}", children=_copy(node.children)))
        else:
            result.append(node)
    root.children = result


def _copy(nodes: list[ConfigNode]) -> list[ConfigNode]:
    return [ConfigNode(text=n.text, children=_copy(n.children)) for n in nodes]


def _is_not_config(line: str) -> bool:
    """「conf t」「end」「copy run start」のような、設定ではない行かどうか。"""
    words = line.lower().split()
    first = words[0]
    if len(first) >= 4 and "configure".startswith(first):
        return len(words) == 1 or "terminal".startswith(words[1])
    return line.lower() == "end" or first in ("copy", "write", "show")


def _note(notes: list[str], message: str) -> None:
    if message not in notes:
        notes.append(message)

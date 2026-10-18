"""現行 Config のツリーに投入 Config のツリーを反映して、投入後の想定 Config を作る。"""

import copy
import re
from collections.abc import Callable

from config_review.checks import L3, Checker, Problem, command_kind
from config_review.parser import ConfigNode
from config_review.vlan import ALL_VLANS, calc_allowed_vlans, format_vlan_list, parse_vlan_list

# 値を 1 つしか持てないコマンド。投入すると、同じコマンドの既存の行を置き換える。
# 例：description A がある所に description B を投入すると、A は消えて B だけになる。
OVERWRITE_COMMANDS = (
    "hostname",
    "description",
    "name",
    "ip address",
    "router-id",
    "switchport mode",
    "switchport access vlan",
    "switchport trunk native vlan",
    "mtu",
    "speed",
    "duplex",
    "vrf member",
    "channel-group",
    "bandwidth",
    "spanning-tree port type",
)

# 「no 〇〇」の形のまま show run に表示されるコマンド。
# 値は「肯定の形（〇〇）も show run に表示されるか」。
#   shutdown・switchport：どちらの形も表示される
#   ip redirects など：既定で有効なので、無効にしたときの「no 〇〇」だけが表示される
SHOWN_NO_FORMS = {
    "shutdown": True,
    "switchport": True,
    "ip redirects": False,
    "ipv6 redirects": False,
}

# トランクで通す VLAN の一覧。add・remove があるので、単純な上書きではなく計算して 1 行にまとめる。
ALLOWED_VLAN = "switchport trunk allowed vlan"

# 最上位の「vlan 10」「vlan 1,10,20」のような行（VLAN を作る行と、作った VLAN の一覧の行）。
# 「vlan configuration 10」「vlan access-map」などは別のコマンドなので当てはまらない。
VLAN_LINE = re.compile(r"vlan (\d[\d,\-]*)")


def apply_changes(
    current: ConfigNode, changes: ConfigNode, problems: list[Problem] | None = None
) -> ConfigNode:
    """現行 Config に投入 Config を反映した、新しいツリーを返す。

    current は差分を出すときに必要なので、書き換えずにコピーしてから反映する。
    実機ではエラーになって入らないはずの行は反映せず、理由を problems に足す。
    """
    result = copy.deepcopy(current)
    checker = Checker.for_config(current, [] if problems is None else problems)
    _merge(result, changes, checker=checker)
    return result


def _merge(target: ConfigNode, changes: ConfigNode, checker: Checker | None = None) -> None:
    """changes の子の行を、1 行ずつ target の子に反映する。

    checker を渡すのは最上位（root）のときだけ。最上位の行と interface の下の行を確かめる。
    """
    top_level = checker is not None
    for change in changes.children:
        text = change.text

        if top_level and not checker.check_top_level(target, change):
            continue  # 「feature interface-vlan」がないのに「interface Vlan10」など、入らないブロック

        if top_level and VLAN_LINE.fullmatch(text.removeprefix("no ")):
            if text.startswith("no "):
                checker.check_vlan_removal(target, text, _vlan_numbers(text.removeprefix("no ")))
            _apply_vlan(target, change)
            continue

        if text.startswith("no "):
            _apply_no(target, text.removeprefix("no "))
            continue

        if _matches(text, ALLOWED_VLAN):
            _apply_allowed_vlan(target, text)
            continue

        if text == "switchport":
            # L2 に切り替えると、ip address などの L3 の設定は消える
            target.children = [c for c in target.children if command_kind(c.text) != L3]

        if text in SHOWN_NO_FORMS and not SHOWN_NO_FORMS[text]:
            # 既定の状態に戻すだけなので、行は増えない（「no ip redirects」が消えるだけ）
            _remove_matching(target, "no " + text)
            continue

        # 「shutdown」を投入したら、反対の「no shutdown」は残しておけない。
        # 上書きするコマンドなら、同じコマンドの既存の行も消す。
        replaced = _replaced_by(text)

        def should_remove(t: str) -> bool:
            return t == "no " + text or replaced(t)

        existing = _find_child(target, text)
        if existing is None:
            # 消した行があれば、その場所に新しい行を入れる（差分で上下に離れないように）。
            existing = ConfigNode(text=text)
            _replace(target, should_remove, existing)
        else:
            target.children = [
                child
                for child in target.children
                if child is existing or not should_remove(child.text)
            ]

        if top_level and text.startswith("interface "):
            # 「L2 のポートに ip address」のような、実機ではエラーになる行を取り除く
            change = checker.check_interface(target, existing, change)

        # interface の下の行のように、子があれば同じルールで反映する。
        _merge(existing, change)


def _apply_no(target: ConfigNode, command: str) -> None:
    """「no 〇〇」を反映する。"""
    if command in SHOWN_NO_FORMS:
        # 「no shutdown」のように、no の形のまま行として残るコマンド。
        # 「no switchport」は「switchport mode trunk」などの switchport の設定もまとめて消える。
        no_line = ConfigNode(text="no " + command)
        _replace(target, lambda t: _matches(t, command) or t == no_line.text, no_line)
        return
    _remove_matching(target, command)


def _replace(target: ConfigNode, should_remove: Callable[[str], bool], node: ConfigNode) -> None:
    """should_remove に当てはまる行を消して、最初に消した行の場所に node を入れる（なければ末尾）。"""
    kept: list[ConfigNode] = []
    position: int | None = None
    for child in target.children:
        if should_remove(child.text):
            if position is None:
                position = len(kept)
        else:
            kept.append(child)
    if position is None:
        position = len(kept)
    kept.insert(position, node)
    target.children = kept


def _replaced_by(text: str) -> Callable[[str], bool]:
    """text を投入したときに置き換わる（消える）既存の行を見分ける関数を返す。"""
    for command in OVERWRITE_COMMANDS:
        if not text.startswith(command + " "):
            continue
        if command == "ip address":
            # secondary は primary と別に何個でも持てるので、何も置き換えない。
            # primary を投入したときも、置き換わるのは primary の行だけ。
            if _is_secondary(text):
                return lambda t: False
            return lambda t: _matches(t, "ip address") and not _is_secondary(t)
        return lambda t: _matches(t, command)
    return lambda t: False


def _is_secondary(text: str) -> bool:
    return "secondary" in text.split()


def _matches(text: str, command: str) -> bool:
    """text が command そのもの、または command に値を付けた行かどうか。

    "description A" は "description" に当てはまるが、
    "interface Vlan100" は "interface Vlan10" には当てはまらない。
    """
    return text == command or text.startswith(command + " ")


def _remove_matching(target: ConfigNode, command: str) -> None:
    """target の子のうち、command に当てはまる行を（その子の行ごと）取り除く。"""
    target.children = [
        child for child in target.children if not _matches(child.text, command)
    ]


def _apply_allowed_vlan(target: ConfigNode, text: str) -> None:
    """allowed vlan の行を計算して、target の中の allowed vlan の行を 1 行に置き換える。

    running-config では、一覧が長いと「allowed vlan 1-100」「allowed vlan add 200」のように
    複数行に分かれることがある。だから既存の行も上から順に計算して、今の一覧を求める。
    行が 1 つもないときは、NX-OS の既定値の「全部の VLAN を通す」状態。
    """
    lines = [child for child in target.children if _matches(child.text, ALLOWED_VLAN)]

    vlans = set(ALL_VLANS)
    for line in lines + [ConfigNode(text=text)]:
        vlans = calc_allowed_vlans(vlans, line.text.removeprefix(ALLOWED_VLAN + " "))

    # 元の行があった場所に、新しい 1 行を入れる（なければ末尾）。
    position = target.children.index(lines[0]) if lines else len(target.children)
    _remove_matching(target, ALLOWED_VLAN)

    # 全部の VLAN を通すのは既定値なので、show run には行が出ない。
    if vlans == ALL_VLANS:
        return
    value = format_vlan_list(vlans) if vlans else "none"
    target.children.insert(position, ConfigNode(text=f"{ALLOWED_VLAN} {value}"))


def _vlan_numbers(text: str) -> set[int] | None:
    """「vlan 10」「vlan 1,10,20」の行なら VLAN 番号の集合を、違えば None を返す。"""
    m = VLAN_LINE.fullmatch(text)
    return parse_vlan_list(m.group(1)) if m else None


def _apply_vlan(root: ConfigNode, change: ConfigNode) -> None:
    """VLAN を作る・消す行を反映して、VLAN の一覧の行（vlan 1,10,20）も更新する。

    NX-OS の show run では、作られている VLAN が「vlan 1,10,20」の 1 行にまとめて表示され、
    name などの設定がある VLAN だけが、そのあとに「vlan 10」＋子の行として表示される。
    """
    negate = change.text.startswith("no ")
    numbers = _vlan_numbers(change.text.removeprefix("no "))

    # 子の行（name など）を持たない vlan の行が一覧の行。
    # 現行 Config に一覧がなければ（一部だけ貼り付けたときなど）、VLAN 1 と、
    # vlan のブロックがある VLAN だけが作られている状態とみなす。
    summary = next(
        (c for c in root.children if not c.children and _vlan_numbers(c.text) is not None), None
    )
    if summary is not None:
        vlans = _vlan_numbers(summary.text)
    else:
        vlans = {1}
        for child in root.children:
            vlans |= _vlan_numbers(child.text) or set()

    if negate:
        vlans -= numbers
        # 消した VLAN の設定（vlan 10 ＋ name など）も一緒に消える
        root.children = [
            c
            for c in root.children
            if c is summary or (n := _vlan_numbers(c.text)) is None or not n <= numbers
        ]
    else:
        vlans |= numbers
        if change.children:
            block = _find_child(root, change.text)
            if block is None:
                block = ConfigNode(text=change.text)
                _insert_vlan_block(root, block, summary)
            _merge(block, change)

    if summary is None:
        # 一覧の行は、vlan のブロックより前に置く
        summary = ConfigNode(text="")
        position = next(
            (i for i, c in enumerate(root.children) if _vlan_numbers(c.text) is not None),
            len(root.children),
        )
        root.children.insert(position, summary)

    if vlans:
        summary.text = f"vlan {format_vlan_list(vlans)}"
    else:
        root.children.remove(summary)


def _insert_vlan_block(root: ConfigNode, block: ConfigNode, summary: ConfigNode | None) -> None:
    """vlan のブロックを、ほかの vlan のブロックと番号順になる場所に入れる。"""
    number = min(_vlan_numbers(block.text))
    blocks = [
        (i, min(n))
        for i, c in enumerate(root.children)
        if c is not summary and (n := _vlan_numbers(c.text)) is not None
    ]
    smaller = [i for i, n in blocks if n < number]

    if smaller:
        position = smaller[-1] + 1
    elif blocks:
        position = blocks[0][0]
    elif summary is not None:
        position = root.children.index(summary) + 1
    else:
        position = len(root.children)
    root.children.insert(position, block)


def _find_child(target: ConfigNode, text: str) -> ConfigNode | None:
    """target の子から、text と完全に同じ行を探す。なければ None。"""
    for child in target.children:
        if child.text == text:
            return child
    return None

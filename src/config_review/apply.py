"""現行 Config のツリーに投入 Config のツリーを反映して、投入後の想定 Config を作る。"""

import copy
import ipaddress
import re
from collections.abc import Callable

from config_review.checks import (
    INTERFACE_FEATURES,
    L3,
    TOP_LEVEL_FEATURES,
    Checker,
    Problem,
    command_kind,
)
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
    "channel-group",
    "bandwidth",
    "spanning-tree port type",
    "spanning-tree cost",
    # load-interval は counter 1〜3 の 3 つを別々に持てるので、番号ごとに上書きする
    "load-interval counter 1",
    "load-interval counter 2",
    "load-interval counter 3",
    "service-policy type qos input",
)
# OVERWRITE_COMMANDS のうち spanning-tree cost・load-interval・service-policy type qos input は、
# 2026-10-19 に NX-OS 10.4(2) の実機で確認

# 「ip access-group A in」は、同じ向き（in / out）の行だけを上書きする。in と out は別々に持てる
# （2026-10-19 に NX-OS 10.4(2) の実機で、in の上書きと、in と out が両方残ることを確認。out の上書きは未確認）
ACCESS_GROUP = re.compile(r"ip access-group \S+ (in|out)")

# 既定値と同じ値を入れると、show run には行が出ない（2026-10-19 に NX-OS 10.4(2) の実機で確認）。
# 値は「消える行のコマンド」
DEFAULT_VALUE_LINES = {
    "load-interval counter 1 30": "load-interval counter 1",
    "load-interval counter 2 300": "load-interval counter 2",
}

# 「ip router ospf 1 area 0」は、show run では「area 0.0.0.0」と表示される
# （2026-10-19 に NX-OS 10.4(2) の実機で area 0 を確認。ほかの番号も同じ書き方になるはず）
OSPF_AREA = re.compile(r"(ip router ospf \S+ area )(\d+)((?: .*)?)")

# 「no feature 〇〇」で、その feature を使う設定（router ospf・ip ospf の行など）も黙って消える feature
# （2026-10-19 に NX-OS 10.4(2) の実機で確認。interface-vlan は interface Vlan〇〇 がまるごと消えた）。
# ここにない feature は確かめていないので、消さずに確認のお願いを出す
FEATURES_REMOVING_USERS = ("interface-vlan", "ospf", "pim", "hsrp")

# 「no 〇〇」の形のまま show run に表示されるコマンド。
# 値は「肯定の形（〇〇）も show run に表示されるか」。
#   shutdown・switchport：どちらの形も表示される
#   ip redirects など：既定で有効なので、無効にしたときの「no 〇〇」だけが表示される
SHOWN_NO_FORMS = {
    "shutdown": True,
    "switchport": True,
    "ip redirects": False,
    "ipv6 redirects": False,
    "cdp enable": False,
    "snmp trap link-status": False,
    "logging event port link-status": True,
}
# snmp trap link-status・logging event port link-status は 2026-10-19 に NX-OS 10.4(2) の実機で確認

# 「channel-group 10 mode on」は、show run では「channel-group 10」と表示される（mode on が既定のため）
CHANNEL_GROUP_ON = re.compile(r"(channel-group \d+) mode on")
# channel-group を入れると、その番号の port-channel の interface が自動でできる
CHANNEL_GROUP = re.compile(r"channel-group (\d+)( mode \S+)?")

# トランクで通す VLAN の一覧。add・remove があるので、単純な上書きではなく計算して 1 行にまとめる。
ALLOWED_VLAN = "switchport trunk allowed vlan"

# interface の VRF を決める行。VRF が変わると、その interface の L3 の設定はすべて消える。
VRF_MEMBER = "vrf member"

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
        text = _display_form(text)

        if top_level and not checker.check_top_level(target, change):
            continue  # 「feature interface-vlan」がないのに「interface Vlan10」など、入らないブロック

        if top_level and VLAN_LINE.fullmatch(text.removeprefix("no ")):
            if text.startswith("no "):
                checker.check_vlan_removal(target, text, _vlan_numbers(text.removeprefix("no ")))
            _apply_vlan(target, change)
            continue

        if top_level and text.startswith("no feature "):
            _remove_feature_users(target, text.removeprefix("no feature "), checker)

        if _matches(text.removeprefix("no "), VRF_MEMBER):
            _apply_vrf_member(target, text)
            continue

        if text.startswith("no "):
            _apply_no(target, text.removeprefix("no "))
            continue

        if _matches(text, ALLOWED_VLAN):
            _apply_allowed_vlan(target, text)
            continue

        if text == "switchport":
            # L2 に切り替えると、ip address などの L3 の設定は消える。
            # L3 から切り替えたときは mtu も消える（2026-10-19 に NX-OS 10.4(2) の実機で確認）
            was_l3 = any(c.text == "no switchport" or command_kind(c.text) == L3 for c in target.children)
            target.children = [
                c
                for c in target.children
                if command_kind(c.text) != L3 and not (was_l3 and _matches(c.text, "mtu"))
            ]

        if text in DEFAULT_VALUE_LINES:
            _remove_matching(target, DEFAULT_VALUE_LINES[text])
            continue

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

        if top_level and text.startswith("interface "):
            _add_port_channels(target, existing, change)


def _add_port_channels(root: ConfigNode, interface: ConfigNode, change: ConfigNode) -> None:
    """投入した channel-group の番号の port-channel が Config になければ、interface の前に作る。

    NX-OS では channel-group を入れると「interface port-channel〇〇」が自動でできる
    （2026-10-19 に NX-OS 10.4(2) の実機で確認。mode on・active のどちらでもできた）。
    現行 Config にもとからある channel-group は見ない（一部だけ貼り付けた Config で、port-channel を貼っていないだけかもしれないので）。
    """
    applied = {c.text for c in interface.children}
    for child in change.children:
        m = CHANNEL_GROUP.fullmatch(child.text)
        if m is None or CHANNEL_GROUP_ON.sub(r"\1", child.text) not in applied:
            continue  # エラーで入らなかった channel-group は数えない
        name = f"interface port-channel{m.group(1)}"
        if _find_child(root, name) is None:
            root.children.insert(_port_channel_position(root, interface, int(m.group(1))), ConfigNode(text=name))


PORT_CHANNEL = re.compile(r"interface port-channel(\d+)")


def _port_channel_position(root: ConfigNode, interface: ConfigNode, number: int) -> int:
    """自動でできた port-channel を入れる場所。

    show run では、port-channel は Ethernet より前に出る
    （2026-10-19 に NX-OS 10.4(2) の実機で、ほかの port-channel がないときに interface Ethernet1/1 の前に出ると確認）。
    ほかの port-channel があるときは番号順に並べる（こちらは未確認）。
    """
    others = [(i, int(m.group(1))) for i, c in enumerate(root.children) if (m := PORT_CHANNEL.fullmatch(c.text))]
    if others:
        larger = [i for i, n in others if n > number]
        return larger[0] if larger else others[-1][0] + 1
    ethernet = next((i for i, c in enumerate(root.children) if c.text.startswith("interface Ethernet")), None)
    return ethernet if ethernet is not None else root.children.index(interface)


def _display_form(text: str) -> str:
    """投入の行を、show run に表示される書き方にそろえる。

    そろえておかないと、現行 Config の「area 0.0.0.0」と投入の「area 0」が別の行に見えて、2 行になってしまう。
    """
    if m := CHANNEL_GROUP_ON.fullmatch(text):
        return m.group(1)
    if (m := OSPF_AREA.fullmatch(text)) and int(m.group(2)) < 2**32:
        return f"{m.group(1)}{ipaddress.IPv4Address(int(m.group(2)))}{m.group(3)}"
    return text


def _remove_feature_users(root: ConfigNode, feature: str, checker: Checker) -> None:
    """「no feature 〇〇」で、その feature を使う設定を消す（実機で確かめた feature だけ）。

    確かめていない feature は消さずに、残る扱いにしたことを知らせる。
    """
    top = [p for p, f in TOP_LEVEL_FEATURES if f == feature]
    sub = [p for p, f in INTERFACE_FEATURES if f == feature]
    users: list[str] = []
    for block in root.children:
        if any(p.fullmatch(block.text) for p in top):
            users.append(block.text)
            continue
        users += [f"{block.text}（{c.text}）" for c in block.children if any(p.fullmatch(c.text) for p in sub)]
    if not users:
        return
    line = f"no feature {feature}"
    if feature not in FEATURES_REMOVING_USERS:
        checker.problems.append(Problem(
            line, line,
            f"この feature を使う設定（{'、'.join(users)}）が残っています。"
            "実機で消えるのか、エラーになるのかは確かめていないので、想定 Config には残したままにしました。",
            rejected=False,
        ))
        return
    root.children = [b for b in root.children if not any(p.fullmatch(b.text) for p in top)]
    for block in root.children:
        block.children = [c for c in block.children if not any(p.fullmatch(c.text) for p in sub)]
    checker.problems.append(Problem(
        line, line,
        f"この feature を使う設定（{'、'.join(users)}）は、実機ではエラーにならずに黙って消えます。"
        "想定 Config からも消しました。消えてよい設定か確かめてください。",
        rejected=False,
    ))


def _apply_no(target: ConfigNode, command: str) -> None:
    """「no 〇〇」を反映する。"""
    if command in SHOWN_NO_FORMS:
        # 「no shutdown」のように、no の形のまま行として残るコマンド。
        # 「no switchport」は「switchport mode trunk」などの switchport の設定もまとめて消える。
        no_line = ConfigNode(text="no " + command)
        _replace(target, lambda t: _matches(t, command) or t == no_line.text, no_line)
        return
    _remove_matching(target, command)


def _apply_vrf_member(target: ConfigNode, text: str) -> None:
    """「vrf member 〇〇」「no vrf member 〇〇」を反映する。

    NX-OS では、interface の VRF が変わると ip address などの L3 の設定がすべて消える。
    VRF なし → VRF あり、VRF A → VRF B、no vrf member のどれでも消え、
    「Warning: Deleted all L3 config on interface 〇〇」と表示される。
    同じ VRF を入れ直したときは何も消えない。
    今と違う名前で「no vrf member 〇〇」を入れるとエラーになり、何も変わらない（checks.py で弾く）。
    （2026-10-19 に NX-OS 10.4(2) の実機（loopback）で確認）
    """
    current = next((c.text for c in target.children if _matches(c.text, VRF_MEMBER)), None)
    if text == current:
        return  # 同じ VRF の入れ直し
    if text.startswith("no "):
        if current is not None and text in ("no " + VRF_MEMBER, "no " + current):
            target.children = [c for c in target.children if command_kind(c.text) != L3]
        return
    # 消した L3 の設定の先頭の場所に、新しい vrf member の行を入れる（show run でも ip address より前に出る）
    _replace(target, lambda t: command_kind(t) == L3, ConfigNode(text=text))


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
    if m := ACCESS_GROUP.fullmatch(text):
        direction = m.group(1)
        return lambda t: bool((n := ACCESS_GROUP.fullmatch(t)) and n.group(1) == direction)
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

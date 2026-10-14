"""現行 Config のツリーに投入 Config のツリーを反映して、投入後の想定 Config を作る。"""

import copy

from config_review.parser import ConfigNode
from config_review.vlan import ALL_VLANS, calc_allowed_vlans, format_vlan_list

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
)

# トランクで通す VLAN の一覧。add・remove があるので、単純な上書きではなく計算して 1 行にまとめる。
ALLOWED_VLAN = "switchport trunk allowed vlan"


def apply_changes(current: ConfigNode, changes: ConfigNode) -> ConfigNode:
    """現行 Config に投入 Config を反映した、新しいツリーを返す。

    current は差分を出すときに必要なので、書き換えずにコピーしてから反映する。
    """
    result = copy.deepcopy(current)
    _merge(result, changes)
    return result


def _merge(target: ConfigNode, changes: ConfigNode) -> None:
    """changes の子の行を、1 行ずつ target の子に反映する。"""
    for change in changes.children:
        if change.text.startswith("no "):
            _remove_matching(target, change.text.removeprefix("no "))
            continue

        if _matches(change.text, ALLOWED_VLAN):
            _apply_allowed_vlan(target, change.text)
            continue

        # 「shutdown」を投入したら、反対の「no shutdown」は残しておけない。
        _remove_matching(target, "no " + change.text)

        command = _overwrite_command(change.text)
        if command is not None:
            _remove_matching(target, command)

        existing = _find_child(target, change.text)
        if existing is None:
            existing = ConfigNode(text=change.text)
            target.children.append(existing)

        # interface の下の行のように、子があれば同じルールで反映する。
        _merge(existing, change)


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


def _overwrite_command(text: str) -> str | None:
    """text が置き換え対象のコマンドなら、そのコマンド名を返す。違えば None。"""
    for command in OVERWRITE_COMMANDS:
        if text.startswith(command + " "):
            return command
    return None


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


def _find_child(target: ConfigNode, text: str) -> ConfigNode | None:
    """target の子から、text と完全に同じ行を探す。なければ None。"""
    for child in target.children:
        if child.text == text:
            return child
    return None

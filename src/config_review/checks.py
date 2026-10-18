"""実機に投入するとエラーになって入らないはずの行を見つける。

再鑑ツールが「入る」と予想した行が、実機ではエラーで弾かれると、
レビューした人は「設定される」と思い込んだまま作業当日を迎えてしまう。
そこで、反映（apply.py）の前に投入 Config の行を 1 行ずつ確かめて、
エラーになるはずの行は想定 Config に入れず、理由を Problem として残す。
"""

from dataclasses import dataclass

from config_review.parser import ConfigNode

L2 = "L2"  # switchport（スイッチのポート）
L3 = "L3"  # ルーテッドポート（IP アドレスを持てるポート）

# L3 のポートでしか使えないコマンド（no の形も含む）。L2 のポートに入れるとエラーになる。
L3_COMMANDS = (
    "ip address",
    "ipv6 address",
    "vrf member",
    "ip router",
    "ipv6 router",
    "ip ospf",
    "ipv6 ospfv3",
    "ip pim",
    "ip proxy-arp",
    "ip redirects",
    "ipv6 redirects",
    "ip unreachables",
    "hsrp",
    "vrrp",
)

# L2 のポートでしか使えないコマンド。「switchport」だけの行は L2 に切り替えるコマンドなので別扱い。
L2_COMMANDS = ("switchport",)

# Ethernet と port-channel は、switchport / no switchport で L2 と L3 を切り替えられる。
# それ以外（Vlan・loopback・mgmt・tunnel、Ethernet1/1.100 のようなサブインターフェース）は L3 だけ。
SWITCHABLE = ("interface Ethernet", "interface port-channel")


@dataclass
class Problem:
    interface: str  # 「interface Ethernet1/1」
    line: str  # 問題のある投入の行
    message: str  # 理由（画面に出す文章）
    rejected: bool  # True：実機ではエラーで入らない（想定 Config に入れていない）

    def __str__(self) -> str:
        if self.rejected:
            return f"{self.interface}：「{self.line}」は実機ではエラーになって入らないはずです。{self.message}"
        return f"{self.interface}：「{self.line}」について確認してください。{self.message}"


def _matches(text: str, command: str) -> bool:
    return text == command or text.startswith(command + " ")


def _kind(text: str) -> str | None:
    """行が L2 だけ・L3 だけのコマンドなら L2 / L3 を、どちらでもなければ None を返す。"""
    command = text.removeprefix("no ")
    if command == "switchport":
        return None  # L2 と L3 を切り替える行
    if any(_matches(command, c) for c in L2_COMMANDS):
        return L2
    if any(_matches(command, c) for c in L3_COMMANDS):
        return L3
    return None


def _is_switchable(interface: str) -> bool:
    return interface.startswith(SWITCHABLE) and "." not in interface


def interface_mode(root: ConfigNode, interface: ConfigNode) -> str | None:
    """interface が今 L2 か L3 かを返す。Config から判断できなければ None。

    NX-OS の show run では、
      - L2 のポートには「switchport」や「switchport mode 〇〇」が
      - L3 のポートには「no switchport」や「ip address 〇〇」が
    表示される。どれもないときは機種や「system default switchport」の設定で決まる。
    """
    if not _is_switchable(interface.text):
        return L3

    for child in interface.children:
        if child.text == "switchport":
            return L2
        if child.text == "no switchport":
            return L3
    kinds = {_kind(child.text) for child in interface.children}
    if L2 in kinds:
        return L2
    if L3 in kinds:
        return L3

    # Ethernet の初期状態を決める設定（一部だけ貼り付けた Config では見つからないこともある）
    for child in root.children:
        if child.text == "system default switchport":
            return L2
        if child.text == "no system default switchport":
            return L3
    return None


def check_interface(
    root: ConfigNode, interface: ConfigNode, change: ConfigNode, problems: list[Problem]
) -> ConfigNode:
    """interface に投入する行（change の子）を上から順に確かめる。

    エラーになるはずの行を除いた change のコピーを返し、理由を problems に足す。
    「no switchport」→「ip address」の順なら成功、逆の順なら失敗するので、
    1 行ずつ L2 / L3 の状態を進めながら確かめる。
    """
    mode = interface_mode(root, interface)
    switchable = _is_switchable(interface.text)
    allowed = ConfigNode(text=change.text)
    unknown_kinds: set[str] = set()
    unknown_lines: list[str] = []

    for child in change.children:
        text = child.text
        if text == "switchport" or text == "no switchport":
            if not switchable:
                problems.append(Problem(
                    interface.text, text,
                    "この interface は L3 だけで、L2（switchport）には切り替えられません。"
                    "想定 Config には入れていません。",
                    rejected=True,
                ))
                continue
            if text == "switchport" and mode != L2:
                l3_lines = [c.text for c in interface.children if _kind(c.text) == L3]
                if l3_lines:
                    problems.append(Problem(
                        interface.text, text,
                        f"L3 の設定（{' / '.join(l3_lines)}）が残ったまま L2 に切り替えています。"
                        "実機では L3 の設定が消えるか、エラーになるはずですが、ツールは L3 の設定を残したままにしています。",
                        rejected=False,
                    ))
            mode = L2 if text == "switchport" else L3
            allowed.children.append(child)
            continue

        kind = _kind(text)
        if kind is None or kind == mode:
            allowed.children.append(child)
            continue

        if mode is None:
            # L2 か L3 かわからないので、入れたうえで確認をお願いする
            unknown_kinds.add(kind)
            unknown_lines.append(text)
            allowed.children.append(child)
            continue

        if kind == L3:
            how = "先に「no switchport」で L3 に切り替える必要があります。"
        elif switchable:
            how = "先に「switchport」で L2 に切り替える必要があります。"
        else:
            how = "この interface は L3 だけで、L2（switchport）の設定は入れられません。"
        problems.append(Problem(
            interface.text, text,
            f"今は {mode} のポートなので、{kind} の設定は入れられません。{how}想定 Config には入れていません。",
            rejected=True,
        ))

    if unknown_kinds:
        if len(unknown_kinds) == 2:
            assumed = "L2 と L3 の設定が混ざっているので、どちらかは実機でエラーになるはずです（想定 Config にはどちらも入れました）。"
        else:
            assumed = f"{next(iter(unknown_kinds))} のポートとみなして想定 Config に入れました。"
        message = (
            "現行 Config からは、この interface が L2（switchport）か L3（no switchport）か判断できません。"
            f"{assumed}"
            "show run に「switchport」「no switchport」の行があるか、"
            "「system default switchport」の設定を確かめてください。"
        )
        problems.append(Problem(interface.text, " / ".join(unknown_lines), message, rejected=False))

    return allowed

"""実機に投入するとエラーになって入らないはずの行を見つける。

再鑑ツールが「入る」と予想した行が、実機ではエラーで弾かれると、
レビューした人は「設定される」と思い込んだまま作業当日を迎えてしまう。
そこで、反映（apply.py）の途中で投入 Config の行を 1 行ずつ確かめて、
エラーになるはずの行は想定 Config に入れず、理由を Problem として残す。

今あるチェック：
  - L2 のポートに L3 の設定（ip address など）、L3 のポートに L2 の設定（switchport 〇〇）
  - feature が有効になっていないコマンド（feature interface-vlan がないのに interface Vlan10 など）
  - 作られていない VLAN を使う設定、使われている VLAN を消す設定（こちらは入るので要確認だけ）
"""

import re
from dataclasses import dataclass, field

from config_review.parser import ConfigNode
from config_review.vlan import parse_vlan_list

L2 = "L2"  # switchport（スイッチのポート）
L3 = "L3"  # ルーテッドポート（IP アドレスを持てるポート）

# L3 のポートでしか使えないコマンド（no の形も含む）。L2 のポートに入れるとエラーになる。
L3_COMMANDS = (
    "ip address",
    "ipv6 address",
    "ipv6 link-local",
    "ip unnumbered",
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
    "ip forward",
    "ip dhcp relay",
    "ipv6 dhcp relay",
    "hsrp",
    "vrrp",
)

# L2 のポートでしか使えないコマンド。「switchport」だけの行は L2 に切り替えるコマンドなので別扱い。
L2_COMMANDS = ("switchport",)

# no の形のまま show run に出る L3 の設定。現行 Config の L2 / L3 の判断に使ってよい。
SHOWN_L3_NO_FORMS = ("no ip redirects", "no ipv6 redirects")

# switchport / no switchport で L2 と L3 を切り替えられる interface
SWITCHABLE = re.compile(r"interface (Ethernet|port-channel)[\d/]+")
# L3 だけの interface（SVI・loopback・mgmt・tunnel・Ethernet1/1.100 のようなサブインターフェース）
L3_ONLY = re.compile(r"interface (Vlan\d+|loopback\d+|mgmt\d+|Tunnel\d+|(Ethernet|port-channel)[\d/]+\.\d+)")
# nve などそれ以外の interface は、使えるコマンドが違うので L2 / L3 のチェックをしない

# 使うのに feature の有効化が必要なコマンド。(行の形, 必要な feature)
# feature が無効だと、NX-OS ではコマンドそのものが無いことになり、投入するとエラーになる。
TOP_LEVEL_FEATURES = (
    (re.compile(r"interface Vlan\d+"), "interface-vlan"),
    (re.compile(r"interface nve\d+"), "nv overlay"),
    (re.compile(r"router ospf \S+"), "ospf"),
    (re.compile(r"router ospfv3 \S+"), "ospfv3"),
    (re.compile(r"router bgp \S+"), "bgp"),
    (re.compile(r"router eigrp \S+"), "eigrp"),
    (re.compile(r"vpc domain \d+"), "vpc"),
)
INTERFACE_FEATURES = (
    (re.compile(r"channel-group \d+ mode (active|passive)"), "lacp"),
    (re.compile(r"ip router ospf .*"), "ospf"),
    (re.compile(r"ip ospf .*"), "ospf"),
    (re.compile(r"ipv6 router ospfv3 .*"), "ospfv3"),
    (re.compile(r"ip router eigrp .*"), "eigrp"),
    (re.compile(r"ip pim .*"), "pim"),
    (re.compile(r"hsrp .*"), "hsrp"),
    (re.compile(r"vrrp .*"), "vrrp"),
    (re.compile(r"ip dhcp relay .*"), "dhcp"),
    (re.compile(r"vpc( \d+| peer-link)"), "vpc"),
)

# VLAN を使う interface の設定。作られていない VLAN を指定すると、入るが通信できない。
VLAN_USERS = re.compile(r"switchport (access vlan|trunk native vlan) (\d+)")
# トランクで通す VLAN の一覧（「allowed vlan 10,20」「allowed vlan add 30」）。消す VLAN が含まれていたら知らせる
ALLOWED_VLANS = re.compile(r"switchport trunk allowed vlan (?:add )?(\d[\d,\-]*)")
SVI = re.compile(r"interface Vlan(\d+)")
VLAN_SUMMARY = re.compile(r"vlan (\d[\d,\-]*)")


@dataclass
class Problem:
    interface: str  # 「interface Ethernet1/1」（interface 以外なら、その行）
    line: str  # 問題のある投入の行
    message: str  # 理由（画面に出す文章）
    rejected: bool  # True：実機ではエラーで入らない（想定 Config に入れていない）

    def __str__(self) -> str:
        where = "" if self.interface == self.line else f"{self.interface}："
        if self.rejected:
            return f"{where}「{self.line}」は実機ではエラーになって入らないはずです。{self.message}"
        return f"{where}「{self.line}」について確認してください。{self.message}"


def _matches(text: str, command: str) -> bool:
    return text == command or text.startswith(command + " ")


def command_kind(text: str) -> str | None:
    """行が L2 だけ・L3 だけのコマンドなら L2 / L3 を、どちらでもなければ None を返す。"""
    command = text.removeprefix("no ")
    if command == "switchport":
        return None  # L2 と L3 を切り替える行
    if any(_matches(command, c) for c in L2_COMMANDS):
        return L2
    if any(_matches(command, c) for c in L3_COMMANDS):
        return L3
    return None


def interface_mode(root: ConfigNode, interface: ConfigNode) -> str | None:
    """interface が今 L2 か L3 かを返す。Config から判断できなければ None。

    NX-OS の show run では、
      - L2 のポートには「switchport」や「switchport mode 〇〇」が
      - L3 のポートには「no switchport」や「ip address 〇〇」が
    表示される。どれもないときは機種や「system default switchport」の設定で決まる。
    """
    if L3_ONLY.fullmatch(interface.text):
        return L3

    for child in interface.children:
        if child.text == "switchport":
            return L2
        if child.text == "no switchport":
            return L3
    # 「no ip address」のような既定に戻すだけの行は、L3 の証拠にならないので使わない
    kinds = {
        command_kind(child.text)
        for child in interface.children
        if not child.text.startswith("no ") or child.text in SHOWN_L3_NO_FORMS
    }
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


def _feature_in_use(root: ConfigNode, feature: str) -> bool:
    """feature を使う設定が、もう Config にあるか。

    あれば feature は有効になっているはず（feature の行を貼り付け忘れただけ）なので、エラーにしない。
    """
    for block in root.children:
        if any(p.fullmatch(block.text) for p, f in TOP_LEVEL_FEATURES if f == feature):
            return True
        for child in block.children:
            if any(p.fullmatch(child.text) for p, f in INTERFACE_FEATURES if f == feature):
                return True
    return False


def vlan_summary(root: ConfigNode) -> ConfigNode | None:
    """VLAN の一覧の行（子の行を持たない「vlan 1,10,20」の行）。なければ None。"""
    return next(
        (c for c in root.children if not c.children and VLAN_SUMMARY.fullmatch(c.text)), None
    )


@dataclass
class Checker:
    """投入 Config を確かめて、見つけた Problem をためていく。

    一部だけ貼り付けた現行 Config だと「feature の行がない」「VLAN の一覧にない」が
    本当に無いのか、貼り付けていないだけなのか区別できない。そこで、
    現行 Config に feature の行・VLAN の一覧の行が 1 つでもあれば「全部貼られている」とみなす。
    """

    problems: list[Problem]
    features_known: bool = False
    vlans_known: bool = False
    _warned_features: set[str] = field(default_factory=set)
    # 投入 Config の中の「no feature 〇〇」で無効にした feature
    _disabled_features: set[str] = field(default_factory=set)

    @classmethod
    def for_config(cls, current: ConfigNode, problems: list[Problem]) -> "Checker":
        return cls(
            problems=problems,
            features_known=any(c.text.startswith("feature ") for c in current.children),
            vlans_known=vlan_summary(current) is not None,
        )

    # ---- feature ----

    def _feature_missing(self, root: ConfigNode, feature: str, where: str, line: str) -> bool:
        """feature が無効なら Problem を足す。エラーで入らないと言い切れるときだけ True を返す。

        root は反映の途中の状態なので、投入 Config の前のほうで「feature 〇〇」を入れていれば有効になっている。
        """
        if any(c.text == f"feature {feature}" for c in root.children):
            return False
        if feature not in self._disabled_features and _feature_in_use(root, feature):
            return False
        if self.features_known:
            self.problems.append(Problem(
                where, line,
                f"「feature {feature}」が有効になっていないので、このコマンドは使えません。"
                f"先に「feature {feature}」を投入する必要があります。想定 Config には入れていません。",
                rejected=True,
            ))
            return True
        if feature not in self._warned_features:
            # 同じ feature の確認のお願いは 1 回だけにする
            self._warned_features.add(feature)
            self.problems.append(Problem(
                where, line,
                f"「feature {feature}」が有効でないとエラーになります。現行 Config に feature の行がないので、"
                "有効かどうか判断できませんでした。show run の feature の行を確かめてください。",
                rejected=False,
            ))
        return False

    def check_top_level(self, root: ConfigNode, change: ConfigNode) -> bool:
        """interface Vlan10・router ospf 1 のような最上位の行を確かめる。入らないなら False。"""
        if change.text.startswith("no feature "):
            # 無効にしたあとは、その feature を使う設定が残っていても「有効」とはみなさない
            self._disabled_features.add(change.text.removeprefix("no feature "))
        elif change.text.startswith("feature "):
            self._disabled_features.discard(change.text.removeprefix("feature "))
        for pattern, feature in TOP_LEVEL_FEATURES:
            if pattern.fullmatch(change.text):
                # interface Vlan10 自体が入らなければ、その下の行も全部入らない
                return not self._feature_missing(root, feature, change.text, change.text)
        return True

    # ---- VLAN ----

    def _vlans(self, root: ConfigNode) -> set[int] | None:
        summary = vlan_summary(root)
        if not self.vlans_known or summary is None:
            return None
        return parse_vlan_list(VLAN_SUMMARY.fullmatch(summary.text).group(1))

    def _check_vlan_exists(self, root: ConfigNode, where: str, line: str, number: int) -> None:
        vlans = self._vlans(root)
        if vlans is not None and number not in vlans:
            self.problems.append(Problem(
                where, line,
                f"VLAN {number} が作られていません（vlan の一覧の行にありません）。"
                f"設定は入りますが、VLAN を作るまで通信できないはずです。先に「vlan {number}」の投入が必要か確かめてください。",
                rejected=False,
            ))

    def check_vlan_removal(self, root: ConfigNode, line: str, numbers: set[int]) -> None:
        """「no vlan 10」で消す VLAN を、まだ使っている interface があれば知らせる（1 つにまとめて）。"""
        users: list[str] = []
        for interface in root.children:
            lines = [
                c.text
                for c in interface.children
                if ((m := VLAN_USERS.fullmatch(c.text)) and int(m.group(2)) in numbers)
                or ((m := ALLOWED_VLANS.fullmatch(c.text)) and parse_vlan_list(m.group(1)) & numbers)
            ]
            if (m := SVI.fullmatch(interface.text)) and int(m.group(1)) in numbers:
                lines.append(interface.text)
            if lines:
                users.append(f"{interface.text}（{' / '.join(lines)}）")
        if users:
            self.problems.append(Problem(
                line, line,
                f"消す VLAN を使っている設定があります：{'、'.join(users)}。"
                "VLAN を消すと、この VLAN では通信できなくなるはずです。",
                rejected=False,
            ))

    # ---- interface ----

    def check_interface(self, root: ConfigNode, interface: ConfigNode, change: ConfigNode) -> ConfigNode:
        """interface に投入する行（change の子）を上から順に確かめる。

        エラーになるはずの行を除いた change のコピーを返し、理由を problems に足す。
        「no switchport」→「ip address」の順なら成功、逆の順なら失敗するので、
        1 行ずつ L2 / L3 の状態を進めながら確かめる。
        """
        allowed = ConfigNode(text=change.text)
        if (m := SVI.fullmatch(interface.text)) and not interface.children:
            # 新しく作る SVI だけ確かめる（前からある SVI は、もう VLAN と一緒に動いている）
            self._check_vlan_exists(root, interface.text, interface.text, int(m.group(1)))

        switchable = bool(SWITCHABLE.fullmatch(interface.text))
        checks_mode = switchable or bool(L3_ONLY.fullmatch(interface.text))
        mode = interface_mode(root, interface) if checks_mode else None
        unknown_kinds: set[str] = set()
        unknown_lines: list[str] = []

        for child in change.children:
            text = child.text
            if any(
                p.fullmatch(text) and self._feature_missing(root, f, interface.text, text)
                for p, f in INTERFACE_FEATURES
            ):
                continue
            if m := VLAN_USERS.fullmatch(text):
                self._check_vlan_exists(root, interface.text, text, int(m.group(2)))

            if not checks_mode:
                allowed.children.append(child)
                continue

            if text == "switchport" and not switchable:
                self.problems.append(Problem(
                    interface.text, text,
                    "この interface は L3 だけで、L2（switchport）には切り替えられません。"
                    "想定 Config には入れていません。",
                    rejected=True,
                ))
                continue
            if text == "switchport" and mode != L2:
                self._check_kept_ip_lines(interface, text)
            if text == "switchport" or text == "no switchport":
                mode = L2 if text == "switchport" else L3
                allowed.children.append(child)
                continue

            kind = command_kind(text)
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
            self.problems.append(Problem(
                interface.text, text,
                f"今は {mode} のポートなので、{kind} の設定は入れられません。{how}想定 Config には入れていません。",
                rejected=True,
            ))

        if unknown_kinds:
            if len(unknown_kinds) == 2:
                assumed = "L2 と L3 の設定が混ざっているので、どちらかは実機でエラーになるはずです（想定 Config にはどちらも入れました）。"
            else:
                assumed = f"{next(iter(unknown_kinds))} のポートとみなして想定 Config に入れました。"
            self.problems.append(Problem(
                interface.text, " / ".join(unknown_lines),
                "現行 Config からは、この interface が L2（switchport）か L3（no switchport）か判断できません。"
                f"{assumed}"
                "show run に「switchport」「no switchport」の行があるか、"
                "「system default switchport」の設定を確かめてください。",
                rejected=False,
            ))

        return allowed

    def _check_kept_ip_lines(self, interface: ConfigNode, line: str) -> None:
        """L2 に切り替えるとき、L3 の一覧にない ip の設定が残る想定になっていれば知らせる。

        ツールは L3_COMMANDS の一覧にある設定だけを「消える」扱いにしているので、
        ip access-group のような一覧にない設定が、実機でも残るのか消えるのかはわからない。
        """
        kept = [
            c.text
            for c in interface.children
            if c.text.removeprefix("no ").startswith(("ip ", "ipv6 ")) and command_kind(c.text) is None
        ]
        if kept:
            self.problems.append(Problem(
                interface.text, line,
                f"L2 に切り替えると ip address などの L3 の設定は消える扱いにしましたが、"
                f"{' / '.join(kept)} は残る扱いにしています。実機でも残るか確かめてください。",
                rejected=False,
            ))

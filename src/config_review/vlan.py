"""VLAN の一覧（"10,20-22" のような文字列）と、VLAN 番号の集合を行き来する。"""

# NX-OS のトランクで通せる VLAN の範囲。「allowed vlan all」はこの全部を意味する。
ALL_VLANS = frozenset(range(1, 4095))


def parse_vlan_list(text: str) -> set[int]:
    """"10,20-22" を {10, 20, 21, 22} にする。"""
    vlans: set[int] = set()
    for part in text.split(","):
        if "-" in part:
            start, end = part.split("-")
            vlans.update(range(int(start), int(end) + 1))
        else:
            vlans.add(int(part))
    return vlans


def format_vlan_list(vlans: set[int]) -> str:
    """{10, 20, 21, 22} を "10,20-22" にする。連続した番号は「始め-終わり」にまとめる。"""
    parts: list[str] = []
    numbers = sorted(vlans)
    i = 0
    while i < len(numbers):
        start = numbers[i]
        # start から 1 ずつ続いている間、i を進める
        while i + 1 < len(numbers) and numbers[i + 1] == numbers[i] + 1:
            i += 1
        end = numbers[i]
        parts.append(str(start) if start == end else f"{start}-{end}")
        i += 1
    return ",".join(parts)


def calc_allowed_vlans(current: set[int], value: str) -> set[int]:
    """「switchport trunk allowed vlan」に続く部分（value）を、current に当てはめた結果を返す。

    value の例：
      "10,20"       → 10,20 だけにする（置き換え）
      "add 30"      → 今の一覧に 30 を足す
      "remove 20"   → 今の一覧から 20 を引く
      "except 99"   → 99 以外の全部にする
      "all" / "none"→ 全部 / なし
    """
    words = value.split()
    keyword = words[0]

    if keyword == "all":
        return set(ALL_VLANS)
    if keyword == "none":
        return set()
    if keyword == "add":
        return current | parse_vlan_list(words[1])
    if keyword == "remove":
        return current - parse_vlan_list(words[1])
    if keyword == "except":
        return set(ALL_VLANS) - parse_vlan_list(words[1])
    return parse_vlan_list(keyword)

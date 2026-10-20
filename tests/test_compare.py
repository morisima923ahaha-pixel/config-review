from pathlib import Path

import pytest

from config_review.compare import compare

SAMPLES = Path(__file__).parent.parent / "samples"


def test_flat_change_with_abbreviation_gives_same_diff_as_indented():
    current = """interface Ethernet1/1
  shutdown"""
    indented = """interface Ethernet1/1
  no shutdown"""
    flat = """conf t
int e1/1
no shutdown
end"""

    assert compare(current, flat).diff == compare(current, indented).diff


def test_sample_files():
    result = compare(
        (SAMPLES / "cli" / "nxos_running.txt").read_text(encoding="utf-8"),
        (SAMPLES / "cli" / "nxos_change.txt").read_text(encoding="utf-8"),
    )

    assert result.diff == [
        "-hostname LAB-NX01",
        "+hostname LAB-NX02",
        "-feature lacp",
        "-vlan 1,10,20",
        "+vlan 1,10,20,30",
        "+vlan 30",
        "+  name GUEST",
        " interface Vlan10",
        "-  description USERS-GW",
        "+  description USERS-GW-NEW",
        "-  ip address 192.0.2.1/24",
        "+  ip address 192.0.2.2/24",
        " interface Ethernet1/1",
        "-  switchport trunk allowed vlan 10,20",
        "+  switchport trunk allowed vlan 10,20,30",
        " interface Ethernet1/2",
        "-  shutdown",
        "+  no shutdown",
        "+  description TO-LAB-SW02",
        "+  switchport access vlan 30",
    ]
    assert result.notes == []


def test_no_change_gives_empty_diff():
    result = compare("hostname A", "hostname A")

    assert result.diff == []
    assert result.expected == "hostname A"


def test_invalid_vlan_in_changes_raises_value_error():
    with pytest.raises(ValueError, match="10-2"):
        compare("vlan 1,10", "vlan 10-2")


# 会社の人に見せるデモ（samples/demo/）が、説明どおりの結果になること
DEMO = SAMPLES / "demo"


def demo(prefix: str):
    return compare(
        (DEMO / "0_現行config_左に読み込む.txt").read_text(encoding="utf-8"),
        next(DEMO.glob(f"{prefix}_*.txt")).read_text(encoding="utf-8"),
    )


def test_demo_1_interface_change():
    result = demo("1")

    assert result.problems == []
    assert "-  shutdown" in result.diff and "+  no shutdown" in result.diff
    assert "+  switchport access vlan 40" in result.diff


def test_demo_2_port_channel():
    result = demo("2")

    assert result.problems == []
    interfaces = [line for line in result.expected.splitlines() if line.startswith("interface")]
    assert interfaces.index("interface port-channel10") < interfaces.index("interface Ethernet1/1")
    # README の説明（範囲指定を 1 つずつに分ける・member にも同じ設定が入る）まで固定する（Codex の 7 回目 #8）
    member = [
        "-  shutdown",
        "+  no shutdown",
        "+  switchport mode trunk",
        "+  switchport trunk allowed vlan 10,20,30",
        "+  channel-group 10 mode active",
    ]
    assert result.diff == [
        "+interface port-channel10",
        "+  description TO-SW02",
        "+  switchport",
        "+  switchport mode trunk",
        "+  switchport trunk allowed vlan 10,20,30",
        " interface Ethernet1/3",
        *member,
        " interface Ethernet1/4",
        *member,
    ]


def test_demo_3_allowed_vlan_add():
    result = demo("3")

    assert result.diff == [
        " interface Ethernet1/1",
        "-  switchport trunk allowed vlan 10,20",
        "+  switchport trunk allowed vlan 10,20,30",
    ]


def test_demo_4_vrf_change_deletes_ip_address():
    result = demo("4")

    assert "-  ip address 192.0.2.1/24" in result.diff


def test_demo_5_ip_address_on_l2_port_is_rejected():
    result = demo("5")

    assert [p.line for p in result.errors] == ["ip address 198.51.100.1/30"]
    assert "ip address" not in result.expected.split("interface Ethernet1/1")[1].split("interface")[0]

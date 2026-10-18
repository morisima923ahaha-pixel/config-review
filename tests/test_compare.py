from pathlib import Path

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
        (SAMPLES / "nxos_running.txt").read_text(encoding="utf-8"),
        (SAMPLES / "nxos_change.txt").read_text(encoding="utf-8"),
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

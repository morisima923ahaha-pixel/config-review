from config_review.normalize import expand_interface_names, parse_changes, parse_running
from config_review.parser import to_text


def changes(text: str) -> str:
    return to_text(parse_changes(text)[0])


def test_conf_t_and_end_are_ignored():
    text = """conf t
hostname LAB-NX02
end
copy running-config startup-config"""

    root, notes = parse_changes(text)

    assert to_text(root) == "hostname LAB-NX02"
    assert len(notes) == 3


def test_flat_config_uses_block_lines_and_exit():
    text = """configure terminal
interface Ethernet1/1
description A
shutdown
exit
hostname LAB-NX02"""

    assert changes(text) == """interface Ethernet1/1
  description A
  shutdown
hostname LAB-NX02"""


def test_flat_config_next_block_closes_previous_block():
    text = """interface Ethernet1/1
description A
interface Ethernet1/2
description B"""

    assert changes(text) == """interface Ethernet1/1
  description A
interface Ethernet1/2
  description B"""


def test_flat_config_global_command_goes_back_to_top_level():
    text = """interface Ethernet1/1
description A
feature lacp"""

    assert changes(text) == """interface Ethernet1/1
  description A
feature lacp"""


def test_flat_config_vlan_block():
    text = """vlan 30
name GUEST
exit"""

    assert changes(text) == "vlan 30\n  name GUEST"


def test_flat_no_interface_is_top_level():
    text = """no interface Vlan10
hostname A"""

    assert changes(text) == "no interface Vlan10\nhostname A"


def test_exit_is_ignored_in_indented_config():
    text = """interface Ethernet1/1
  description A
  exit
hostname B"""

    assert changes(text) == """interface Ethernet1/1
  description A
hostname B"""


def test_tabs_are_treated_as_indent():
    text = "interface Ethernet1/1\n\tdescription A"

    assert changes(text) == "interface Ethernet1/1\n  description A"


def test_interface_abbreviations():
    assert changes("int e1/1\n  shutdown") == "interface Ethernet1/1\n  shutdown"
    assert changes("int vlan 10\n  shutdown") == "interface Vlan10\n  shutdown"
    assert changes("int po10\n  shutdown") == "interface port-channel10\n  shutdown"
    assert changes("interface lo0\n  shutdown") == "interface loopback0\n  shutdown"
    assert changes("no int eth1/1.100") == "no interface Ethernet1/1.100"


def test_interface_range_is_split_into_each_interface():
    text = """interface Ethernet1/1-2, Ethernet1/5
  description SERVER"""

    assert changes(text) == """interface Ethernet1/1
  description SERVER
interface Ethernet1/2
  description SERVER
interface Ethernet1/5
  description SERVER"""


def test_expand_interface_names():
    assert expand_interface_names("e1/1/1-3") == ["Ethernet1/1/1", "Ethernet1/1/2", "Ethernet1/1/3"]
    assert expand_interface_names("Vlan10-11") == ["Vlan10", "Vlan11"]
    assert expand_interface_names("unknown1/1") is None


def test_unknown_interface_is_left_as_is():
    assert changes("interface xyz1\n  shutdown") == "interface xyz1\n  shutdown"


def test_non_interface_line_starting_with_in_is_not_changed():
    # 「in」で始まるだけの行（interface の省略形ではない）はそのまま
    assert changes("install feature-set fex") == "install feature-set fex"


def test_running_config_interface_names_are_normalized():
    assert to_text(parse_running("interface ethernet1/1\n  shutdown")) == "interface Ethernet1/1\n  shutdown"

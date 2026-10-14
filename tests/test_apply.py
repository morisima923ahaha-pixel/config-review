from config_review.apply import apply_changes
from config_review.parser import parse_config, to_text


def apply(current: str, changes: str) -> str:
    """文字列で受け取って文字列で返す、テスト用の近道。"""
    return to_text(apply_changes(parse_config(current), parse_config(changes)))


def test_new_line_is_added():
    current = "hostname LAB-NX01"
    changes = "feature lacp"

    assert apply(current, changes) == "hostname LAB-NX01\nfeature lacp"


def test_existing_line_is_not_duplicated():
    current = "feature lacp"
    changes = "feature lacp"

    assert apply(current, changes) == "feature lacp"


def test_line_is_added_under_existing_interface():
    current = """interface Ethernet1/1
  switchport mode trunk"""
    changes = """interface Ethernet1/1
  description TO-LAB-SW01"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport mode trunk
  description TO-LAB-SW01"""


def test_new_interface_is_added_with_children():
    current = "hostname LAB-NX01"
    changes = """interface Ethernet1/3
  description NEW"""

    assert apply(current, changes) == """hostname LAB-NX01
interface Ethernet1/3
  description NEW"""


def test_no_removes_only_the_line_in_the_same_interface():
    current = """interface Ethernet1/1
  shutdown
interface Ethernet1/2
  shutdown"""
    changes = """interface Ethernet1/2
  no shutdown"""

    assert apply(current, changes) == """interface Ethernet1/1
  shutdown
interface Ethernet1/2"""


def test_no_removes_line_with_any_value():
    current = """interface Ethernet1/1
  description OLD"""
    changes = """interface Ethernet1/1
  no description"""

    assert apply(current, changes) == "interface Ethernet1/1"


def test_no_parent_removes_its_children():
    current = """interface Vlan10
  description USERS-GW
hostname LAB-NX01"""
    changes = "no interface Vlan10"

    assert apply(current, changes) == "hostname LAB-NX01"


def test_no_does_not_remove_a_similar_name():
    current = """interface Vlan10
interface Vlan100"""
    changes = "no interface Vlan10"

    assert apply(current, changes) == "interface Vlan100"


def test_positive_command_removes_its_no_form():
    current = """interface Vlan10
  no shutdown"""
    changes = """interface Vlan10
  shutdown"""

    assert apply(current, changes) == """interface Vlan10
  shutdown"""


def test_description_is_overwritten():
    current = """interface Ethernet1/1
  description OLD"""
    changes = """interface Ethernet1/1
  description NEW"""

    assert apply(current, changes) == """interface Ethernet1/1
  description NEW"""


def test_allowed_vlan_add_is_not_treated_as_overwrite():
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10,20"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan add 30"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport trunk allowed vlan 10,20
  switchport trunk allowed vlan add 30"""


def test_current_tree_is_not_modified():
    current = parse_config("hostname LAB-NX01")

    apply_changes(current, parse_config("hostname LAB-NX02"))

    assert to_text(current) == "hostname LAB-NX01"

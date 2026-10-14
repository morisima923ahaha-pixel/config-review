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


def test_allowed_vlan_add_is_merged_into_one_line():
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10,20"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan add 30"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport trunk allowed vlan 10,20,30"""


def test_allowed_vlan_remove():
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10,20,30"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan remove 20"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport trunk allowed vlan 10,30"""


def test_allowed_vlan_without_keyword_overwrites():
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10,20"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan 30"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport trunk allowed vlan 30"""


def test_allowed_vlan_keeps_its_position():
    current = """interface Ethernet1/1
  switchport mode trunk
  switchport trunk allowed vlan 10
  mtu 9216"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan add 20"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport mode trunk
  switchport trunk allowed vlan 10,20
  mtu 9216"""


def test_allowed_vlan_split_lines_in_running_config_are_combined():
    # 一覧が長いと、running-config でも「add」の行に分かれて表示される
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10-12
  switchport trunk allowed vlan add 100"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan add 13"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport trunk allowed vlan 10-13,100"""


def test_allowed_vlan_remove_from_default_all():
    # allowed vlan の行がない = 全部の VLAN を通している状態
    current = """interface Ethernet1/1
  switchport mode trunk"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan remove 30"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport mode trunk
  switchport trunk allowed vlan 1-29,31-4094"""


def test_allowed_vlan_add_to_default_all_changes_nothing():
    current = """interface Ethernet1/1
  switchport mode trunk"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan add 30"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport mode trunk"""


def test_allowed_vlan_remove_last_vlan_becomes_none():
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan remove 10"""

    assert apply(current, changes) == """interface Ethernet1/1
  switchport trunk allowed vlan none"""


def test_allowed_vlan_all_removes_the_line():
    current = """interface Ethernet1/1
  switchport trunk allowed vlan 10"""
    changes = """interface Ethernet1/1
  switchport trunk allowed vlan all"""

    assert apply(current, changes) == "interface Ethernet1/1"


def test_current_tree_is_not_modified():
    current = parse_config("hostname LAB-NX01")

    apply_changes(current, parse_config("hostname LAB-NX02"))

    assert to_text(current) == "hostname LAB-NX01"

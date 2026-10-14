from config_review.diff import diff_trees
from config_review.parser import parse_config


def diff(before: str, after: str) -> list[str]:
    return diff_trees(parse_config(before), parse_config(after))


def test_no_difference_returns_empty_list():
    config = """interface Ethernet1/1
  description A"""

    assert diff(config, config) == []


def test_added_top_level_line():
    assert diff("hostname A", "hostname A\nfeature lacp") == ["+feature lacp"]


def test_removed_parent_shows_its_children():
    before = """interface Vlan10
  description USERS-GW"""

    assert diff(before, "") == [
        "-interface Vlan10",
        "-  description USERS-GW",
    ]


def test_change_inside_interface_shows_parent_line():
    before = """interface Ethernet1/1
  description OLD
interface Ethernet1/2
  shutdown"""
    after = """interface Ethernet1/1
  description NEW
interface Ethernet1/2
  shutdown"""

    assert diff(before, after) == [
        " interface Ethernet1/1",
        "-  description OLD",
        "+  description NEW",
    ]

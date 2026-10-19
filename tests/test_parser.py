from pathlib import Path

from config_review.parser import ConfigNode, parse_config, to_text

SAMPLE = Path(__file__).parent.parent / "samples" / "cli" / "nxos_running.txt"


def test_top_level_lines_become_children_of_root():
    config = "hostname LAB-NX01\nfeature lacp"

    root = parse_config(config)

    assert [node.text for node in root.children] == ["hostname LAB-NX01", "feature lacp"]


def test_indented_lines_become_children_of_interface():
    config = """interface Ethernet1/1
  description TO-LAB-SW01
  switchport mode trunk"""

    root = parse_config(config)

    interface = root.children[0]
    assert interface.text == "interface Ethernet1/1"
    assert [node.text for node in interface.children] == [
        "description TO-LAB-SW01",
        "switchport mode trunk",
    ]


def test_three_levels_of_nesting():
    config = """router ospf 1
  vrf LAB
    area 0.0.0.1 nssa"""

    root = parse_config(config)

    router = root.children[0]
    vrf = router.children[0]
    assert vrf.text == "vrf LAB"
    assert vrf.children[0].text == "area 0.0.0.1 nssa"


def test_returning_to_top_level_after_nesting():
    config = """router ospf 1
  vrf LAB
    area 0.0.0.1 nssa
hostname LAB-NX01"""

    root = parse_config(config)

    assert [node.text for node in root.children] == ["router ospf 1", "hostname LAB-NX01"]


def test_comments_and_blank_lines_are_ignored():
    config = """!Command: show running-config

hostname LAB-NX01
!"""

    root = parse_config(config)

    assert [node.text for node in root.children] == ["hostname LAB-NX01"]


def test_trailing_spaces_and_crlf_are_ignored():
    config = "interface Ethernet1/1  \r\n  shutdown \r\n"

    root = parse_config(config)

    assert root.children == [
        ConfigNode("interface Ethernet1/1", [ConfigNode("shutdown")]),
    ]


def test_to_text_restores_the_original_config():
    config = """interface Ethernet1/1
  description TO-LAB-SW01
router ospf 1
  vrf LAB
    area 0.0.0.1 nssa"""

    assert to_text(parse_config(config)) == config


def test_sample_file_can_be_parsed():
    root = parse_config(SAMPLE.read_text(encoding="utf-8"))

    texts = [node.text for node in root.children]
    assert "hostname LAB-NX01" in texts
    assert "interface Ethernet1/1" in texts
    assert not any(text.startswith("!") for text in texts)

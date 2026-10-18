from config_review.compare import compare

L2_PORT = """interface Ethernet1/1
  switchport mode trunk
  switchport trunk allowed vlan 10"""

L3_PORT = """interface Ethernet1/1
  no switchport
  ip address 192.0.2.1/30"""


def test_l3_command_on_l2_port_is_rejected():
    result = compare(L2_PORT, "interface Ethernet1/1\n  ip address 192.0.2.1/30")

    assert result.diff == []
    assert "ip address" not in result.expected
    assert [(p.interface, p.line, p.rejected) for p in result.problems] == [
        ("interface Ethernet1/1", "ip address 192.0.2.1/30", True),
    ]
    assert "no switchport" in result.errors[0].message


def test_no_switchport_before_l3_command_is_accepted():
    result = compare(L2_PORT, "interface Ethernet1/1\n  no switchport\n  ip address 192.0.2.1/30")

    assert result.problems == []
    assert result.expected.splitlines() == [
        "interface Ethernet1/1",
        "  no switchport",
        "  ip address 192.0.2.1/30",
    ]


def test_l3_command_before_no_switchport_is_rejected():
    # 投入の順番が逆なら、ip address の時点ではまだ L2 なのでエラーになる
    result = compare(L2_PORT, "interface Ethernet1/1\n  ip address 192.0.2.1/30\n  no switchport")

    assert [p.line for p in result.errors] == ["ip address 192.0.2.1/30"]
    assert "ip address" not in result.expected


def test_l2_command_on_l3_port_is_rejected():
    result = compare(L3_PORT, "interface Ethernet1/1\n  switchport access vlan 10")

    assert [p.line for p in result.errors] == ["switchport access vlan 10"]
    assert "「switchport」で L2" in result.errors[0].message
    assert result.diff == []


def test_switchport_before_l2_command_is_accepted():
    result = compare(L3_PORT, "interface Ethernet1/1\n  switchport\n  switchport access vlan 10")

    # ip address が残っている警告は出るが、switchport access vlan はエラーにならない
    assert result.errors == []
    assert "  switchport access vlan 10" in result.expected.splitlines()


def test_mode_is_inferred_from_commands_without_switchport_line():
    # 「switchport」の行がなくても、switchport mode があれば L2 とわかる
    current = "interface Ethernet1/1\n  switchport mode access"

    result = compare(current, "interface Ethernet1/1\n  vrf member A")

    assert [p.line for p in result.errors] == ["vrf member A"]


def test_svi_cannot_take_switchport_commands():
    current = "interface Vlan10\n  ip address 192.0.2.1/24"

    result = compare(current, "interface Vlan10\n  switchport\n  switchport mode trunk")

    assert [p.line for p in result.errors] == ["switchport", "switchport mode trunk"]
    assert result.diff == []


def test_subinterface_is_l3():
    result = compare("", "interface Ethernet1/1.100\n  switchport access vlan 10\n  ip address 192.0.2.1/30")

    assert [p.line for p in result.errors] == ["switchport access vlan 10"]
    assert "  ip address 192.0.2.1/30" in result.expected.splitlines()


def test_unknown_mode_gives_warning_but_keeps_line():
    # switchport の行も L2/L3 の設定もない Ethernet は、機種や設定で L2 か L3 かが変わる
    current = "interface Ethernet1/1\n  description SERVER"

    result = compare(current, "interface Ethernet1/1\n  ip address 192.0.2.1/30")

    assert result.errors == []
    assert [(p.line, p.rejected) for p in result.warnings] == [("ip address 192.0.2.1/30", False)]
    assert "L3 のポートとみなして" in result.warnings[0].message
    assert "  ip address 192.0.2.1/30" in result.expected.splitlines()


def test_unknown_mode_with_both_kinds_warns_about_mixture():
    result = compare("", "interface Ethernet1/1\n  switchport access vlan 10\n  ip address 192.0.2.1/30")

    assert len(result.warnings) == 1
    assert "混ざっている" in result.warnings[0].message


def test_system_default_switchport_decides_unknown_ports():
    current = "system default switchport\ninterface Ethernet1/1\n  description SERVER"

    result = compare(current, "interface Ethernet1/1\n  ip address 192.0.2.1/30")

    assert [p.line for p in result.errors] == ["ip address 192.0.2.1/30"]


def test_unrelated_commands_are_not_checked():
    result = compare(L2_PORT, "interface Ethernet1/1\n  description UPLINK\n  ip dhcp snooping trust")

    assert result.problems == []


def test_check_uses_state_after_earlier_blocks():
    # 同じ interface のブロックが 2 回あっても、1 回目の反映後の状態で確かめる
    changes = """interface Ethernet1/1
  no switchport
interface Ethernet1/1
  ip address 192.0.2.1/30"""

    result = compare(L2_PORT, changes)

    assert result.problems == []


def test_interface_range_checks_each_port():
    current = L2_PORT + "\ninterface Ethernet1/2\n  no switchport"

    result = compare(current, "interface Ethernet1/1-2\n  ip address 192.0.2.1/30")

    assert [p.interface for p in result.errors] == ["interface Ethernet1/1"]


def test_switchport_on_port_with_l3_config_warns():
    result = compare(L3_PORT, "interface Ethernet1/1\n  switchport")

    assert result.errors == []
    assert [p.line for p in result.warnings] == ["switchport"]
    assert "ip address 192.0.2.1/30" in result.warnings[0].message


def test_port_channel_is_checked_like_ethernet():
    current = "interface port-channel10\n  switchport mode trunk"

    result = compare(current, "int po10\n  ip address 192.0.2.1/30")

    assert [p.interface for p in result.errors] == ["interface port-channel10"]

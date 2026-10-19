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


def test_switchport_removes_l3_config():
    # L2 に切り替えると、L3 の設定は消える（Codex のレビューから。Cisco の資料に記載あり）
    result = compare(L3_PORT, "interface Ethernet1/1\n  switchport")

    assert result.problems == []
    assert result.diff == [
        " interface Ethernet1/1",
        "-  no switchport",
        "-  ip address 192.0.2.1/30",
        "+  switchport",
    ]


def test_l3_command_before_switchport_is_removed_by_switchport():
    result = compare(L3_PORT, "interface Ethernet1/1\n  ip address 192.0.2.5/30\n  switchport")

    assert result.problems == []
    assert result.expected.splitlines() == ["interface Ethernet1/1", "  switchport"]


def test_l3_command_after_switchport_is_rejected():
    result = compare(L3_PORT, "interface Ethernet1/1\n  switchport\n  ip address 192.0.2.5/30")

    assert [p.line for p in result.errors] == ["ip address 192.0.2.5/30"]


def test_no_switchport_on_subinterface_is_accepted():
    # サブインターフェースは L3 なので、no switchport を書いてもエラーにしない
    result = compare("", "interface Ethernet1/1.2\n  no switchport\n  ip address 192.0.2.1/30")

    assert result.errors == []
    assert "  no switchport" in result.expected.splitlines()


def test_more_l3_commands_are_checked():
    result = compare(L2_PORT, "interface Ethernet1/1\n  ip unnumbered loopback0\n  ip forward")

    assert [p.line for p in result.errors] == ["ip unnumbered loopback0", "ip forward"]


def test_nve_is_not_checked_as_l2_or_l3():
    result = compare("feature nv overlay", "interface nve1\n  switchport\n  source-interface loopback1")

    assert result.problems == []


def test_no_form_is_not_evidence_of_l3():
    # 「no ip address」は既定に戻すだけなので、L3 の証拠にしない
    current = "interface Ethernet1/1\n  no ip address"

    result = compare(current, "interface Ethernet1/1\n  switchport access vlan 10")

    assert result.errors == []


# ---- feature ----

FEATURES = "feature lacp\nfeature ospf"


def test_svi_without_feature_interface_vlan_is_rejected():
    result = compare(FEATURES, "interface Vlan10\n  ip address 192.0.2.1/24\n  no shutdown")

    assert [(p.line, p.rejected) for p in result.problems] == [("interface Vlan10", True)]
    assert "feature interface-vlan" in result.errors[0].message
    assert "Vlan10" not in result.expected


def test_feature_enabled_earlier_in_changes_is_accepted():
    changes = "feature interface-vlan\ninterface Vlan10\n  ip address 192.0.2.1/24"

    result = compare(FEATURES, changes)

    assert result.problems == []
    assert "interface Vlan10" in result.expected


def test_feature_enabled_after_use_is_rejected():
    # 投入の順番が逆なら、interface Vlan10 の時点ではまだ使えない
    changes = "interface Vlan10\n  ip address 192.0.2.1/24\nfeature interface-vlan"

    result = compare(FEATURES, changes)

    assert [p.line for p in result.errors] == ["interface Vlan10"]


def test_feature_disabled_in_changes_rejects_later_use():
    changes = "no feature lacp\ninterface Ethernet1/1\n  channel-group 10 mode active"

    result = compare(FEATURES + "\n" + L2_PORT, changes)

    assert [p.line for p in result.errors] == ["channel-group 10 mode active"]


def test_channel_group_mode_on_does_not_need_lacp():
    result = compare("feature ospf\n" + L2_PORT, "interface Ethernet1/1\n  channel-group 10 mode on")

    assert result.problems == []


def test_interface_command_without_feature_is_rejected():
    current = FEATURES + "\n" + L3_PORT

    result = compare(current, "interface Ethernet1/1\n  ip router ospf 1 area 0.0.0.0\n  ip pim sparse-mode")

    assert [p.line for p in result.errors] == ["ip pim sparse-mode"]
    assert "feature pim" in result.errors[0].message


def test_partial_config_without_feature_lines_gives_one_warning():
    # feature の行が 1 つもない現行 Config は、一部だけ貼られた可能性があるので断定しない
    changes = "interface Vlan10\n  no shutdown\ninterface Vlan20\n  no shutdown"

    result = compare("hostname LAB", changes)

    assert result.errors == []
    assert len(result.warnings) == 1
    assert "feature interface-vlan" in result.warnings[0].message
    assert "interface Vlan20" in result.expected


# ---- VLAN ----

VLANS = "vlan 1,10\nvlan 10\n  name USERS"


def test_access_vlan_that_does_not_exist_gives_warning():
    result = compare(VLANS + "\n" + L2_PORT, "interface Ethernet1/1\n  switchport access vlan 20")

    assert result.errors == []
    assert [p.line for p in result.warnings] == ["switchport access vlan 20"]
    assert "  switchport access vlan 20" in result.expected.splitlines()


def test_vlan_created_earlier_in_changes_is_fine():
    changes = "vlan 20\ninterface Ethernet1/1\n  switchport access vlan 20"

    result = compare(VLANS + "\n" + L2_PORT, changes)

    assert result.problems == []


def test_vlan_check_is_skipped_without_vlan_summary():
    result = compare(L2_PORT, "interface Ethernet1/1\n  switchport access vlan 20")

    assert result.problems == []


def test_new_svi_for_missing_vlan_gives_warning():
    current = "feature interface-vlan\n" + VLANS

    result = compare(current, "interface Vlan20\n  no shutdown")

    assert [p.interface for p in result.warnings] == ["interface Vlan20"]


def test_removing_vlan_in_use_gives_warning():
    current = VLANS + "\ninterface Ethernet1/2\n  switchport\n  switchport access vlan 10"

    result = compare(current, "no vlan 10")

    assert [p.line for p in result.warnings] == ["no vlan 10"]
    assert "Ethernet1/2" in result.warnings[0].message


def test_port_channel_is_checked_like_ethernet():
    current = "interface port-channel10\n  switchport mode trunk"

    result = compare(current, "int po10\n  ip address 192.0.2.1/30")

    assert [p.interface for p in result.errors] == ["interface port-channel10"]


def test_feature_in_use_is_treated_as_enabled():
    # feature の行を貼り忘れていても、もう SVI があるなら feature interface-vlan は有効のはず
    current = "feature lacp\ninterface Vlan10\n  no shutdown"

    result = compare(current, "interface Vlan20\n  no shutdown")

    assert result.problems == []


def test_problem_text_does_not_repeat_line():
    result = compare(FEATURES, "interface Vlan10\n  no shutdown")

    assert str(result.errors[0]).startswith("「interface Vlan10」は実機では")


def test_switchport_warns_about_ip_lines_it_keeps():
    current = L3_PORT + "\n  ip access-group ACL in"

    result = compare(current, "interface Ethernet1/1\n  switchport")

    assert "ip address" not in result.expected
    assert [p.line for p in result.warnings] == ["switchport"]
    assert "ip access-group ACL in" in result.warnings[0].message


def test_feature_disabled_in_changes_is_not_revived_by_existing_use():
    # 先に channel-group を消してから無効にしたので、no feature lacp は入る。そのあとの active はエラー
    current = "feature lacp\ninterface Ethernet1/1\n  switchport\n  channel-group 10 mode active"
    changes = """interface Ethernet1/1
  no channel-group 10
no feature lacp
interface Ethernet1/2
  channel-group 20 mode active"""

    result = compare(current, changes)

    assert [p.line for p in result.errors] == ["channel-group 20 mode active"]


def test_no_feature_lacp_fails_while_lacp_is_used():
    # 2026-10-19 に実機で確認：active の channel-group が残っていると、no feature lacp はエラーになる
    current = "feature lacp\ninterface Ethernet1/1\n  switchport\n  channel-group 10 mode active"

    result = compare(current, "no feature lacp")

    assert [p.line for p in result.errors] == ["no feature lacp"]
    assert "LACP disable failed" in result.errors[0].message
    assert result.expected == current  # feature lacp も channel-group も残る


def test_no_feature_lacp_is_accepted_with_mode_on():
    # mode on は LACP を使わないので、無効にできる
    current = "feature lacp\ninterface Ethernet1/1\n  channel-group 10"

    result = compare(current, "no feature lacp")

    assert result.problems == []
    assert result.expected == "interface Ethernet1/1\n  channel-group 10"


def test_primary_address_cannot_be_removed_before_secondary():
    # 2026-10-19 に実機で確認：「Must delete secondary address before deleting primary address」
    current = """interface loopback1
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary"""

    result = compare(current, "interface loopback1\n  no ip address 192.0.2.1/24")

    assert [p.line for p in result.errors] == ["no ip address 192.0.2.1/24"]
    assert "Must delete secondary address" in result.errors[0].message
    assert result.expected == current


def test_primary_address_can_be_removed_after_secondary():
    current = """interface loopback1
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary"""
    changes = """interface loopback1
  no ip address 198.51.100.1/24 secondary
  no ip address 192.0.2.1/24"""

    result = compare(current, changes)

    assert result.problems == []
    assert result.expected == "interface loopback1"


def test_primary_address_can_be_removed_after_vrf_change():
    # VRF を変えると secondary も消えるので、そのあとの no ip address はエラーにしない
    current = """interface loopback1
  vrf member A
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary"""
    changes = """interface loopback1
  vrf member B
  no ip address 192.0.2.1/24"""

    result = compare(current, changes)

    assert result.errors == []
    assert result.expected == "interface loopback1\n  vrf member B"


def test_rejected_switchport_on_loopback_keeps_secondary_check():
    # loopback に switchport は入らないので、secondary は残ったまま。primary は消せない
    current = """interface loopback1
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary"""
    changes = """interface loopback1
  switchport
  no ip address 192.0.2.1/24"""

    result = compare(current, changes)

    assert [p.line for p in result.errors] == ["switchport", "no ip address 192.0.2.1/24"]


def test_rejected_l2_l3_line_shows_device_error():
    result = compare("interface Ethernet1/1\n  switchport mode trunk", "interface Ethernet1/1\n  ip address 192.0.2.1/30")

    assert "Syntax error while parsing 'ip address 192.0.2.1/30'" in result.errors[0].message


def test_missing_feature_shows_device_error_only_when_checked():
    result = compare(
        "feature ospf",
        "interface Ethernet1/1\n  channel-group 10 mode active\ninterface Vlan10\n  no shutdown\nrouter eigrp 1",
    )

    messages = {p.line: p.message for p in result.errors}
    assert "LACP process needs to be started" in messages["channel-group 10 mode active"]
    assert "Syntax error while parsing 'interface Vlan10'" in messages["interface Vlan10"]
    assert "実機の表示" not in messages["router eigrp 1"]  # eigrp は実機で確かめていない


def test_device_error_is_not_shown_for_unchecked_line_of_checked_feature():
    # Codex の指摘：同じ feature でも、確かめた形にだけ添える（ip ospf・router ospf は 2026-10-19 の昼に確認）
    result = compare(
        "feature lacp",
        "router ospf 1\ninterface Ethernet1/1\n  no switchport\n  ip router ospf 1 area 0.0.0.0\n"
        "  ip ospf cost 10\n  ipv6 router ospfv3 1 area 0.0.0.0\n  vrrp 1",
    )

    messages = {p.line: p.message for p in result.errors}
    assert "Syntax error while parsing 'router ospf 1'" in messages["router ospf 1"]
    assert "Syntax error while parsing 'ip ospf cost 10'" in messages["ip ospf cost 10"]
    assert "Syntax error while parsing 'ip router ospf 1 area 0.0.0.0'" in messages["ip router ospf 1 area 0.0.0.0"]
    assert "実機の表示" not in messages["ipv6 router ospfv3 1 area 0.0.0.0"]
    assert "実機の表示" not in messages["vrrp 1"]


# ここから下は、2026-10-19 の昼に NX-OS 10.4(2) の実機で確かめた結果に合わせている
def test_no_vrf_member_with_other_name_is_rejected():
    current = "interface loopback1\n  vrf member A\n  ip address 192.0.2.1/24"

    result = compare(current, "interface loopback1\n  no vrf member B")

    assert result.diff == []
    assert [p.line for p in result.errors] == ["no vrf member B"]
    assert "ERROR: VRF B not configured on interface loopback1" in result.errors[0].message


def test_no_vrf_member_with_same_name_deletes_l3_config():
    current = "interface loopback1\n  vrf member A\n  ip address 192.0.2.1/24"

    result = compare(current, "interface loopback1\n  no vrf member A")

    assert result.errors == []
    assert result.expected == "interface loopback1"


def test_vrf_change_in_changes_is_used_for_no_vrf_member():
    current = "interface loopback1\n  vrf member A"

    result = compare(current, "interface loopback1\n  vrf member B\n  no vrf member B")

    assert result.errors == []
    assert result.expected == "interface loopback1"


def test_dhcp_relay_on_loopback_is_rejected():
    result = compare("feature dhcp\ninterface loopback1", "interface loopback1\n  ip dhcp relay address 192.0.2.200")

    assert [p.line for p in result.errors] == ["ip dhcp relay address 192.0.2.200"]
    assert "not allowed on loopback" in result.errors[0].message


def test_no_feature_removes_its_users():
    current = """feature ospf
router ospf 1
interface loopback1
  ip address 192.0.2.1/24
  ip router ospf 1 area 0.0.0.0
  ip ospf cost 10"""

    result = compare(current, "no feature ospf")

    assert result.expected == "interface loopback1\n  ip address 192.0.2.1/24"
    assert "黙って消えます" in result.warnings[0].message
    assert "router ospf 1" in result.warnings[0].message


def test_no_feature_interface_vlan_removes_svi():
    current = "feature interface-vlan\ninterface Vlan10\n  ip address 192.0.2.1/24\ninterface Ethernet1/1"

    result = compare(current, "no feature interface-vlan")

    assert result.expected == "interface Ethernet1/1"


def test_no_feature_hsrp_removes_hsrp_block():
    current = "feature hsrp\ninterface Ethernet1/1\n  no switchport\n  hsrp 1\n    ip 192.0.2.6"

    result = compare(current, "no feature hsrp")

    assert result.expected == "interface Ethernet1/1\n  no switchport"


def test_no_feature_not_checked_on_device_keeps_users():
    current = "feature bgp\nrouter bgp 65000\n  router-id 192.0.2.1"

    result = compare(current, "no feature bgp")

    assert result.expected == "router bgp 65000\n  router-id 192.0.2.1"
    assert "確かめていない" in result.warnings[0].message


def test_rejected_channel_group_does_not_add_port_channel():
    result = compare("feature ospf\ninterface Ethernet1/1", "interface Ethernet1/1\n  channel-group 20 mode active")

    assert [p.line for p in result.errors] == ["channel-group 20 mode active"]
    assert "port-channel" not in result.expected


def test_secondary_added_in_changes_blocks_primary_removal():
    # Codex の指摘を確かめたテスト（指摘はまちがいだった）：投入の中で足した secondary も数える
    changes = """interface loopback1
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary
  no ip address 192.0.2.1/24"""

    result = compare("interface loopback1", changes)

    assert [p.line for p in result.errors] == ["no ip address 192.0.2.1/24"]


def test_channel_group_mode_change_is_overwritten():
    # Codex の指摘を確かめたテスト（指摘はまちがいだった）：mode を変えても行は 1 つ
    current = "feature lacp\ninterface port-channel10\ninterface Ethernet1/1\n  channel-group 10"

    result = compare(current, "interface Ethernet1/1\n  channel-group 10 mode active")

    assert result.expected == "feature lacp\ninterface port-channel10\ninterface Ethernet1/1\n  channel-group 10 mode active"


def test_feature_enabled_after_another_feature_disabled_is_accepted():
    # Codex の指摘（2 回目）を確かめたテスト：feature を入れたあとなら、別の feature を消していても入る
    result = compare("feature lacp", "no feature lacp\nfeature interface-vlan\ninterface Vlan10\n  no shutdown")

    assert result.problems == []


def test_removing_vlan_in_allowed_list_gives_one_warning():
    current = """vlan 1,10,20
interface Ethernet1/1
  switchport mode trunk
  switchport trunk allowed vlan 10,20
interface Ethernet1/2
  switchport access vlan 20"""

    result = compare(current, "no vlan 10,20")

    assert len(result.warnings) == 1
    assert "Ethernet1/1" in result.warnings[0].message
    assert "Ethernet1/2" in result.warnings[0].message


def test_feature_disabled_then_enabled_again_is_accepted():
    # Codex の指摘（3 回目）を確かめたテスト：入れ直したあとは使える
    current = "feature lacp\ninterface Ethernet1/2\n  switchport"
    changes = "no feature lacp\nfeature lacp\ninterface Ethernet1/2\n  channel-group 20 mode active"

    result = compare(current, changes)

    assert result.problems == []

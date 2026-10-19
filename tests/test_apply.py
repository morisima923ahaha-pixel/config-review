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
  description A
interface Ethernet1/2
  description B"""
    changes = """interface Ethernet1/2
  no description"""

    assert apply(current, changes) == """interface Ethernet1/1
  description A
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


# ---- 弱点2：VLAN の一覧の行（vlan 1,10,20） ----


def test_new_vlan_is_added_to_vlan_list():
    current = """vlan 1,10,20
vlan 10
  name USERS"""
    changes = """vlan 30
  name GUEST"""

    assert apply(current, changes) == """vlan 1,10,20,30
vlan 10
  name USERS
vlan 30
  name GUEST"""


def test_new_vlan_without_name_only_updates_the_list():
    # name などの設定がない VLAN は、一覧の行にだけ出る
    current = "vlan 1,10"
    changes = "vlan 20-22"

    assert apply(current, changes) == "vlan 1,10,20-22"


def test_vlan_block_is_inserted_in_number_order():
    current = """vlan 1,10,30
vlan 10
  name A
vlan 30
  name C"""
    changes = """vlan 20
  name B"""

    assert apply(current, changes) == """vlan 1,10,20,30
vlan 10
  name A
vlan 20
  name B
vlan 30
  name C"""


def test_no_vlan_removes_it_from_list_and_its_block():
    current = """vlan 1,10,20
vlan 10
  name USERS
vlan 20
  name SERVERS"""
    changes = "no vlan 10"

    assert apply(current, changes) == """vlan 1,20
vlan 20
  name SERVERS"""


def test_existing_vlan_name_is_overwritten():
    current = """vlan 1,10
vlan 10
  name OLD"""
    changes = """vlan 10
  name NEW"""

    assert apply(current, changes) == """vlan 1,10
vlan 10
  name NEW"""


def test_vlan_list_is_created_when_current_has_none():
    # 一覧の行がない Config は、VLAN 1 だけがある状態とみなす
    current = "hostname LAB-NX01"
    changes = "vlan 30"

    assert apply(current, changes) == "hostname LAB-NX01\nvlan 1,30"


def test_vlan_configuration_is_not_treated_as_vlan_list():
    current = "vlan 1,10"
    changes = """vlan configuration 10
  ip igmp snooping"""

    assert apply(current, changes) == """vlan 1,10
vlan configuration 10
  ip igmp snooping"""


# ---- 弱点3：上書きした行は、元の行の場所に入る ----


def test_overwritten_line_keeps_its_position():
    current = """hostname LAB-NX01
feature lacp"""
    changes = "hostname LAB-NX02"

    assert apply(current, changes) == """hostname LAB-NX02
feature lacp"""


# ---- 弱点4：ip address secondary ----


def test_secondary_address_does_not_overwrite_primary():
    current = """interface Vlan10
  ip address 192.0.2.1/24"""
    changes = """interface Vlan10
  ip address 198.51.100.1/24 secondary"""

    assert apply(current, changes) == """interface Vlan10
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary"""


def test_primary_address_overwrites_only_primary():
    current = """interface Vlan10
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary"""
    changes = """interface Vlan10
  ip address 192.0.2.2/24"""

    assert apply(current, changes) == """interface Vlan10
  ip address 192.0.2.2/24
  ip address 198.51.100.1/24 secondary"""


def test_no_secondary_removes_only_that_address():
    current = """interface Vlan10
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary
  ip address 203.0.113.1/24 secondary"""
    changes = """interface Vlan10
  no ip address 198.51.100.1/24 secondary"""

    assert apply(current, changes) == """interface Vlan10
  ip address 192.0.2.1/24
  ip address 203.0.113.1/24 secondary"""


# ---- 弱点5：no shutdown などの「no の形で表示される行」 ----


def test_no_shutdown_on_new_svi_is_shown():
    current = "hostname LAB-NX01"
    changes = """interface Vlan30
  ip address 192.0.2.1/24
  no shutdown"""

    assert apply(current, changes) == """hostname LAB-NX01
interface Vlan30
  ip address 192.0.2.1/24
  no shutdown"""


def test_no_shutdown_replaces_shutdown_in_place():
    current = """interface Ethernet1/2
  description A
  shutdown
  mtu 9216"""
    changes = """interface Ethernet1/2
  no shutdown"""

    assert apply(current, changes) == """interface Ethernet1/2
  description A
  no shutdown
  mtu 9216"""


def test_shutdown_replaces_no_shutdown_in_place():
    current = """interface Vlan10
  no shutdown
  ip address 192.0.2.1/24"""
    changes = """interface Vlan10
  shutdown"""

    assert apply(current, changes) == """interface Vlan10
  shutdown
  ip address 192.0.2.1/24"""


def test_no_switchport_removes_switchport_settings():
    current = """interface Ethernet1/5
  switchport mode trunk
  switchport trunk allowed vlan 10
  mtu 9216"""
    changes = """interface Ethernet1/5
  no switchport
  ip address 192.0.2.1/30"""

    assert apply(current, changes) == """interface Ethernet1/5
  no switchport
  mtu 9216
  ip address 192.0.2.1/30"""


def test_no_ip_redirects_is_shown_and_ip_redirects_removes_it():
    current = "interface Vlan10"

    after_no = apply(current, "interface Vlan10\n  no ip redirects")
    assert after_no == "interface Vlan10\n  no ip redirects"

    assert apply(after_no, "interface Vlan10\n  ip redirects") == "interface Vlan10"


def test_vlan_block_is_not_mistaken_for_vlan_list():
    # 一覧の行がない Config（一部だけ貼り付けた場合）でも、vlan 10 のブロックを壊さない
    current = """vlan 10
  name USERS"""
    changes = """vlan 30
  name GUEST"""

    assert apply(current, changes) == """vlan 1,10,30
vlan 10
  name USERS
vlan 30
  name GUEST"""


def test_vrf_member_and_channel_group_are_overwritten():
    current = """interface Vlan10
  vrf member A
interface Ethernet1/1
  channel-group 10 mode active"""
    changes = """interface Vlan10
  vrf member B
interface Ethernet1/1
  channel-group 20 mode active"""

    # channel-group を入れると、その番号の port-channel ができる
    assert apply(current, changes) == """interface Vlan10
  vrf member B
interface port-channel20
interface Ethernet1/1
  channel-group 20 mode active"""


# ここから下の port-channel・上書き・no の形・mtu のテストは、2026-10-19 に NX-OS 10.4(2) の実機で確かめた結果に合わせている
def test_channel_group_mode_on_is_shown_without_mode():
    changes = "interface Ethernet1/1\n  channel-group 10 mode on"

    assert apply("interface Ethernet1/1", changes) == """interface port-channel10
interface Ethernet1/1
  channel-group 10"""


def test_port_channel_is_placed_before_ethernet():
    current = "interface Vlan10\ninterface Ethernet1/1\ninterface Ethernet1/2"
    changes = "interface Ethernet1/2\n  channel-group 10 mode on"

    assert apply(current, changes) == """interface Vlan10
interface port-channel10
interface Ethernet1/1
interface Ethernet1/2
  channel-group 10"""


def test_port_channel_is_placed_in_number_order():
    # ほかの port-channel があるときの並び順は、実機で確かめていない（Codex の 6 回目 #1）。今のツールの動きを固定するだけ
    current = "interface port-channel5\ninterface port-channel20\ninterface Ethernet1/1"
    changes = "interface Ethernet1/1\n  channel-group 10 mode on"

    assert apply(current, changes).splitlines()[:3] == [
        "interface port-channel5",
        "interface port-channel10",
        "interface port-channel20",
    ]


def test_existing_port_channel_is_not_added_again():
    current = "interface port-channel10\n  description UPLINK\ninterface Ethernet1/1"
    changes = "interface Ethernet1/1\n  channel-group 10 mode active"

    assert apply(current, changes) == """interface port-channel10
  description UPLINK
interface Ethernet1/1
  channel-group 10 mode active"""


def test_existing_channel_group_does_not_add_port_channel():
    # 一部だけ貼った現行 Config では、port-channel のブロックを貼っていないだけかもしれない
    current = "interface Ethernet1/1\n  channel-group 10 mode active"

    assert apply(current, "interface Ethernet1/1\n  description A") == current + "\n  description A"


def test_load_interval_and_spanning_tree_cost_are_overwritten():
    current = """interface Ethernet1/1
  spanning-tree cost 100
  load-interval counter 1 60
  load-interval counter 2 120"""
    changes = """interface Ethernet1/1
  spanning-tree cost 200
  load-interval counter 1 90"""

    # counter 2 は別の値なので残る
    assert apply(current, changes) == """interface Ethernet1/1
  spanning-tree cost 200
  load-interval counter 1 90
  load-interval counter 2 120"""


def test_no_cdp_enable_is_shown_and_cdp_enable_removes_it():
    assert apply("interface Ethernet1/1", "interface Ethernet1/1\n  no cdp enable") == """interface Ethernet1/1
  no cdp enable"""
    assert apply("interface Ethernet1/1\n  no cdp enable", "interface Ethernet1/1\n  cdp enable") == "interface Ethernet1/1"


def test_switchport_from_l3_removes_mtu():
    current = """interface Ethernet1/1
  no switchport
  mtu 9216
  ip address 192.0.2.1/30"""

    assert apply(current, "interface Ethernet1/1\n  switchport") == """interface Ethernet1/1
  switchport"""


def test_switchport_on_l2_keeps_mtu():
    current = """interface Ethernet1/1
  switchport mode trunk
  mtu 9216"""

    assert apply(current, "interface Ethernet1/1\n  switchport") == """interface Ethernet1/1
  switchport mode trunk
  mtu 9216
  switchport"""


# vrf member の動きは、2026-10-19 に NX-OS 10.4(2) の実機で確かめた結果に合わせている
def test_changing_vrf_deletes_l3_config():
    current = """interface Vlan10
  description USERS
  vrf member A
  ip address 192.0.2.1/24
  ip address 198.51.100.1/24 secondary
  no ip redirects
  ip router ospf 1 area 0.0.0.0
  no shutdown"""
    changes = """interface Vlan10
  vrf member B"""

    # L3 の設定は消えるが、description や shutdown は残る
    assert apply(current, changes) == """interface Vlan10
  description USERS
  vrf member B
  no shutdown"""


def test_joining_vrf_from_default_deletes_l3_config():
    current = """interface Vlan10
  ip address 192.0.2.1/24
  no shutdown"""
    changes = """interface Vlan10
  vrf member B"""

    # vrf member の行は、消えた ip address の場所に入る
    assert apply(current, changes) == """interface Vlan10
  vrf member B
  no shutdown"""


def test_same_vrf_again_keeps_l3_config():
    current = """interface Vlan10
  vrf member A
  ip address 192.0.2.1/24"""
    changes = """interface Vlan10
  vrf member A"""

    assert apply(current, changes) == current


def test_no_vrf_member_deletes_l3_config():
    current = """interface Vlan10
  vrf member A
  ip address 192.0.2.1/24
  no shutdown"""
    changes = """interface Vlan10
  no vrf member A"""

    assert apply(current, changes) == """interface Vlan10
  no shutdown"""


def test_ip_address_after_vrf_change_is_kept():
    # ふだんの手順：VRF を変えてから ip address を入れ直す
    current = """interface Vlan10
  vrf member A
  ip address 192.0.2.1/24"""
    changes = """interface Vlan10
  vrf member B
  ip address 192.0.2.1/24"""

    assert apply(current, changes) == """interface Vlan10
  vrf member B
  ip address 192.0.2.1/24"""


def test_ip_address_before_vrf_change_is_deleted():
    # 順番が逆だと、入れた ip address も VRF の変更で消える
    current = """interface Vlan10
  vrf member A
  ip address 192.0.2.1/24"""
    changes = """interface Vlan10
  ip address 192.0.2.2/24
  vrf member B"""

    assert apply(current, changes) == """interface Vlan10
  vrf member B"""


# ここから下は、2026-10-19 の昼に NX-OS 10.4(2) の実機で確かめた結果に合わせている
def test_vrf_change_deletes_more_l3_config():
    current = """interface Ethernet1/1
  description A
  no switchport
  mtu 9216
  load-interval counter 1 60
  ip access-group ACL1 in
  vrf member A
  ip address 192.0.2.5/30
  ip directed-broadcast
  ipv6 address 2001:db8::5/64
  ipv6 nd ra-interval 30 min 10
  ip igmp version 3
  ip local-proxy-arp"""

    # ip access-group・mtu・load-interval・description は残る
    assert apply(current, "interface Ethernet1/1\n  vrf member B") == """interface Ethernet1/1
  description A
  no switchport
  mtu 9216
  load-interval counter 1 60
  ip access-group ACL1 in
  vrf member B"""


def test_no_vrf_member_with_other_name_changes_nothing():
    current = "interface loopback1\n  vrf member A\n  ip address 192.0.2.1/24"

    assert apply(current, "interface loopback1\n  no vrf member B") == current


def test_access_group_is_overwritten_per_direction():
    current = "interface Ethernet1/1\n  no switchport\n  ip access-group ACL1 in"
    changes = "interface Ethernet1/1\n  ip access-group ACL2 in\n  ip access-group ACL1 out"

    assert apply(current, changes) == """interface Ethernet1/1
  no switchport
  ip access-group ACL2 in
  ip access-group ACL1 out"""


def test_service_policy_input_is_overwritten():
    current = "interface Ethernet1/1\n  service-policy type qos input PM1"

    assert apply(current, "interface Ethernet1/1\n  service-policy type qos input PM2") == (
        "interface Ethernet1/1\n  service-policy type qos input PM2"
    )


def test_default_load_interval_is_not_shown():
    current = "interface Ethernet1/1\n  load-interval counter 1 60\n  load-interval counter 2 120"
    changes = "interface Ethernet1/1\n  load-interval counter 1 30\n  load-interval counter 2 300"

    assert apply(current, changes) == "interface Ethernet1/1"


def test_no_snmp_trap_link_status_is_shown_and_positive_removes_it():
    no_form = apply("interface Ethernet1/1", "interface Ethernet1/1\n  no snmp trap link-status")
    assert no_form == "interface Ethernet1/1\n  no snmp trap link-status"
    assert apply(no_form, "interface Ethernet1/1\n  snmp trap link-status") == "interface Ethernet1/1"


def test_logging_event_link_status_shows_both_forms():
    no_form = apply("interface Ethernet1/1", "interface Ethernet1/1\n  no logging event port link-status")
    assert no_form == "interface Ethernet1/1\n  no logging event port link-status"
    assert apply(no_form, "interface Ethernet1/1\n  logging event port link-status") == (
        "interface Ethernet1/1\n  logging event port link-status"
    )


def test_ospf_area_number_is_shown_as_dotted():
    current = "interface loopback1\n  ip router ospf 1 area 0.0.0.0"

    # 投入の「area 0」は現行の「area 0.0.0.0」と同じ行なので、2 行にならない
    assert apply(current, "interface loopback1\n  ip router ospf 1 area 0") == current
    assert apply("interface loopback1", "interface loopback1\n  ip router ospf 1 area 10") == (
        "interface loopback1\n  ip router ospf 1 area 0.0.0.10"
    )


def test_dotted_ospf_area_is_kept_as_is():
    changes = "interface loopback1\n  ip router ospf 1 area 0.0.0.1\n  ip router ospf 2 area 5 secondaries none"

    assert apply("interface loopback1", changes) == (
        "interface loopback1\n  ip router ospf 1 area 0.0.0.1\n  ip router ospf 2 area 0.0.0.5 secondaries none"
    )

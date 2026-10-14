from config_review.vlan import ALL_VLANS, calc_allowed_vlans, format_vlan_list, parse_vlan_list


def test_parse_single_and_range():
    assert parse_vlan_list("10,20-22") == {10, 20, 21, 22}


def test_format_joins_consecutive_numbers_into_range():
    assert format_vlan_list({22, 10, 21, 20}) == "10,20-22"


def test_format_and_parse_round_trip():
    text = "1,3-5,100,4000-4094"

    assert format_vlan_list(parse_vlan_list(text)) == text


def test_calc_add():
    assert calc_allowed_vlans({10, 20}, "add 30") == {10, 20, 30}


def test_calc_remove():
    assert calc_allowed_vlans({10, 20, 30}, "remove 20-30") == {10}


def test_calc_except():
    assert calc_allowed_vlans({10}, "except 1-4093") == {4094}


def test_calc_all_and_none():
    assert calc_allowed_vlans({10}, "all") == set(ALL_VLANS)
    assert calc_allowed_vlans({10}, "none") == set()


def test_calc_plain_list_overwrites():
    assert calc_allowed_vlans({10, 20}, "30,40") == {30, 40}

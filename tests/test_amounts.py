from modules.amounts import parse_amount_id, parse_primary_amount_id


def test_parse_amount_id_k_suffix():
    assert parse_primary_amount_id("10k") == 10000.0
    assert parse_primary_amount_id("10 k") == 10000.0


def test_parse_amount_id_rb_jt():
    assert parse_primary_amount_id("10 rb") == 10000.0
    assert parse_primary_amount_id("2jt") == 2000000.0


def test_parse_amount_id_slang():
    assert parse_primary_amount_id("goceng") == 5000.0
    assert parse_primary_amount_id("ceban") == 10000.0
    assert parse_primary_amount_id("cepe") == 100000.0
    assert parse_primary_amount_id("gope") == 500.0


def test_parse_amount_id_kembalian_diff():
    assert parse_primary_amount_id("bayar 10k kembalian goceng") == 5000.0


def test_parse_amount_id_transfer_intent_not_corrupted_by_rp_cleanup():
    result = parse_amount_id("transfer 10k")
    assert result is not None
    assert result.intent == "payment"
    assert result.primary == 10000.0

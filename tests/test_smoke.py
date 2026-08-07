from etl.helpers import norm_id

def test_norm_id():
    assert norm_id("condition", "Major Depression") == "condition:major_depression"

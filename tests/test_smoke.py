"""Smoke tests — the loaders import, and their pure helpers behave.

This file previously imported `norm_id` from `etl.helpers`, a function that has
never existed, so the suite failed at collection and `pytest` in the README's
Quick Start was a broken instruction.

Deliberately minimal. Real coverage of the loaders is separate work. What is here
guards behaviours that were actually wrong at some point, so a regression fails
loudly rather than silently.
"""

from etl.graph_utils import cq
from etl.helpers import prop_str
from etl.hpsa_loader import norm_county
from etl.synthea_loader import _float


def test_modules_import():
    """Every loader is importable — collection is the point of a smoke test."""
    import etl.hpsa_loader  # noqa: F401
    import etl.loader  # noqa: F401
    import etl.nppes_loader  # noqa: F401
    import etl.stamp_sources  # noqa: F401
    import etl.synthea_loader  # noqa: F401


def test_norm_county_keeps_independent_cities_distinct():
    """Baltimore City is not Baltimore County.

    Stripping " City" merged six pairs across MD, MO and VA and misattributed 262
    shortage rows. The " County" suffix must still be stripped, because the two
    sources spell it differently.
    """
    assert norm_county("Baltimore City") == "Baltimore City"
    assert norm_county("Baltimore County") == "Baltimore"
    assert norm_county("Worcester County") == "Worcester"
    assert norm_county("St. Mary's County") == "St. Mary's"   # apostrophes survive


def test_cq_cannot_break_out_of_a_cypher_literal():
    """Values are interpolated into Cypher, so a stray quote must not escape."""
    assert cq("Queen Anne's") == '"Queen Anne\'s"'    # apostrophes are safe, kept
    assert '"' not in cq('He said "hi"')[1:-1]        # inner quotes dropped
    assert "\\" not in cq("a\\b")                      # backslashes dropped
    assert cq(None) == '""'


def test_float_coercion_is_total():
    """Source CSVs carry blanks; a bad value must be None, never an exception."""
    assert _float("1.5") == 1.5
    assert _float("") is None
    assert _float(None) is None
    assert _float("not a number") is None


def test_prop_str_renders_a_cypher_property_map():
    assert prop_str({"a": 1, "b": "x"}) == '{a: 1, b: "x"}'

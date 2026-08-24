"""MCP tool configuration -- guards the failures that actually happened.

`mcp_server/server.py` is a thin shim: samyama_mcp generates most tools from the
live schema, and `config.yaml` declares the rest. So the config is what is worth
testing, and it is where every past mistake lived. Nothing here needs a server.
"""

import os
import re

import yaml

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "mcp_server", "config.yaml")


def _custom_tools():
    with open(_CONFIG) as fh:
        return yaml.safe_load(fh)["custom_tools"]


def test_config_declares_the_referral_tools():
    """The graph exists to answer these; a stub config is how it shipped before."""
    names = {t["name"] for t in _custom_tools()}
    assert {"data_sources", "find_referral", "find_referral_excluding",
            "service_coverage_by_state"} <= names
    for t in _custom_tools():
        assert t["cypher_template"].strip(), f"{t['name']} has an empty template"
        assert t.get("description"), f"{t['name']} has no description"


def test_every_placeholder_has_a_parameter():
    """`template.format(**params)` raises KeyError at call time otherwise."""
    for t in _custom_tools():
        placeholders = set(re.findall(r"\{(\w+)\}", t["cypher_template"]))
        declared = {p["name"] for p in t.get("parameters") or []}
        assert placeholders == declared, (
            f"{t['name']}: placeholders {placeholders} != parameters {declared}")


def test_no_template_uses_return_distinct():
    """RETURN DISTINCT is a silent no-op on engine 1.7.0 -- it returns every
    row. WITH DISTINCT is correct. A template using the broken form would
    over-report with no error at all."""
    for t in _custom_tools():
        assert not re.search(r"\bRETURN\s+DISTINCT\b", t["cypher_template"], re.I), \
            f"{t['name']} uses RETURN DISTINCT; use WITH DISTINCT"


def test_no_alias_is_named_call():
    """samyama_mcp's read-only guard uppercases every token and rejects CALL as
    a write keyword, so `AS call` makes a read query fail as a write."""
    for t in _custom_tools():
        assert not re.search(r"\bAS\s+call\b", t["cypher_template"], re.I), \
            f"{t['name']} aliases a column to `call`; the guard reads it as CALL"


def test_templates_only_reference_relationships_this_graph_has():
    """The scaffold this replaced traversed TREATED_BY, TREATS and HAS_SYMPTOM,
    none of which exist here -- so both its tools returned nothing, forever."""
    real = {"OFFERS", "PRACTICES_IN", "HAS_TAXONOMY", "HAS_TYPE", "LOCATED_IN",
            "SPEAKS", "COVERS", "HAS_CONDITION", "LIVES_IN", "IN_COUNTY",
            "HAS_PROVIDERS", "IN_STATE", "IN_CATEGORY"}
    for t in _custom_tools():
        for rel in re.findall(r"\[\s*\w*\s*:\s*(\w+)\s*\]", t["cypher_template"]):
            assert rel in real, f"{t['name']} traverses :{rel}, not in this graph"


def test_templates_pass_the_readonly_guard_with_their_defaults():
    """Formatting with declared defaults must produce a query samyama_mcp will
    actually run -- this is the check that caught `AS call`."""
    from samyama_mcp.escape import escape_string, is_readonly_cypher
    for t in _custom_tools():
        vals = {}
        for p in t.get("parameters") or []:
            d = p.get("default")
            vals[p["name"]] = escape_string(d) if isinstance(d, str) else d
        cypher = t["cypher_template"].format(**vals)
        assert is_readonly_cypher(cypher), f"{t['name']} is rejected as a write"

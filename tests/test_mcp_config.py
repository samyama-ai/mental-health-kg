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


def _documented_edge_types():
    """The edge inventory in DATASET_CARD.md, which is the published one.

    Derived rather than hardcoded so a new edge type cannot be used here while
    the dataset card still omits it -- the list drifting silently is how the
    scaffold came to traverse three relationships that never existed.
    """
    card = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "DATASET_CARD.md")
    with open(card) as fh:
        text = fh.read()
    block = re.search(r"^Edges:(.+?)\.$", text, re.M | re.S)
    assert block, "DATASET_CARD.md no longer carries an `Edges:` inventory"
    names = set(re.findall(r"`([A-Z_]+)`", block.group(1)))
    assert len(names) >= 13, f"only found {len(names)} edge types in the card"
    return names


def test_templates_only_reference_relationships_this_graph_has():
    """The scaffold this replaced traversed TREATED_BY, TREATS and HAS_SYMPTOM,
    none of which exist here -- so both its tools returned nothing, forever."""
    real = _documented_edge_types()
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


def test_prop_str_omits_empty_values():
    """The invariant `coalesce(f.intake, f.phone)` depends on.

    `etl/loader.py` writes `r.get("intake", "")`, and Cypher's coalesce does not
    treat "" as absent -- so if prop_str ever wrote empty strings, every facility
    without an intake line would return a blank number instead of falling back to
    f.phone. It does not: empties are skipped, so the property is absent and reads
    back as NULL. Measured on the loaded graph, 0 of 17,254 facilities return a
    null or empty number.
    """
    from etl.helpers import prop_str
    rendered = prop_str({"name": "X", "intake": "", "phone": "802-555-0100"})
    assert "intake" not in rendered
    assert "phone" in rendered
    assert prop_str({"intake": None, "phone": "p"}).count("intake") == 0


# --- mcp_server/server.py ------------------------------------------------
# The config tests above never import the module, so a typo in build_server or a
# wrong keyword to SamyamaMCPServer would ship silently. These exercise the
# integration surface without needing a graph: the client and the generator are
# both replaced, so what is under test is our wiring, not theirs.

def test_server_module_imports():
    import mcp_server.server as srv
    assert callable(srv.build_server) and callable(srv.main)


class _FakeServer:
    def __init__(self, client, graph=None, server_name=None, config=None):
        self.client, self.graph = client, graph
        self.server_name, self.config = server_name, config
        self.ran = False

    def list_tools(self):
        # deliberately reverse-sorted: an unsorted print is then detectable
        return ["find_referral", "data_sources", "count_facility"]

    def run(self):
        self.ran = True


def _patch(monkeypatch, box):
    """Replace the client and the generator at their source modules.

    build_server imports them inside the function, so patching the attribute on
    the defining module is what takes effect.
    """
    import samyama
    import samyama_mcp.server as mcpsrv

    monkeypatch.setattr(samyama.SamyamaClient, "connect",
                        staticmethod(lambda url: f"client:{url}"))

    def factory(client, **kw):
        box["server"] = _FakeServer(client, **kw)
        return box["server"]

    monkeypatch.setattr(mcpsrv, "SamyamaMCPServer", factory)


def test_build_server_passes_the_right_arguments(monkeypatch):
    """Guards the keyword names SamyamaMCPServer actually takes."""
    import mcp_server.server as srv
    box = {}
    _patch(monkeypatch, box)
    built = srv.build_server("http://example:18080", graph="mental-health", name="MH")
    assert built.client == "client:http://example:18080"
    assert built.graph == "mental-health"
    assert built.server_name == "MH"
    assert built.config is not None, "config.yaml was not loaded"
    assert built.config.custom_tools, "custom tools did not reach the server"


def test_list_tools_prints_names_and_does_not_start_a_transport(monkeypatch, capsys):
    """`sorted(tools)` must work on what list_tools returns, and --list-tools
    must return before run() is called."""
    import mcp_server.server as srv
    box = {}
    _patch(monkeypatch, box)
    srv.main(["--url", "http://example:18080", "--list-tools"])
    out = capsys.readouterr().out
    assert "3 tools" in out
    printed = [ln.strip()[2:] for ln in out.splitlines() if ln.strip().startswith("- ")]
    assert printed == ["count_facility", "data_sources", "find_referral"], printed
    assert box["server"].ran is False


def test_run_is_called_without_list_tools(monkeypatch):
    import mcp_server.server as srv
    box = {}
    _patch(monkeypatch, box)
    srv.main(["--url", "http://example:18080"])
    assert box["server"].ran is True


def test_url_defaults_to_the_environment(monkeypatch):
    """MH_URL is what every other entry point in this repo reads."""
    import importlib

    import mcp_server.server as srv
    monkeypatch.setenv("MH_URL", "http://from-env:9999")
    srv = importlib.reload(srv)
    box = {}
    _patch(monkeypatch, box)
    srv.main(["--list-tools"])
    assert box["server"].client == "client:http://from-env:9999"

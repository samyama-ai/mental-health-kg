"""Shared write helpers for the layered loaders.

`helpers.py` is the domain-agnostic file copied verbatim across every KG repo;
this module is the part specific to loading several sources into one graph, and
it exists because three loaders had grown their own copy of the same function.

Three things live here, each of them a bug we actually hit:

**cq() — quote a value safely.** The loaders interpolate keys straight into
Cypher. Nothing in this dataset currently breaks (county names contain
apostrophes, which are fine inside a double-quoted literal), but a single `"` in
a source file would produce either a parse error or an injected clause.

**link_many_to_one() — attach many nodes to one, set-wise.**
`helpers.batch_create_edges` emits one MATCH pattern per edge, and its cost grows
with the node count of the matched label: it SIGKILLed the server at 3,500
Patient nodes, and silently wrote 236 of 3,536 edges when a batch spanned many
distinct pairs. This is two patterns regardless of batch size.

**verify() — count what was written, not what was intended.** Every loader was
reporting the length of its input list. The HRSA loader reported
`IN_STATE = 3,037` while the graph held 3,023: fourteen counties whose state was
missing produced no edge, and nothing noticed. Counts now come from the graph.

**refuse_rerun() — no in-place replacement.** These loaders use CREATE, so a second
run duplicates a layer, and it looks like a successful load until the counts are
read. Recreating the container and importing a snapshot takes about four seconds,
which is faster and simpler than deleting in place.

(An earlier version of this note claimed DETACH DELETE corrupted the property
index. That does not reproduce and has been retracted — the evidence was
contaminated by the engine ignoring the `graph` parameter, samyama-graph#15.)
"""

from __future__ import annotations

from etl.helpers import GRAPH


def cq(value) -> str:
    """Render a value as a double-quoted Cypher string literal.

    Backslashes and double quotes are dropped rather than escaped: this engine's
    handling of escaped quotes inside literals is not something to rely on, and
    no key in these sources legitimately contains either. Apostrophes are safe
    and are left alone — `Queen Anne's` and `O'Brien` are real county names.
    """
    s = "" if value is None else str(value)
    return '"' + s.replace("\\", "").replace('"', "").replace("\n", " ").replace("\r", "") + '"'


def link_many_to_one(client, src_label, src_prop, src_keys,
                     rel, tgt_label, tgt_prop, tgt_value, graph=GRAPH, chunk=500):
    """Create (src)-[:rel]->(tgt) for many sources and ONE target node."""
    for i in range(0, len(src_keys), chunk):
        keys = ", ".join(cq(k) for k in src_keys[i:i + chunk])
        client.query(
            f"MATCH (s:{src_label}) WHERE s.{src_prop} IN [{keys}] "
            f"WITH s MATCH (t:{tgt_label}) WHERE t.{tgt_prop} = {cq(tgt_value)} "
            f"CREATE (s)-[:{rel}]->(t)", graph)


def count_nodes(client, label, graph=GRAPH) -> int:
    r = client.query(f"MATCH (n:{label}) RETURN count(n)", graph).records
    return r[0][0] if r else 0


def count_edges(client, rel, graph=GRAPH) -> int:
    r = client.query(f"MATCH ()-[r:{rel}]->() RETURN count(r)", graph).records
    return r[0][0] if r else 0


def verify(client, counts: dict, expected: dict, graph=GRAPH) -> list[str]:
    """Replace intended counts with actual ones; return a list of discrepancies.

    `expected` maps an edge type or `label:Name` to the number the loader meant
    to write. Anything that disagrees with the graph is both corrected in
    `counts` and returned, so the caller can print it loudly instead of shipping
    a number that was never true.
    """
    problems = []
    for key, intended in expected.items():
        if key.startswith("label:"):
            actual = count_nodes(client, key.split(":", 1)[1], graph)
        else:
            actual = count_edges(client, key, graph)
        counts[key.replace("label:", "")] = actual
        if actual != intended:
            problems.append(
                f"{key}: intended {intended:,}, graph has {actual:,} "
                f"({actual - intended:+,})")
    return problems


def already_loaded(client, label, graph=GRAPH) -> int:
    """How many nodes of `label` exist. Non-zero means a re-run will duplicate.

    None of these loaders is idempotent -- they CREATE. Re-importing a snapshot
    on top of an existing graph once silently doubled it to 35,356 nodes, which
    looks like a working load until the counts are read. Callers refuse to run
    and point at a fresh container -- see refuse_rerun().
    """
    return count_nodes(client, label, graph)


def refuse_rerun(existing: dict, layer: str) -> None:
    """Stop, and say why in-place replacement is not offered.

    These loaders CREATE rather than MERGE, so a second run duplicates the layer
    and it looks like a successful load until the counts are read.

    No --replace is offered because it is not needed: recreating the container and
    importing a snapshot takes ~4s for 1.67M edges, which is faster than deleting
    in place and leaves no room for a partial wipe.
    """
    raise SystemExit(
        f"Refusing to run: the graph already holds "
        + ", ".join(f"{v:,} :{k}" for k, v in existing.items() if v)
        + f".\n\nThese loaders CREATE, so a second run duplicates the {layer} layer.\n"
          "In-place deletion is NOT offered: DETACH DELETE leaves the property\n"
          "index dirty on this engine, and subsequent IN-list writes then attach\n"
          "edges to unrelated nodes. Verified 2026-08-14.\n\n"
          "Start clean instead:\n"
          "  docker rm -f samyama-mh && docker run -d --name samyama-mh \\\n"
          "    -p 18080:8080 public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0\n"
          "  curl -X POST http://localhost:18080/api/snapshot/import \\\n"
          "    -F \"file=@<a snapshot without this layer>.sgsnap\"")

"""Shared helpers for the Mental Health KG loader.

Cypher escaping, batched node/edge creation, and CSV reading — the standard
mechanics shared across Samyama KG loaders, factored out so `loader.py` stays
readable.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

GRAPH = "mental-health"   # Samyama tenant / graph name
BATCH_SIZE = 300


# ---------------------------------------------------------------------------
# Cypher value escaping + property serialization
# ---------------------------------------------------------------------------
def _escape(value) -> str:
    """Make a value safe inside a double-quoted Cypher string literal.

    Drops backslashes and double quotes (a trailing '\\' or an embedded '"' would
    otherwise break the literal) and collapses newlines to spaces.
    """
    if value is None:
        return ""
    return (
        str(value)
        .replace("\\", "")
        .replace('"', "")
        .replace("\n", " ")
        .replace("\r", "")
    )


def _q(val) -> str:
    return f'"{_escape(val)}"'


def prop_str(props: dict) -> str:
    """Serialize a dict to a Cypher property map: {k: "v", n: 3, b: true}."""
    parts = []
    for key, val in props.items():
        if val is None or val == "":
            continue
        if isinstance(val, bool):
            parts.append(f"{key}: {'true' if val else 'false'}")
        elif isinstance(val, (int, float)):
            if isinstance(val, float) and not math.isfinite(val):
                continue  # NaN/inf are not valid Cypher numeric literals — skip the prop
            parts.append(f"{key}: {val}")
        else:
            parts.append(f"{key}: {_q(val)}")
    return "{" + ", ".join(parts) + "}"


def _match_to_where(var_name: str, match_str: str) -> str:
    """'name: "X"' -> 'var.name = "X"' (index scans need WHERE, not inline props)."""
    return f"{var_name}.{match_str.replace(': ', ' = ', 1)}"


# ---------------------------------------------------------------------------
# Batched writes
# ---------------------------------------------------------------------------
def batch_create_nodes(client, nodes, graph: str = GRAPH, batch_size: int = BATCH_SIZE) -> None:
    """Create nodes in chunked CREATE queries. Each node: (label, props_dict)."""
    for start in range(0, len(nodes), batch_size):
        chunk = nodes[start:start + batch_size]
        if not chunk:
            continue
        parts = [f"(:{label} {prop_str(props)})" for label, props in chunk]
        client.query(f"CREATE {', '.join(parts)}", graph)


def batch_create_edges(client, edges, graph: str = GRAPH, batch_size: int = BATCH_SIZE) -> None:
    """Create edges between EXISTING nodes in chunked MATCH...WHERE...CREATE queries.

    Each edge: (src_label, src_match, rel_type, tgt_label, tgt_match, props_or_None)
    where *_match is a single-property match string like 'id: "2016-1-1-17-en.md"'.
    MATCH patterns are deduplicated within a chunk so each node is matched once.
    """
    for start in range(0, len(edges), batch_size):
        chunk = edges[start:start + batch_size]
        if not chunk:
            continue
        var_map: dict = {}
        match_parts, where_parts, create_parts = [], [], []
        for src_label, src_match, rel, tgt_label, tgt_match, props in chunk:
            src_key = (src_label, src_match)
            tgt_key = (tgt_label, tgt_match)
            if src_key not in var_map:
                v = f"n{len(var_map)}"
                var_map[src_key] = v
                match_parts.append(f"({v}:{src_label})")
                where_parts.append(_match_to_where(v, src_match))
            if tgt_key not in var_map:
                v = f"n{len(var_map)}"
                var_map[tgt_key] = v
                match_parts.append(f"({v}:{tgt_label})")
                where_parts.append(_match_to_where(v, tgt_match))
            prop_part = f" {prop_str(props)}" if props else ""
            create_parts.append(
                f"({var_map[src_key]})-[:{rel}{prop_part}]->({var_map[tgt_key]})"
            )
        q = (
            f"MATCH {', '.join(match_parts)} "
            f"WHERE {' AND '.join(where_parts)} "
            f"CREATE {', '.join(create_parts)}"
        )
        client.query(q, graph)


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------
def read_csv(path) -> list[dict]:
    """Read a CSV into a list of dict rows (empty list if the file is missing)."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

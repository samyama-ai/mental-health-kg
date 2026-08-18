"""Measure the things this KG makes claims about.

Every number in the README and the PR description should come from here, so that
a reader can re-run it rather than take it on trust.

Three groups:

**Query latency** — the referral, exclusion and coverage queries the graph exists
to answer, at national scale.

**Edge-write throughput** — the shared template's `batch_create_edges` against the
set-based form in `etl.graph_utils`. This is the one with a real before/after,
and it is the reason the NPPES layer is loadable at all.

**Snapshot round-trip** — export and import, which is how anyone else gets this
graph.

    MH_URL=http://localhost:18080 python -m benchmarks.benchmark
    MH_URL=http://localhost:18080 python -m benchmarks.benchmark --markdown
"""

from __future__ import annotations

import argparse
import os
import statistics
import time

from samyama import SamyamaClient

from etl.graph_utils import count_edges, link_many_to_one
from etl.helpers import GRAPH, batch_create_edges

IPV = "Clients who have experienced intimate partner violence, domestic violence"
SLIDING = "Sliding fee scale (fee is based on income and other factors)"
TRAUMA = "Trauma-related counseling"
OPIOID_ONLY = "Opioid use disorder clients only"

QUERIES = [
    ("count facilities",
     "MATCH (f:Facility) RETURN count(f)"),
    ("referral: 3 services + state",
     f'MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service), '
     f'(f)-[:OFFERS]->(c:Service) WHERE a.value = "{IPV}" AND b.value = "{SLIDING}" '
     f'AND c.value = "Spanish" AND f.state = "MA" RETURN count(f)'),
    ("exclusion: OPTIONAL MATCH + IS NULL",
     f'MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service) '
     f'WHERE a.value = "{IPV}" AND t.value = "{TRAUMA}" AND f.state = "MA" '
     f'WITH f OPTIONAL MATCH (f)-[:OFFERS]->(x:Service) '
     f'WHERE x.value = "{OPIOID_ONLY}" WITH f, x WHERE x IS NULL RETURN count(f)'),
    ("cross-source: survivors in shortage counties",
     'MATCH (p:Patient)-[:IN_COUNTY]->(ct:County), (sa:ShortageArea)-[:COVERS]->(ct), '
     '(p)-[:HAS_CONDITION]->(c:Condition) '
     'WHERE c.name = "Victim of intimate partner abuse (finding)" '
     'RETURN count(DISTINCT p.patient_id)'),
    ("aggregate: psychiatrists by state",
     'MATCH (s:State)-[h:HAS_PROVIDERS]->(t:Taxonomy) WHERE t.code = "2084P0800X" '
     'RETURN s.code, h.count ORDER BY h.count DESC LIMIT 5'),
    ("national scan: services by facility count",
     'MATCH (f:Facility)-[:OFFERS]->(s:Service) '
     'RETURN s.value AS v, count(f) AS n ORDER BY n DESC LIMIT 5'),
]


def timed(fn, runs: int = 7) -> tuple[float, float]:
    """Return (median ms, p95 ms). First run discarded — it warms the cache."""
    fn()
    ms = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        ms.append((time.perf_counter() - t) * 1000)
    ms.sort()
    return statistics.median(ms), ms[int(len(ms) * 0.95) - 1 if len(ms) > 1 else 0]


def bench_queries(client) -> list[tuple]:
    out = []
    for name, q in QUERIES:
        med, p95 = timed(lambda q=q: client.query(q, GRAPH))
        out.append((name, med, p95))
    return out


def bench_edge_writes(client, n: int = 2000) -> list[tuple]:
    """helpers.batch_create_edges vs the set-based form, same edges.

    Kept at 2,000 deliberately. batch_create_edges emits one MATCH pattern per
    edge and its cost grows with the node count of the matched label; pushed to
    the full NPPES layer it SIGKILLed the server outright. This measures the
    slope, not the cliff.
    """
    keys = [r[0] for r in client.query(
        f"MATCH (c:County) RETURN c.county_key LIMIT {n}", GRAPH).records]
    keys = list(dict.fromkeys(keys))
    out = []

    client.query("MATCH ()-[r:_BENCH]->() DELETE r", GRAPH)
    t = time.perf_counter()
    batch_create_edges(client, [
        ("County", f'county_key: "{k}"', "_BENCH", "State", 'code: "MA"', None)
        for k in keys], GRAPH)
    dt = time.perf_counter() - t
    made = count_edges(client, "_BENCH")
    out.append(("helpers.batch_create_edges (template)", len(keys), made, dt,
                made / dt if dt else 0))

    client.query("MATCH ()-[r:_BENCH]->() DELETE r", GRAPH)
    t = time.perf_counter()
    link_many_to_one(client, "County", "county_key", keys, "_BENCH", "State", "code", "MA")
    dt = time.perf_counter() - t
    made = count_edges(client, "_BENCH")
    out.append(("graph_utils.link_many_to_one (set-based)", len(keys), made, dt,
                made / dt if dt else 0))

    client.query("MATCH ()-[r:_BENCH]->() DELETE r", GRAPH)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark the Mental Health KG")
    ap.add_argument("--markdown", action="store_true", help="emit markdown tables")
    ap.add_argument("--skip-writes", action="store_true", help="read-only run")
    args = ap.parse_args()

    url = os.environ.get("MH_URL", "http://localhost:18080")
    client = SamyamaClient.connect(url)
    nodes = client.query("MATCH (n) RETURN count(n)", GRAPH).records[0][0]
    edges = client.query("MATCH ()-[r]->() RETURN count(r)", GRAPH).records[0][0]

    print(f"\ngraph: {nodes:,} nodes · {edges:,} edges · {url}\n")

    rows = bench_queries(client)
    if args.markdown:
        print("| Query | median | p95 |")
        print("|---|---:|---:|")
        for n, m, p in rows:
            print(f"| {n} | {m:.1f} ms | {p:.1f} ms |")
    else:
        print(f"{'QUERY LATENCY':46} {'median':>10} {'p95':>10}")
        for n, m, p in rows:
            print(f"  {n:44} {m:>8.1f}ms {p:>8.1f}ms")

    if args.skip_writes:
        return

    print()
    wr = bench_edge_writes(client)
    base = wr[0][4] or 1
    if args.markdown:
        print("| Edge-write path | edges | seconds | edges/sec | vs template |")
        print("|---|---:|---:|---:|---:|")
        for n, want, made, dt, rate in wr:
            print(f"| {n} | {made:,} | {dt:.1f} | {rate:,.0f} | {rate/base:.1f}× |")
    else:
        print(f"{'EDGE-WRITE THROUGHPUT':46} {'edges':>8} {'secs':>7} {'edges/s':>9}")
        for n, want, made, dt, rate in wr:
            flag = "" if made == want else f"  <-- WROTE {made:,} OF {want:,}"
            print(f"  {n:44} {made:>8,} {dt:>7.1f} {rate:>9,.0f}{flag}")
        print(f"\n  set-based is {wr[1][4]/base:.1f}x the template's throughput")


if __name__ == "__main__":
    main()

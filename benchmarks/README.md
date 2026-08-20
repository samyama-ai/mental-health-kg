# Benchmarks

Every number quoted in the README or a PR description comes from here. Re-run it
rather than take it on trust:

```bash
MH_URL=http://localhost:18080 python -m benchmarks.benchmark
MH_URL=http://localhost:18080 python -m benchmarks.benchmark --markdown
```

Measured 2026-08-19 against **113,710 nodes / 1,665,153 edges** — the full
four-source graph — on `samyama-graph:1.1.0` (binary reports 1.7.0), single
container, no tuning.

## Query latency

20 runs each, first discarded as cache warm-up. p95 is nearest-rank; an earlier
table reported it over 7 runs with an index that actually landed on the 86th
percentile, so those tail figures were optimistic and are superseded here.

| Query | median | p95 |
|---|---:|---:|
| count facilities | **0.3 ms** | 0.5 ms |
| aggregate — psychiatrists by state | **2.2 ms** | 2.4 ms |
| national scan — services by facility count | **9.0 ms** | 10.9 ms |
| **referral — 3 services + state** | **46.6 ms** | 53.8 ms |
| **exclusion — OPTIONAL MATCH + IS NULL** | **47.9 ms** | 56.7 ms |
| cross-source — survivors in shortage counties | **68.0 ms** | 85.0 ms |

**Why this matters.** The referral query is the one the graph exists to answer,
and it joins three service constraints plus a state filter across 1.42M `OFFERS`
edges. At a **47 ms** median it is 2–3% of a 1.5–2 s conversational turn budget,
so a runtime lookup is affordable. The cross-source query — synthetic population
joined to counties joined to federal shortage designations — is the most expensive
at 68 ms median / 85 ms p95, and still well inside budget.

## Edge-write throughput — the before/after

`helpers.batch_create_edges` is the shared template helper every KG repo copies.
It emits **one MATCH pattern per edge**, so a 300-edge batch is a 300-pattern
query and its cost grows with the node count of the matched label.
`graph_utils.link_many_to_one` uses **two patterns regardless of batch size**.

Same 2,000 edges, same graph:

| Path | edges | seconds | edges/sec | |
|---|---:|---:|---:|---|
| `helpers.batch_create_edges` (template) | 2,000 | 5.0 | 398 | baseline |
| `graph_utils.link_many_to_one` (set-based) | 2,000 | 0.6 | **3,220** | **8.1×** |

**2,000 is deliberately modest — it measures the slope, not the cliff.** At real
scale the template does not merely slow down, it fails:

| Observed | Template behaviour |
|---|---|
| 3,500 `Patient` nodes | server killed, **exit 137** |
| 2.6M `Provider` nodes | ~16 edges/sec → **90+ hours** for the NPPES layer |

The set-based form is why the NPPES layer loads in 21 minutes instead of not at
all. Reported upstream as
[samyama-graph#19](https://git.samyama.ai/Samyama.ai/samyama-graph/issues/19).

*Correction, 2026-08-18: this table previously also claimed the template silently
wrote 236 of 3,536 edges. That does not reproduce — a clean test writes 50, 150 and
300 patterns per query correctly, just slowly. The original observation could not
be trusted because the engine ignores the `graph` parameter
([#15](https://git.samyama.ai/Samyama.ai/samyama-graph/issues/15)), so supposedly
separate test graphs were one shared graph. `graph_utils.verify()` remains worth
having — it caught a real, explainable shortfall in `HAS_PROVIDERS` — but it was
not catching silent partial writes, because there were none.*

## Snapshot round-trip

| Operation | Time | Result |
|---|---:|---|
| Export 1.67M edges | 15.7 s | 15 MB `.sgsnap` |
| **Import into a fresh container** | **4.0 s** | 113,710 nodes / 1,665,153 edges restored |

**Import is the number that matters.** It is how anyone else obtains this graph,
and at 4 seconds for 1.67M edges it is also the reason no loader offers an
in-place `--replace`: recreating a container and re-importing is simply faster
than deleting a layer in place, and leaves no room for a half-finished wipe.

## Load times, for reference

Measured during the builds rather than by this script:

| Layer | Input | Time |
|---|---|---:|
| FindTreatment.gov — 17,254 facilities, 1.47M edges | 11 CSVs | ~14 min |
| Synthea — 3,500 patients | 2 of 18 CSVs | 3.5 s |
| HRSA — 6,420 designations, 3,043 counties | 13,836 rows | 25 s |
| NPPES — 82,978 providers + national aggregate | 11.6 GB streamed | 19 min |

NPPES dominates because 166k per-provider edges are written after an 11.6 GB
single-pass scan; the national aggregate for all 50 states costs about a minute of
that.

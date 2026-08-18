"""Load behavioural-health providers from the NPPES NPI registry.

The facility layer says an organisation exists and what services it lists. It
says nothing about the clinicians inside it: how many, of what discipline, or
whether they are licensed in the state they practise in. NPPES is the federal
register of every provider with a National Provider Identifier, and it carries
exactly that -- name, practice address, taxonomy, licence number.

    # ~1.07 GB zip, ~9 GB of CSV inside; the monthly full-replacement file
    curl -L -A '<a browser UA>' \
      https://download.cms.gov/nppes/NPPES_Data_Dissemination_August_2026_V2.zip \
      -o data/nppes.zip
    python -m etl.nppes_loader --zip data/nppes.zip --taxonomy data/bh_taxonomy.json \
      --url http://localhost:18080

The zip is streamed, never unpacked -- the 11.6 GB CSV is read a row at a time.
The rows that survive the taxonomy filter ARE accumulated in memory before the
write, which is why `--states` matters: 83k providers is a few hundred MB, and
the full 2.6M is not something to hold.

Taxonomy selection is deliberately NOT "Grouping == Behavioral Health & Social
Service Providers". Psychiatrists sit under Allopathic & Osteopathic Physicians,
so that grouping alone misses them. See scripts that build bh_taxonomy.json:
psychiatry, psychiatric nursing, mental-health clinics and substance-use
facilities are included; plain neurology (epilepsy, sleep medicine, vascular)
shares the "Psychiatry & Neurology" classification and is excluded, as are
genetic counsellors and assistive-technology rehabilitation counsellors.

NPPES is a US federal government work in the public domain, like the rest of
this graph, so these nodes carry `source: "NPPES"` and no synthetic flag.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import zipfile
from collections import Counter

from samyama import SamyamaClient

from etl.graph_utils import already_loaded, cq, link_many_to_one, refuse_rerun, verify
from etl.helpers import GRAPH, batch_create_nodes

# NPPES ships up to 15 taxonomy slots per provider.
TAX_SLOTS = range(1, 16)


def _esc(v: str) -> str:
    return (v or "").replace("\\", " ").replace('"', "'").strip()


def stream_providers(zip_path: str, wanted: dict, limit: int | None = None):
    """Yield (record, primary_taxonomy) for behavioural-health providers."""
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist()
                    if n.lower().startswith("npidata_pfile")
                    and n.lower().endswith(".csv")
                    and "fileheader" not in n.lower())
        print(f"  reading {name}", flush=True)
        with zf.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1"))
            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break
                if row.get("NPI Deactivation Date", "").strip():
                    continue          # deactivated NPIs are not practising
                tax = None
                for s in TAX_SLOTS:
                    code = row.get(f"Healthcare Provider Taxonomy Code_{s}", "").strip()
                    if code in wanted:
                        # Prefer the slot flagged primary, else the first match.
                        if row.get(f"Healthcare Provider Primary Taxonomy Switch_{s}") == "Y":
                            tax = code
                            break
                        tax = tax or code
                if tax:
                    yield row, tax


def load_nppes(client: SamyamaClient, zip_path: str, taxonomy_path: str,
               limit: int | None = None, states: set[str] | None = None) -> dict:
    """Load at two grains in a single pass over the 11.6 GB file.

    NATIONALLY, an aggregate: one (State)-[:HAS_PROVIDERS {count}]->(Taxonomy)
    edge per pair, ~4,000 edges. Enough to compare real clinical capacity
    against HRSA shortage scores in every state.

    FOR `states`, the individuals themselves, with name, practice address and
    licence number.

    The full register at individual grain is 2,610,822 providers and ~5.2M
    edges -- 85x the rest of this graph, and the edge writes ran at ~16/sec
    because `WHERE npi IN [...]` scans every Provider node, so it needed 90+
    hours. The scan cost falls with the node count, which is what makes the
    two-grain split work rather than being a compromise.
    """
    with open(taxonomy_path) as fh:
        wanted = json.load(fh)
    counts: dict[str, int] = {}
    t0 = time.time()

    existing = {lbl: already_loaded(client, lbl) for lbl in ("Provider", "Taxonomy")}
    if any(existing.values()):
        refuse_rerun(existing, "NPPES")

    for label, prop in [("Provider", "npi"), ("Taxonomy", "code")]:
        try:
            client.query(f"CREATE INDEX ON :{label}({prop})", GRAPH)
        except Exception as e:  # noqa: BLE001
            print(f"  [index] skipped :{label}({prop}) - {e}", flush=True)

    print("Phase 1/3: taxonomy nodes ...", flush=True)
    batch_create_nodes(client, [
        ("Taxonomy", {"code": t["code"], "grouping": t["grouping"],
                      "classification": t["classification"],
                      "specialization": t["specialization"], "source": "NUCC"})
        for t in wanted.values()], GRAPH)
    counts["taxonomies"] = len(wanted)

    print("Phase 2/3: streaming providers ...", flush=True)
    nodes, by_state, by_tax = [], {}, {}
    agg: Counter = Counter()          # (state, taxonomy) -> count, ALL states
    seen = Counter()
    for row, tax in stream_providers(zip_path, wanted, limit):
        st = _esc(row.get("Provider Business Practice Location Address State Name"))
        if len(st) == 2:
            agg[(st, tax)] += 1
        if states and st not in states:
            continue                  # aggregate already counted; skip the node
        npi = row["NPI"].strip()
        entity = row.get("Entity Type Code", "").strip()
        if entity == "2":
            name = _esc(row.get("Provider Organization Name (Legal Business Name)"))
        else:
            name = " ".join(x for x in (
                _esc(row.get("Provider First Name")),
                _esc(row.get("Provider Last Name (Legal Name)"))) if x)
        nodes.append(("Provider", {
            "npi": npi,
            "name": name,
            "is_organization": entity == "2",
            "city": _esc(row.get("Provider Business Practice Location Address City Name")),
            "state": st,
            # NPPES zips are ZIP+4 unspaced; the supply layer keys on 5-digit.
            "zip": _esc(row.get("Provider Business Practice Location Address Postal Code"))[:5],
            "phone": _esc(row.get("Provider Business Practice Location Address Telephone Number")),
            "taxonomy": tax,
            "licence": _esc(row.get("Provider License Number_1")),
            "licence_state": _esc(row.get("Provider License Number State Code_1")),
            "source": "NPPES",
        }))
        by_state.setdefault(st, []).append(npi)
        by_tax.setdefault(tax, []).append(npi)
        seen[st] += 1
        if len(nodes) % 50000 == 0:
            print(f"    {len(nodes):,} kept ...", flush=True)
    batch_create_nodes(client, nodes, GRAPH)
    counts["providers"] = len(nodes)

    print("Phase 3/3: edges ...", flush=True)
    n = 0
    for st, npis in by_state.items():
        if st and len(st) == 2:
            link_many_to_one(client, "Provider", "npi", npis,
                             "PRACTICES_IN", "State", "code", st)
            n += len(npis)
    counts["PRACTICES_IN"] = n
    n = 0
    for tax, npis in by_tax.items():
        link_many_to_one(client, "Provider", "npi", npis,
                         "HAS_TAXONOMY", "Taxonomy", "code", tax)
        n += len(npis)
    counts["HAS_TAXONOMY"] = n

    # National aggregate. State and Taxonomy are tiny labels (52 and 76), so
    # helpers.batch_create_edges is safe here -- its cost problem is driven by
    # the cardinality of the matched labels, not by the number of edges.
    print("Phase 3/3b: national aggregate ...", flush=True)
    # One query per (state, taxonomy) pair. helpers.batch_create_edges was used
    # here first and silently wrote 236 of 3,536 edges: a batch spanning many
    # distinct State/Taxonomy pairs produces 128+ MATCH patterns in one query
    # and most of them are dropped without an error.
    for (st, tax), c in sorted(agg.items()):
        client.query(
            f"MATCH (s:State) WHERE s.code = {cq(st)} WITH s "
            f"MATCH (t:Taxonomy) WHERE t.code = {cq(tax)} "
            f"CREATE (s)-[:HAS_PROVIDERS {{count: {int(c)}}}]->(t)", GRAPH)
    counts["HAS_PROVIDERS"] = len(agg)
    counts["providers_counted_nationally"] = sum(agg.values())

    problems = verify(client, counts, {
        "label:Provider": counts["providers"],
        "label:Taxonomy": counts["taxonomies"],
        "PRACTICES_IN": counts["PRACTICES_IN"],
        "HAS_TAXONOMY": counts["HAS_TAXONOMY"],
        "HAS_PROVIDERS": counts["HAS_PROVIDERS"],
    })
    counts["seconds"] = round(time.time() - t0, 1)
    print("\nNPPES provider layer loaded", flush=True)
    for pr in problems:
        print(f"  [MISMATCH] {pr}", flush=True)
    for k, v in counts.items():
        print(f"  {k:16} {v:>10,}" if isinstance(v, int) else f"  {k:16} {v:>10}")
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Load behavioural-health NPPES providers")
    ap.add_argument("--zip", required=True, help="NPPES data dissemination zip")
    ap.add_argument("--taxonomy", required=True, help="bh_taxonomy.json")
    ap.add_argument("--limit", type=int, default=None, help="Cap rows read (testing)")
    ap.add_argument("--states", default=None,
                    help="Comma-separated state codes for individual providers. "
                         "Omitting this loads ALL 2.6M nationally, which takes "
                         "90+ hours; --all-states is required to mean it.")
    ap.add_argument("--all-states", action="store_true",
                    help="Really load every individual provider nationally")
    ap.add_argument("--url", default=None, help="Server URL (omit for embedded)")
    args = ap.parse_args(argv)
    if not args.states and not args.all_states:
        raise SystemExit(
            "Refusing to run without --states.\n"
            "The national aggregate is written either way. Loading INDIVIDUAL\n"
            "providers for every state means 2,610,822 nodes and ~5.2M edges,\n"
            "which measured 90+ hours because `WHERE npi IN [...]` scans every\n"
            "Provider node. Use e.g. --states MA,VT, or --all-states to mean it.")
    client = SamyamaClient.connect(args.url) if args.url else SamyamaClient.embedded()
    load_nppes(client, args.zip, args.taxonomy, args.limit,
               set(args.states.split(",")) if args.states else None)


if __name__ == "__main__":
    main()

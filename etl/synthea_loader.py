"""Load a Synthea synthetic patient cohort into the graph as a DEMAND layer.

The FindTreatment.gov layer is supply: real, public-domain facilities and the
services they offer. This adds demand: simulated people with a location, an
income and a set of conditions. Joined on State, the two answer a question
neither can alone -- for each person needing help, does a facility exist that
matches their language, their ability to pay and their need?

PROVENANCE IS NOT OPTIONAL. Every node this loader creates carries
`synthetic: true` and `source: "Synthea"`. Nothing here is a real person, and
no query result should ever mix the two populations without saying which is
which. Synthea also invents its own hospitals and clinicians -- those are NOT
loaded, because they would be indistinguishable from the real facilities that
are the whole point of this graph.

Only two of Synthea's eighteen CSVs are used. observations.csv and
claims_transactions.csv are ~85% of the bytes and carry blood-pressure readings
and billing lines, which say nothing about whether care is reachable.

    python -m etl.synthea_loader --data-dir out_ma/csv --url http://localhost:18080
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

from samyama import SamyamaClient

from etl.helpers import GRAPH, batch_create_nodes, read_csv

# Conditions worth modelling for a referral graph. Synthea emits ~200 distinct
# descriptions; the rest (sinusitis, fractures) add edges and answer nothing.
BEHAVIOURAL = {
    "Victim of intimate partner abuse (finding)",
    "Reports of violence in the environment (finding)",
    "Clients who have experienced sexual abuse",
    "Posttraumatic stress disorder (disorder)",
    "Major depressive disorder (disorder)",
    "Severe anxiety (panic) (finding)",
    "Unhealthy alcohol drinking behavior (finding)",
    "Alcoholism (disorder)",
    "Misuses drugs (finding)",
    "Dependent drug abuse (disorder)",
    "Opioid abuse",
    "Homeless (finding)",
}

# US state name -> USPS code, so patients join the State nodes the supply
# layer already created. Synthea writes the full name; FindTreatment uses codes.
STATES = {
    "Massachusetts": "MA", "Vermont": "VT", "New Hampshire": "NH", "Maine": "ME",
    "Connecticut": "CT", "Rhode Island": "RI", "New York": "NY", "California": "CA",
    "Texas": "TX", "Florida": "FL", "Illinois": "IL", "Ohio": "OH",
    "Pennsylvania": "PA", "Michigan": "MI", "Georgia": "GA", "North Carolina": "NC",
    "New Jersey": "NJ", "Virginia": "VA", "Washington": "WA", "Arizona": "AZ",
    "Maryland": "MD", "Kentucky": "KY", "North Dakota": "ND", "Wisconsin": "WI",
    "Minnesota": "MN", "Colorado": "CO", "Alabama": "AL", "Louisiana": "LA",
    "Oregon": "OR", "Oklahoma": "OK", "Connecticut ": "CT",
}


def _age(birthdate: str) -> int | None:
    try:
        y, m, d = (int(x) for x in birthdate.split("-"))
    except (ValueError, AttributeError):
        return None
    today = date.today()
    return today.year - y - ((today.month, today.day) < (m, d))


def _float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _link(client, patient_ids, rel, tgt_label, tgt_prop, tgt_value, chunk=500):
    """Attach many patients to ONE target node, set-wise.

    helpers.batch_create_edges emits one MATCH pattern per edge -- 300+ patterns
    in a single query. That does not scale with the number of nodes already
    carrying the matched label: it survived 2,000 Patient nodes and killed the
    server (SIGKILL, exit 137) at 3,500. Here the pattern count is fixed at two
    regardless of batch size, and the WHERE ... IN list does the selection.
    """
    for i in range(0, len(patient_ids), chunk):
        ids = ", ".join(f'"{p}"' for p in patient_ids[i:i + chunk])
        client.query(
            f"MATCH (p:Patient) WHERE p.patient_id IN [{ids}] "
            f"WITH p MATCH (t:{tgt_label}) WHERE t.{tgt_prop} = \"{tgt_value}\" "
            f"CREATE (p)-[:{rel}]->(t)", GRAPH)


def load_synthea(client: SamyamaClient, data_dir: str, cohort: str) -> dict:
    """Load patients + behavioural conditions. Returns a dict of counts."""
    d = Path(data_dir)
    counts: dict[str, int] = {}
    t0 = time.time()

    for label, prop in [("Patient", "patient_id"), ("Condition", "code")]:
        try:
            client.query(f"CREATE INDEX ON :{label}({prop})", GRAPH)
        except Exception as e:  # noqa: BLE001 - index creation is best-effort
            print(f"  [index] skipped :{label}({prop}) - {e}", flush=True)

    print("Phase 1/3: patients ...", flush=True)
    patients = read_csv(d / "patients.csv")
    nodes = []
    for r in patients:
        nodes.append(("Patient", {
            # Namespaced by cohort ON PURPOSE. Synthea's -s seed determines the
            # patient UUIDs, so two cohorts generated with the same seed reuse
            # them: loading MA and VT both at seed 20260812 gave 3,500 nodes
            # with only 2,260 distinct ids, and every id-equality match returned
            # two people. Use a distinct seed per cohort AND keep this prefix.
            "patient_id": f"{cohort}::{r['Id']}",
            "synthea_id": r["Id"],
            "cohort": cohort,
            "synthetic": True,
            "source": "Synthea",
            "gender": r.get("GENDER", ""),
            "ethnicity": r.get("ETHNICITY", ""),
            "race": r.get("RACE", ""),
            "age": _age(r.get("BIRTHDATE", "")),
            "city": r.get("CITY", ""),
            "state": STATES.get(r.get("STATE", ""), r.get("STATE", "")),
            "zip": r.get("ZIP", ""),
            "county": r.get("COUNTY", ""),
            "latitude": _float(r.get("LAT")),
            "longitude": _float(r.get("LON")),
            "income": _float(r.get("INCOME")),
        }))
    batch_create_nodes(client, nodes, GRAPH)
    counts["patients"] = len(nodes)
    kept = {r["Id"] for r in patients}
    ns = lambda i: f"{cohort}::{i}"

    print("Phase 2/3: conditions ...", flush=True)
    rows = [r for r in read_csv(d / "conditions.csv")
            if r["PATIENT"] in kept and r["DESCRIPTION"] in BEHAVIOURAL]
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r["CODE"], r["DESCRIPTION"])
    # Condition codes are shared SNOMED vocabulary, not per-cohort: a second
    # cohort must reuse the nodes the first created, or every code exists twice.
    existing = {r[0] for r in client.query(
        "MATCH (c:Condition) RETURN c.code", GRAPH).records}
    fresh = {c: n for c, n in seen.items() if c not in existing}
    batch_create_nodes(client, [
        ("Condition", {"code": code, "name": name,
                       "synthetic": True, "source": "Synthea"})
        for code, name in fresh.items()], GRAPH)
    counts["conditions_new"] = len(fresh)
    counts["conditions_reused"] = len(seen) - len(fresh)

    print("Phase 3/3: edges ...", flush=True)
    # One HAS_CONDITION per (patient, code); Synthea repeats a finding across
    # encounters, and 40 identical edges say nothing 1 edge does not.
    pairs = {(r["PATIENT"], r["CODE"]) for r in rows}
    by_code: dict[str, list[str]] = {}
    for pid, code in pairs:
        by_code.setdefault(code, []).append(ns(pid))
    for code, pids in by_code.items():
        _link(client, pids, "HAS_CONDITION", "Condition", "code", code)
    counts["HAS_CONDITION"] = len(pairs)

    # LIVES_IN reuses the State nodes the supply layer created -- this edge is
    # the join between demand and supply.
    by_state: dict[str, list[str]] = {}
    for r in patients:
        st = STATES.get(r.get("STATE", ""))
        if st:
            by_state.setdefault(st, []).append(ns(r["Id"]))
    for st, pids in by_state.items():
        _link(client, pids, "LIVES_IN", "State", "code", st)
    counts["LIVES_IN"] = sum(len(v) for v in by_state.values())

    counts["seconds"] = round(time.time() - t0, 1)
    print("\nSynthea demand layer loaded", flush=True)
    for k, v in counts.items():
        print(f"  {k:16} {v:>10,}" if isinstance(v, int) else f"  {k:16} {v:>10}")
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Load a Synthea cohort into the graph as a demand layer")
    ap.add_argument("--data-dir", required=True, help="Synthea csv/ output directory")
    ap.add_argument("--cohort", default=None,
                    help="Cohort tag, e.g. 'MA-2000-seed20260812' (default: dir name)")
    ap.add_argument("--url", default=None, help="Server URL (omit for embedded)")
    args = ap.parse_args(argv)
    cohort = args.cohort or Path(args.data_dir).resolve().parent.name
    client = SamyamaClient.connect(args.url) if args.url else SamyamaClient.embedded()
    load_synthea(client, args.data_dir, cohort)


if __name__ == "__main__":
    main()

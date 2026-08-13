"""Load HRSA Mental Health Professional Shortage Areas as a corroboration layer.

FindTreatment.gov says where facilities are. Synthea says where people are.
Neither says whether the federal government already considers an area
under-served -- HRSA does, and it publishes a score.

A Mental Health HPSA is a designated geographic area, population group or
facility with too few psychiatric providers for its population. The score runs
0-25; higher is worse, and it is what drives National Health Service Corps
placement. Adding it means a coverage gap we compute can be checked against a
designation that already exists, rather than resting on our arithmetic alone.

    curl -sL https://data.hrsa.gov/DataDownload/DD_Files/HPSA_DASHBOARD.csv \
        -o data/hpsa.csv
    python -m etl.hpsa_loader --csv data/hpsa.csv --url http://localhost:18080

Only Discipline == "Mental Health" and HPSA Status == "Designated" are loaded.
The file also carries Primary Care and Dental Health, and 8,184 mental-health
rows marked "Proposed For Withdrawal" which are not current shortages.

This is REAL federal data, so unlike the Synthea layer these nodes carry no
`synthetic` flag -- they carry `source: "HRSA"`.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from samyama import SamyamaClient

from etl.helpers import GRAPH, batch_create_nodes, read_csv

# HRSA writes full state names; the supply layer keys State on USPS code.
STATE_CODE = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "Puerto Rico": "PR", "U.S. Virgin Islands": "VI", "Guam": "GU",
    "American Samoa": "AS", "Northern Mariana Islands": "MP",
}


# Synthea writes "Worcester County", HRSA writes "Worcester". Without this the
# two sources create separate County nodes and the patient -> shortage-area
# traversal silently returns nothing -- it looks like an engine bug and is not.
_SUFFIXES = (" County", " Parish", " Borough", " Census Area", " Municipality",
             " City and Borough", " City", " Municipio")


def norm_county(name: str) -> str:
    n = (name or "").strip()
    changed = True
    while changed:                     # "St. Louis City County" -> "St. Louis"
        changed = False
        for suf in _SUFFIXES:
            if n.endswith(suf) and len(n) > len(suf):
                n, changed = n[: -len(suf)].strip(), True
    return n


def _num(val, cast=float):
    try:
        return cast(val)
    except (TypeError, ValueError):
        return None


def link_many_to_one(client, src_label, src_prop, src_keys,
                     rel, tgt_label, tgt_prop, tgt_value, chunk=500):
    """Link many source nodes to ONE target, two MATCH patterns per query.

    Deliberately not helpers.batch_create_edges: that emits one pattern per
    edge, and its cost grows with how many nodes already carry the matched
    label -- it SIGKILLed the server at 3,500 Patient nodes.
    """
    for i in range(0, len(src_keys), chunk):
        keys = ", ".join(f'"{k}"' for k in src_keys[i:i + chunk])
        client.query(
            f"MATCH (s:{src_label}) WHERE s.{src_prop} IN [{keys}] "
            f"WITH s MATCH (t:{tgt_label}) WHERE t.{tgt_prop} = \"{tgt_value}\" "
            f"CREATE (s)-[:{rel}]->(t)", GRAPH)


def load_hpsa(client: SamyamaClient, csv_path: str) -> dict:
    counts: dict[str, int] = {}
    t0 = time.time()

    rows = [r for r in read_csv(csv_path)
            if r.get("Discipline") == "Mental Health"
            and r.get("HPSA Status") == "Designated"]
    counts["rows_kept"] = len(rows)

    for label, prop in [("ShortageArea", "hpsa_id"), ("County", "county_key")]:
        try:
            client.query(f"CREATE INDEX ON :{label}({prop})", GRAPH)
        except Exception as e:  # noqa: BLE001
            print(f"  [index] skipped :{label}({prop}) - {e}", flush=True)

    # --- counties -------------------------------------------------------
    # County names repeat across states (nine states have a Washington
    # County), so the key must carry the state.
    print("Phase 1/3: counties ...", flush=True)
    counties: dict[str, tuple[str, str]] = {}
    for r in rows:
        st, cty = STATE_CODE.get(r["State"]), norm_county(r["County"])
        if st and cty:
            counties[f"{st}::{cty}"] = (cty, st)
    # Patients may live in counties with no designation; create those too, so
    # "no shortage designation" is distinguishable from "county not loaded".
    for rec in client.query(
            "MATCH (p:Patient) RETURN p.county, p.state", GRAPH).records:
        cty, st = norm_county(rec[0]), rec[1]
        if cty and st:
            counties.setdefault(f"{st}::{cty}", (cty, st))
    batch_create_nodes(client, [
        ("County", {"county_key": k, "name": n, "state": s, "source": "HRSA"})
        for k, (n, s) in counties.items()], GRAPH)
    counts["counties"] = len(counties)

    by_state: dict[str, list[str]] = {}
    for k, (_, s) in counties.items():
        by_state.setdefault(s, []).append(k)
    for st, keys in by_state.items():
        link_many_to_one(client, "County", "county_key", keys,
                         "IN_STATE", "State", "code", st)
    counts["IN_STATE"] = len(counties)

    # --- shortage areas -------------------------------------------------
    # 13,836 rows collapse to 6,420 designations; one HPSA can span several
    # counties. Score is constant within an id (verified), so first row wins.
    print("Phase 2/3: shortage areas ...", flush=True)
    areas: dict[str, dict] = {}
    for r in rows:
        hid = r["HPSA ID"]
        if hid not in areas:
            areas[hid] = {
                "hpsa_id": hid,
                "name": r.get("HPSA Name", ""),
                "score": _num(r.get("HPSA Score"), int),
                "category": r.get("HPSA Type (Category)", ""),
                "population": _num(r.get("HPSA Designation Population")),
                "rural": r.get("Rural Status", ""),
                "designated_on": r.get("Designation Date", ""),
                "state": STATE_CODE.get(r["State"], r["State"]),
                "source": "HRSA",
            }
    batch_create_nodes(client, [("ShortageArea", a) for a in areas.values()], GRAPH)
    counts["shortage_areas"] = len(areas)

    # --- edges ----------------------------------------------------------
    print("Phase 3/3: edges ...", flush=True)
    covers: dict[str, list[str]] = {}
    for r in rows:
        st, cty = STATE_CODE.get(r["State"]), norm_county(r["County"])
        if st and cty:
            covers.setdefault(f"{st}::{cty}", []).append(r["HPSA ID"])
    n = 0
    for ckey, hids in covers.items():
        link_many_to_one(client, "ShortageArea", "hpsa_id", sorted(set(hids)),
                         "COVERS", "County", "county_key", ckey)
        n += len(set(hids))
    counts["COVERS"] = n

    # Patients into counties -- this is what makes "does this person live in a
    # federally designated shortage area?" a single traversal.
    pats: dict[str, list[str]] = {}
    for rec in client.query(
            "MATCH (p:Patient) RETURN p.patient_id, p.county, p.state", GRAPH).records:
        pid, cty, st = rec[0], norm_county(rec[1]), rec[2]
        if cty and st:
            pats.setdefault(f"{st}::{cty}", []).append(pid)
    n = 0
    for ckey, pids in pats.items():
        link_many_to_one(client, "Patient", "patient_id", pids,
                         "IN_COUNTY", "County", "county_key", ckey)
        n += len(pids)
    counts["IN_COUNTY"] = n

    counts["seconds"] = round(time.time() - t0, 1)
    print("\nHRSA shortage layer loaded", flush=True)
    for k, v in counts.items():
        print(f"  {k:16} {v:>10,}" if isinstance(v, int) else f"  {k:16} {v:>10}")
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Load HRSA Mental Health HPSAs")
    ap.add_argument("--csv", required=True, help="HPSA_DASHBOARD.csv path")
    ap.add_argument("--url", default=None, help="Server URL (omit for embedded)")
    args = ap.parse_args(argv)
    client = SamyamaClient.connect(args.url) if args.url else SamyamaClient.embedded()
    load_hpsa(client, args.csv)


if __name__ == "__main__":
    main()

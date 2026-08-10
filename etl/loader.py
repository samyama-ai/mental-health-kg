"""
Mental Health KG ETL Loader — US behavioural-health services layer
==================================================================
Loads US mental-health and substance-use treatment facilities from
FindTreatment.gov (SAMHSA / BHSIS) into a Samyama property graph.

Schema: 5 node labels, 5 edge types.
  Facility{facility_id,name,name2,street1,street2,city,state,zip,
           phone,intake,hotline,website,latitude,longitude}
  State{code}
  FacilityType{code,name}          -- MH | SA
  ServiceCategory{code,name}       -- the 33 SAMHSA service categories
  Service{service_id,category_code,value}
  Language{name}

  (:Facility)-[:LOCATED_IN]->(:State)
  (:Facility)-[:HAS_TYPE]->(:FacilityType)
  (:Facility)-[:OFFERS]->(:Service)
  (:Service)-[:IN_CATEGORY]->(:ServiceCategory)
  (:Facility)-[:SPEAKS]->(:Language)

Reads the CSV files produced by `python -m etl.download_data` from --data-dir:
  facilities.csv  states.csv  facility_types.csv  service_categories.csv
  services.csv  languages.csv
  edge_located_in.csv  edge_has_type.csv  edge_offers.csv
  edge_in_category.csv  edge_speaks.csv

Why Language is lifted out of Service: referral matching turns on it directly
("a facility near her that takes her insurance and speaks Haitian Creole"), so
it earns its own label rather than sitting inside the generic service list. The
same values remain reachable as Services under categories SL and OL.

Data source: https://findtreatment.gov  (SAMHSA / BHSIS)
Licence: US federal government work — public domain.

Usage:
    python -m etl.loader --data-dir data
    python -m etl.loader --data-dir data --limit 500        # fast subset
    python -m etl.loader --data-dir data --url http://localhost:8080
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from samyama import SamyamaClient

from etl.helpers import GRAPH, batch_create_nodes, batch_create_edges, read_csv, _q


def _float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def load_mental_health(
    client: SamyamaClient,
    data_dir: str = "data",
    limit: int | None = None,
) -> dict:
    """Load the FindTreatment.gov CSVs into Samyama. Returns a dict of counts."""
    d = Path(data_dir)
    counts = {}

    # --- indexes (best-effort; these are what make the edge MATCHes fast) ---
    indexes = [("Facility", "facility_id"), ("State", "code"),
               ("FacilityType", "code"), ("ServiceCategory", "code"),
               ("Service", "service_id"), ("Language", "name")]
    for label, prop in indexes:
        try:
            client.query(f"CREATE INDEX ON :{label}({prop})", GRAPH)
        except Exception as e:
            print(f"  [index] skipped :{label}({prop}) — {e}", flush=True)
    print(f"Created {len(indexes)} indexes", flush=True)

    t0 = time.time()

    # ---- NODES ----
    print("Phase 1/2: Loading nodes ...", flush=True)

    states = read_csv(d / "states.csv")
    batch_create_nodes(client, [("State", {"code": r["code"]}) for r in states])
    counts["states"] = len(states)

    ftypes = read_csv(d / "facility_types.csv")
    batch_create_nodes(client, [
        ("FacilityType", {"code": r["code"], "name": r["name"]}) for r in ftypes])
    counts["facility_types"] = len(ftypes)

    cats = read_csv(d / "service_categories.csv")
    batch_create_nodes(client, [
        ("ServiceCategory", {"code": r["code"], "name": r["name"]}) for r in cats])
    counts["service_categories"] = len(cats)

    svcs = read_csv(d / "services.csv")
    batch_create_nodes(client, [
        ("Service", {"service_id": r["service_id"],
                     "category_code": r["category_code"],
                     "value": r["value"]})
        for r in svcs])
    counts["services"] = len(svcs)

    langs = read_csv(d / "languages.csv")
    batch_create_nodes(client, [("Language", {"name": r["name"]}) for r in langs])
    counts["languages"] = len(langs)

    facilities = read_csv(d / "facilities.csv")
    if limit is not None:          # honor --limit 0 rather than treating it as "all"
        facilities = facilities[:limit]
    keep = {r["facility_id"] for r in facilities}      # ids we actually loaded
    batch_create_nodes(client, [
        ("Facility", {
            "facility_id": r["facility_id"], "name": r["name"],
            "name2": r.get("name2", ""),
            "street1": r.get("street1", ""), "street2": r.get("street2", ""),
            "city": r.get("city", ""), "state": r.get("state", ""),
            "zip": r.get("zip", ""), "phone": r.get("phone", ""),
            "intake": r.get("intake", ""), "hotline": r.get("hotline", ""),
            "website": r.get("website", ""),
            "latitude": _float(r.get("latitude")),
            "longitude": _float(r.get("longitude")),
        })
        for r in facilities])
    counts["facilities"] = len(facilities)

    # ---- EDGES ---- (only for facilities we kept, so --limit stays consistent)
    print("Phase 2/2: Loading edges ...", flush=True)

    loc = [r for r in read_csv(d / "edge_located_in.csv") if r["facility_id"] in keep]
    batch_create_edges(client, [
        ("Facility", f"facility_id: {_q(r['facility_id'])}", "LOCATED_IN",
         "State", f"code: {_q(r['state_code'])}", None)
        for r in loc])
    counts["LOCATED_IN"] = len(loc)

    typ = [r for r in read_csv(d / "edge_has_type.csv") if r["facility_id"] in keep]
    batch_create_edges(client, [
        ("Facility", f"facility_id: {_q(r['facility_id'])}", "HAS_TYPE",
         "FacilityType", f"code: {_q(r['type_code'])}", None)
        for r in typ])
    counts["HAS_TYPE"] = len(typ)

    # IN_CATEGORY is facility-independent, so it is never filtered by --limit.
    cat = read_csv(d / "edge_in_category.csv")
    batch_create_edges(client, [
        ("Service", f"service_id: {_q(r['service_id'])}", "IN_CATEGORY",
         "ServiceCategory", f"code: {_q(r['category_code'])}", None)
        for r in cat])
    counts["IN_CATEGORY"] = len(cat)

    off = [r for r in read_csv(d / "edge_offers.csv") if r["facility_id"] in keep]
    batch_create_edges(client, [
        ("Facility", f"facility_id: {_q(r['facility_id'])}", "OFFERS",
         "Service", f"service_id: {_q(r['service_id'])}", None)
        for r in off])
    counts["OFFERS"] = len(off)

    spk = [r for r in read_csv(d / "edge_speaks.csv") if r["facility_id"] in keep]
    batch_create_edges(client, [
        ("Facility", f"facility_id: {_q(r['facility_id'])}", "SPEAKS",
         "Language", f"name: {_q(r['language'])}", None)
        for r in spk])
    counts["SPEAKS"] = len(spk)

    elapsed = time.time() - t0
    counts["nodes"] = (counts["facilities"] + counts["states"]
                       + counts["facility_types"] + counts["service_categories"]
                       + counts["services"] + counts["languages"])
    counts["edges"] = (counts["LOCATED_IN"] + counts["HAS_TYPE"]
                       + counts["IN_CATEGORY"] + counts["OFFERS"]
                       + counts["SPEAKS"])

    print(f"\n{'=' * 60}", flush=True)
    print(f"Mental Health KG load complete in {elapsed:.1f}s", flush=True)
    print(f"{'=' * 60}", flush=True)
    for k, v in counts.items():
        print(f"  {k:<20s} {v:,}", flush=True)
    return counts


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Load FindTreatment.gov facilities into Samyama")
    ap.add_argument("--data-dir", default="data", help="Directory with the CSV files")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap the number of facilities (fast demo)")
    ap.add_argument("--url", default=None,
                    help="Samyama server URL (omit for embedded)")
    args = ap.parse_args(argv)

    client = SamyamaClient.connect(args.url) if args.url else SamyamaClient.embedded()
    load_mental_health(client, data_dir=args.data_dir, limit=args.limit)


if __name__ == "__main__":
    main()

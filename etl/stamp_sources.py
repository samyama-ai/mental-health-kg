"""Record a :DataSource manifest in the graph, so a snapshot says how old it is.

A .sgsnap travels without this repo. Somebody importing one six months from now
has no way to tell whether the service tags are current, and the answer is not
obvious: FindTreatment.gov advertises weekly updates but its authoritative
refresh is the annual N-MHSS survey, and HRSA rebuilds its file daily while 13%
of the designations inside it have not changed in over three years.

One node per source, carrying the fetch date, the real cadence and the caveat
that matters. Node-level `source` properties already point at these by name.

    python -m etl.stamp_sources --url http://localhost:18080
"""

from __future__ import annotations

import argparse

from samyama import SamyamaClient

from etl.helpers import GRAPH, batch_create_nodes

SOURCES = [
    {
        "name": "FindTreatment.gov",
        "publisher": "SAMHSA / BHSIS",
        "url": "https://findtreatment.gov",
        "licence": "US federal government work - public domain",
        "real_data": True,
        "fetched_on": "2026-08-10",
        "cadence": "annual (N-MHSS survey); monthly additions; weekly corrections",
        "caveat": ("The weekly channel is opt-in - it fires only when a facility "
                   "notifies SAMHSA. Service tags (IPV, languages, sliding fee) come "
                   "from the annual survey and may be up to a year old."),
        "produces": "Facility, Service, ServiceCategory, Language, FacilityType, State",
    },
    {
        "name": "HRSA",
        "publisher": "Health Resources and Services Administration",
        "url": "https://data.hrsa.gov/DataDownload/DD_Files/HPSA_DASHBOARD.csv",
        "licence": "US federal government work - public domain",
        "real_data": True,
        "fetched_on": "2026-08-13",
        "cadence": "file rebuilt daily; designations change rarely",
        "caveat": ("Measured on this copy: 8% of designations updated in the last 90 "
                   "days, 73% within a year, 13% not in over 3 years. Newest "
                   "2026-08-05, oldest 2016-09-22; designation dates back to 1973."),
        "produces": "ShortageArea, County",
    },
    {
        "name": "NPPES",
        "publisher": "CMS / National Plan and Provider Enumeration System",
        "url": "https://download.cms.gov/nppes/NPI_Files.html",
        "licence": "US federal government work - public domain",
        "real_data": True,
        "fetched_on": "2026-08-13",
        "cadence": "monthly full-replacement file; no usable incremental feed",
        "caveat": ("Freshest FILE, stalest RECORDS. Published 2026-08-10 covering "
                   "NPIs through 2026-08-09, but 70.7% of loaded providers were "
                   "last updated over 3 years ago and 50.9% have never been "
                   "updated since they registered. Authoritative for who is "
                   "licensed in what discipline; NOT a current directory of where "
                   "they practise - prefer the per-state aggregates over named "
                   "rows. Individual providers loaded for MA and VT only. Applied "
                   "Behaviour Analysis excluded (587,194 behaviour technicians "
                   "work in autism services, not behavioural-health referral)."),
        "produces": "Provider, Taxonomy",
    },
    {
        "name": "Synthea",
        "publisher": "The MITRE Corporation",
        "url": "https://github.com/synthetichealth/synthea",
        "licence": "Apache 2.0",
        "real_data": False,
        "fetched_on": "2026-08-12",
        "cadence": "not a feed - a generator; output pinned by jar version and seed",
        "caveat": ("SYNTHETIC. No node from this source describes a real person. "
                   "Cohorts: MA-2000-s20260812, VT-1500-s20260813. The IPV finding is "
                   "lifetime screening prevalence, not current need."),
        "produces": "Patient, Condition",
    },
]


def stamp(client: SamyamaClient) -> int:
    """Rewrite the manifest from scratch. Idempotent, and updatable.

    An earlier version skipped any source already present, which meant a data
    refresh left a stale `fetched_on` in the graph with no warning -- the one
    thing a provenance manifest must never do. The nodes are three in number and
    carry no edges, so replacing them wholesale is both cheap and correct.
    """
    try:
        client.query("CREATE INDEX ON :DataSource(name)", GRAPH)
    except Exception as e:  # noqa: BLE001
        print(f"  [index] skipped - {e}", flush=True)
    before = len(client.query("MATCH (d:DataSource) RETURN d.name", GRAPH).records)
    if before:
        client.query("MATCH (d:DataSource) DETACH DELETE d", GRAPH)
        print(f"  refreshed {before} existing manifest node(s)")
    batch_create_nodes(client, [("DataSource", s) for s in SOURCES], GRAPH)
    for s in SOURCES:
        print(f"  + {s['name']:20} fetched {s['fetched_on']}  "
              f"{'real' if s['real_data'] else 'SYNTHETIC'}")
    return len(SOURCES)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write the :DataSource manifest")
    ap.add_argument("--url", default=None, help="Server URL (omit for embedded)")
    args = ap.parse_args(argv)
    client = SamyamaClient.connect(args.url) if args.url else SamyamaClient.embedded()
    n = stamp(client)
    print(f"\n{n} source(s) recorded")


if __name__ == "__main__":
    main()

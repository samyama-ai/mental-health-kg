"""Download US behavioural-health facilities from FindTreatment.gov and build the load CSVs.

Pulls the SAMHSA BHSIS facility locator and flattens it into node/edge CSVs that
`etl.loader` consumes.

    python -m etl.download_data                          # whole US
    python -m etl.download_data --out mydata             # different output dir
    python -m etl.download_data --near 42.3601,-71.0589 --radius-miles 25

Source:  FindTreatment.gov API (SAMHSA / BHSIS), API doc v1.11, 2026-05-26
         https://findtreatment.gov/assets/FindTreatment-Developer-Guide.pdf
Licence: US federal government work — public domain.
Refresh: new facilities monthly; names/addresses/phones/services weekly.

API notes learned by probing (2026-08-10), because the published doc is wrong in
one place and silent in another:

  * `sAddr` is **"{lat},{lng}"**, NOT "{lng},{lat}" as Appendix A states. The
    worked examples in the same document use lat,lng and only that order returns
    rows; the reversed order silently returns recordCount=0 rather than an error.
  * Records carry **no stable facility identifier**. `_irow` is a per-response
    row index and changes between queries, so it cannot be used as a key. We mint
    `facility_id` as a SHA-1 over (name, street1, city, state, zip) — see
    `_facility_id`. Consequence documented in docs/schema.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://findtreatment.gov/locator/exportsAsJson/v2"
UA = "samyama-mental-health-kg-loader"

RETRIES = 3
PAGE_SIZE = 100
THROTTLE_S = 0.15          # be a polite citizen of a public health service
MILES_TO_M = 1609.344

# The national sweep is a set of centre+radius probes, not one.
#
# A single 5,000 km probe from the geographic centre of the contiguous US was
# believed to cover the whole country. It does not: Honolulu is 5,922 km from
# that centre and Guam is 11,199 km, so Hawaii and the Pacific territories fell
# outside the radius entirely and no facility in them was ever fetched. The
# symptom was 52 :State nodes with no HI, and HRSA counties in HI/GU/AS/MP left
# with no IN_STATE edge to attach to.
#
# Alaska (4,179 km) and Puerto Rico (3,911 km) are inside the mainland probe and
# were never affected. Results are deduplicated by facility_id, so probes may
# overlap freely.
US_PROBES = [
    ("39.8283,-98.5795", 5_000_000),    # contiguous US + AK + PR + VI
    ("20.7984,-156.3319", 800_000),     # Hawaii (centred on Maui)
    ("13.4757,144.7489", 400_000),      # Guam + Northern Mariana Islands
    ("-14.2756,-170.7020", 300_000),    # American Samoa
]
US_CENTRE, US_RADIUS_M = US_PROBES[0]

# Service categories (the `f2` code) whose values we lift into first-class nodes
# rather than leaving as generic services, because A3-style referral matching
# turns on them directly.
LANGUAGE_CATEGORIES = {"SL", "OL"}

# Sanity floor: the national count measured 2026-08-10 was 24,816. A large drop
# means the API changed or a query silently failed, and we would rather shout
# than write a truncated dataset.
EXPECTED_MIN_NATIONAL = 20_000


def _get(url: str) -> bytes:
    """Fetch a URL, retrying with backoff on transient errors.

    A 4xx (client error) is permanent, so it is raised immediately and not
    retried; only 5xx, connection and timeout errors are retried (429 is treated
    as transient).
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                raise RuntimeError(f"fetch failed permanently: HTTP {e.code}") from e
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException) as e:
            last = e
        if attempt < RETRIES:
            time.sleep(2 * attempt)
    raise RuntimeError(f"failed after {RETRIES} attempts: {last}")


def _page(addr: str, radius_m: float, page: int) -> dict:
    q = urllib.parse.urlencode({
        "sAddr": addr,          # "{lat},{lng}" — see module docstring
        "limitType": 2,         # 2 = distance search
        "limitValue": int(radius_m),
        "sType": "both",        # substance use + mental health
        "pageSize": PAGE_SIZE,
        "page": page,
        "sort": 0,
    })
    body = _get(f"{API}?{q}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        # The API answers malformed queries with a bare text string and HTTP 200.
        raise RuntimeError(f"non-JSON response (likely bad parameters): {body[:120]!r}") from e


def fetch_all(addr: str, radius_m: float, allow_empty: bool = False) -> list[dict]:
    """Page through the locator and return every facility row.

    A zero-record answer is normally a bug — a swapped sAddr or a radius given in
    miles — so it raises. `allow_empty` is for the small territory probes, where a
    genuinely empty result is a real possibility and must not abort the sweep.
    """
    first = _page(addr, radius_m, 1)
    total_pages = first.get("totalPages") or 0
    total = first.get("recordCount") or 0
    if not total:
        if allow_empty:
            return []
        raise RuntimeError(
            "the locator returned 0 records — check the sAddr order is lat,lng "
            "and that the radius is in metres"
        )
    print(f"[download] {total} facilities across {total_pages} pages", flush=True)

    rows = list(first.get("rows", []))
    for p in range(2, total_pages + 1):
        try:
            rows.extend(_page(addr, radius_m, p).get("rows", []))
        except RuntimeError as e:
            print(f"[download]   WARN page {p} failed, skipping: {e}", flush=True)
        time.sleep(THROTTLE_S)
        if p % 25 == 0 or p == total_pages:
            print(f"[download]   page {p}/{total_pages} — {len(rows)} rows", flush=True)
    return rows


def _s(r: dict, key: str) -> str:
    """Read a field as a string. The API returns JSON null for absent values, so
    `r.get(key, "")` is not enough — the key is present with a None value."""
    return (r.get(key) or "").strip()


def _facility_id(r: dict) -> str:
    """Mint a stable key. The API supplies none — see module docstring."""
    parts = [_s(r, "name1"), _s(r, "street1"),
             _s(r, "city"), _s(r, "state"), _s(r, "zip")]
    key = "|".join(p.lower() for p in parts)
    return "ft-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _split_values(f3: str) -> list[str]:
    """`f3` packs several values into one semicolon-delimited string."""
    return [v.strip() for v in (f3 or "").split(";") if v.strip()]


def _num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _write_csvs(rows: list[dict], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)

    # A single physical facility is listed once per care type — the same name and
    # address appears as both MH (mental health) and SA (substance use), each row
    # carrying its OWN service list. So everything below accumulates per
    # facility_id ACROSS rows; accumulating per row double-counts every edge and
    # keeps only one of the two care types.
    facilities: dict[str, dict] = {}
    fac_types: dict[str, set] = {}        # facility_id -> {"MH", "SA"}
    fac_services: dict[str, set] = {}     # facility_id -> {service_id}
    fac_langs: dict[str, set] = {}        # facility_id -> {language}
    fac_state: dict[str, str] = {}

    states: set[str] = set()
    categories: dict[str, str] = {}       # code -> display name
    services: dict[str, tuple] = {}       # service_id -> (category_code, value)
    languages: set[str] = set()

    skipped = 0
    for r in rows:
        if not _s(r, "name1"):            # no name, no usable key
            skipped += 1
            continue
        fid = _facility_id(r)

        rec = {
            "facility_id": fid, "name": _s(r, "name1"), "name2": _s(r, "name2"),
            "street1": _s(r, "street1"), "street2": _s(r, "street2"),
            "city": _s(r, "city"), "state": _s(r, "state"), "zip": _s(r, "zip"),
            "phone": _s(r, "phone"), "intake": _s(r, "intake1"),
            "hotline": _s(r, "hotline1"), "website": _s(r, "website"),
            "latitude": _num(r.get("latitude")), "longitude": _num(r.get("longitude")),
        }
        if fid not in facilities:
            facilities[fid] = rec
        else:
            # Merge: the two rows agree on name/address by construction, but one
            # may carry a website or intake line the other omits.
            for k, v in rec.items():
                if v not in (None, "") and facilities[fid].get(k) in (None, ""):
                    facilities[fid][k] = v

        ftype = _s(r, "typeFacility").upper()
        if ftype:
            fac_types.setdefault(fid, set()).add(ftype)

        st = _s(r, "state").upper()
        if st:
            states.add(st)
            fac_state[fid] = st

        for s in r.get("services") or []:
            code = (s.get("f2") or "").strip()
            label = (s.get("f1") or "").strip()
            if not code:
                continue
            categories.setdefault(code, label)

            for value in _split_values(s.get("f3", "")):
                sid = f"{code}::{value}"
                services.setdefault(sid, (code, value))
                fac_services.setdefault(fid, set()).add(sid)
                if code in LANGUAGE_CATEGORIES:
                    languages.add(value)
                    fac_langs.setdefault(fid, set()).add(value)

    # Edges are emitted once per (facility, target) pair, from the accumulated sets.
    e_located = [[fid, st] for fid, st in sorted(fac_state.items())]
    e_offers = [[fid, sid] for fid in sorted(fac_services)
                for sid in sorted(fac_services[fid])]
    e_speaks = [[fid, lang] for fid in sorted(fac_langs)
                for lang in sorted(fac_langs[fid])]
    e_has_type = [[fid, t] for fid in sorted(fac_types)
                  for t in sorted(fac_types[fid])]
    e_in_category = [[sid, services[sid][0]] for sid in sorted(services)]

    def _safe(cell):
        # Neutralize CSV formula injection: a leading =,+,-,@ (or tab/CR) can
        # execute in spreadsheet apps. Prefix such *text* cells with a quote —
        # but leave legitimate numbers (e.g. a negative longitude) untouched.
        if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r"):
            try:
                float(cell)
            except ValueError:
                return "'" + cell
        return cell

    def w(name, header, data):
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(header)
            wr.writerows([[_safe(c) for c in row] for row in data])

    fac_cols = ["facility_id", "name", "name2", "street1", "street2", "city",
                "state", "zip", "phone", "intake", "hotline", "website",
                "latitude", "longitude"]
    w("facilities.csv", fac_cols,
      [[facilities[f][c] for c in fac_cols] for f in sorted(facilities)])
    w("states.csv", ["code"], [[s] for s in sorted(states)])
    w("facility_types.csv", ["code", "name"],
      [["MH", "Mental health treatment"], ["SA", "Substance use treatment"]])
    w("service_categories.csv", ["code", "name"],
      [[c, categories[c]] for c in sorted(categories)])
    w("services.csv", ["service_id", "category_code", "value"],
      [[sid, *services[sid]] for sid in sorted(services)])
    w("languages.csv", ["name"], [[l] for l in sorted(languages)])

    w("edge_located_in.csv", ["facility_id", "state_code"], e_located)
    w("edge_has_type.csv", ["facility_id", "type_code"], e_has_type)
    w("edge_offers.csv", ["facility_id", "service_id"], e_offers)
    w("edge_in_category.csv", ["service_id", "category_code"], e_in_category)
    w("edge_speaks.csv", ["facility_id", "language"], e_speaks)

    both = sum(1 for t in fac_types.values() if len(t) > 1)
    counts = {
        "facilities": len(facilities), "states": len(states),
        "service_categories": len(categories), "services": len(services),
        "languages": len(languages),
        "LOCATED_IN": len(e_located), "HAS_TYPE": len(e_has_type),
        "OFFERS": len(e_offers), "IN_CATEGORY": len(e_in_category),
        "SPEAKS": len(e_speaks),
        "(facilities offering both MH and SA)": both,
    }
    print(f"[download] wrote CSVs into {out}/", flush=True)
    for k, v in counts.items():
        print(f"  {k:<20s} {v:,}", flush=True)
    if skipped:
        print(f"[download] skipped {skipped} record(s) with no name", flush=True)
    return counts


def download_all(out: str = "data", near: str | None = None,
                 radius_miles: float | None = None) -> dict:
    national = near is None
    if national:
        probes = US_PROBES
    else:
        probes = [(near, radius_miles * MILES_TO_M if radius_miles else US_RADIUS_M)]

    rows: list[dict] = []
    for i, (addr, radius_m) in enumerate(probes):
        print(f"[download] FindTreatment.gov — centre {addr}, "
              f"radius {radius_m / 1000:,.0f} km", flush=True)
        # Only the first probe is load-bearing; an empty territory probe is a
        # legitimate answer and must not abort the national sweep.
        got = fetch_all(addr, radius_m, allow_empty=national and i > 0)
        print(f"[download]   {len(got):,} records", flush=True)
        rows.extend(got)
    # Probes overlap; _write_csvs keys facilities by facility_id, so duplicates
    # collapse there rather than needing a pass here.

    if national and len(rows) < EXPECTED_MIN_NATIONAL:
        print(f"[download]   WARN got {len(rows)} rows but expected at least "
              f"{EXPECTED_MIN_NATIONAL:,} nationally — the API may have changed "
              f"or pages may have been dropped. Counts below may be short.",
              flush=True)

    return _write_csvs(rows, Path(out))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Download FindTreatment.gov facilities into load CSVs")
    ap.add_argument("--out", default="data", help="Output directory (default: data)")
    ap.add_argument("--near", default=None,
                    help='Centre as "lat,lng" (default: whole US)')
    ap.add_argument("--radius-miles", type=float, default=None,
                    help="Search radius in miles (used with --near)")
    args = ap.parse_args(argv)
    download_all(args.out, args.near, args.radius_miles)


if __name__ == "__main__":
    main()

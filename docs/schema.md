# Mental Health KG — Design Notes

**v0.1 — US behavioural-health services layer.**

US mental-health and substance-use treatment facilities, with the services they
offer, the languages they speak, the populations they serve and the payment they
accept. Built for referral routing: *which help exists where, for whom, in what
language.*

Measured on a full national load, 2026-08-10.

## Scale

| | |
|---|---|
| Facilities | **17,254** |
| Nodes | **17,678** |
| Edges | **1,474,079** |
| Snapshot | 9.0 MB gzipped (105 MB raw) |

## Node labels

| Label | Count | Key | Fields |
|-------|------:|-----|--------|
| Facility | 17,254 | `facility_id` | name, name2, street1, street2, city, state, zip, phone, intake, hotline, website, latitude, longitude |
| Service | 313 | `service_id` | category_code, value |
| State | 52 | `code` | — |
| ServiceCategory | 33 | `code` | name |
| Language | 24 | `name` | — |
| FacilityType | 2 | `code` | name — `MH` \| `SA` |

## Edge types

| Edge | From → To | Count | Properties |
|------|-----------|------:|-----------|
| OFFERS | Facility → Service | 1,417,479 | — |
| HAS_TYPE | Facility → FacilityType | 23,293 | — |
| LOCATED_IN | Facility → State | 17,254 | — |
| SPEAKS | Facility → Language | 15,740 | — |
| IN_CATEGORY | Service → ServiceCategory | 313 | — |

## Design decisions

**`HAS_TYPE` is an edge, not a property.** The source lists each physical facility
**once per care type** — the same name and address returns as one `MH` row and one
`SA` row, each carrying its own service list. A facility can genuinely be both, and
**6,039 of 17,254 (35%) are**. Storing the type as a property would silently keep
whichever row was seen first and discard the other. The loader accumulates across
both rows.

**`Service` is a (category, value) pair.** The API packs several values into one
semicolon-delimited string per category, so `service_id` is `"{category}::{value}"`
— e.g. `SG::Adult women`. Keeping the category as an edge to `ServiceCategory`
rather than a property means *"which facilities offer anything under Payment
Assistance"* is one traversal.

**`Language` is lifted out of `Service` deliberately.** Referral matching turns on
it directly, so it earns its own label. The same values remain reachable as
Services under categories `SL` (Language Services) and `OL` (Other Languages).

**`miles` is not modelled.** It is the distance from the query point — a property
of the request, not of the facility, and meaningless once stored.

## Node identity

The API supplies **no stable identifier**. `_irow` is a per-response row index that
changes between queries.

`facility_id` is minted as `"ft-" + sha1(name|street1|city|state|zip)[:16]`.
Facilities are therefore deduplicated by **exact match** on that tuple; a facility
listed under two spellings appears as two nodes. Names are not normalised.

This is correct behaviour for multi-site organisations — Casa Esperanza Inc has
four sites on Eustis Street in Roxbury and is four `Facility` nodes, which is what
referral routing needs.

## Source

| | |
|---|---|
| Source | **FindTreatment.gov** — SAMHSA / BHSIS facility locator |
| API doc | v1.11, 2026-05-26 |
| Endpoint | `GET /locator/exportsAsJson/v2` |
| Licence | **US federal government work — public domain** |
| Refresh | new facilities monthly; names, addresses, phones and services **weekly** |

### API defects worked around

Recorded because they cost time and are not in the published documentation.

1. **Coordinates are `"{lat},{lng}"`, not `"{lng},{lat}"`.** Appendix A of the
   developer guide states longitude first; the worked examples in the same document
   use latitude first, and only that order returns rows. The reversed order **fails
   silently** — HTTP 200 with `recordCount: 0` rather than an error.
2. **No stable facility identifier** — see *Node identity* above.
3. **Malformed queries return HTTP 200** with a bare text body rather than JSON, so
   the loader treats a JSON decode failure as a parameter error.

### Engine defects encountered

Found while querying the loaded graph. Both affect anyone building a KG from the
shared template, which pins `samyama>=0.6.0` and therefore resolves to **0.6.1**.

- **`RETURN DISTINCT` is a silent no-op** in SDK 0.6.1. `count(DISTINCT …)` and
  `WITH DISTINCT …` both work correctly. Reproduced minimally: 3 identical nodes +
  1 different, `RETURN DISTINCT p.name` returns 4 rows instead of 2. The engine at
  v1.1.0 carries a regression test (`test_return_distinct_values`) asserting the
  correct behaviour, so this appears fixed but unpublished.
- **`EXISTS { … }` block syntax is not supported** — parse error. Use
  `OPTIONAL MATCH … WHERE x IS NULL` for a negative constraint.

## Planned — not in v0.1

Lifted from the remaining service categories, all present in the data:

| Category | Becomes |
|---|---|
| `SG` Special Programs/Groups | `Population` — Adult women, Pregnant/postpartum women, Seniors |
| `AGE` Age Groups Accepted · `SN` Sex Accepted | eligibility on `Population` |
| `EXCL` Exclusive Services | **negative** eligibility — *"Opioid use disorder clients only"* |
| `PAY` · `PYAS` Payment / Assistance | `Payment` — so "takes Medicaid AND has a sliding scale" is a traversal |

Also planned: **County** nodes (the API supports county search) so referral routing
works below state level.

## Later layers — deferred, not dropped

The following were scoped in the original schema proposal and remain valid as later
phases. They are deferred because the US services layer is what the lead use case
needs first.

| Layer | Sources | Note |
|---|---|---|
| Disease burden | CDC NISVS, WHO VAW database, IHME GBD | population prevalence |
| Social determinants | World Bank WDI | — |
| Clinical evidence | ClinicalTrials.gov, PubMed | — |
| Therapy + biology | ChEMBL, SIDER/FAERS, OpenTargets | — |
| DV service directories | DomesticShelters.org (~3,000 US/Canada programs), NNEDV state coalitions | ★ closest fit to referral routing; **no public API — needs outreach** |

## Excluded on purpose

- **DSM-5** — APA copyright; cannot be ingested or redistributed. ICD-11 and MeSH
  give equivalent coverage and are free. (The original scaffold's
  `Condition.dsm_code` field was removed for this reason.)
- **PGC psychiatric GWAS summary statistics** — free for scientific research, but
  commercial use requires Data Access Committee permission.
- **UMLS, SNOMED CT** — licence required.
- **Scraped social-media mental-health corpora** — no informed consent, real
  re-identification risk.

## Not modelled

- **Individual-level records of any kind.** This KG is facility, service and policy
  level only. No patients, no survivors, no sessions.
- **`Condition -[:HAS_SYMPTOM]-> Symptom`** (in the original scaffold) — no open
  dataset provides a usable symptom–disorder mapping, and the ones that do are
  DSM-derived. Modelling it would also make the graph diagnosis-shaped, which is out
  of scope by design.
- **Inverse edges.** Relationships are declared in one direction only; Cypher
  traverses both ways, so a `TREATED_BY` to pair with `TREATS` is redundant storage
  and a source of drift.

## Scope statement

This graph describes services, facilities and policy. It is **not** a diagnostic or
screening tool and must not be presented as one.

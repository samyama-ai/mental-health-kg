# Dataset Card — Mental Health Knowledge Graph

**113,710 nodes · 1,665,153 edges · four sources · built 2026-08-18**

A graph of US behavioural-health provision: which facilities exist, what they
offer, which clinicians are licensed to practise, where the federal government
already designates a shortage, and a simulated population to measure coverage
against.

Built for **referral routing** — *which help exists where, for whom, in what
language, at what price* — and for **coverage analytics**, which is the question
of where that help does *not* exist.

---

## Sources

| Source | Publisher | Licence | Fetched | Produces |
|---|---|---|---|---|
| [FindTreatment.gov](https://findtreatment.gov) | SAMHSA / BHSIS | US federal government work — **public domain** | 2026-08-10 | Facility, Service, ServiceCategory, Language, FacilityType, State |
| [NPPES NPI Registry](https://download.cms.gov/nppes/NPI_Files.html) | CMS | US federal government work — **public domain** | 2026-08-13 | Provider, Taxonomy |
| [HRSA HPSA](https://data.hrsa.gov/data/download) | HRSA / HHS | US federal government work — **public domain** | 2026-08-13 | ShortageArea, County |
| [Synthea](https://github.com/synthetichealth/synthea) | The MITRE Corporation | **Apache 2.0** | 2026-08-12 | Patient, Condition |

The [NUCC taxonomy](https://www.nucc.org/) code set (published, 2026-08-13) supplies
the human-readable classification, grouping and specialisation on `Taxonomy` nodes.
It is a lookup applied to the NPPES layer rather than a fifth source, so it has no
`DataSource` node and is not counted in the four above.

**No licence in this graph restricts redistribution.** Three sources are US
federal government works and therefore public domain; Synthea is Apache 2.0. The
`.sgsnap` snapshot can be shared freely.

The graph records its own provenance: `MATCH (d:DataSource) RETURN d` returns one
node per source with its fetch date, real refresh cadence, caveats, and a
`real_data` flag distinguishing the synthetic layer.

---

## Contents

| Label | Count | Real? | |
|---|---:|---|---|
| Provider | 82,978 | real | licensed clinicians, MA and VT, with licence numbers |
| Facility | 17,254 | real | every US behavioural-health facility |
| ShortageArea | 6,420 | real | designated Mental Health HPSAs |
| Patient | 3,500 | **synthetic** | simulated people, MA and VT |
| County | 3,043 | real | |
| Service | 313 | real | |
| Taxonomy | 76 | real | behavioural-health provider taxonomies |
| State | 52 | real | |
| ServiceCategory | 33 | real | |
| Language | 24 | real | |
| Condition | 11 | **synthetic** | behavioural-health findings |
| DataSource | 4 | — | provenance manifest |
| FacilityType | 2 | real | MH / SA |

Edges: `OFFERS` 1,417,479 · `PRACTICES_IN` 82,978 · `HAS_TAXONOMY` 82,978 ·
`HAS_TYPE` 23,293 · `LOCATED_IN` 17,254 · `SPEAKS` 15,740 · `COVERS` 7,842 ·
`HAS_CONDITION` 3,918 · `LIVES_IN` 3,500 · `IN_COUNTY` 3,500 · `HAS_PROVIDERS`
3,329 · `IN_STATE` 3,029 · `IN_CATEGORY` 313.

---

## What is synthetic, and what that means

`Patient` and `Condition` come from Synthea and describe **nobody**. Every such
node carries `synthetic: true` and `source: "Synthea"`, and `DataSource` marks the
layer `real_data: false`, so consumers can filter programmatically rather than by
convention.

Synthea also generates its own hospitals and clinicians. Those are **deliberately
not loaded** — they would be indistinguishable from the real facilities the graph
exists to describe.

Two caveats that must travel with any figure derived from the synthetic layer:

- The `Victim of intimate partner abuse (finding)` rate of ~40% is **lifetime
  screening prevalence, not current need**. CDC lifetime figures are ~41% for
  women and ~26% for men, so the cohort is plausible — but it is not a count of
  people currently seeking help.
- Cohorts are pinned by generator version and seed (`MA-2000-s20260812`,
  `VT-1500-s20260813`). **Use a distinct seed per cohort**: Synthea's seed
  determines patient UUIDs, and two cohorts at the same seed collide.

---

## Currency

The graph is only as current as its slowest authoritative layer, and that layer is
**annual**.

| Source | Publisher cadence | What actually moves |
|---|---|---|
| FindTreatment.gov | **annual** N-MHSS survey; monthly additions; weekly corrections | the weekly channel is **opt-in** — it fires only when a facility notifies SAMHSA |
| NPPES | monthly full replacement | freshest **file**, stalest **records** — 70.7% of loaded providers last updated over 3 years ago, and 50.9% never updated since they registered |
| HRSA | file rebuilt daily | designations rarely change — 13% untouched in over 3 years, dates back to 1973 |
| Synthea | not a feed | pinned by version + seed |

**Recommended rebuild cadence: monthly.** Weekly re-downloads near-identical
service data. Neither real source offers an incremental feed; both are full
snapshots. Full detail in [`docs/schema.md`](docs/schema.md#data-currency).

---

## Known limitations

- **These are behavioural-health facilities, not domestic-violence shelters.**
  6,072 facilities are tagged as serving survivors of intimate partner violence,
  but none is an emergency shelter with beds. A survivor needing to leave tonight
  is not served by this data.
- **No crisis lines.** Zero facilities offer a service matching *hotline* or
  *crisis*. The graph is for referral, not crisis response.
- **Individual clinicians cover MA and VT only.** Every other state has the
  national aggregate count per taxonomy, not named providers.
- **Applied Behaviour Analysis is excluded** from the provider layer — 587,194
  behaviour technicians and 128,519 behaviour analysts work in autism services
  rather than behavioural-health referral. Psychiatrists number 75,403 by
  comparison.
- **Service tags are survey answers** up to a year old, and they are what every
  referral query filters on.
- **Provider addresses are mostly years out of date.** 70.7% of loaded NPPES
  records were last updated over three years ago and half have never been updated
  since the provider registered. NPPES is authoritative for *who is licensed in
  what discipline*; it is not a current directory of where they practise. Prefer
  the per-state aggregate counts over the named rows for anything load-bearing.
- **Hawaii and the Pacific territories are missing from the facility layer.** The
  national sweep was a single 5,000 km probe from the geographic centre of the
  contiguous US, which reaches Alaska (4,179 km) and Puerto Rico (3,911 km) but
  not Honolulu (5,922 km) or Guam (11,199 km). The graph therefore holds 52
  `State` nodes with no HI, and 14 HRSA counties in HI, GU, AS and MP with no
  `IN_STATE` edge. `etl/download_data.py` now sweeps four probes instead of one —
  109 facilities in HI and 6 in GU/MP — but **this snapshot predates that fix**
  and every count on this page is from the four-source build of 2026-08-18.
- **Facility deduplication is exact-match** on name+address; a facility listed
  under two spellings appears twice. This is correct for multi-site organisations
  and wrong for typos.

---

## Reproducing it

Raw data is **not** checked into this repository — see `.gitignore`. Each loader
documents its source URL and the exact fetch command.

The snapshot is distributed as a release asset rather than committed, because a
15 MB binary does not belong in git history. It goes on the engine repo in the
shared `kg-snapshots-vN` train, the same route the other KGs use:

```
https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-vN/mental-health-full.sgsnap
```

**Not yet published** — queued for the next cut. Build from source until then.

```bash
docker run -d --name samyama-mh -p 18080:8080 \
  public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0
curl -X POST http://localhost:18080/api/snapshot/import \
  -F "file=@mental-health-full.sgsnap"        # ~4s for 1.67M edges
```

Building from source instead: `etl/download_data.py` → `etl/loader.py` →
`etl/synthea_loader.py` → `etl/hpsa_loader.py` → `etl/nppes_loader.py` →
`etl/stamp_sources.py`. Loaders refuse to run against a non-empty layer; start
from a fresh container rather than deleting in place.

Performance figures: [`benchmarks/README.md`](benchmarks/README.md).

---

## Ethical note

The graph holds **knowledge, resources, policy and provenance. It never holds
people.** No survivor, no session, no transcript, no contact record. The only
person-shaped nodes are Synthea's, and they are simulated and flagged as such.

Real clinicians appear because NPPES is a public federal register — but licence
numbers are masked in any published demo artifact.

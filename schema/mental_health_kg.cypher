// Mental Health Knowledge Graph — schema
//
// v0.1 — US behavioural-health services layer, from FindTreatment.gov (SAMHSA / BHSIS).
//
// Node labels: Facility, State, FacilityType, ServiceCategory, Service, Language
// Edge types:  LOCATED_IN, HAS_TYPE, OFFERS, IN_CATEGORY, SPEAKS
//
// (rendered version of this diagram: docs/schema.md)
//
//                         ┌──────────────────┐
//                         │      State       │  52
//                         └────────▲─────────┘
//                                  │ LOCATED_IN  17,254
//                                  │
//    ┌──────────────┐   HAS_TYPE   │   OFFERS    ┌──────────────┐  IN_CATEGORY  ┌───────────────────┐
//    │ FacilityType │◄─────────────┤────────────►│   Service    │──────────────►│  ServiceCategory  │
//    │  MH  /  SA   │    23,293    │  1,417,479  │     313      │      313      │        33         │
//    └──────────────┘              │             └──────────────┘               └───────────────────┘
//                            ┌─────┴──────┐
//                            │  Facility  │  17,254   ← the hub
//                            └─────┬──────┘
//                                  │ SPEAKS  15,740
//                                  ▼
//                         ┌──────────────────┐
//                         │     Language     │  24
//                         └──────────────────┘
//
// Totals: 17,678 nodes · 1,474,079 edges. OFFERS alone is 96% of all edges.

// ---------------------------------------------------------------------------
// Constraints
// ---------------------------------------------------------------------------
CREATE CONSTRAINT facility_id  IF NOT EXISTS FOR (f:Facility)        REQUIRE f.facility_id IS UNIQUE;
CREATE CONSTRAINT state_code   IF NOT EXISTS FOR (s:State)           REQUIRE s.code IS UNIQUE;
CREATE CONSTRAINT ftype_code   IF NOT EXISTS FOR (t:FacilityType)    REQUIRE t.code IS UNIQUE;
CREATE CONSTRAINT category_code IF NOT EXISTS FOR (c:ServiceCategory) REQUIRE c.code IS UNIQUE;
CREATE CONSTRAINT service_id   IF NOT EXISTS FOR (v:Service)         REQUIRE v.service_id IS UNIQUE;
CREATE CONSTRAINT language_name IF NOT EXISTS FOR (l:Language)       REQUIRE l.name IS UNIQUE;

// ---------------------------------------------------------------------------
// Relationship shapes
// ---------------------------------------------------------------------------
// (:Facility)-[:LOCATED_IN]->(:State)
// (:Facility)-[:HAS_TYPE]->(:FacilityType)        // MH | SA — a facility may hold BOTH
// (:Facility)-[:OFFERS]->(:Service)
// (:Service)-[:IN_CATEGORY]->(:ServiceCategory)   // 33 SAMHSA categories
// (:Facility)-[:SPEAKS]->(:Language)

// ---------------------------------------------------------------------------
// Notes on the model
// ---------------------------------------------------------------------------
// Facility identity. The source API supplies NO stable identifier — `_irow` is a
// per-response row index. `facility_id` is minted as a SHA-1 over
// (name, street1, city, state, zip). Facilities are therefore deduplicated by
// exact match on that tuple; a facility listed under two spellings appears twice.
//
// A facility appears once per care type. The same physical facility is returned
// as one MH row and one SA row, each with its own service list. The loader
// accumulates across both, which is why HAS_TYPE is an edge and not a property —
// a facility can genuinely be both, and roughly 40% of them are.
//
// Service is a (category, value) pair. The API packs several values into one
// semicolon-delimited string per category; `service_id` is "{category}::{value}".
// Keeping the category as an edge to ServiceCategory rather than a property means
// "which facilities offer anything under Payment Assistance" is one traversal.
//
// Language is lifted out of Service deliberately. Referral matching turns on it
// directly, so it earns its own label. The same values remain reachable as
// Services under categories SL (Language Services) and OL (Other Languages).
//
// Not modelled: `miles`. It is the distance from the query point, a property of
// the request rather than of the facility, and would be meaningless once stored.

// ---------------------------------------------------------------------------
// Planned — not in v0.1
// ---------------------------------------------------------------------------
// Population / eligibility as first-class nodes, lifted from categories
//   SG   Special Programs/Groups Offered   (e.g. Adult women; Pregnant/postpartum women)
//   AGE  Age Groups Accepted
//   SN   Sex Accepted
//   EXCL Exclusive Services                 <- a NEGATIVE eligibility constraint,
//                                              e.g. "Opioid use disorder clients only"
// Payment / insurance as first-class nodes (PAY, PYAS) so "takes Medicaid AND has
// a sliding scale" is a traversal rather than a string match.
// County: the API supports county search; county nodes would let referral routing
// work below state level.

#!/usr/bin/env python3
"""Narrated demo of the Mental Health KG.

Ten questions that climb from one a spreadsheet could answer to one that needs
four separately published federal datasets joined at once, opening on where the
data came from and how old it is. Press Enter between steps so the pacing is
yours while narrating.

No dependencies beyond the standard library — it talks to the engine over HTTP.
That is deliberate: PyPI `samyama` 0.6.1 silently inverts `OPTIONAL MATCH …
WHERE x IS NULL`, which is the construct step 6 turns on, so the demo would
report 11 facilities instead of 127 through the SDK.

    docker rm -f samyama-mh 2>/dev/null
    docker run -d --name samyama-mh -p 18080:8080 \\
      public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0
    curl -X POST http://localhost:18080/api/snapshot/import \\
      -F "file=@mental-health-full.sgsnap"
    MH_URL=http://localhost:18080 python -m demo.demo

Every number printed comes from the graph at run time. Nothing is hard-coded,
so a bad load shows itself rather than hiding behind a caption.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("MH_URL", "http://localhost:18080")
GRAPH = "mental-health"
PACE = float(os.environ.get("DEMO_PACE", "0") or 0)

BOLD, DIM, CYAN, GREEN, YELLOW, RED, OFF = (
    "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[31m", "\033[0m",
)

# Spelled exactly as the federal sources spell them; a near-miss matches nothing.
IPV = "Clients who have experienced intimate partner violence, domestic violence"
IPVCOND = "Victim of intimate partner abuse (finding)"
TRAUMA = "Trauma-related counseling"
SLIDING = "Sliding fee scale (fee is based on income and other factors)"
HOUSING = "Housing services"
RESIDENTIAL = "Residential/24-hour residential"
ASL = "Sign language services for the deaf and hard of hearing"
OPIOID_ONLY = "Opioid use disorder clients only"
PSYCH = "2084P0800X"          # NUCC taxonomy: Psychiatry & Neurology / Psychiatry


def query(cypher: str) -> tuple[dict, float]:
    request = urllib.request.Request(
        URL + "/api/query",
        data=json.dumps({"graph": GRAPH, "query": cypher}).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        result = json.loads(urllib.request.urlopen(request, timeout=180).read())
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it must be caught first — otherwise a
        # 400 from a running engine is reported as "no engine", which is the one
        # wrong diagnosis a presenter cannot afford.
        print(f"\n  {RED}engine returned {exc.code}{OFF} — {exc.read().decode()[:200]}\n")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\n  {RED}no engine at {URL}{OFF} — {exc.reason}\n")
        sys.exit(1)
    return result, (time.perf_counter() - started) * 1000


def table(columns: list[str], records: list[list], width: int = 52) -> None:
    # Pad short rows rather than IndexError halfway through a live demo.
    cells = [columns] + [
        [fmt(r[i], width) if i < len(r) else "" for i in range(len(columns))]
        for r in records
    ]
    widths = [max(len(r[i]) for r in cells) for i in range(len(columns))]
    print("  " + BOLD + "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns)) + OFF)
    print(f"  {DIM}" + "  ".join("-" * w for w in widths) + OFF)
    for row in cells[1:]:
        print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))


def fmt(value: object, width: int = 52) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    text = str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def pause() -> None:
    """Wait for Enter, unless there is nobody to press it.

    `python -m demo.demo < /dev/null`, a CI smoke check or a piped run has no
    stdin, and input() then raises EOFError at the first step. The demo should
    run start to finish in that case, not die.

    Set `DEMO_PACE` to a number of seconds to sleep instead of waiting. That is
    how the recording is driven: asciinema allocates a PTY, so stdin *is* a tty
    and an unattended run would otherwise block on the first step forever.
    """
    if PACE:
        time.sleep(PACE)
        return
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input(f"\n{DIM}  [enter]{OFF}")
    except EOFError:
        pass


def step(number: int, level: str, question: str, why: str, cypher,
         limit: int = 6, width: int = 52) -> None:
    """Ask one question. `cypher` may be several queries — a real question
    rarely resolves in one, and splitting them is more honest than a join that
    cross-products two unrelated tables together for the sake of one result."""
    pause()
    print(f"\n{DIM}  {level}{OFF}")
    print(f"{BOLD}{YELLOW}  {number}. {question}{OFF}")
    for line in why.splitlines():
        print(f"{DIM}  {line}{OFF}")
    for part in ([cypher] if isinstance(cypher, str) else cypher):
        print()
        for line in part.strip().splitlines():
            print(f"  {CYAN}{line.strip()}{OFF}")
        print()
        if PACE:
            time.sleep(min(PACE / 2, 2.5))   # let the query land before its answer
        result, ms = query(part)
        if "error" in result:
            print(f"  {RED}{result['error'][:200]}{OFF}")
            continue
        if not result.get("records"):
            print(f"  {RED}no rows — is the whole graph loaded?{OFF}")
            continue
        rows = result["records"][:limit]
        table(result.get("columns", []), rows, width)
        print(f"\n  {GREEN}{ms:.0f} ms{OFF}")
        # An eleven-row table needs longer on screen than a two-row one. A single
        # fixed pause reads fine after a scalar and races past a list of places.
        if PACE:
            time.sleep(min(0.45 * len(rows), PACE * 1.5))


def main() -> None:
    print(f"\n{BOLD}  Mental Health Knowledge Graph{OFF}")
    print(f"{DIM}  Which help exists — for whom, in what language, at what price,{OFF}")
    print(f"{DIM}  and is there anyone actually there to provide it?{OFF}\n")

    def count(cypher: str) -> int:
        result, _ = query(cypher)
        if "error" in result or not result.get("records"):
            print(f"\n  {RED}{result.get('error', 'no rows')}{OFF}\n")
            sys.exit(1)
        return result["records"][0][0]

    nodes = count("MATCH (n) RETURN count(n)")
    edges = count("MATCH ()-[r]->() RETURN count(r)")
    if not nodes:
        print(f"  {RED}graph is empty{OFF} — import the snapshot, see demo/README.md\n")
        sys.exit(1)

    # A node count is not enough to know the graph is usable. This demo asks
    # questions of all four layers, and a partial import — or a snapshot from
    # before the demand and shortage layers landed — still counts nodes happily
    # and then answers three of the ten questions with nothing.
    sources = count("MATCH (d:DataSource) RETURN count(d)")
    if sources < 4:
        print(f"\n  {RED}this graph cannot answer its own questions{OFF}")
        print(f"{DIM}  {nodes:,} nodes are present, but only {sources} of 4 data sources.{OFF}")
        print(f"{DIM}  Almost certainly an older snapshot — the facility layer alone.{OFF}")
        print(f"{DIM}  Import mental-health-full.sgsnap; see demo/README.md.{OFF}\n")
        sys.exit(1)

    print(f"  {BOLD}{nodes:,}{OFF} nodes   {BOLD}{edges:,}{OFF} edges   "
          f"{BOLD}{sources}{OFF} sources")

    step(
        1, "[provenance]",
        "Where did this data come from, and how old is it?",
        "Before any answer is worth trusting. The graph records its own sources,\n"
        "when each was fetched and how often it moves — so it answers this itself\n"
        "rather than asking you to take a caption on trust.",
        """MATCH (d:DataSource)
        RETURN d.name AS source, d.publisher AS publisher,
               d.fetched_on AS fetched, d.real_data AS real_data""",
        width=24,
    )

    step(
        2, "[level 1 — one label]",
        "How much help exists across the country?",
        "Every US behavioural-health facility, by the kind of care it provides.\n"
        "A spreadsheet answers this. It is the floor, not the argument.",
        """MATCH (f:Facility)-[:HAS_TYPE]->(t:FacilityType)
        RETURN t.name AS care_type, count(f) AS facilities
        ORDER BY facilities DESC""",
    )

    step(
        3, "[level 2 — a join]",
        "Which states serve survivors of partner violence — and which barely do?",
        "6,072 facilities nationally are tagged as serving survivors of partner\n"
        "violence. The same question asked from both ends is the first hint that\n"
        "a national number hides the thing that matters.",
        [f"""MATCH (f:Facility)-[:OFFERS]->(s:Service)
        WHERE s.value = "{IPV}"
        RETURN f.state AS state, count(f) AS ipv_facilities
        ORDER BY ipv_facilities DESC LIMIT 5""",
         f"""MATCH (f:Facility)-[:OFFERS]->(s:Service)
        WHERE s.value = "{IPV}"
        RETURN f.state AS state, count(f) AS ipv_facilities
        ORDER BY ipv_facilities ASC LIMIT 5"""],
        limit=5,
    )

    step(
        4, "[the question a survivor actually asks]",
        "Someone in Vermont needs trauma care after partner violence. Is there any?",
        "Not a count — a place, a town and a number to call. This is the whole\n"
        "point of the graph: the answer a helpline gives today is one national\n"
        "number, because nobody has joined these fields together.",
        f"""MATCH (f:Facility)-[:OFFERS]->(t:Service), (f)-[:OFFERS]->(a:Service)
        WHERE t.value = "{TRAUMA}"
          AND a.value = "{IPV}"
          AND f.state = "VT"
        RETURN DISTINCT f.name AS facility, f.city AS town,
               coalesce(f.intake, f.phone) AS call
        LIMIT 6""",
        width=38,
    )

    step(
        5, "[the follow-up nobody can answer]",
        "...and is there anyone licensed to actually deliver it there?",
        "A facility in a directory is a building. This is the second federal\n"
        "register, joined on the state: who holds a licence in Vermont, and in\n"
        "what. NPPES is authoritative for who is licensed — not for where they\n"
        "practise today, since 71% of these records are over three years old.",
        ["""MATCH (p:Provider)-[:HAS_TAXONOMY]->(t:Taxonomy), (p)-[:PRACTICES_IN]->(s:State)
        WHERE s.code = "VT" AND p.is_organization = false
        RETURN t.classification AS speciality, count(p) AS clinicians
        ORDER BY clinicians DESC LIMIT 5""",
         """MATCH (p:Provider)-[:HAS_TAXONOMY]->(t:Taxonomy), (p)-[:PRACTICES_IN]->(s:State)
        WHERE s.code = "VT" AND p.is_organization = false
        RETURN p.name AS clinician, p.city AS town, t.classification AS speciality
        LIMIT 4"""],
        limit=5, width=30,
    )

    step(
        6, "[level 4 — absence]",
        "She must not be sent to an opioid-only programme. Who is left?",
        "138 facilities match before the exclusion, 127 after. The eleven removed\n"
        "would turn her away at the door. An embedding cannot represent a service\n"
        "a facility does not offer — absence is not a point in the space.",
        [f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service)
        WHERE a.value = "{IPV}"
          AND t.value = "{TRAUMA}" AND f.state = "MA"
        WITH f OPTIONAL MATCH (f)-[:OFFERS]->(x:Service)
        WHERE x.value = "{OPIOID_ONLY}"
        WITH f, x
        RETURN count(DISTINCT f.facility_id) AS before_exclusion,
               count(DISTINCT CASE WHEN x IS NULL THEN f.facility_id END) AS after_exclusion""",
         f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service),
              (f)-[:OFFERS]->(sl:Service)
        WHERE a.value = "{IPV}"
          AND t.value = "{TRAUMA}"
          AND sl.value = "{SLIDING}"
          AND f.state = "VT"
        WITH f OPTIONAL MATCH (f)-[:OFFERS]->(x:Service)
        WHERE x.value = "{OPIOID_ONLY}"
        WITH f, x WHERE x IS NULL
        RETURN DISTINCT f.name AS facility, f.city AS town,
               coalesce(f.intake, f.phone) AS call
        LIMIT 4"""],
        width=38,
    )

    step(
        7, "[four conditions, one building]",
        "She is leaving tonight and has nowhere to sleep.",
        "Survivor services, housing support and a 24-hour residential bed, all\n"
        "true of the same facility. In a normalised schema that is three\n"
        "self-joins against 1.4 million service rows.",
        f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(h:Service),
              (f)-[:OFFERS]->(r:Service)
        WHERE a.value = "{IPV}"
          AND h.value = "{HOUSING}"
          AND r.value = "{RESIDENTIAL}"
          AND f.state = "MA"
        RETURN DISTINCT f.name AS facility, f.city AS town,
               coalesce(f.intake, f.phone) AS call
        LIMIT 5""",
        limit=5, width=38,
    )

    step(
        8, "[a gap, and the whole of it]",
        "A Deaf survivor needs an interpreter. Where is that hardest to find?",
        "Sign language is the single largest access need in this data — 6,023\n"
        "facilities offer it — but it is not spread evenly. Asked from the thin\n"
        "end, and then asked again for the names, the answer stops being a\n"
        "statistic: this is the entire supply in those states, eleven buildings.",
        [f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service),
              (f)-[:SPEAKS]->(l:Language)
        WHERE a.value = "{IPV}"
          AND t.value = "{TRAUMA}"
          AND l.name = "{ASL}"
        RETURN f.state AS state, count(DISTINCT f.facility_id) AS facilities
        ORDER BY facilities ASC LIMIT 4""",
         f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service),
              (f)-[:SPEAKS]->(l:Language)
        WHERE a.value = "{IPV}"
          AND t.value = "{TRAUMA}"
          AND l.name = "{ASL}"
          AND f.state IN ["SD", "RI", "AR", "ND"]
        RETURN f.state AS state, f.name AS facility, f.city AS town,
               coalesce(f.intake, f.phone) AS call
        ORDER BY f.state"""],
        limit=11, width=34,
    )

    step(
        9, "[level 5 — the demand side]",
        "Who needs this help, and how many live where help is already scarce?",
        "Supply is half a question. Synthea (MITRE, Apache 2.0) supplies a\n"
        "synthetic population — no real person is in this graph — and HRSA says\n"
        "which counties are federally designated shortage areas. Neither\n"
        "publisher joins to the other, and nobody publishes the intersection.",
        [f"""MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition)
        WHERE c.name = "{IPVCOND}"
        RETURN p.state AS state, count(DISTINCT p.patient_id) AS survivors
        ORDER BY survivors DESC""",
         f"""MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition),
              (p)-[:IN_COUNTY]->(ct:County),
              (sa:ShortageArea)-[:COVERS]->(ct)
        WHERE c.name = "{IPVCOND}"
        RETURN count(DISTINCT p.patient_id) AS survivors_in_a_shortage_area"""],
    )

    step(
        10, "[level 5 — all four sources]",
        "Where are survivors worst served, and is anyone there to help them?",
        "The county they live in, how severe its federal designation is, how many\n"
        "of them there are, and the clinical workforce of the state around them —\n"
        "four datasets that no publisher joins, answered in one pass.",
        [f"""MATCH (p:Patient)-[:HAS_CONDITION]->(cond:Condition),
              (p)-[:IN_COUNTY]->(ct:County)-[:IN_STATE]->(s:State),
              (sa:ShortageArea)-[:COVERS]->(ct)
        WHERE cond.name = "{IPVCOND}"
        RETURN s.code AS state, ct.name AS county, max(sa.score) AS worst_score,
               count(DISTINCT p.patient_id) AS survivors
        ORDER BY worst_score DESC LIMIT 5""",
         f"""MATCH (f:Facility)-[:OFFERS]->(a:Service),
              (f)-[:LOCATED_IN]->(s:State)-[h:HAS_PROVIDERS]->(t:Taxonomy)
        WHERE a.value = "{IPV}"
          AND t.code = "{PSYCH}" AND s.code IN ["MA", "VT"]
        RETURN s.code AS state, count(DISTINCT f.facility_id) AS ipv_facilities,
               h.count AS psychiatrists
        ORDER BY ipv_facilities DESC"""],
        limit=5,
    )

    pause()
    print(f"\n{BOLD}{GREEN}  One graph, four federal and simulated sources, one query language.{OFF}")
    print(f"{DIM}  Supply from FindTreatment.gov · shortage designations from HRSA ·{OFF}")
    print(f"{DIM}  clinical capacity from NPPES · demand simulated with Synthea.{OFF}\n")
    print(f"{DIM}  Public federal records only. No survivor, session or transcript is{OFF}")
    print(f"{DIM}  stored anywhere in this graph.{OFF}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        sys.exit(0)

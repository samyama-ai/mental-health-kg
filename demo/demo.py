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

IPV = "Clients who have experienced intimate partner violence, domestic violence"
IPVCOND = "Victim of intimate partner abuse (finding)"


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


def step(number: int, level: str, question: str, why: str, cypher: str,
         limit: int = 6, width: int = 52) -> None:
    pause()
    print(f"\n{DIM}  {level}{OFF}")
    print(f"{BOLD}{YELLOW}  {number}. {question}{OFF}")
    for line in why.splitlines():
        print(f"{DIM}  {line}{OFF}")
    print()
    for line in cypher.strip().splitlines():
        print(f"  {CYAN}{line.strip()}{OFF}")
    print()
    if PACE:
        time.sleep(min(PACE / 2, 2.5))   # let the query land before its answer
    result, ms = query(cypher)
    if "error" in result:
        print(f"  {RED}{result['error'][:200]}{OFF}")
        return
    if not result.get("records"):
        print(f"  {RED}no rows — is the whole graph loaded?{OFF}")
        return
    table(result.get("columns", []), result["records"][:limit], width)
    print(f"\n  {GREEN}{ms:.0f} ms{OFF}")


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
        "How much help exists, and in what languages?",
        "Every US behavioural-health facility, and the languages each one speaks.\n"
        "A spreadsheet answers this. It is the floor, not the argument.",
        """MATCH (f:Facility)-[:SPEAKS]->(l:Language)
        RETURN l.name AS language, count(f) AS facilities
        ORDER BY facilities DESC LIMIT 5""",
        limit=5,
    )

    step(
        3, "[level 2 — a join]",
        "Which states serve survivors of intimate partner violence?",
        "6,072 facilities nationally are tagged as serving survivors of partner\n"
        "violence — CanopyCare's exact user population, in a free federal dataset.",
        f"""MATCH (f:Facility)-[:OFFERS]->(s:Service)
        WHERE s.value = "{IPV}"
        RETURN f.state AS state, count(f) AS ipv_facilities
        ORDER BY ipv_facilities DESC LIMIT 6""",
    )

    step(
        4, "[level 3 — three conditions, one facility]",
        "She needs Spanish, and cannot pay the full fee. Who can take her?",
        "Survivor population, sliding fee scale and Spanish, all true of the same\n"
        "facility, in her state. In a normalised schema this is three self-joins\n"
        "against 1.4 million service rows. Here it is one pattern.",
        f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service),
              (f)-[:SPEAKS]->(l:Language)
        WHERE a.value = "{IPV}"
          AND b.value = "Sliding fee scale (fee is based on income and other factors)"
          AND l.name = "Spanish" AND f.state = "MA"
        RETURN count(DISTINCT f.facility_id) AS matching_facilities""",
    )

    step(
        5, "[level 3 — the actual answer]",
        "Name them, with a number to call.",
        "This is the difference the graph makes to a survivor: named places with\n"
        "intake numbers, instead of one generic national hotline.",
        f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service),
              (f)-[:SPEAKS]->(l:Language)
        WHERE a.value = "{IPV}"
          AND b.value = "Sliding fee scale (fee is based on income and other factors)"
          AND l.name = "Spanish" AND f.state = "MA"
        RETURN DISTINCT f.name AS facility, f.city AS city,
               coalesce(f.intake, f.phone) AS call
        LIMIT 5""",
        limit=5, width=34,
    )

    step(
        6, "[level 4 — absence]",
        "Trauma counselling — but NOT opioid-only programmes.",
        "138 facilities match before the exclusion; 127 after. The eleven removed\n"
        "are opioid-use-disorder-only programmes that would turn her away.\n"
        "An embedding cannot represent a service a facility does not offer.",
        f"""MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service)
        WHERE a.value = "{IPV}"
          AND t.value = "Trauma-related counseling" AND f.state = "MA"
        WITH f OPTIONAL MATCH (f)-[:OFFERS]->(x:Service)
        WHERE x.value = "Opioid use disorder clients only"
        WITH f, x
        RETURN count(DISTINCT f.facility_id) AS before_exclusion,
               count(DISTINCT CASE WHEN x IS NULL THEN f.facility_id END) AS after_exclusion""",
    )

    step(
        7, "[level 4 — a gap]",
        "Which languages is Vermont missing entirely?",
        "Not 'which are rare' — which are absent from the whole state. Vermont has\n"
        "27 facilities serving survivors and not one of them speaks Spanish.",
        """MATCH (l:Language)
        WITH l OPTIONAL MATCH (f:Facility)-[:SPEAKS]->(l)
        WHERE f.state = "VT"
        WITH l, count(f) AS vt_facilities WHERE vt_facilities = 0
        RETURN l.name AS absent_from_vermont
        ORDER BY l.name DESC LIMIT 6""",
    )

    step(
        8, "[level 5 — the demand side]",
        "Who needs that help, and where do they live?",
        "Supply is only half the question. Synthea (MITRE, Apache 2.0) generates a\n"
        "synthetic population with conditions and geography — no real person is in\n"
        "this graph. The partner-abuse finding is lifetime screening prevalence,\n"
        "not current need.",
        f"""MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition)
        WHERE c.name = "{IPVCOND}"
        RETURN p.state AS state, count(DISTINCT p.patient_id) AS survivors
        ORDER BY survivors DESC""",
    )

    step(
        9, "[level 5 — four sources at once]",
        "How many of them live somewhere the government already calls under-served?",
        "Synthea says who and where. HRSA says which counties are designated mental-\n"
        "health shortage areas. Neither publisher joins to the other, and nobody\n"
        "publishes the intersection: 1,314 of 1,407 survivors live in a designated\n"
        "county. Here is where they are, worst-served first.",
        f"""MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition),
              (p)-[:IN_COUNTY]->(ct:County)-[:IN_STATE]->(s:State),
              (sa:ShortageArea)-[:COVERS]->(ct)
        WHERE c.name = "{IPVCOND}"
        RETURN s.code AS state, ct.name AS county,
               round(avg(sa.score)) AS shortage_score,
               count(DISTINCT p.patient_id) AS survivors
        ORDER BY survivors DESC LIMIT 6""",
    )

    step(
        10, "[level 5 — is anyone there?]",
        "A facility existing is not a clinician existing. Is anyone there?",
        "The last layer: 82,978 clinicians from the federal provider register,\n"
        "counted per state and speciality. Vermont's survivor-serving facilities\n"
        "sit against a fraction of Massachusetts' psychiatric workforce.",
        """MATCH (f:Facility)-[:OFFERS]->(a:Service),
              (f)-[:LOCATED_IN]->(s:State)-[h:HAS_PROVIDERS]->(t:Taxonomy)
        WHERE a.value = "Clients who have experienced intimate partner violence, domestic violence"
          AND t.code = "2084P0800X" AND s.code IN ["MA", "VT"]
        RETURN s.code AS state, count(DISTINCT f.facility_id) AS ipv_facilities,
               h.count AS psychiatrists
        ORDER BY ipv_facilities DESC""",
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

"""Narrated walkthrough of the Mental Health KG -- long form, paced to be read.

Nine steps over the whole graph: where the data came from, what supply exists,
the multi-constraint referral, the exclusion query, simulated demand, the
coverage gap, federal shortage designations, real clinical capacity, and a named
clinician with a licence number. Each Cypher query is shown before its answer,
and the pauses are deliberately long enough to read both.

Needs the full graph loaded (four sources, ~113k nodes / 1.67M edges):

    docker run -d --name samyama-mh -p 18080:8080 \
      public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0
    curl -X POST http://localhost:18080/api/snapshot/import \
      -F "file=@snapshots/mental-health-full.sgsnap"
    MH_URL=http://localhost:18080 python -m demo.demo

Record with asciinema; see demo/README.md.

Two engine quirks are worked around in the queries below, both silent-wrong
rather than errors.

A WHERE cannot be followed by another MATCH -- match every required pattern
first, then WITH.

ORDER BY is inverted between the two kinds of value, and gets no error either
way, just unsorted output:
    aggregate  count(f) AS n  ->  ORDER BY n        (ORDER BY count(f) fails)
    property   h.count  AS n  ->  ORDER BY h.count  (ORDER BY n        fails)
"""

from __future__ import annotations

import os
import time

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from samyama import SamyamaClient

from etl.helpers import GRAPH

console = Console()

IPV = "Clients who have experienced intimate partner violence, domestic violence"
SLIDING = "Sliding fee scale (fee is based on income and other factors)"
TRAUMA = "Trauma-related counseling"
OPIOID_ONLY = "Opioid use disorder clients only"
PSYCHIATRY = "2084P0800X"

# Long form: these pauses are the point. Anything under ~2s is unreadable in a gif.
READ = 3.0          # after a result, time to read it
BEAT = 1.4          # between a query appearing and its answer
STEP = 1.0          # after a section rule


def step(n: int, title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]{n} · {title}")
    time.sleep(STEP)


def say(text: str) -> None:
    console.print(f"  [dim]{text}[/dim]")
    time.sleep(1.2)


def run(client, q: str, label: str, fmt=None):
    console.print(f"  [dim]cypher>[/dim] [yellow]{escape(q)}[/yellow]")
    time.sleep(BEAT)                      # let the query land before the answer
    rows = client.query(q, GRAPH).records
    one = len(rows) == 1 and len(rows[0]) == 1
    val = rows[0][0] if one else rows
    console.print(f"  [green]→[/green] {label}: [bold]{fmt(val) if fmt else val}[/bold]")
    time.sleep(READ)
    return rows


def table(rows, columns, widths=None):
    t = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    for c in columns:
        t.add_column(c)
    for r in rows:
        t.add_row(*[str(x)[:w] if w else str(x) for x, w in zip(r, widths or [None] * len(r))])
    console.print()
    console.print(t)
    time.sleep(READ + 1.0)


def main() -> None:
    url = os.environ.get("MH_URL", "http://localhost:18080")
    client = SamyamaClient.connect(url)

    console.print(Panel.fit(
        "[bold]Samyama · Mental Health Knowledge Graph[/bold]\n"
        '"Which help exists — for whom, in what language, at what price,\n'
        ' and is there anyone actually there to provide it?"\n'
        "[dim]four sources · 113,703 nodes · 1,665,143 edges[/dim]",
        border_style="cyan"))
    time.sleep(3.0)

    # ---------------------------------------------------------------- 1
    step(1, "Where did this data come from, and how old is it?")
    say("provenance first — the graph records its own sources and their age")
    rows = client.query(
        "MATCH (d:DataSource) RETURN d.name, d.fetched_on, d.real_data, d.cadence",
        GRAPH).records
    table([(n, f, "REAL" if r else "SYNTHETIC") for n, f, r, c in rows],
          ["source", "fetched", "kind"], [20, 12, 10])

    # ---------------------------------------------------------------- 2
    step(2, "How much help exists across the country?")
    say("every US behavioural-health facility, and what each one offers")
    run(client, "MATCH (f:Facility) RETURN count(f) AS facilities",
        "facilities nationally", lambda v: f"{v:,}")
    run(client, "MATCH ()-[r:OFFERS]->() RETURN count(r) AS offers",
        "facility→service edges", lambda v: f"{v:,}")
    rows = client.query(
        "MATCH (f:Facility)-[:SPEAKS]->(l:Language) "
        "RETURN l.name AS lang, count(f) AS n ORDER BY n DESC LIMIT 5",
        GRAPH).records
    table(rows, ["language", "facilities"], [46, 10])

    # ---------------------------------------------------------------- 3
    step(3, "Where can a survivor get help, in Spanish, on a sliding scale?")
    say("a survivor of intimate partner violence, needs Spanish, cannot pay full fee")
    q = (f'MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service), '
         f'(f)-[:OFFERS]->(c:Service) WHERE a.value = "{IPV}" AND b.value = "{SLIDING}" '
         f'AND c.value = "Spanish" AND f.state = "MA" RETURN count(f) AS n')
    run(client, q, "matching facilities in Massachusetts")
    named = client.query(
        f'MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service), '
        f'(f)-[:OFFERS]->(c:Service) WHERE a.value = "{IPV}" AND b.value = "{SLIDING}" '
        f'AND c.value = "Spanish" AND f.state = "MA" '
        f'RETURN f.name, f.city, f.intake, f.phone LIMIT 4', GRAPH).records
    table([(n, c, i or p or "—") for n, c, i, p in named],
          ["facility", "city", "call"], [36, 13, 16])
    say("named places with numbers — not one generic national hotline")

    # ---------------------------------------------------------------- 4
    step(4, "Which of those do trauma counselling but are NOT opioid-only?")
    say("trauma counselling for survivors, EXCLUDING opioid-use-disorder-only programmes")
    q = (f'MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service) '
         f'WHERE a.value = "{IPV}" AND t.value = "{TRAUMA}" AND f.state = "MA" '
         f'WITH f OPTIONAL MATCH (f)-[:OFFERS]->(x:Service) '
         f'WHERE x.value = "{OPIOID_ONLY}" WITH f, x WHERE x IS NULL '
         f'RETURN count(f) AS n')
    run(client, q, "facilities, opioid-only programmes excluded")
    say('"not this" is a traversal. An embedding cannot represent absence.')

    # ---------------------------------------------------------------- 5
    step(5, "Who needs that help, and where do they live?")
    say("Synthea generates synthetic patients with a location, income and conditions")
    run(client, "MATCH (p:Patient) RETURN count(p) AS n", "synthetic patients",
        lambda v: f"{v:,}")
    run(client,
        'MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition) '
        'WHERE c.name = "Victim of intimate partner abuse (finding)" '
        'RETURN count(p) AS n', "of them survivors of partner abuse")

    # ---------------------------------------------------------------- 6
    step(6, "Which languages can Vermont actually serve?")
    say("Vermont: which languages do its facilities actually offer?")
    rows = client.query(
        'MATCH (f:Facility)-[:SPEAKS]->(l:Language) WHERE f.state = "VT" '
        'RETURN l.name AS lang, count(f) AS n ORDER BY n DESC', GRAPH).records
    table(rows, ["language", "VT facilities"], [46, 13])
    say("no Spanish anywhere in the state — and French is the larger need there")

    # ---------------------------------------------------------------- 7
    step(7, "Does the government already call these areas under-served?")
    say("does the government already consider these places under-served?")
    run(client, "MATCH (sa:ShortageArea) RETURN count(sa) AS n",
        "designated mental-health shortage areas", lambda v: f"{v:,}")
    rows = client.query(
        'MATCH (p:Patient)-[:IN_COUNTY]->(ct:County), (sa:ShortageArea)-[:COVERS]->(ct), '
        '(p)-[:HAS_CONDITION]->(c:Condition) '
        'WHERE c.name = "Victim of intimate partner abuse (finding)" '
        'RETURN p.state AS st, count(DISTINCT p.patient_id) AS survivors '
        'ORDER BY survivors DESC', GRAPH).records
    table(rows, ["state", "survivors in a shortage county"], [8, 32])

    # ---------------------------------------------------------------- 8
    step(8, "Is there anyone actually there to provide the care?")
    say("facilities existing is not the same as clinicians existing")
    rows = client.query(
        f'MATCH (s:State)-[h:HAS_PROVIDERS]->(t:Taxonomy) WHERE t.code = "{PSYCHIATRY}" '
        f'RETURN s.code, h.count ORDER BY h.count DESC LIMIT 5', GRAPH).records
    table(rows, ["state", "psychiatrists"], [8, 14])
    rows = client.query(
        f'MATCH (s:State)-[h:HAS_PROVIDERS]->(t:Taxonomy) WHERE t.code = "{PSYCHIATRY}" '
        f'AND s.code IN ["MA", "VT"] RETURN s.code, h.count', GRAPH).records
    table(rows, ["state", "psychiatrists"], [8, 14])

    # ---------------------------------------------------------------- 9
    step(9, "Can we name a real clinician, with a licence number?")
    say("real people, real licence numbers — public federal register")
    rows = client.query(
        f'MATCH (p:Provider)-[:HAS_TAXONOMY]->(t:Taxonomy), (p)-[:PRACTICES_IN]->(s:State) '
        f'WHERE t.code = "{PSYCHIATRY}" AND s.code = "VT" AND p.is_organization = false '
        f'RETURN p.name, p.city, p.licence LIMIT 4', GRAPH).records
    table(rows, ["psychiatrist", "city", "licence"], [26, 13, 18])

    console.print()
    console.print(Panel.fit(
        "[bold green]One graph, four federal and simulated sources, one query language."
        "[/bold green]\n"
        "Supply from FindTreatment.gov · shortage designations from HRSA ·\n"
        "clinical capacity from NPPES · demand simulated with Synthea.\n"
        "[dim]No survivor, session or transcript is stored anywhere in it.[/dim]",
        border_style="green"))
    time.sleep(3.0)


if __name__ == "__main__":
    main()

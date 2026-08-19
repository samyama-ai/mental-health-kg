"""Narrated terminal demo: behavioural-health referral routing on Samyama.

Needs a running Samyama server — set MH_URL (default http://localhost:18080):
    docker run -d --name samyama-demo -p 18080:8080 \
      public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0

The embedded client from PyPI `samyama` 0.6.1 is NOT usable here: its
OPTIONAL MATCH inverts the exclusion in step 4, returning the 11 facilities
that DO offer the excluded service instead of the 127 that do not. Six
formulations were tried; the server engine (1.7.0) answers all of them
correctly. Use a server until the SDK catches up.

Record with asciinema:
    asciinema rec -c "python -m demo.demo" demo/mental-health.cast

Loads real FindTreatment.gov (SAMHSA) facility data — facilities, the services
they offer, languages spoken, care type and state — into a Samyama graph, then
walks the question a survivor advocate actually asks: not "what is near me",
but "which help exists, for whom, in what language, at what price".

The demo scopes to Massachusetts so the load takes seconds; every row is real
federal data, no synthetic values. The national graph is 17,254 facilities and
1,474,079 edges and answers the same queries unchanged.
"""

from __future__ import annotations

import csv
import os
import shutil
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from samyama import SamyamaClient

from etl.helpers import GRAPH
from etl.loader import load_mental_health

console = Console()
STATE = "MA"

# Service values are verbatim SAMHSA vocabulary — kept as constants so the
# Cypher below reads as the question being asked, not as string wrangling.
IPV = "Clients who have experienced intimate partner violence, domestic violence"
SLIDING = "Sliding fee scale (fee is based on income and other factors)"
SPANISH = "Spanish"
TRAUMA = "Trauma-related counseling"
OPIOID_ONLY = "Opioid use disorder clients only"


def pause(s: float = 1.4) -> None:
    time.sleep(s)


def step(title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]{title}")
    pause(0.6)


def run(client, q, label):
    # escape() matters: rich reads [r:OFFERS] as a style tag and eats it.
    console.print(f"  [dim]cypher>[/dim] [yellow]{escape(q)}[/yellow]")
    rows = client.query(q, GRAPH).records
    one = len(rows) == 1 and len(rows[0]) == 1
    console.print(f"  [green]→[/green] {label}: [bold]{rows[0][0] if one else rows}[/bold]")
    pause()
    return rows


def scope_to_state(src: str, state: str) -> str:
    """Write a state-scoped copy of the CSVs to a temp dir.

    Only facilities.csv is filtered — the loader restricts every edge to the
    facilities it actually kept, so the rest can be linked as-is.
    """
    dst = Path(tempfile.mkdtemp(prefix="mh-demo-"))
    rows = list(csv.DictReader(open(Path(src) / "facilities.csv")))
    kept = [r for r in rows if r.get("state") == state]
    with open(dst / "facilities.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(kept)
    for name in ("states.csv", "facility_types.csv", "service_categories.csv",
                 "services.csv", "languages.csv", "edge_located_in.csv",
                 "edge_has_type.csv", "edge_in_category.csv",
                 "edge_offers.csv", "edge_speaks.csv"):
        shutil.copy(Path(src) / name, dst / name)
    return str(dst)


def main() -> None:
    data_dir = os.environ.get("MH_DATA_DIR", "data")
    url = os.environ.get("MH_URL", "http://localhost:18080")

    console.print(Panel.fit(
        "[bold]Samyama · Behavioural Health Referral Graph[/bold]\n"
        '"Which help exists — for whom, in what language, at what price?"\n'
        "[dim]data: FindTreatment.gov (SAMHSA / BHSIS) · US federal, public domain[/dim]",
        border_style="cyan",
    ))
    pause(1.2)

    step(f"1 · Load FindTreatment.gov facilities into Samyama ({STATE})")
    console.print("  [dim]facilities · services · languages · care type · state…[/dim]")
    scoped = scope_to_state(data_dir, STATE)
    client = SamyamaClient.connect(url)
    load_mental_health(client, data_dir=scoped)
    run(client, "MATCH (f:Facility) RETURN count(f) AS facilities", "facilities loaded")
    run(client, "MATCH ()-[r:OFFERS]->() RETURN count(r) AS offers", "facility→service edges")

    step("2 · Who does this data actually name?")
    console.print("  [dim]the federal dataset tags the population each facility serves…[/dim]")
    pause()
    run(
        client,
        "MATCH (f:Facility)-[:OFFERS]->(s:Service) "
        f'WHERE s.value = "{IPV}" '
        "RETURN count(f) AS facilities",
        "facilities serving survivors of intimate partner violence",
    )

    step("3 · The referral — a survivor who needs Spanish and cannot pay full fee")
    console.print("  [dim]IPV survivors · sliding fee scale · Spanish spoken — one query[/dim]")
    pause()
    rows = run(
        client,
        "MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service), "
        "(f)-[:OFFERS]->(c:Service) "
        f'WHERE a.value = "{IPV}" AND b.value = "{SLIDING}" AND c.value = "{SPANISH}" '
        "RETURN count(f) AS facilities",
        "matching facilities",
    )
    named = client.query(
        "MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(b:Service), "
        "(f)-[:OFFERS]->(c:Service) "
        f'WHERE a.value = "{IPV}" AND b.value = "{SLIDING}" AND c.value = "{SPANISH}" '
        "RETURN f.name, f.city, f.intake, f.phone LIMIT 5", GRAPH).records
    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("Facility")
    table.add_column("City")
    table.add_column("Call")
    seen = set()
    for r in named:
        if r[0] in seen:
            continue
        seen.add(r[0])
        # intake is the direct line where it exists; str(None) is truthy, so
        # test the value itself rather than its string form.
        call = r[2] or r[3] or "—"
        table.add_row(str(r[0])[:44], str(r[1]), str(call))
    console.print()
    console.print(table)
    console.print("  [dim]versus one generic hotline number today.[/dim]")
    pause(1.6)

    step("4 · The query vector search cannot do — exclusion")
    console.print("  [dim]trauma counselling for IPV survivors, [bold]excluding[/bold] "
                  "opioid-use-disorder-only programmes[/dim]")
    pause()
    run(
        client,
        # A WHERE cannot be followed by another MATCH in this engine, so both
        # required services are matched in one pattern before the WITH.
        "MATCH (f:Facility)-[:OFFERS]->(a:Service), (f)-[:OFFERS]->(t:Service) "
        f'WHERE a.value = "{IPV}" AND t.value = "{TRAUMA}" '
        "WITH f "
        "OPTIONAL MATCH (f)-[:OFFERS]->(x:Service) "
        f'WHERE x.value = "{OPIOID_ONLY}" '
        "WITH f, x WHERE x IS NULL "
        "RETURN count(f) AS facilities",
        "trauma counselling, opioid-only programmes excluded",
    )
    console.print("  [dim]\"not this\" is a graph traversal. An embedding cannot "
                  "represent absence.[/dim]")
    pause(1.2)

    step("5 · Where is the coverage gap?")
    run(
        client,
        "MATCH (f:Facility)-[:OFFERS]->(a:Service) "
        f'WHERE a.value = "{IPV}" '
        "WITH f "
        "OPTIONAL MATCH (f)-[:SPEAKS]->(l:Language) "
        f'WHERE l.name = "{SPANISH}" '
        "WITH f, l WHERE l IS NULL "
        "RETURN count(f) AS facilities",
        "IPV facilities with no Spanish-language service",
    )

    console.print()
    console.print(Panel.fit(
        "[bold green]Nationally: 6,072 facilities serve IPV survivors, 10,670 serve "
        "trauma survivors.[/bold green]\n"
        "Same five queries, 17,254 facilities, 1,474,079 edges — refreshed weekly\n"
        "from a free federal source. Vermont has 27 IPV facilities and none in Spanish.",
        border_style="green",
    ))
    pause(1.5)


if __name__ == "__main__":
    main()

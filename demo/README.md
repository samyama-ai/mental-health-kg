# Demo

A narrated walkthrough of the whole graph — **ten questions, ~2 minutes**, that
climb from one a spreadsheet could answer to one that needs four separately
published federal datasets joined at once. Every Cypher query is shown before its
answer, with the latency it actually took.

| # | Kind | Question |
|---|---|---|
| 1 | provenance | Where did this data come from, and how old is it? |
| 2 | one label | How much help exists across the country? |
| 3 | a join | Which states serve survivors of partner violence — and which barely do? |
| 4 | **the real question** | Someone in Vermont needs trauma care after partner violence. Is there any? |
| 5 | **the follow-up** | …and is there anyone licensed to actually deliver it there? |
| 6 | absence | She must not be sent to an opioid-only programme. Who is left? |
| 7 | four conditions | She is leaving tonight and has nowhere to sleep. |
| 8 | a gap | A Deaf survivor needs an interpreter. Where is that hardest to find? |
| 9 | demand | Who needs this help, and how many live where help is already scarce? |
| 10 | all four sources | Where are survivors worst served, and is anyone there to help them? |

Steps 4 and 5 are the pair worth watching: a directory can answer *where is
there a building*, and a licence register can answer *who is licensed here*.
Neither can answer both, because nobody joins them. Several steps run more than
one query — a real question rarely resolves in one, and showing two is more
honest than a join that cross-products two unrelated tables for the sake of a
single result.

It opens on provenance — which datasets these answers rest on and how old each
one is — because that is the first question worth asking of any graph.

**No dependencies beyond the standard library.** The demo talks to the engine
over HTTP rather than through the `samyama` SDK. That is deliberate: PyPI
`samyama` 0.6.1 silently inverts `OPTIONAL MATCH … WHERE x IS NULL`, the
construct step 6 turns on, and would report 11 facilities where the engine
returns 127. See *Engine defects encountered* in
[`../docs/schema.md`](../docs/schema.md).

## Running it

The demo **queries** a graph; it does not build one. You need a server with all
four layers loaded — which means having the snapshot first.

**It is not in this repo.** `mental-health-full.sgsnap` is ~15 MB; snapshots ship
as release assets on the engine repo, in the shared `kg-snapshots-vN` train:

```
https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-vN/mental-health-full.sgsnap
```

**Not yet published** — it is queued for the next `kg-snapshots` cut. Until then
build it yourself (*Building it from scratch*, below). Everything in the next
block assumes you have the file.

```bash
docker rm -f samyama-mh 2>/dev/null                                 # always fresh
docker run -d --name samyama-mh -p 18080:8080 \
  public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0
until curl -sf http://localhost:18080/api/status >/dev/null; do sleep 1; done

curl -X POST http://localhost:18080/api/snapshot/import \
  -F "file=@mental-health-full.sgsnap"                              # ~2.5 s

curl -s http://localhost:18080/api/status      # expect 113,710 nodes
MH_URL=http://localhost:18080 python -m demo.demo
```

Press **Enter** between steps, so the pacing is yours while narrating. Piped or
redirected (`< /dev/null`, CI), it runs start to finish without pausing.

### Building it from scratch

Five loaders, in this order. The middle three need files this repo does not
carry; the source table in [`../README.md`](../README.md#schema) says where each
one comes from.

```bash
python -m etl.download_data                                     # FindTreatment.gov -> data/ (~6 min)
python -m etl.loader --data-dir data --url http://localhost:18080

python -m etl.synthea_loader --data-dir <synthea>/output/csv --cohort MA \
  --url http://localhost:18080
python -m etl.hpsa_loader --csv HPSA_DASHBOARD.csv --url http://localhost:18080
python -m etl.nppes_loader --zip NPPES_Data_Dissemination.zip \
  --taxonomy bh_taxonomy.json --states MA,VT --url http://localhost:18080

python -m etl.stamp_sources --url http://localhost:18080        # the :DataSource manifest

curl -X POST http://localhost:18080/api/snapshot/export -o mental-health-full.sgsnap
```

`stamp_sources` runs **last** — it writes the four `:DataSource` nodes the demo's
preflight checks for, so a graph built without it refuses to run.

**Always start from a fresh container.** The image persists between restarts
inconsistently: importing on top of a graph that already holds the same data adds
a second copy rather than replacing it. Caught early on the facility-only graph,
where a 17,678-node import came back as 35,356 — which looks like a successful
import until the counts are read.

The demo refuses to run against a graph carrying fewer than four `:DataSource`
nodes. A partial import, or a snapshot from before the demand and shortage layers
landed, still counts nodes happily and then answers three of the ten questions
with nothing — an empty answer in front of an audience is the one failure worth
guarding against.

## Re-recording

```bash
DEMO_PACE=5 asciinema rec --overwrite --cols 100 --rows 30 --idle-time-limit 9.0 \
  -c "bash -c 'MH_URL=http://localhost:18080 python3 -m demo.demo'" \
  demo/mental-health.cast
agg --font-size 16 --speed 1.0 --idle-time-limit 9.0 \
  demo/mental-health.cast demo/mental-health.gif
```

Four settings matter and are easy to get wrong.

**`DEMO_PACE` is required for an unattended recording.** asciinema allocates a
PTY, so `stdin.isatty()` is true and the demo waits for an Enter that never
comes. `DEMO_PACE=5` sleeps five seconds instead, and gives a reproducible
recording rather than one paced by whoever held the keyboard. It was 3.5 s once
and the result was unreadable — the steps now run several queries each, so more
lands on screen per step than the pause was built for.

On top of that fixed pause, `step()` dwells in proportion to how many rows came
back (`0.45 s` each, capped at `1.5 × DEMO_PACE`). An eleven-row list of
facilities needs longer than a single count, and one fixed number cannot serve
both.

**`--cols 100`, not 80.** The population filter this graph turns on is a
93-character federal string — `"Clients who have experienced intimate partner
violence, domestic violence"`. At 80 columns it wraps mid-query and the Cypher
stops being readable. Truncating it in the display would misrepresent the query
that ran, so the terminal gets wider instead.

**`--idle-time-limit` truncates pauses, including deliberate ones.** It must sit
above the longest pause in `demo.py`. With `DEMO_PACE=5` the step pause and the
row dwell fall consecutively, so the longest gap approaches 12 s; **9.0** caps it
at a still-readable 9 s rather than cutting it to nothing. An earlier recording
used 1.5 s against 1.4 s pauses and came out unreadably fast.

**`--font-size 16`, not the default 14.** At 14 the output renders small and
cramped beside the sibling repos. 16 gives 983×694 from a 100×30 terminal.

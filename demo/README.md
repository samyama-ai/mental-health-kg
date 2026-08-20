# Demo

A narrated walkthrough of the whole graph — **ten questions, ~65 seconds**, that
climb from one a spreadsheet could answer to one that needs four separately
published federal datasets joined at once. Every Cypher query is shown before its
answer, with the latency it actually took.

| # | Level | Question |
|---|---|---|
| 1 | provenance | Where did this data come from, and how old is it? |
| 2 | 1 — one label | How much help exists, and in what languages? |
| 3 | 2 — a join | Which states serve survivors of intimate partner violence? |
| 4 | 3 — three conditions | She needs Spanish, and cannot pay the full fee. Who can take her? |
| 5 | 3 — the answer | Name them, with a number to call. |
| 6 | 4 — absence | Trauma counselling — but NOT opioid-only programmes. |
| 7 | 4 — a gap | Which languages is Vermont missing entirely? |
| 8 | 5 — demand | Who needs that help, and where do they live? |
| 9 | 5 — four sources | How many live somewhere already called under-served? |
| 10 | 5 — capacity | A facility existing is not a clinician existing. Is anyone there? |

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
DEMO_PACE=4 asciinema rec --overwrite --cols 100 --rows 30 --idle-time-limit 5.0 \
  -c "bash -c 'MH_URL=http://localhost:18080 python3 -m demo.demo'" \
  demo/mental-health.cast
agg --font-size 16 --speed 1.0 --idle-time-limit 5.0 \
  demo/mental-health.cast demo/mental-health.gif
```

Four settings matter and are easy to get wrong.

**`DEMO_PACE` is required for an unattended recording.** asciinema allocates a
PTY, so `stdin.isatty()` is true and the demo waits for an Enter that never
comes. `DEMO_PACE=4` sleeps four seconds instead — long enough to read a table,
and it gives a reproducible recording rather than one paced by whoever held the
keyboard.

**`--cols 100`, not 80.** The population filter this graph turns on is a
93-character federal string — `"Clients who have experienced intimate partner
violence, domestic violence"`. At 80 columns it wraps mid-query and the Cypher
stops being readable. Truncating it in the display would misrepresent the query
that ran, so the terminal gets wider instead.

**`--idle-time-limit` truncates pauses, including deliberate ones.** It must sit
above the longest pause in `demo.py` — 4.0 s with `DEMO_PACE=4`. 5.0 leaves
headroom. An earlier recording used 1.5 s against 1.4 s pauses and came out
unreadably fast.

**`--font-size 16`, not the default 14.** At 14 the output renders small and
cramped beside the sibling repos. 16 gives 983×694 from a 100×30 terminal.

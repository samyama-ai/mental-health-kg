# Demo

Long-form narrated walkthrough of the whole graph — nine steps, ~95 seconds,
paced to be read rather than skimmed. Every Cypher query is shown before its
answer.

1. Where did this data come from, and how old is it?
2. How much help exists across the country?
3. Where can a survivor get help, in Spanish, on a sliding scale?
4. Which of those do trauma counselling but are NOT opioid-only?
5. Who needs that help, and where do they live?
6. Which languages can Vermont actually serve?
7. Does the government already call these areas under-served?
8. Is there anyone actually there to provide the care?
9. Can we name a real clinician, with a licence number?

Recorded at 80×24 to match the other KG repos.

## Running it

The demo **queries** the graph; it does not build one. You need a server with the
four layers loaded.

### If you have the snapshot

`mental-health-full.sgsnap` is ~15 MB and is **not in this repo** — snapshots ship
as release assets, never in git. Download it from the repo's Releases page, then:

```bash
docker run -d --name samyama-mh -p 18080:8080 \
  public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0

# wait for the server, then import (1.67M edges restores in ~2.5s)
until curl -sf http://localhost:18080/api/status >/dev/null; do sleep 1; done
curl -X POST http://localhost:18080/api/snapshot/import \
  -F "file=@mental-health-full.sgsnap"

# confirm before running the demo
curl -s http://localhost:18080/api/status      # expect ~113,703 nodes

MH_URL=http://localhost:18080 python -m demo.demo
```

**Always start from a fresh container.** The image persists between restarts
inconsistently: importing on top of an existing graph once silently doubled it to
35,356 nodes, which looks like a successful import until the counts are read. If
`samyama-mh` already exists, `docker rm -f samyama-mh` first.

### If you are building it from scratch

See the loaders in [`../etl/`](../etl/) and the source table in
[`../README.md`](../README.md). Roughly: `download_data` + `loader` for the
facility layer, then `synthea_loader`, `hpsa_loader`, `nppes_loader`,
`stamp_sources`. Export the snapshot at the end with:

```bash
curl -X POST http://localhost:18080/api/snapshot/export -o mental-health-full.sgsnap
```

The demo needs a **server**, not the embedded client: PyPI `samyama` 0.6.1
inverts the `OPTIONAL MATCH` exclusion in step 4, returning the facilities that
*do* offer the excluded service. See *Engine defects encountered* in
[`../docs/schema.md`](../docs/schema.md).

## Re-recording

```bash
asciinema rec --overwrite --cols 80 --rows 24 --idle-time-limit 5.0 \
  -c "bash -c 'MH_URL=http://localhost:18080 python -m demo.demo'" \
  demo/mental-health.cast
agg --font-size 16 --speed 1.0 --idle-time-limit 5.0 \
  demo/mental-health.cast demo/mental-health.gif
```

Three settings matter and are easy to get wrong.

**`--idle-time-limit` truncates pauses**, including deliberate ones. It must sit
**above the longest pause in `demo.py`**, which is `READ + 1.0` = **4.0 s** after
every table — not `READ` alone. An earlier recording used 1.5 s against 1.4 s
pauses and came out unreadably fast. 5.0 leaves headroom.

**`--speed` above 1.0 compresses everything again.** Leave it at 1.0 for long
form; 1.4 was the other half of why the first recording was too quick.

**`--font-size 16`, not the default 14.** The sibling repos render 787×560 from
an 80×24 terminal; at 14 ours came out 691×490, which looks small and cramped
beside them. 16 gives 790×560.

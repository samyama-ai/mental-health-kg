# Demo

Long-form narrated walkthrough of the whole graph — nine steps, ~92 seconds,
paced to be read rather than skimmed. Every Cypher query is shown before its
answer.

1. Where the data comes from (the `:DataSource` manifest, with fetch dates)
2. Supply — facilities, services, languages
3. The referral — four constraints at once, down to named places and numbers
4. The exclusion query — what vector search cannot do
5. Demand — simulated patients, so no real person is involved
6. The coverage gap — supply against demand, per language
7. Federal corroboration — HRSA shortage designations
8. Real clinical capacity — the NPI register
9. Down to a named clinician with a licence number

Recorded at 80×24 to match the other KG repos.

## Running it

Needs the full graph loaded — four sources, ~113k nodes / 1.67M edges:

```bash
docker run -d --name samyama-mh -p 18080:8080 \
  public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0

curl -X POST http://localhost:18080/api/snapshot/import \
  -F "file=@snapshots/mental-health-full.sgsnap"          # ~2.5s for 1.5M edges

MH_URL=http://localhost:18080 python -m demo.demo
```

The demo **queries** the graph; it does not load it. Earlier versions loaded a
Massachusetts subset first, which is no longer practical now that four sources
are involved — importing the snapshot is both faster and closer to how anyone
else would start.

It needs a **server**, not the embedded client: PyPI `samyama` 0.6.1 inverts the
`OPTIONAL MATCH` exclusion in step 4, returning the facilities that *do* offer
the excluded service. See *Engine defects encountered* in
[`../docs/schema.md`](../docs/schema.md).

## Re-recording

```bash
asciinema rec --overwrite --cols 80 --rows 24 --idle-time-limit 4.0 \
  -c "bash -c 'MH_URL=http://localhost:18080 python -m demo.demo'" \
  demo/mental-health.cast
agg --font-size 14 --speed 1.0 --idle-time-limit 4.0 \
  demo/mental-health.cast demo/mental-health.gif
```

Two settings matter and are easy to get wrong. `--idle-time-limit` **truncates
pauses** — the earlier recording used 1.5s against 1.4s pauses and came out
unreadably fast, so it must sit above the longest pause in `demo.py` (currently
3s). And `--speed` above 1.0 compresses everything again; leave it at 1.0 for
long form.

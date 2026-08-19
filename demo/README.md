# Demo

Narrated walkthrough of the Mental Health KG, scoped to Massachusetts (408 facilities,
37,669 edges) so it loads in seconds. Every number shown is real FindTreatment.gov data.

Five steps: load -> who the data names -> the multi-constraint referral -> the exclusion
query -> the coverage gap.

Needs a **running server** — the embedded client from PyPI `samyama` 0.6.1 inverts the
`OPTIONAL MATCH` exclusion in step 4. See *Engine defects encountered* in
[`../docs/schema.md`](../docs/schema.md).

```bash
docker run -d --name samyama-demo -p 18080:8080 \
  public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0

MH_URL=http://localhost:18080 python -m demo.demo
```

`MH_DATA_DIR` overrides the CSV location (default `data/`).

Record/regenerate:

```bash
asciinema rec --overwrite --cols 92 --rows 32 --idle-time-limit 2.0 \
  -c "bash -c 'python -m demo.demo'" demo/mental-health.cast
agg --font-size 14 --speed 1.4 demo/mental-health.cast demo/mental-health.gif
```

Record against a **fresh** container — the loader uses `CREATE`, so replaying into a
server that already holds the graph duplicates every node.

# Mental Health Knowledge Graph

**{{N}} nodes. {{M}} edges. Conditions, symptoms, treatments, medications, and risk factors from {{K}} clinical sources.**

![Mental health demo](demo/mental-health.gif)

> Part of the **Samyama** ecosystem — loaded into and queried via the graph engine at [samyama-ai/samyama-graph](https://github.com/samyama-ai/samyama-graph).
> This repo holds the loader and source-data specifics for the KG.

<a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-blue" alt="License"></a>

---

We loaded {{SOURCES}} into one graph, then asked:

> *"Which treatments are indicated for the most conditions?"*

```cypher
MATCH (t:Treatment)-[:TREATS]->(c:Condition)
RETURN t.name, count(c) AS conditions
ORDER BY conditions DESC LIMIT 5
```

**One query across every condition and treatment.** Powered by [Samyama Graph](https://github.com/samyama-ai/samyama-graph).

---

## Demo

A narrated walkthrough on a fast, real subset: load -> symptoms per condition -> treatment options -> medication interactions.

```bash
python -m demo.demo                                                     # run live
asciinema rec --overwrite --cols 92 --rows 32 --idle-time-limit 2.0 \
  -c "bash -c 'python -m demo.demo'" demo/mental-health.cast            # re-record
agg demo/mental-health.cast demo/mental-health.gif                      # convert to gif
```

---

## Schema

**Node labels** -- Condition, Symptom, Treatment, Medication, RiskFactor, Population
**Edge types** -- HAS_SYMPTOM, TREATED_BY, TREATS, PRESCRIBED_FOR, INCREASES_RISK, AFFECTS
**Data sources** -- {{SOURCES}}

See [`schema/mental_health_kg.cypher`](schema/mental_health_kg.cypher) for the full schema.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

python -m etl.download_data          # fetch source data into data/
python -m etl.loader                 # build + load the graph
python -m mcp_server.server          # expose the KG over MCP
pytest                               # run tests
```

## Structure
```
etl/          # downloaders + graph loader
schema/       # cypher schema / ontology
mcp_server/   # MCP server exposing the KG
demo/         # narrated demo (cast + gif)
benchmarks/   # benchmark queries
docs/         # design + source notes
tests/        # pytest
pyproject.toml
```

---
_Scaffolded from the KG template pattern. Replace the `{{...}}` placeholders and the schema/loaders for the mental-health sources._

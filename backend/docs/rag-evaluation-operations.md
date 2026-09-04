# RAG Evaluation Operations

## Purpose

Evaluation is an offline quality gate. It is never imported by the FastAPI
request path and it never blocks the service from starting. The strict Golden
Dataset is `corpus/benchmarks/golden-v2.yaml`; it contains exactly 100
synthetic, versioned samples.

## Install optional RAGAS dependencies

```powershell
cd backend
pip install -e ".[eval]"
```

The normal backend install deliberately does not install or import RAGAS.
Set `DASHSCOPE_API_KEY` only in the environment used by the offline job.

## Run levels

Validate the dataset before any run:

```powershell
python -m app.corpus.cli --store memory validate-golden corpus/benchmarks/golden-v2.yaml
```

Use deterministic evaluation for CI or a credential-free regression check:

```powershell
python -m app.corpus.cli evaluate corpus/benchmarks/golden-v2.yaml <corpus-version> --deterministic-only
```

Run the complete offline job only with a reachable Milvus Standalone service,
the evaluation dependencies, and a valid DashScope key:

```powershell
python -m app.corpus.cli evaluate corpus/benchmarks/golden-v2.yaml <corpus-version> --include-generation --include-agent --ragas --output data/public-corpus/evaluations/full.json
```

`--ragas` fails the command when RAGAS is unavailable, a provider call fails,
or any core metric is missing. Retrieval results remain in the report for
diagnosis; the tool never writes proxy scores as RAGAS scores.

## Baseline and rollback

Compare only reports with the same Golden Dataset version and Top-K:

```powershell
python -m app.corpus.cli compare <baseline.json> <candidate.json>
```

The JSON report is the source of truth and Markdown is rendered from it.
Pair writes use temporary files and restore the previous pair if replacement
fails. A gate override requires both a non-empty reason and `--override-by`;
both are persisted with a timestamp.

To roll back a release, withdraw the candidate corpus or publish the approved
previous corpus version. To roll back the evaluation change itself, remove the
offline CI invocation or omit the `--ragas` flag. Neither action changes the
online FastAPI request path.

## External-service failures

Milvus, DashScope, Tavily, and RAGAS failures must be recorded as structured
errors or `failed`/`unavailable` statuses. Do not claim a complete run passed
unless a report contains real values for Context Precision, Context Recall,
Faithfulness, and Answer Relevancy.

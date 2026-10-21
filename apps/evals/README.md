# Evaluations

This package runs answer evaluations through Temporal and scores completed
answers with an LLM judge. The bundled development dataset contains 45 cases
(30 NQ and 15 HotpotQA), pending human review. Structural corpus verification
is available separately. Retrieval, reliability, and gold-evidence evaluation
remain planned.

## Entry point

From the repository root:

```sh
uv run python -m apps.evals.run --help
uv run python -m apps.evals.run \
  --dataset apps/evals/datasets/kilt-v1/dev.json --validate-only
```

Validation checks the schema, paragraph range ordering, and unique case IDs.
Empty datasets are rejected. It does not check Elasticsearch, evidence support,
or leakage between splits. Start the eval worker in another terminal alongside
the existing Temporal server and answer worker:

```sh
uv run python -m apps.evals.worker
```

`TEMPORAL_ADDRESS` configures the Temporal connection (default `localhost:7233`).
The eval worker uses the separate `kilt-evals` task queue. The CLI loads and
selects the dataset once, then submits the selected cases to `EvalWorkflow`.
Each case runs as an activity that invokes AnswerWorkflow and scores the result.
Activities do not retry, preventing duplicate answer submissions; an activity
failure is recorded and the workflow continues with the next case.

Evaluate one case with:

```sh
uv run python -m apps.evals.run \
  --dataset apps/evals/datasets/kilt-v1/dev.json \
  --case-id nq-dev-737118727843422688 --timeout 120
```

Codex can call `run_evals` with `limit`, `case_id`, `tags`, and `timeout`,
then poll `get_evals` with the returned `run_id`. The bundled dev dataset is
available in the MCP image. Both workers must be running.

The eval activity invokes `AnswerWorkflow` directly on `kilt-answers`, sending
the question, tracing context, and eval session ID. Gold labels are sent to
Temporal in the eval request and used by the eval worker and judge; they are
not included in the answer request.
The answer has its own execution timeout. MCP submissions propagate the
`run_evals` span context through Temporal, nesting each `eval` beneath that
submission span. CLI submissions without parent context create an eval root per
case. Answers keep separate traces, correlated by eval run ID, answer workflow
ID, and trace IDs. The answer root records `eval_trace_id`; the eval span
records `answer_trace_id`.
The CLI submits evals directly through Temporal; no MCP URL or running MCP
server is required. `--mode mcp` is the default execution mode and uses this
direct execution path. `retrieval` and `gold-evidence` modes are not implemented.
`--run-name` labels the eval workflow ID; the CLI waits for results and prints
JSON to stdout without writing run artifacts.

Evaluator results are keyed by evaluator name. Cases whose answer run does
not complete have an unscored reason; activity failures have no judgments:

```json
{
  "evaluators": {
    "answer_correctness": {
      "correctness": 1,
      "reason": "The actual answer is equivalent to an accepted reference."
    }
  }
}
```

Use `--limit` (positive integer, default `1`) to run several cases and `--tags`
to require all listed dataset tags:

```sh
uv run python -m apps.evals.run \
  --dataset apps/evals/datasets/kilt-v1/dev.json \
  --limit 5 --tags page_verified passage_verified
```

Cases run sequentially in dataset order after filtering, excluding rejected
cases. No matches produces an error before connecting to Temporal. `--case-id` can
also be combined with tags. Output is a JSON array unless `--case-id` is supplied.
`--validate-only` continues to validate the entire dataset. `--limit` controls
case count, rather than the answer tool's retrieval limit.

## Docker

Start Elasticsearch, Temporal, and MCP as described in the MCP README. Then
start the eval pool in its own terminal:

```sh
docker compose -f compose/evals.yaml up --build
```

Each Compose file runs independently: `temporal.yaml` owns infrastructure,
`mcp.yaml` owns the answer worker and MCP server, and `evals.yaml` owns the eval
worker and CLI. They share the default network. The eval worker polls only
`kilt-evals`. Scale it independently with `--scale eval-worker=2` on the `up`
command above. This increases capacity across eval runs; cases within a run
remain sequential.

Submit an eval from the same image (the bundled dataset is included):

```sh
docker compose -f compose/evals.yaml run --rm eval-run \
  --dataset apps/evals/datasets/kilt-v1/dev.json \
  --limit 5 --tags page_verified
```

Use the same Compose project name for this stack and any already-running
Temporal/Elasticsearch services.
Compose may report the other stacks as orphan containers because they share a
project; leave them running and do not use `--remove-orphans`. Follow worker
logs with `docker compose -f compose/evals.yaml logs -f eval-worker`, or stop
only the eval pool with `docker compose -f compose/evals.yaml stop`.
After eval code changes, rebuild only its worker, keeping dependencies running:

```sh
docker compose -f compose/evals.yaml up --build
```

## Answer evaluator

`evaluators/answers.py` uses a structured LLM judgment to compare the question,
accepted answer aliases, and actual short answer. It allows semantic equivalents
and returns correctness (`1` or `0`) with a brief reason. Missing, invalid, or
failed judgments return `correctness: null` with an error instead of counting
as incorrect. Unanswerable cases are unscored with an explanatory reason.
The result also records judge model, prompt version, usage, and available cost.

Set `EVAL_ANSWER_MODEL` in `compose/.env` to choose a judge; when unset it uses
`MCP_ANSWER_MODEL`. The eval worker receives the corresponding OpenAI/Anthropic
API keys or `OLLAMA_API_BASE`. Token limits and provider timeout use the existing
`MCP_ANSWER_MAX_TOKENS` and `MCP_ANSWER_TIMEOUT_SECONDS` settings. Rebuild the
eval worker after these changes. The case activity allows an additional 90
seconds for judging and transport cleanup after the answer wait deadline.

## Langfuse

Evaluator observations are direct children of the case's `eval` span. Each
entry in `EVALUATORS` is an `(evaluator_name, evaluator)` pair. The name is
used for both the observation and its result key.
Currently the hierarchy is:

```text
eval
  answer_correctness
    judge_model
```

Additional evaluators get sibling spans by adding entries to the list;
relevancy and retrieval evaluators are not implemented yet.
Root span outputs and returned CLI/Temporal results use the same evaluator
names, such as `evaluators.answer_correctness`.

The eval worker uses the same `LANGFUSE_*` settings as the answer worker.
Configure `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and optionally
`LANGFUSE_BASE_URL` in `compose/.env`, then rebuild the eval worker.
Without credentials (or with `LANGFUSE_TRACING_ENABLED=false`), evaluation
continues without tracing.

Each case activity emits an `eval` observation, grouped by eval workflow
ID as its Langfuse session. It records case ID, dataset tags, Temporal run and
activity IDs, question, accepted answers, output, and the answer workflow ID
for correlation. A separate `answer` trace wraps direct Temporal execution.
Answer activities continue that trace; evaluator generations stay in the eval
trace. Both traces share the eval workflow session ID. The eval span records
`answer_id` and `answer_trace_id`, and the answer root records `eval_run_id`
and `eval_trace_id`. Case results expose both trace IDs when tracing is enabled.
Applicable correctness results are attached as numeric scores with the judgment
reason. The judge generation and its cost belong to the eval trace. Failed
judgments and failed or timed-out cases are marked as errors;
exceptions are captured by the observation context. Telemetry runs outside
workflow replay, and the worker flushes pending events on shutdown.

## Layout

- `run.py`: CLI, JSON array loader, case selection, and a standalone MCP polling helper.
- `workflow.py`: sequential case orchestration and activity failure handling.
- `activities.py`: direct answer workflow execution, judging, and trace correlation.
- `worker.py`: Temporal eval worker and telemetry flushing.
- `models.py`: curated case and evidence schemas.
- `tasks/`: MCP, retrieval-only, and gold-evidence adapter placeholders.
- `evaluators/`: implemented answer correctness judge; retrieval and reliability placeholders.
- `datasets/kilt-v1/`: development JSON array, manifest, and build/verification CLI.
- `runs/`: ignored generated predictions, configuration, and scores.

Dataset sources, build instructions, and case format are documented in the
[KILT v1 README](datasets/kilt-v1/README.md).

## Next implementation steps

1. Import and validate a reviewed development pilot against Elasticsearch.
2. Implement retrieval task and evidence metrics for a model-free baseline.
3. Implement gold-evidence evaluation to isolate synthesis from retrieval.
4. Connect tasks and evaluators through Langfuse experiments.
5. Persist run configuration, dataset/evaluator versions, complete outputs,
   workflow IDs, trace IDs, and scores for later rescoring.

Keep expected answers out of application requests. Store evaluator versions and
dataset versions with scores; use the same frozen test cases across comparisons.

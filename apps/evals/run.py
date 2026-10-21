"""CLI entry point for evaluation dataset checks and future experiments."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession
from opentelemetry.trace import INVALID_SPAN, use_span
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from apps.evals.models import EvalCase
from apps.evals.workflow import TASK_QUEUE, EvalRunRequest, EvalWorkflow
from backend.config import Settings


def load_cases(path: Path) -> list[EvalCase]:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(records, list):
        raise ValueError(f"{path}: dataset must be a JSON array")
    cases = []
    seen = set()
    for index, record in enumerate(records):
        try:
            case = EvalCase.model_validate(record)
            if case.case_id in seen:
                raise ValueError(f"duplicate case_id: {case.case_id}")
        except ValueError as error:
            raise ValueError(f"{path}: record[{index}]: {error}") from error
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: dataset is empty")
    return cases


async def evaluate_case(
    case: EvalCase,
    session: ClientSession,
    *,
    timeout: float = 120,
    poll_interval: float = 1,
) -> dict:
    """Run a loaded case through MCP and return its execution output.

    The session must already be initialized. A timeout stops polling; it does
    not cancel the server workflow. Gold labels never leave this process.
    """
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("timeout and poll_interval must be positive")
    if "rejected" in case.tags:
        raise ValueError(f"{case.case_id}: rejected cases cannot be evaluated")

    async def call(name: str, arguments: dict) -> dict:
        # Keep answer latency/cost in its own trace, outside the eval trace.
        # The SDK still propagates the new MCP client span to the server.
        with use_span(INVALID_SPAN):
            response = await session.call_tool(name, arguments)
        if response.is_error:
            raise RuntimeError(f"{name}: {response.content}")
        payload = response.structured_content
        if payload is None:
            payload = json.loads(response.content[0].text)
        if not isinstance(payload, dict):
            raise ValueError(f"{name}: expected an object response")
        return payload

    run_id = None
    started = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(timeout):
            output = await call("answer", {"question": case.question})
            run_id = output["run_id"]
            while True:
                output = await call("get_answer", {"run_id": run_id})
                if output["status"] != "RUNNING":
                    break
                await asyncio.sleep(poll_interval)
    except TimeoutError:
        output = {"run_id": run_id, "status": "TIMEOUT"}

    return {
        "case_id": case.case_id,
        "output": output,
        "elapsed_seconds": asyncio.get_running_loop().time() - started,
        "evaluators": {},
    }


def select_cases(
    cases: list[EvalCase],
    *,
    case_id: str | None = None,
    limit: int = 1,
    tags: list[str] | None = None,
) -> list[EvalCase]:
    """Select eligible cases in dataset order, requiring every requested tag."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    selected = [
        case
        for case in cases
        if (case_id is None or case.case_id == case_id)
        and "rejected" not in case.tags
        and set(tags or ()).issubset(case.tags)
    ][:limit]
    if not selected:
        raise ValueError("No eligible cases match the requested case ID and tags")
    return selected


async def _evaluate_remote(
    args: argparse.Namespace, cases: list[EvalCase]
) -> dict | list[dict]:
    client = await Client.connect(
        Settings().temporal_address, data_converter=pydantic_data_converter
    )
    results = await client.execute_workflow(
        EvalWorkflow.run,
        EvalRunRequest(
            cases=cases,
            timeout=args.timeout,
        ),
        id=f"kilt-eval-{args.run_name}-{uuid4()}",
        task_queue=TASK_QUEUE,
    )
    return results[0] if args.case_id else results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--mode", choices=("mcp", "retrieval", "gold-evidence"), default="mcp"
    )
    parser.add_argument("--run-name", default="baseline")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--case-id", help="Evaluate a single case through AnswerWorkflow"
    )
    parser.add_argument(
        "--limit", type=int, default=1, help="Maximum cases to run (default: 1)"
    )
    parser.add_argument(
        "--tags", nargs="+", default=[], help="Require all listed dataset tags"
    )
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    try:
        cases = load_cases(args.dataset)
        if args.limit <= 0:
            raise ValueError("limit must be positive")
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.validate_only:
        print(f"Validated {len(cases)} cases (schema and unique IDs only).")
        return
    if args.mode != "mcp":
        parser.error("Execution requires --mode mcp.")
    try:
        selected = select_cases(
            cases, case_id=args.case_id, limit=args.limit, tags=args.tags
        )
        result = asyncio.run(_evaluate_remote(args, selected))
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

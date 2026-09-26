# JobSchedulerService practice brief

I'm preparing for a Senior Engineer assessment using Python. Help me practice implementing a service in memory. Keep this exercise at the service level: no API, UI, database, real sleeps, or background threads.

Act as an interviewer and reviewer. Let me implement the solution. Answer clarification questions, but do not provide implementation code or a full solution unless I explicitly ask. Review my work against the contract and explain concrete correctness or maintainability issues.

This is an original practice exercise, not a claimed assessment question.

## Time budget

Allow 50 minutes total. Work on the initial contract for the first 25 minutes, then introduce the follow-up requirements. Ask me to set a timer and tell you when I reach the follow-up stage; do not assume you can track time between messages.

## Initial task

Build an in-memory `JobSchedulerService` with these operations:

```python
schedule(job_id, payload, run_at)
cancel(job_id)
run_due(now)
get_job(job_id)
```

Inject an executor callable when constructing the service. It receives a job's payload; returning normally means success and raising an exception means failure.

### Contract

- Job IDs are strings and remain unique for the lifetime of the service, including after completion or cancellation. Reject duplicate IDs without changing existing jobs.
- Timestamps are integers. Calls are sequential, and timestamps supplied to `run_due` are nondecreasing.
- A pending job is due when `run_at <= now`.
- Execute due jobs in ascending scheduled-time order, breaking ties by job ID.
- `run_due(now)` executes jobs synchronously. Successful jobs must never execute again.
- Initially, a failed job becomes terminally failed. An executor failure must not prevent other due jobs from running.
- Only pending jobs can be cancelled. Cancelled jobs never execute.
- `get_job` exposes the job ID, payload, scheduled time, and status.
- Returned data must not allow callers to mutate internal state. Likewise, modifying the original payload after scheduling must not alter the stored payload. Assume payloads contain ordinary, copyable Python data.
- Scheduling a time earlier than the latest `now` is permitted; the job becomes eligible on the next `run_due` call.
- Assume the executor does not call back into the scheduler.

Before coding, choose and explain consistent return values and error behavior for missing IDs, invalid cancellation, and duplicate IDs. Also define what `run_due` returns. Keep these choices stable across the follow-up.

### Initial examples

- Jobs `b` and `a`, both scheduled at 10, execute as `a`, then `b`, when `run_due(10)` is called.
- A job scheduled at 11 does not execute during `run_due(10)`.
- Calling `run_due(10)` again must not rerun a successful job.
- Cancelling a pending job prevents its execution.
- If the first due job raises an exception, later due jobs still execute.

## Follow-up: introduce after 25 minutes

Extend the same implementation to support retries without breaking earlier behavior:

- Configure a fixed, positive integer retry delay when constructing the service.
- Failed jobs retry up to **three total attempts**, including the first attempt.
- After a retryable failure, schedule the next attempt at `now + retry_delay`, using the `now` supplied to the current `run_due` call.
- Each job gets at most one attempt per `run_due` call, even if the caller advances time by a large amount.
- Retrying jobs count as pending and can be cancelled before their next attempt.
- Order retry attempts together with other due jobs by their next scheduled attempt time, then job ID.
- After the third failed attempt, mark the job terminally failed.
- Expose attempt count and last error through `get_job`. Store the error as a string; clear it when an attempt succeeds.
- Preserve the original payload across retries, even if the executor mutates the argument it receives.
- Continue processing other due jobs when an attempt fails.

### Follow-up example

With a retry delay of 5, a job scheduled at 10 first runs during `run_due(20)` and fails. Its next attempt is at 25, not 15. If it fails during `run_due(100)`, its third attempt is scheduled at 105. It must not consume multiple attempts during that single call at 100.

## Review criteria

- Correct handling of exact due-time boundaries and deterministic ordering.
- Explicit, consistent job lifecycle and failure behavior.
- No duplicate execution after success or cancellation.
- Correct retry limits, scheduling, and payload isolation.
- Clear separation between selecting due jobs, executing them, and updating state.
- Straightforward code that accommodates the follow-up with limited changes.
- Ability to explain operation complexity and design tradeoffs.

Start by asking me to clarify the return/error contract. Do not implement the service for me.

# HisabDo safety integration notes

## Changes
- `main.py` now imports `inspect_support_request` and applies it before calling `rag.retrieve` in `POST /search`.
- Unsafe messages return HTTP 400 with a machine-readable `detail.code` and a generic user-facing message.
- Valid human-support requests return `escalation_requested: true` and `escalation_status: "not_connected"`.
- The response explicitly does not claim that a live agent or ticket has been contacted; this project ZIP contains no live support/ticket integration.
- `conversation_safety.py` and its 9 focused tests are retained.

## Verification performed
- `pytest -q test_conversation_safety.py`: 9 passed.
- `python -m py_compile main.py conversation_safety.py`: passed.
- Full `pytest -q` was attempted but test collection stopped because `sentence_transformers` is not installed in the execution environment (`ModuleNotFoundError`). The full regression suite is therefore NOT verified in this run.

## Apply
Replace the matching files in your local Day10 project with the files in this package. Keep a backup first. Install project dependencies in the project's virtual environment, then run `pytest -q`.

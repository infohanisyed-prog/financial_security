# HisabDo LLM + citation integration

## Files in this patch
- `main.py`: adds `POST /chat`.
- `chat_service.py`: runs safety checks, retrieves approved context, invokes the LLM only when eligible sources exist, and validates citation IDs.
- `llm_service.py`: optional OpenAI-compatible Chat Completions client using only the Python standard library.
- `test_chat_service.py`: tests fail-closed retrieval, citation validation, prompt-injection blocking, and support-escalation messaging.

## Configuration
Set these environment variables in the runtime environment (do not commit secrets):

- `OPENAI_API_KEY`: API key from the provider you are authorized to use.
- `OPENAI_MODEL`: model identifier supported by that provider.
- `OPENAI_BASE_URL`: optional; defaults to `https://api.openai.com/v1` for OpenAI-compatible providers.

No API key is included in this patch. Without configuration, `/chat` returns a safe fallback.

## API
`POST /chat`

```json
{
  "question": "How do I ...?",
  "top_k": 3
}
```

The response contains `status`, `answer`, and `citations`. A successful answer must include one or more exact source IDs in square brackets, e.g. `[faq-001]`; unknown or missing citations are rejected and replaced with the safe fallback.

## Important current KB limitation
The supplied knowledge base currently has 8 records and 0 records approved for production indexing. Therefore `/chat` will return `source_unavailable` and will **not call the LLM** until a genuine source is verified, approved, privacy-reviewed, and marked indexing-eligible through the existing audit workflow. Do not change approval fields just to enable generation.

Human-support phrases are identified, but no real support-ticket or agent handoff is configured. The API says so explicitly.

## Tests
Run from the project directory:

```cmd
pytest -q test_chat_service.py test_conversation_safety.py
pytest -q --ignore=backup_safety_patch --ignore=_safety_patch_temp
```

The first command passed 15 tests in the patch validation environment. The complete suite must be rerun in the project's environment where `sentence-transformers` is installed.

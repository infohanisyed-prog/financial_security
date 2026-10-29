HisabDo Knowledge Source Audit - Patch

Files:
- semantic_search.py: updated to reject duplicate document IDs; require verified=true,
  audit.approval_status=approved, audit.indexing_eligible=true, source_owner, valid
  HTTP(S) source_url, ISO last_verified_date, and privacy_review=approved before indexing.
  SearchResult now includes audit/source metadata.
- rag_service.py: enforces the same metadata eligibility policy and returns audit metadata
  with source attribution.
- test_semantic_search_patched.py: focused policy and data-integrity tests.

main.py does not need a code change for these specific requirements; its existing API
endpoints can remain as they are.

Install/test from the project virtual environment:
  pip install pytest numpy sentence-transformers
  pytest -q test_semantic_search_patched.py

Important:
The current KB documents were reported as pending and missing source-owner/source-URL/
last-verified-date metadata. They will continue to be excluded. Do not fill these fields
with invented values or mark documents approved merely to make retrieval return results.
A source owner must supply genuine source URLs and review dates and explicitly approve
content/privacy review before indexing.

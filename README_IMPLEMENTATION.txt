HisabDo ingestion pipeline patch
================================
Files:
- ingestion_pipeline.py: local JSON ingestion, conservative boilerplate cleanup,
  approval/privacy gating, type-specific chunking, content hashing, new/modified/
  deleted source detection, duplicate/parse logging, optional embeddings and reports.
- test_ingestion_pipeline.py: deterministic tests using a fake embedding model.

Run inside the project's virtual environment:
  pip install pytest numpy sentence-transformers
  pytest -q test_ingestion_pipeline.py

First run staging validation without downloading an embedding model:
  python ingestion_pipeline.py --input HisabDo_Cleaned_Staging_Knowledge_Set.json --output ingestion_output --no-embeddings

The supplied 8 records are pending/unverified, so they will be quarantined and
will not be embedded. This is expected and is the correct fail-closed behavior.

After real owner approval, source verification and privacy clearance, update each
record's approval_status, privacy_review, verified, source_owner, source_url and
last_updated_date using genuine evidence. Then run without --no-embeddings.

Incremental sync compares document IDs and content SHA-256 hashes. It reports
new/modified/unchanged/deleted sources. The local pipeline records deleted IDs
in its manifest/report; connect this manifest to the production vector store's
delete API before claiming remote vector deletion is live.

Chunk sizes are initial word-window settings, not token counts. Benchmark using
the pinned embedding model's tokenizer and a labelled query set before production.

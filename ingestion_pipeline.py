"""Repeatable local ingestion pipeline for HisabDo knowledge records.

Input: normalized JSON with a top-level `records` list (or legacy `documents` list).
Only approved, verified, privacy-cleared records are chunked for production embeddings.
Staging/pending records are reported but never embedded.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG = {
    "faq": {"size": 260, "overlap": 15},
    "accounting_feature_table": {"size": 400, "overlap": 20},
    "workflow_guide": {"size": 430, "overlap": 50},
    "feature_guide": {"size": 430, "overlap": 50},
    "user_documentation": {"size": 600, "overlap": 80},
    "default": {"size": 400, "overlap": 50},
}
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD = 0.42

def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def clean_boilerplate(text: str) -> str:
    """Conservative cleanup: remove only standalone common chrome labels."""
    lines = []
    chrome = re.compile(r"^\s*(home|menu|skip to content|back to top|cookie settings|"
                        r"privacy settings|all rights reserved)\s*$", re.I)
    for line in text.splitlines():
        if chrome.match(line):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()

def eligible(record: dict[str, Any]) -> bool:
    return (
        record.get("approval_status") == "approved"
        and record.get("privacy_review") == "approved"
        and record.get("content_status", "active") == "active"
        and bool(record.get("source_owner"))
        and bool(record.get("source_url"))
        and bool(record.get("last_updated_date"))
        and record.get("verified") is True
    )

def normalize(record: dict[str, Any]) -> dict[str, Any]:
    required = ("document_id", "title", "category", "content")
    missing = [key for key in required if not str(record.get(key, "")).strip()]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    out = dict(record)
    out["content"] = clean_boilerplate(str(record["content"]))
    if not out["content"]:
        raise ValueError("content is empty after conservative cleanup")
    out["query_aliases"] = [str(x).strip() for x in record.get("query_aliases", []) if str(x).strip()]
    out["content_hash_sha256"] = sha256(out["content"])
    return out

def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Word-window chunking, preserving sentence/paragraph text as far as possible."""
    words = text.split()
    if not words:
        return []
    size = max(1, int(size)); overlap = max(0, min(int(overlap), size - 1))
    chunks, start = [], 0
    while start < len(words):
        end = min(len(words), start + size)
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return chunks

def load_records(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("records", data.get("documents", []))
    if not isinstance(raw, list):
        raise ValueError("input must contain a records/documents list")
    records, errors = [], []
    seen = set()
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, dict):
                raise ValueError("record must be a JSON object")
            record = normalize(item)
            rid = record["document_id"]
            if rid in seen:
                errors.append({"record": rid, "error": "duplicate document ID"})
                continue
            seen.add(rid)
            records.append(record)
        except Exception as exc:
            errors.append({"record": str(index), "error": str(exc)})
    return records, errors

def run_ingestion(input_path: Path, output_dir: Path, model_name: str = MODEL_NAME,
                  embed: bool = True, model=None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    records, errors = load_records(input_path)
    manifest_path = output_dir / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    previous_hashes = previous.get("source_hashes", {})
    current_hashes = {r["document_id"]: r["content_hash_sha256"] for r in records}
    current_ids = set(current_hashes)
    previous_ids = set(previous_hashes)

    actions = {}
    for rid, digest in current_hashes.items():
        if rid not in previous_hashes:
            actions[rid] = "new"
        elif previous_hashes[rid] != digest:
            actions[rid] = "modified"
        else:
            actions[rid] = "unchanged"
    deleted = sorted(previous_ids - current_ids)

    active_records = [r for r in records if eligible(r)]
    quarantined = [r["document_id"] for r in records if not eligible(r)]
    chunks, chunk_errors = [], []
    for record in active_records:
        try:
            cfg = CONFIG.get(record.get("category"), CONFIG["default"])
            parts = chunk_text(record["content"], cfg["size"], cfg["overlap"])
            for n, part in enumerate(parts):
                chunks.append({
                    "chunk_id": f'{record["document_id"]}::{n}',
                    "document_id": record["document_id"],
                    "title": record["title"],
                    "category": record["category"],
                    "section": record.get("section"),
                    "product_module": record.get("product_module"),
                    "source_url": record.get("source_url"),
                    "language": record.get("language"),
                    "content_hash_sha256": record["content_hash_sha256"],
                    "chunk_index": n,
                    "text": part,
                })
        except Exception as exc:
            chunk_errors.append({"record": record["document_id"], "error": str(exc)})

    vectors = None
    embedding_error = None
    if embed and chunks:
        try:
            if model is None:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(model_name)
            import numpy as np
            vectors = np.asarray(model.encode([c["text"] for c in chunks],
                                               normalize_embeddings=True,
                                               convert_to_numpy=True), dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(chunks) or not np.isfinite(vectors).all():
                raise ValueError("invalid embedding matrix shape or values")
            np.savez_compressed(output_dir / "vectors.npz", vectors=vectors)
        except Exception as exc:
            embedding_error = str(exc)
            vectors = None

    (output_dir / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"built_at": now, "model_name": model_name, "threshold": SIMILARITY_THRESHOLD,
                "source_hashes": current_hashes, "deleted_source_ids": deleted}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "run_at": now, "input_file": str(input_path), "records_seen": len(records),
        "approved_records": len(active_records), "quarantined_records": quarantined,
        "chunks_created": len(chunks), "actions": actions, "deleted_sources": deleted,
        "duplicate_or_parse_errors": errors, "chunk_errors": chunk_errors,
        "embedding_model": model_name, "similarity_threshold": SIMILARITY_THRESHOLD,
        "vectors_written": vectors is not None, "embedding_error": embedding_error,
        "release_status": "ready_for_review" if active_records and vectors is not None else "blocked_or_staging_only"
    }
    (output_dir / "execution_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="HisabDo_Cleaned_Staging_Knowledge_Set.json")
    parser.add_argument("--output", default="ingestion_output")
    parser.add_argument("--no-embeddings", action="store_true", help="Run validation/chunk staging without loading a model")
    args = parser.parse_args()
    result = run_ingestion(Path(args.input), Path(args.output), embed=not args.no_embeddings)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not result["duplicate_or_parse_errors"] and not result["chunk_errors"] else 1

if __name__ == "__main__":
    raise SystemExit(main())

"""
HisabDo retrieval benchmark
Run from the project directory:
    python benchmark_retrieval.py

The test set is synthetic/proposed diagnostic data, not historical Day 1 results.
Diagnostic results include unapproved documents and MUST NOT be used as production evidence.
"""
import json
import math
import re
from pathlib import Path
from collections import defaultdict

from semantic_search import SemanticKnowledgeBase

BASE = Path(__file__).resolve().parent
KB_PATH = BASE / "knowledge_base.json"
TEST_PATH = BASE / "hisabdo_retrieval_test_set.json"
TOP_K = 3


def load_cases(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("questions") or data.get("test_cases") or data.get("cases") or data.get("items") or []
    else:
        rows = []
    cases = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        query = row.get("query") or row.get("question") or row.get("user_query") or row.get("text")
        expected = (row.get("expected_source_ids") or row.get("expected_ids")
                    or row.get("relevant_doc_ids") or row.get("expected_source_id") or [])
        if isinstance(expected, str):
            expected = [] if expected.upper() in {"NO_APPROVED_SOURCE", "NONE", "NO_SOURCE"} else [expected]
        expected = [str(x) for x in expected if str(x).upper() not in {"NO_APPROVED_SOURCE", "NONE", "NO_SOURCE"}]
        if query:
            cases.append({"query": str(query), "expected": expected, "unsupported": not bool(expected)})
    return cases


def result_id(result):
    if isinstance(result, dict):
        return str(result.get("id", ""))
    return str(getattr(result, "id", ""))


def dcg(relevances):
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def score_run(cases, results_by_query, k=TOP_K):
    evaluated = [c for c in cases if not c["unsupported"]]
    if not evaluated:
        return {"queries": 0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}
    recalls, reciprocal_ranks, ndcgs = [], [], []
    for case in evaluated:
        ids = [result_id(x) for x in results_by_query.get(case["query"], [])[:k]]
        expected = set(case["expected"])
        hits = [1 if x in expected else 0 for x in ids]
        recalls.append(len(set(ids) & expected) / len(expected))
        rank = next((i + 1 for i, x in enumerate(ids) if x in expected), None)
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        ideal = dcg([1] * min(len(expected), k))
        ndcgs.append(dcg(hits) / ideal if ideal else 0.0)
    return {
        "queries": len(evaluated),
        "recall_at_k": round(sum(recalls) / len(recalls), 4),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        "ndcg_at_k": round(sum(ndcgs) / len(ndcgs), 4),
    }


def normalized(q):
    q = q.lower().strip()
    q = re.sub(r"\s+", " ", q)
    q = re.sub(r"[^\w\s]", "", q)
    return q


def run_variant(kb, cases, label, strategy, rerank=False, alpha=None, metadata=False, normalize=False):
    results = {}
    errors = []
    for case in cases:
        q = normalized(case["query"]) if normalize else case["query"]
        filters = None
        if metadata and case["expected"]:
            # The current KB uses faq-* and security-* IDs; apply the matching doc_type.
            prefix = case["expected"][0].split("-", 1)[0]
            if prefix in {"faq", "security"}:
                filters = {"type": prefix}
        try:
            results[case["query"]] = kb.diagnostic_search(
                q, top_k=TOP_K, strategy=strategy,
                metadata_filters=filters, alpha=alpha, rerank=rerank
            )
        except Exception as exc:
            errors.append(f"{case['query']}: {type(exc).__name__}: {exc}")
            results[case["query"]] = []
    metrics = score_run(cases, results)
    unsupported = [c for c in cases if c["unsupported"]]
    unsupported_hits = sum(bool(results.get(c["query"])) for c in unsupported)
    return {
        "name": label,
        "metrics": metrics,
        "unsupported_queries": len(unsupported),
        "unsupported_with_any_diagnostic_hit": unsupported_hits,
        "errors": errors,
        "results": results,
    }


def main():
    if not KB_PATH.exists():
        raise SystemExit(f"Missing {KB_PATH.name} in {BASE}")
    if not TEST_PATH.exists():
        raise SystemExit(f"Missing {TEST_PATH.name} in {BASE}. Put the supplied test JSON beside this script.")

    cases = load_cases(TEST_PATH)
    if not cases:
        raise SystemExit("Could not read test cases. Expected a list or a 'questions'/'test_cases' array.")

    print(f"Loaded {len(cases)} proposed diagnostic questions "
          f"({sum(c['unsupported'] for c in cases)} unsupported).")
    kb = SemanticKnowledgeBase(kb_path=str(KB_PATH))

    variants = [
        ("Dense baseline", "dense", False, None, False, False),
        ("Hybrid baseline", "hybrid", False, 0.5, False, False),
        ("Hybrid + rerank", "hybrid", True, 0.5, False, False),
        ("Hybrid + metadata filter", "hybrid", True, 0.5, True, False),
        ("Hybrid + query normalization", "hybrid", True, 0.5, False, True),
        ("Hybrid alpha 0.25", "hybrid", True, 0.25, False, False),
        ("Hybrid alpha 0.75", "hybrid", True, 0.75, False, False),
    ]

    reports = []
    for label, strategy, rerank, alpha, metadata, norm in variants:
        report = run_variant(kb, cases, label, strategy, rerank, alpha, metadata, norm)
        reports.append(report)
        m = report["metrics"]
        print(f"\n{label}")
        print(f"  Recall@{TOP_K}: {m['recall_at_k']:.4f} | MRR: {m['mrr']:.4f} | nDCG@{TOP_K}: {m['ndcg_at_k']:.4f}")
        print(f"  Unsupported queries with any diagnostic result: "
              f"{report['unsupported_with_any_diagnostic_hit']}/{report['unsupported_queries']}")
        if report["errors"]:
            print("  First error:", report["errors"][0])

    # Production eligibility is intentionally separate from diagnostic ranking.
    eligible_count = None
    try:
        eligible_count = len(kb.documents)
    except Exception:
        pass

    output = {
        "notice": "Synthetic/proposed diagnostic benchmark; not historical Day 1 results. Diagnostic hits are not approved production evidence.",
        "top_k": TOP_K,
        "test_questions": len(cases),
        "supported_questions": sum(not c["unsupported"] for c in cases),
        "unsupported_questions": sum(c["unsupported"] for c in cases),
        "production_eligible_documents": eligible_count,
        "variants": [
            {k: v for k, v in r.items() if k != "results"} for r in reports
        ],
    }
    out_path = BASE / "retrieval_benchmark_report.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved: {out_path.name}")
    if eligible_count == 0:
        print("SAFETY: 0 production-eligible documents. Keep production retrieval fail-closed.")
    print("NOTE: Metadata filtering uses the KB metadata field type, inferred from expected IDs;")
    print("      results are valid only if the KB documents contain matching type values.")


if __name__ == "__main__":
    main()

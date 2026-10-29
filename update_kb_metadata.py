
import json
from pathlib import Path

KB_PATH = Path(__file__).with_name("knowledge_base.json")

OFFICIAL_FAQ_URL = "https://hisabdo.app/faq"
OFFICIAL_WEBSITE_URL = "https://hisabdo.app/"

def main():
    with KB_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    documents = data.get("documents", [])
    updated = []

    for doc in documents:
        audit = doc.setdefault("audit", {})
        doc_id = doc.get("id")

        if doc_id == "faq-001":
            doc["source"] = "Official HisabDo FAQ — product description requires review"
            audit["source_url"] = OFFICIAL_FAQ_URL
            updated.append(doc_id)

        elif doc_id == "faq-002":
            doc["source"] = (
                "HisabDo expense workflow — application access unavailable; "
                "steps require verification"
            )
            audit["source_url"] = OFFICIAL_FAQ_URL
            updated.append(doc_id)

        elif doc_id == "faq-003":
            doc["source"] = "Internal knowledge-base safety policy"
            audit["audit_notes"] = list(audit.get("audit_notes", []))
            note = (
                "Safety policy retained; formal approval and source ownership "
                "have not been established."
            )
            if note not in audit["audit_notes"]:
                audit["audit_notes"].append(note)
            updated.append(doc_id)

        # Never fabricate ownership, verification dates, or approval.
        audit["approval_status"] = "pending"
        audit["indexing_eligible"] = False

    with KB_PATH.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")

    print("Metadata update complete.")
    print("Updated documents:", ", ".join(updated))
    print("Approval remains pending; indexing remains disabled.")

if __name__ == "__main__":
    main()

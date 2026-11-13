
import json
from pathlib import Path

from conversation_context import ConversationContextManager


def load_transcripts():
    path = Path(__file__).parent / "conversation_transcripts.json"
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_all_transcripts_preserve_expected_context():
    data = load_transcripts()
    manager = ConversationContextManager()

    assert data["status"] == "simulated_not_live_chatbot"

    for scenario in data["scenarios"]:
        user_id = scenario["id"]
        session_id = manager.create_session(user_id)

        for turn in scenario["turns"]:
            manager.update_context(
                session_id,
                user_id,
                turn["context_update"],
            )

        actual = manager.get_context(session_id, user_id)

        assert actual == scenario["expected_context"], (
            f"Context mismatch in {scenario['id']}"
        )


def test_transcript_scenarios_have_unique_ids():
    data = load_transcripts()
    ids = [item["id"] for item in data["scenarios"]]

    assert len(ids) == len(set(ids))


def test_all_transcripts_contain_turns():
    data = load_transcripts()

    for scenario in data["scenarios"]:
        assert len(scenario["turns"]) >= 2
        assert scenario["expected_context"]


import pytest

from conversation_context import ConversationContextManager


def test_context_is_preserved_between_followups():
    manager = ConversationContextManager()
    sid = manager.create_session("user-1")

    manager.update_context(
        sid,
        "user-1",
        {"intent": "expense_summary", "category": "food"},
    )

    manager.update_context(
        sid,
        "user-1",
        {"date_range": "this_month"},
    )

    context = manager.get_context(sid, "user-1")

    assert context["intent"] == "expense_summary"
    assert context["category"] == "food"
    assert context["date_range"] == "this_month"


def test_user_cannot_access_another_users_session():
    manager = ConversationContextManager()
    sid = manager.create_session("user-1")

    with pytest.raises(PermissionError):
        manager.get_context(sid, "user-2")


def test_sensitive_or_unknown_fields_are_rejected():
    manager = ConversationContextManager()
    sid = manager.create_session("user-1")

    with pytest.raises(ValueError):
        manager.update_context(
            sid,
            "user-1",
            {"password": "secret"},
        )


def test_context_value_length_is_limited():
    manager = ConversationContextManager()
    sid = manager.create_session("user-1")

    with pytest.raises(ValueError):
        manager.update_context(
            sid,
            "user-1",
            {"category": "x" * 101},
        )


def test_context_field_can_be_cleared():
    manager = ConversationContextManager()
    sid = manager.create_session("user-1")

    manager.update_context(
        sid,
        "user-1",
        {"category": "food"},
    )

    manager.update_context(
        sid,
        "user-1",
        {"category": None},
    )

    assert "category" not in manager.get_context(sid, "user-1")


def test_ended_session_cannot_be_accessed():
    manager = ConversationContextManager()
    sid = manager.create_session("user-1")

    assert manager.end_session(sid, "user-1") is True

    with pytest.raises(PermissionError):
        manager.get_context(sid, "user-1")

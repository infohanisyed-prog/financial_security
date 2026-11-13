
"""Short-lived, user-isolated context for HisabDo follow-up questions."""

from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
import secrets


ALLOWED_FIELDS = {
    "intent",
    "category",
    "date_range",
    "period_label",
    "pending_question",
    "last_topic",
}

MAX_FIELD_LENGTH = 100


@dataclass
class ConversationSession:
    session_id: str
    user_id: str
    context: dict = field(default_factory=dict)
    updated_at: float = field(default_factory=monotonic)


class ConversationContextManager:
    """Stores limited, temporary context without retaining raw chat messages."""

    def __init__(self, ttl_seconds=1800, max_sessions=10000):
        if ttl_seconds <= 0 or max_sessions <= 0:
            raise ValueError("Session limits must be positive.")

        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions = {}
        self._lock = RLock()

    def _remove_expired(self):
        now = monotonic()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session.updated_at > self.ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]

    def create_session(self, user_id):
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("A valid authenticated user_id is required.")

        with self._lock:
            self._remove_expired()

            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("Session capacity reached.")

            session_id = secrets.token_urlsafe(24)
            self._sessions[session_id] = ConversationSession(
                session_id=session_id,
                user_id=user_id,
            )
            return session_id

    def update_context(self, session_id, user_id, updates):
        if not isinstance(updates, dict):
            raise ValueError("Context updates must be a dictionary.")

        unknown = set(updates) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(
                f"Unsupported context fields: {', '.join(sorted(unknown))}"
            )

        clean_updates = {}
        for key, value in updates.items():
            if value is None:
                clean_updates[key] = None
                continue

            if not isinstance(value, str):
                raise ValueError(f"{key} must be a string or None.")

            value = value.strip()
            if len(value) > MAX_FIELD_LENGTH:
                raise ValueError(f"{key} is too long.")

            clean_updates[key] = value

        with self._lock:
            self._remove_expired()
            session = self._sessions.get(session_id)

            if session is None or session.user_id != user_id:
                raise PermissionError("Session not found or not authorized.")

            for key, value in clean_updates.items():
                if value is None:
                    session.context.pop(key, None)
                else:
                    session.context[key] = value

            session.updated_at = monotonic()
            return dict(session.context)

    def get_context(self, session_id, user_id):
        with self._lock:
            self._remove_expired()
            session = self._sessions.get(session_id)

            if session is None or session.user_id != user_id:
                raise PermissionError("Session not found or not authorized.")

            session.updated_at = monotonic()
            return dict(session.context)

    def end_session(self, session_id, user_id):
        with self._lock:
            session = self._sessions.get(session_id)

            if session is None or session.user_id != user_id:
                raise PermissionError("Session not found or not authorized.")

            del self._sessions[session_id]
            return True

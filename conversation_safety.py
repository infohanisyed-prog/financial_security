
"""Defense-in-depth safety checks for HisabDo conversations."""

import re
from dataclasses import dataclass


@dataclass
class SafetyResult:
    allowed: bool
    reason: str
    escalation_required: bool = False


INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior) instructions",
    r"reveal (the )?(system prompt|hidden prompt)",
    r"show (me )?(your )?(system prompt|hidden instructions)",
    r"developer message",
    r"bypass (all )?(safety|security) rules",
    r"act as (an unrestricted|a different) assistant",
]

SENSITIVE_PATTERNS = [
    r"\b\d{13,19}\b",       # Possible payment card number
    r"\b\d{8,17}\b",        # Possible account identifier
]


def inspect_message(message: str) -> SafetyResult:
    if not isinstance(message, str) or not message.strip():
        return SafetyResult(False, "empty_message")

    if len(message) > 2000:
        return SafetyResult(False, "message_too_long")

    normalized = " ".join(message.lower().split())

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, normalized):
            return SafetyResult(False, "possible_prompt_injection")

    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, normalized):
            return SafetyResult(False, "possible_sensitive_data")

    return SafetyResult(True, "allowed")


def inspect_support_request(message: str) -> SafetyResult:
    if not isinstance(message, str) or not message.strip():
        return SafetyResult(False, "empty_message")

    normalized = message.lower()

    support_phrases = [
        "human support",
        "talk to an agent",
        "contact support",
        "speak to a person",
        "account locked",
        "unauthorized transaction",
    ]

    if any(phrase in normalized for phrase in support_phrases):
        return SafetyResult(
            True,
            "human_support_escalation_requested",
            escalation_required=True,
        )

    return inspect_message(message)

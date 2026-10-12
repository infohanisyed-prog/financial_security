
import os

# Use a dedicated test secret, not a production secret.
os.environ.setdefault(
    "EXPENSE_JWT_SECRET",
    "test-only-secret-key-for-local-automated-tests"
)

import pytest
from fastapi.testclient import TestClient

import expense_management_chatbot_security as security


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Give every test its own temporary database.
    test_db = tmp_path / "test_expenses.db"
    monkeypatch.setattr(security, "DB_PATH", test_db)

    security.init_db()

    with TestClient(security.app) as test_client:
        yield test_client


def register_user(client, email="user1@example.com"):
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "SecurePass123!",
            "account_name": "Test Account",
        },
    )
    assert response.status_code == 201
    return response.json()


def login_user(client, email="user1@example.com"):
    response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": "SecurePass123!",
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def get_account_id(client, token):
    response = client.get(
        "/accounts",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    return response.json()["accounts"][0]["id"]


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_user(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecurePass123!",
            "account_name": "My Account",
        },
    )

    assert response.status_code == 201
    assert "user_id" in response.json()


def test_duplicate_email_rejected(client):
    register_user(client)

    response = client.post(
        "/auth/register",
        json={
            "email": "USER1@example.com",
            "password": "AnotherPass123!",
            "account_name": "Duplicate",
        },
    )

    assert response.status_code == 409


def test_login_with_wrong_password_rejected(client):
    register_user(client)

    response = client.post(
        "/auth/login",
        json={
            "email": "user1@example.com",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401


def test_protected_profile_requires_token(client):
    response = client.get("/me")

    assert response.status_code in (401, 403)


def test_valid_login_and_profile(client):
    register_user(client)
    token = login_user(client)

    response = client.get(
        "/me",
        headers=auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["email"] == "user1@example.com"


def test_password_is_not_returned_by_registration(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "safe@example.com",
            "password": "SecurePass123!",
            "account_name": "Safe Account",
        },
    )

    assert response.status_code == 201
    assert "password" not in response.json()
    assert "password_hash" not in response.json()


def test_valid_transaction(client):
    register_user(client)
    token = login_user(client)
    account_id = get_account_id(client, token)

    response = client.post(
        f"/accounts/{account_id}/transactions",
        headers=auth_header(token),
        json={
            "transaction_type": "expense",
            "amount": 250.50,
            "category": "Food",
            "note": "Test transaction",
            "transaction_date": "2026-10-12",
        },
    )

    assert response.status_code == 201
    assert response.json()["amount"] == 250.50


@pytest.mark.parametrize("amount", [0, -10, -0.01])
def test_invalid_transaction_amount_rejected(client, amount):
    register_user(client)
    token = login_user(client)
    account_id = get_account_id(client, token)

    response = client.post(
        f"/accounts/{account_id}/transactions",
        headers=auth_header(token),
        json={
            "transaction_type": "expense",
            "amount": amount,
            "category": "Food",
            "transaction_date": "2026-10-12",
        },
    )

    assert response.status_code == 422


def test_transaction_requires_authentication(client):
    response = client.post(
        "/accounts/1/transactions",
        json={
            "transaction_type": "expense",
            "amount": 100,
            "category": "Food",
            "transaction_date": "2026-10-12",
        },
    )

    assert response.status_code in (401, 403)


def test_user_cannot_add_transaction_to_another_users_account(client):
    register_user(client, "alice@example.com")
    alice_token = login_user(client, "alice@example.com")
    alice_account = get_account_id(client, alice_token)

    register_user(client, "bob@example.com")
    bob_token = login_user(client, "bob@example.com")

    response = client.post(
        f"/accounts/{alice_account}/transactions",
        headers=auth_header(bob_token),
        json={
            "transaction_type": "expense",
            "amount": 100,
            "category": "Food",
            "transaction_date": "2026-10-12",
        },
    )

    assert response.status_code == 404


def test_user_cannot_read_another_users_report(client):
    register_user(client, "alice@example.com")
    alice_token = login_user(client, "alice@example.com")
    alice_account = get_account_id(client, alice_token)

    register_user(client, "bob@example.com")
    bob_token = login_user(client, "bob@example.com")

    response = client.get(
        f"/accounts/{alice_account}/report",
        headers=auth_header(bob_token),
        params={
            "start_date": "2026-10-01",
            "end_date": "2026-10-12",
        },
    )

    assert response.status_code == 404


def test_invalid_report_date_range_rejected(client):
    register_user(client)
    token = login_user(client)
    account_id = get_account_id(client, token)

    response = client.get(
        f"/accounts/{account_id}/report",
        headers=auth_header(token),
        params={
            "start_date": "2026-10-12",
            "end_date": "2026-10-01",
        },
    )

    assert response.status_code == 422

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

APP_NAME = "Expense Management Chatbot — Financial Security"
DB_PATH = Path(os.getenv("EXPENSE_DB_PATH", "expense_management_chatbot.db"))
JWT_SECRET = os.getenv("EXPENSE_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
TOKEN_MINUTES = 30


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

if APP_ENV not in {"development", "production", "testing"}:
    raise RuntimeError("Invalid APP_ENV configuration")

if APP_ENV == "production" and not os.getenv("EXPENSE_JWT_SECRET"):
    raise RuntimeError(
        "EXPENSE_JWT_SECRET must be configured in production"
    )

if APP_ENV == "production" and len(JWT_SECRET) < 32:
    raise RuntimeError(
        "EXPENSE_JWT_SECRET must be at least 32 characters"
    )


app = FastAPI(
    title="Expense Management Chatbot",
    description=(
        "Starter backend for authentication, account ownership enforcement, "
        "and secure financial report filtering."
    ),
    version="1.0.0",
)

bearer_scheme = HTTPBearer(auto_error=False)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(owner_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL
                    CHECK(transaction_type IN ('income', 'expense')),
                amount REAL NOT NULL CHECK(amount > 0),
                category TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                transaction_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_accounts_owner
                ON accounts(owner_user_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_account_date
                ON transactions(account_id, transaction_date);
            """
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=APP_NAME,
    description=(
        "Starter backend for authentication, account ownership enforcement, "
        "and secure financial report filtering."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
# Configure these environment variables in deployment.
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

allowed_hosts = [
    host.strip()
    for host in os.getenv(
        "ALLOWED_HOSTS",
        "localhost,127.0.0.1,testserver"
    ).split(",")
    if host.strip()
]

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=allowed_hosts,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)



def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return hmac.compare_digest(actual, expected)


def create_access_token(user_id: int) -> str:
    now = utc_now()
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is no longer available",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"id": user["id"], "email": user["email"]}


def require_owned_account(account_id: int, user_id: int) -> dict:
    # Critical authorization check: account ownership is part of the query.
    with get_connection() as conn:
        account = conn.execute(
            """
            SELECT id, owner_user_id, name
            FROM accounts
            WHERE id = ? AND owner_user_id = ?
            """,
            (account_id, user_id),
        ).fetchone()

    # 404 avoids confirming whether another customer's account exists.
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return dict(account)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    account_name: str = Field(default="My Account", min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        value = value.lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid email address")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str


class TransactionCreate(BaseModel):
    transaction_type: Literal["income", "expense"]
    amount: float = Field(gt=0, le=1_000_000_000)
    category: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)
    transaction_date: date


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "expense-management-chatbot-security"}


@app.post("/auth/register", status_code=201)
def register(body: RegisterRequest) -> dict:
    now = utc_now().isoformat()
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (email, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (body.email, hash_password(body.password), now),
            )
            user_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO accounts (owner_user_id, name, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, body.account_name, now),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email is already registered")

    return {
        "message": "Registration successful. Please log in.",
        "user_id": user_id,
    }


@app.post("/auth/login")
def login(body: LoginRequest) -> dict:
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (body.email.strip().lower(),),
        ).fetchone()

    # Same error for unknown email and incorrect password.
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "access_token": create_access_token(user["id"]),
        "token_type": "bearer",
        "expires_in_seconds": TOKEN_MINUTES * 60,
    }


@app.get("/me")
def me(current_user: dict = Depends(get_current_user)) -> dict:
    return {"user_id": current_user["id"], "email": current_user["email"]}


@app.get("/accounts")
def list_my_accounts(current_user: dict = Depends(get_current_user)) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, created_at
            FROM accounts
            WHERE owner_user_id = ?
            ORDER BY id
            """,
            (current_user["id"],),
        ).fetchall()

    return {"accounts": [dict(row) for row in rows]}


@app.post("/accounts/{account_id}/transactions", status_code=201)
def create_transaction(
    account_id: int,
    body: TransactionCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    require_owned_account(account_id, current_user["id"])
    now = utc_now().isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transactions
                (account_id, transaction_type, amount, category, note,
                 transaction_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                body.transaction_type,
                body.amount,
                body.category,
                body.note,
                body.transaction_date.isoformat(),
                now,
            ),
        )
        transaction_id = cursor.lastrowid

    return {
        "message": "Transaction recorded",
        "transaction_id": transaction_id,
        "account_id": account_id,
        "transaction_type": body.transaction_type,
        "amount": body.amount,
        "transaction_date": body.transaction_date.isoformat(),
        "data_mode": "user_entered_database_record",
    }


@app.get("/accounts/{account_id}/report")
def account_report(
    account_id: int,
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    account = require_owned_account(account_id, current_user["id"])

    if start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date",
        )

    # Exclusive next-day boundary includes all timestamps on end_date.
    end_exclusive = (end_date + timedelta(days=1)).isoformat()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT transaction_type, COALESCE(SUM(amount), 0) AS total
            FROM transactions
            WHERE account_id = ?
              AND transaction_date >= ?
              AND transaction_date < ?
            GROUP BY transaction_type
            """,
            (account["id"], start_date.isoformat(), end_exclusive),
        ).fetchall()

        transactions = conn.execute(
            """
            SELECT id, transaction_type, amount, category, note, transaction_date
            FROM transactions
            WHERE account_id = ?
              AND transaction_date >= ?
              AND transaction_date < ?
            ORDER BY transaction_date, id
            """,
            (account["id"], start_date.isoformat(), end_exclusive),
        ).fetchall()

    totals = {"income": 0.0, "expense": 0.0}
    for row in rows:
        totals[row["transaction_type"]] = float(row["total"])

    return {
        "account": {"id": account["id"], "name": account["name"]},
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "income_total": round(totals["income"], 2),
        "expense_total": round(totals["expense"], 2),
        "net_total": round(totals["income"] - totals["expense"], 2),
        "transactions": [dict(row) for row in transactions],
        "data_mode": "user_entered_database_records",
        "note": "Totals reflect only this authorized account and requested period.",
    }

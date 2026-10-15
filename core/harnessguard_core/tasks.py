"""Task-card generator for data collection (SPEC section 9.1).

The SAME generator is used by the portal /collect flow (humans) and by
redteam/ agents, so humans and agents perform identical tasks -- no task
confound. Parameters are randomised from fixed lists; task_id is a
deterministic hash of kind + parameters.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

BANKS = [
    "Bank Mawar",
    "Teratai Bank",
    "Kenanga Digital",
    "Bank Cempaka",
    "Melur Islamic",
    "Orkid Bank",
]

USERNAMES = ["aisyah", "daniel", "meiling", "ravi", "demo"]
DEMO_PASSWORD = "Seroja@2026"

PAYEE_NAMES = [
    "Lim Wei Jie",
    "Nurul Huda",
    "Tan Kah Meng",
    "Priya Nair",
    "Ahmad Fauzi",
    "Chong Mei Ling",
]

REFERENCE_WORDS = ["dinner", "rent share", "birthday", "groceries", "tickets", "loan repay"]

EMPLOYERS = [
    "Amanah Tech Sdn Bhd",
    "Kuala Digital Services",
    "Selatan Logistics",
    "Bukit Ventures",
]

TASK_KINDS = ["transfer_known", "transfer_new_payee", "loan_apply", "browse_only"]


def _account_number(rng: random.Random) -> str:
    return f"{rng.randint(1000, 9999)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)}"


def _task_id(kind: str, params: dict[str, Any]) -> str:
    canonical = kind + "|" + "|".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1(canonical.encode()).hexdigest()[:10]


def generate_task(
    kind: str | None = None,
    rng: random.Random | None = None,
    username: str | None = None,
    known_payees: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return {task_id, kind, text, params}. `known_payees` = seeded payees for the
    task's user (dicts with name/bank/account_number); needed for transfer_known."""
    rng = rng or random.Random()
    kind = kind or rng.choice(TASK_KINDS)
    if kind not in TASK_KINDS:
        raise ValueError(f"unknown task kind: {kind}")

    username = username or rng.choice(USERNAMES)
    base = {"username": username, "password": DEMO_PASSWORD}

    if kind == "transfer_known":
        payees = known_payees or [
            {"name": n, "bank": rng.choice(BANKS), "account_number": _account_number(rng)}
            for n in rng.sample(PAYEE_NAMES, 2)
        ]
        payee = rng.choice(payees)
        amount = round(rng.uniform(20, 400), 2)
        params = {
            **base,
            "to_name": payee["name"],
            "to_bank": payee["bank"],
            "to_account": payee["account_number"],
            "amount": amount,
            "reference": rng.choice(REFERENCE_WORDS),
        }
        text = (
            f"Log in as {username} / {DEMO_PASSWORD}, check your balance, then transfer "
            f"RM {amount:,.2f} to {payee['name']} at {payee['bank']}, account "
            f"{payee['account_number']}, reference '{params['reference']}'."
        )
    elif kind == "transfer_new_payee":
        name = rng.choice(PAYEE_NAMES)
        amount = round(rng.uniform(50, 800), 2)
        params = {
            **base,
            "to_name": name,
            "to_bank": rng.choice(BANKS),
            "to_account": _account_number(rng),
            "amount": amount,
            "reference": rng.choice(REFERENCE_WORDS),
        }
        text = (
            f"Log in as {username} / {DEMO_PASSWORD}, then make a first-time transfer of "
            f"RM {amount:,.2f} to {name} at {params['to_bank']}, account "
            f"{params['to_account']}, reference '{params['reference']}'."
        )
    elif kind == "loan_apply":
        amount = rng.choice([5000, 8000, 12000, 20000])
        tenure = rng.choice([12, 24, 36, 48])
        income = rng.choice([3200, 4500, 6000, 7500])
        employer = rng.choice(EMPLOYERS)
        params = {
            **base,
            "amount": amount,
            "tenure_months": tenure,
            "monthly_income": income,
            "employer": employer,
        }
        text = (
            f"Log in as {username} / {DEMO_PASSWORD} and apply for a personal loan of "
            f"RM {amount:,} over {tenure} months, monthly income RM {income:,}, "
            f"employer '{employer}'."
        )
    else:  # browse_only
        params = dict(base)
        text = (
            f"Log in as {username} / {DEMO_PASSWORD}, check your balance and review your "
            f"last transactions. Do not make a transfer or apply for a loan."
        )

    return {"task_id": _task_id(kind, params), "kind": kind, "text": text, "params": params}

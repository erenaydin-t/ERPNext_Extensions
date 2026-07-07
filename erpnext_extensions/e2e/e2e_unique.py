"""Unique identifiers for isolated Playwright / bench E2E data."""

from __future__ import annotations

import random
import time


def e2e_run_id() -> str:
	"""Millisecond timestamp + random suffix (safe for parallel workers)."""
	return f"{int(time.time() * 1000)}-{random.randint(10000, 99999)}"


def e2e_unique_tag(prefix: str = "E2E") -> str:
	prefix = (prefix or "E2E").strip().replace(" ", "-")
	return f"{prefix}-{e2e_run_id()}"


def e2e_unique_cheque_no(prefix: str = "CHQ") -> str:
	"""Cheque number / import key — never reuse across suites."""
	return e2e_unique_tag(prefix)[:140]


def e2e_unique_name(prefix: str, *, max_len: int = 140) -> str:
	return e2e_unique_tag(prefix)[:max_len]

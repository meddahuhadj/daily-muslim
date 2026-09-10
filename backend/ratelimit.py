"""Limiteur mémoire à fenêtre glissante, par clé (typiquement une IP).

Aucune dépendance externe : complet en stdlib. Sert à la fois les sessions
(`/api/session`) et l'assistant AI (`/api/assistant`, coûteux).
"""

from __future__ import annotations

import time
from collections import deque


class SlidingWindowRateLimiter:
    """Autorise jusqu'à `max_hits` appels dans une fenêtre de `window` secondes."""

    def __init__(self, window: float = 60.0, max_hits: int = 12) -> None:
        self.window = window
        self.max_hits = max_hits
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        dq = self._hits.setdefault(key, deque())
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if len(dq) >= self.max_hits:
            return False
        dq.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


def client_ip(request) -> str:
    """IP du client en respectant le proxy (x-forwarded-for, premier saut)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.client.host if request.client else "?")
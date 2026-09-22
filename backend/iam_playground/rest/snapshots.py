"""Process-local account images used only by the stale-read fault.

The image is one committed mutation behind. It is not durable across restart.
"""

from __future__ import annotations

import copy
import threading


class AccountSnapshots:
    def __init__(self) -> None:
        self._prior: dict[str, tuple[dict, ...]] = {}
        self._lock = threading.Lock()

    def rotate(self, app_id: str, before: list[dict]) -> None:
        frozen = tuple(copy.deepcopy(item) for item in before)
        with self._lock:
            self._prior[app_id] = frozen

    def prior(self, app_id: str) -> tuple[dict, ...]:
        with self._lock:
            found = self._prior.get(app_id)
        if found is None:
            return ()
        return tuple(copy.deepcopy(item) for item in found)

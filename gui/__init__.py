from __future__ import annotations

from datetime import datetime

_action_callbacks: list = []


def _register_log_callback(cb) -> None:
    if cb not in _action_callbacks:
        _action_callbacks.append(cb)


def _unregister_log_callback(cb) -> None:
    if cb in _action_callbacks:
        _action_callbacks.remove(cb)


def log_action(message: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"{ts} [{level}] [UI] {message}"
    print(formatted, flush=True)
    for cb in list(_action_callbacks):
        try:
            cb(level, formatted)
        except Exception:
            pass

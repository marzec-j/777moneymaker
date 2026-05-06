"""
BrainJournal — trwały magazyn rekomendacji BrainBota, notatek uczenia i historii czatu.
Thread-safe, atomowy zapis (tmp → rename).
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


class BrainJournal:

    def __init__(self, config: dict):
        data_dir = Path(config.get("data", {}).get("data_dir", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / "brain_journal.json"
        self._lock = threading.Lock()
        self._data = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    return raw
            except Exception:
                pass
        return {
            "recommended_now":    [],
            "watch_later":        [],
            "learning_notes":     [],
            "chat_history":       [],
            "user_guidance":      "",
            "last_scan_ts":       None,
            "top_universe":       [],
            "last_full_scan_date": None,
            "stats": {"total_scanned": 0, "recommended_count": 0},
        }

    def _save(self):
        try:
            tmp = self._path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
        except Exception:
            pass

    # ── Read API ──────────────────────────────────────────────────────────────

    def get_recommended_symbols(self) -> list[str]:
        with self._lock:
            return [r["symbol"] for r in self._data.get("recommended_now", [])]

    def get_recommended_now(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("recommended_now", []))

    def get_watch_later(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("watch_later", []))

    def get_learning_notes(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("learning_notes", []))

    def get_chat_history(self) -> list[dict]:
        with self._lock:
            return list(self._data.get("chat_history", []))

    def get_user_guidance(self) -> str:
        with self._lock:
            return self._data.get("user_guidance", "")

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._data.get("stats", {}))

    def get_last_scan_ts(self):
        with self._lock:
            return self._data.get("last_scan_ts")

    def get_top_universe(self) -> list[str]:
        with self._lock:
            return list(self._data.get("top_universe", []))

    def get_last_full_scan_date(self) -> Optional[str]:
        with self._lock:
            return self._data.get("last_full_scan_date")

    def read_all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    # ── Write API ─────────────────────────────────────────────────────────────

    def update_recommendations(
        self,
        recommended: list[dict],
        watch_later: list[dict],
        total_scanned: int = 0,
    ):
        with self._lock:
            self._data["recommended_now"] = recommended[:50]
            self._data["watch_later"]     = watch_later[:100]
            self._data["last_scan_ts"]    = _now_iso()
            stats = self._data.setdefault("stats", {})
            stats["recommended_count"] = len(recommended)
            stats["total_scanned"]     = total_scanned
            self._save()

    def set_top_universe(self, symbols: list[str]):
        with self._lock:
            self._data["top_universe"] = list(symbols)
            self._save()

    def set_last_full_scan_date(self, date_str: str):
        with self._lock:
            self._data["last_full_scan_date"] = date_str
            self._save()

    def add_learning_note(self, symbol: str, predicted: str, result: str, lesson: str):
        with self._lock:
            notes = self._data.setdefault("learning_notes", [])
            notes.append({
                "ts":        _now_iso(),
                "symbol":    symbol,
                "predicted": predicted,
                "result":    result,
                "lesson":    lesson,
            })
            if len(notes) > 200:
                self._data["learning_notes"] = notes[-200:]
            self._save()

    def add_chat_message(self, role: str, content: str):
        with self._lock:
            history = self._data.setdefault("chat_history", [])
            history.append({"ts": _now_iso(), "role": role, "content": content})
            if len(history) > 500:
                self._data["chat_history"] = history[-500:]
            self._save()

    def set_user_guidance(self, guidance: str):
        with self._lock:
            self._data["user_guidance"] = guidance[:1000]
            self._save()

    def append_user_guidance(self, extra: str):
        with self._lock:
            current = self._data.get("user_guidance", "")
            merged = (current + "\n" + extra).strip()
            self._data["user_guidance"] = merged[-1000:]
            self._save()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")

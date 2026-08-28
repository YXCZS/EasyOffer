from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CorpusRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "registry.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"batches": {}, "approvals": {}, "evaluations": {}, "active_version": None, "withdrawals": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp.replace(self.path)

    def record_batch(self, batch_id: str, value: dict[str, Any]) -> None:
        registry = self.load()
        registry.setdefault("batches", {})[batch_id] = value
        self.save(registry)

    def latest_batch_for(self, corpus_version: str) -> dict[str, Any] | None:
        matches = [
            item for item in self.load().get("batches", {}).values()
            if item.get("corpus_version") == corpus_version and item.get("mode") == "ingest"
        ]
        return matches[-1] if matches else None

    def approve(self, corpus_version: str, approval: dict[str, Any]) -> None:
        registry = self.load()
        registry.setdefault("approvals", {})[corpus_version] = approval
        self.save(registry)

    def approval(self, corpus_version: str) -> dict[str, Any] | None:
        return self.load().get("approvals", {}).get(corpus_version)

    def record_evaluation(self, corpus_version: str, evaluation: dict[str, Any]) -> None:
        registry = self.load()
        registry.setdefault("evaluations", {})[corpus_version] = evaluation
        self.save(registry)

    def evaluation(self, corpus_version: str) -> dict[str, Any] | None:
        return self.load().get("evaluations", {}).get(corpus_version)

    def active_version(self) -> str | None:
        return self.load().get("active_version")

    def set_active(self, corpus_version: str | None) -> None:
        registry = self.load()
        registry["active_version"] = corpus_version
        self.save(registry)

    def withdraw(self, corpus_version: str, reason: str, at: str) -> None:
        registry = self.load()
        registry.setdefault("withdrawals", {})[corpus_version] = {"reason": reason, "at": at}
        if registry.get("active_version") == corpus_version:
            registry["active_version"] = None
        self.save(registry)

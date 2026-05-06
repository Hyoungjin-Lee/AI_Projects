"""pending_proposals.py - 매수 제안 5상태 전이 관리."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).parent.parent
_DEFAULT_FILE = _ROOT / "data" / "pending_proposals.json"

_VALID_STATUSES = {"pending", "accepted", "declined", "exhausted", "expired"}
_TERMINAL_STATUSES = {"accepted", "declined", "exhausted", "expired"}


def _atomic_dump_json(path: Path, data: dict[str, Any]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _backup_corrupt_file(path: Path) -> None:
    backup = path.with_suffix(".json.corrupt")
    try:
        path.replace(backup)
    except OSError:
        pass


@dataclass
class Proposal:
    id: str
    code: str
    name: str
    round: int
    rank: int
    stage: str
    score: float
    tday_rltv: float
    chg: float
    price_ref: float
    top5: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"
    count: int = 0
    created_at: str = ""
    last_sent: str = ""
    resolved_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        status = str(data.get("status", "pending"))
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return cls(
            id=str(data["id"]),
            code=str(data["code"]),
            name=str(data["name"]),
            round=int(data["round"]),
            rank=int(data["rank"]),
            stage=str(data["stage"]),
            score=float(data.get("score", 0)),
            tday_rltv=float(data.get("tday_rltv", 0)),
            chg=float(data.get("chg", 0)),
            price_ref=float(data["price_ref"]),
            top5=list(data.get("top5") or []),
            status=status,
            count=int(data.get("count", 0)),
            created_at=str(data.get("created_at", "")),
            last_sent=str(data.get("last_sent", "")),
            resolved_at=data.get("resolved_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "round": self.round,
            "rank": self.rank,
            "stage": self.stage,
            "score": self.score,
            "tday_rltv": self.tday_rltv,
            "chg": self.chg,
            "price_ref": self.price_ref,
            "top5": list(self.top5),
            "status": self.status,
            "count": self.count,
            "created_at": self.created_at,
            "last_sent": self.last_sent,
            "resolved_at": self.resolved_at,
        }


class PendingProposalsStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else _DEFAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.proposals: list[Proposal] = []
        self._load()

    @classmethod
    def load(cls, path: Path | None = None) -> "PendingProposalsStore":
        return cls(path=path)

    def _load(self) -> None:
        if not self._path.exists():
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _backup_corrupt_file(self._path)
            return

        for payload in (raw.get("proposals") or []):
            try:
                self.proposals.append(Proposal.from_dict(payload))
            except (KeyError, TypeError, ValueError):
                continue

    def persist(self) -> None:
        _atomic_dump_json(
            self._path,
            {"proposals": [proposal.to_dict() for proposal in self.proposals]},
        )

    def get(self, proposal_id: str) -> Proposal | None:
        for proposal in self.proposals:
            if proposal.id == proposal_id:
                return proposal
        return None

    def peek_oldest_pending(self) -> Proposal | None:
        candidates = [proposal for proposal in self.proposals if proposal.status == "pending"]
        if not candidates:
            return None
        return min(candidates, key=lambda proposal: proposal.created_at)

    def pending_ids(self) -> list[str]:
        return [proposal.id for proposal in self.proposals if proposal.status == "pending"]

    def enqueue(self, proposal: Proposal) -> None:
        if self.get(proposal.id) is not None:
            raise ValueError(f"duplicate proposal id: {proposal.id}")
        if proposal.status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {proposal.status}")
        self.proposals.append(proposal)

    def transition(
        self,
        proposal_id: str,
        new_status: str,
        at: datetime | None = None,
    ) -> Proposal:
        if new_status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {new_status}")

        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        if proposal.status in _TERMINAL_STATUSES:
            raise ValueError(f"{proposal_id} already in terminal state: {proposal.status}")

        proposal.status = new_status
        if new_status in _TERMINAL_STATUSES:
            proposal.resolved_at = (at or datetime.now()).isoformat(timespec="seconds")
        return proposal

    def increment_count(self, proposal_id: str, at: datetime | None = None) -> int:
        proposal = self.get(proposal_id)
        if proposal is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        if proposal.status != "pending":
            raise ValueError(f"cannot increment count on status={proposal.status}")

        proposal.count += 1
        proposal.last_sent = (at or datetime.now()).isoformat(timespec="seconds")
        return proposal.count

    def cleanup_expired_on_boot(self, cutoff: datetime) -> list[Proposal]:
        expired: list[Proposal] = []
        resolved_at = datetime.now().isoformat(timespec="seconds")
        for proposal in self.proposals:
            if proposal.status != "pending" or not proposal.last_sent:
                continue
            try:
                sent_at = datetime.fromisoformat(proposal.last_sent)
            except ValueError:
                continue
            if sent_at < cutoff:
                proposal.status = "expired"
                proposal.resolved_at = resolved_at
                expired.append(proposal)
        return expired

    def cleanup_on_boot(self, cutoff: datetime) -> list[Proposal]:
        return self.cleanup_expired_on_boot(cutoff)

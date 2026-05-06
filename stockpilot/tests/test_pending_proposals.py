from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MORNING_REPORT_DIR = PROJECT_ROOT / "morning_report"
if str(MORNING_REPORT_DIR) not in sys.path:
    sys.path.insert(0, str(MORNING_REPORT_DIR))

from pending_proposals import PendingProposalsStore, Proposal


def _proposal(
    proposal_id: str,
    *,
    code: str = "005930",
    stage: str = "최초진입",
    created_at: str,
) -> Proposal:
    return Proposal(
        id=proposal_id,
        code=code,
        name="삼성전자",
        round=2,
        rank=1,
        stage=stage,
        score=85.0,
        tday_rltv=125.0,
        chg=3.2,
        price_ref=87200.0,
        top5=[{"code": code}],
        created_at=created_at,
        last_sent=created_at,
    )


def test_enqueue_and_peek(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    first = _proposal("p1", created_at="2026-04-23T09:00:00")
    second = _proposal("p2", created_at="2026-04-23T09:01:00")
    third = _proposal("p3", created_at="2026-04-23T09:02:00")

    store.enqueue(second)
    store.enqueue(third)
    store.enqueue(first)

    assert store.get("p1") == first
    assert store.peek_oldest_pending() == first


def test_duplicate_id_rejected(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    store.enqueue(_proposal("p1", created_at="2026-04-23T09:00:00"))

    with pytest.raises(ValueError, match="duplicate proposal id"):
        store.enqueue(_proposal("p1", created_at="2026-04-23T09:01:00"))


def test_transition_to_terminal(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    store.enqueue(_proposal("p1", created_at="2026-04-23T09:00:00"))

    accepted = store.transition("p1", "accepted", at=datetime(2026, 4, 23, 9, 5, 0))

    assert accepted.status == "accepted"
    assert accepted.resolved_at == "2026-04-23T09:05:00"

    with pytest.raises(ValueError, match="already in terminal state"):
        store.transition("p1", "declined")


def test_increment_count(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    store.enqueue(_proposal("p1", created_at="2026-04-23T09:00:00"))

    count = store.increment_count("p1", at=datetime(2026, 4, 23, 9, 2, 0))

    assert count == 1
    assert store.get("p1").count == 1
    assert store.get("p1").last_sent == "2026-04-23T09:02:00"


def test_increment_on_non_pending_rejected(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    store.enqueue(_proposal("p1", created_at="2026-04-23T09:00:00"))
    store.transition("p1", "accepted")

    with pytest.raises(ValueError, match="cannot increment count"):
        store.increment_count("p1")


def test_cleanup_expired_on_boot(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    cutoff = datetime(2026, 4, 23, 9, 5, 0)

    expired_target = _proposal("expired-target", created_at="2026-04-23T09:00:00")
    expired_target.last_sent = "2026-04-23T08:59:59"

    fresh_pending = _proposal("fresh-pending", created_at="2026-04-23T09:04:30")
    fresh_pending.last_sent = "2026-04-23T09:05:00"

    declined = _proposal("declined", created_at="2026-04-23T09:00:00")
    declined.status = "declined"
    declined.resolved_at = "2026-04-23T09:01:00"

    store.enqueue(expired_target)
    store.enqueue(fresh_pending)
    store.enqueue(declined)

    expired = store.cleanup_expired_on_boot(cutoff)

    assert [proposal.id for proposal in expired] == ["expired-target"]
    assert store.get("expired-target").status == "expired"
    assert store.get("fresh-pending").status == "pending"
    assert store.get("declined").status == "declined"


def test_same_code_different_stage(tmp_path):
    store = PendingProposalsStore(path=tmp_path / "pending_proposals.json")
    first = _proposal("2-005930-1", stage="최초진입", created_at="2026-04-23T09:00:00")
    second = _proposal(
        "2-005930-2",
        stage="1차_추가매수",
        created_at="2026-04-23T09:01:00",
    )

    store.enqueue(first)
    store.enqueue(second)

    assert store.get("2-005930-1").stage == "최초진입"
    assert store.get("2-005930-2").stage == "1차_추가매수"


def test_persist_roundtrip(tmp_path):
    path = tmp_path / "pending_proposals.json"
    store = PendingProposalsStore(path=path)
    store.enqueue(_proposal("p1", created_at="2026-04-23T09:00:00"))
    store.increment_count("p1", at=datetime(2026, 4, 23, 9, 1, 0))
    store.persist()

    restored = PendingProposalsStore(path=path)

    assert restored.get("p1") is not None
    assert restored.get("p1").count == 1
    assert restored.get("p1").last_sent == "2026-04-23T09:01:00"


def test_corrupt_file_backup(tmp_path):
    path = tmp_path / "pending_proposals.json"
    path.write_text("{broken", encoding="utf-8")

    store = PendingProposalsStore(path=path)

    assert store.proposals == []
    assert not path.exists()
    assert path.with_suffix(".json.corrupt").exists()

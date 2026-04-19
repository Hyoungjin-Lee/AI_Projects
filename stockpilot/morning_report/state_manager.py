"""
state_manager.py — 실행 에이전트 간 공유 상태 관리

역할:
  - 당일 daily_state.json 읽기/쓰기 인터페이스 제공
  - 날짜가 바뀌면 자동으로 초기화
  - 5개 스크립트가 공통으로 import하여 당일 컨텍스트 공유

사용법:
  from state_manager import StateManager
  state = StateManager()
  state.update("market", {"us_sentiment": "강세"})
  sentiment = state.get("market.us_sentiment", "혼조")
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_STATE_FILE = _ROOT / "data" / "daily_state.json"

_EMPTY_STATE = {
    "date": "",
    "market": {
        "us_sentiment": None,
        "usd_krw": None,
        "fear_greed": None,
    },
    "holdings": {},       # {code: {"signal": "BUY"|"SELL"|"HOLD"|"WATCH", "pnl_pct": float}}
    "alerts": {
        "intraday": None, # 장초기 이상 감지 메시지
        "vol_spike": [],  # 거래량 급등 종목 코드 리스트
    },
    "discovery": {
        "candidates": [],  # 발굴된 종목 코드 리스트
        "top_pick": None,
    },
    "watchlist_changed": False,
    "last_updated_by": None,
    "last_updated_at": None,
}


class StateManager:
    """당일 공유 상태 읽기/쓰기 관리자."""

    def __init__(self):
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    # ── 읽기 ──────────────────────────────────────────────────────────────────

    def get_today_state(self) -> dict:
        """오늘 전체 상태 반환."""
        return self._state

    def get(self, key_path: str, default=None):
        """
        점(.) 구분 키 경로로 값 조회.
        예: state.get("market.us_sentiment")
            state.get("holdings.017960.signal")
        """
        keys = key_path.split(".")
        val = self._state
        for k in keys:
            if not isinstance(val, dict) or k not in val:
                return default
            val = val[k]
        return val if val is not None else default

    # ── 쓰기 ──────────────────────────────────────────────────────────────────

    def update(self, section: str, data: dict, caller: str = None) -> None:
        """
        특정 섹션을 업데이트하고 파일에 저장.
        예: state.update("market", {"us_sentiment": "강세"})
        """
        if section not in self._state:
            self._state[section] = {}

        if isinstance(self._state[section], dict) and isinstance(data, dict):
            self._state[section].update(data)
        else:
            self._state[section] = data

        self._state["last_updated_by"] = caller or _caller_name()
        self._state["last_updated_at"] = datetime.now().strftime("%H:%M")
        self._save()

    def set_alert(self, alert_type: str, message: str, caller: str = None) -> None:
        """
        알림 설정.
        alert_type: "intraday" | "vol_spike"
        """
        if alert_type == "vol_spike":
            if message not in self._state["alerts"]["vol_spike"]:
                self._state["alerts"]["vol_spike"].append(message)
        else:
            self._state["alerts"][alert_type] = message

        self._state["last_updated_by"] = caller or _caller_name()
        self._state["last_updated_at"] = datetime.now().strftime("%H:%M")
        self._save()

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        """파일 로드. 날짜 다르면 초기화, 없으면 새로 생성."""
        today = datetime.now().strftime("%Y%m%d")

        if not _STATE_FILE.exists():
            state = dict(_EMPTY_STATE)
            state["date"] = today
            return state

        try:
            raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if raw.get("date") != today:
                # 날짜 바뀌면 초기화
                print(f"[state] 날짜 변경 감지 ({raw.get('date')} → {today}), 상태 초기화", file=sys.stderr)
                state = json.loads(json.dumps(_EMPTY_STATE))  # deep copy
                state["date"] = today
                return state
            # 기존 키 누락분 보완 (버전 업 대비)
            merged = json.loads(json.dumps(_EMPTY_STATE))
            _deep_merge(merged, raw)
            merged["date"] = today
            return merged
        except Exception as e:
            print(f"[state] 로드 실패, 초기화: {e}", file=sys.stderr)
            state = json.loads(json.dumps(_EMPTY_STATE))
            state["date"] = today
            return state

    def _save(self) -> None:
        """현재 상태를 파일에 저장."""
        try:
            _STATE_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[state] 저장 실패: {e}", file=sys.stderr)


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> None:
    """override의 값을 base에 재귀적으로 병합."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _caller_name() -> str:
    """호출한 스크립트 파일명 추출."""
    try:
        return Path(sys.argv[0]).stem
    except Exception:
        return "unknown"


# ── 직접 실행 시 상태 출력 ────────────────────────────────────────────────────

if __name__ == "__main__":
    state = StateManager()
    print("=" * 40)
    print("📊 오늘의 공유 상태")
    print("=" * 40)
    print(json.dumps(state.get_today_state(), ensure_ascii=False, indent=2))

# Stage 5: 기술 설계 — 에이전트 아키텍처 개선

> 날짜: 2026-04-19 | 담당: Claude Sonnet | Effort: High
> 기존 소스 유지 + 신규 기능 추가 방식

---

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                   stockpilot v2.0                    │
│                                                       │
│  ┌─────────────┐    ┌──────────────────────────────┐ │
│  │  launchd    │    │     telegram_bot.py (데몬)    │ │
│  │  스케줄러   │    │     orchestrator.py           │ │
│  └──────┬──────┘    └──────────────┬───────────────┘ │
│         │                          │                  │
│  ┌──────▼──────────────────────────▼──────────────┐  │
│  │            daily_state.json (공유 상태)          │  │
│  └──────┬──────────────────────────────────────────┘  │
│         │                                              │
│  ┌──────▼──────────────────────────────────────────┐  │
│  │              실행 에이전트 팀                     │  │
│  │  watchlist_sync → morning → intraday             │  │
│  │  closing → stock_discovery                       │  │
│  └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 1. state_manager.py 설계

**경로:** `morning_report/state_manager.py`

**역할:** daily_state.json의 읽기/쓰기 공통 인터페이스

```python
# 인터페이스 설계
class StateManager:
    def get_today_state() -> dict          # 오늘 상태 읽기 (날짜 다르면 초기화)
    def update(section, data) -> None      # 특정 섹션 업데이트
    def get(section, default=None)         # 특정 섹션 읽기
```

**daily_state.json 스키마:**
```json
{
  "date": "20260421",
  "market": {
    "us_sentiment": "강세",
    "usd_krw": 1380.5,
    "fear_greed": 62
  },
  "holdings": {
    "017960": {"signal": "SELL", "pnl_pct": -2.3},
    "443060": {"signal": "BUY",  "pnl_pct": 1.5}
  },
  "alerts": {
    "intraday": null,
    "vol_spike": ["017960"]
  },
  "discovery": {
    "candidates": ["017960", "443060"],
    "top_pick": "443060"
  },
  "last_updated_by": "closing_report",
  "last_updated_at": "20:35"
}
```

**각 스크립트 연동 방식 (기존 코드 최소 수정):**
```python
# 기존 스크립트 상단에 2줄만 추가
from state_manager import StateManager
state = StateManager()

# 쓰기 예시 (morning_report)
state.update("market", {"us_sentiment": us_sentiment})
state.update("holdings", {code: {"signal": verdict} for ...})

# 읽기 예시 (stock_discovery)
us_sentiment = state.get("market.us_sentiment", "혼조")
```

---

## 2. telegram_bot.py + orchestrator.py 설계

**경로:**
- `morning_report/telegram_bot.py` — polling 루프
- `morning_report/orchestrator.py` — 명령 라우팅 + 실행

**telegram_bot.py 구조:**
```python
# polling 방식 (webhook 불필요 — 개인 서버 없음)
def run():
    offset = 0
    while True:
        updates = get_updates(offset)
        for update in updates:
            handle_update(update)
            offset = update["update_id"] + 1
        time.sleep(2)
```

**orchestrator.py 명령 라우팅:**
```python
COMMANDS = {
    "/잔고":   cmd_balance,      # KIS 잔고 조회
    "/상태":   cmd_state,        # daily_state 요약
    "/발굴":   cmd_discovery,    # stock_discovery 즉시 실행
    "/도움말": cmd_help,         # 명령어 목록
}
```

**보안 설계:**
- `TELEGRAM_CHAT_ID` 일치 여부 확인 → 본인만 명령 가능
- 모든 명령 로그 기록 (`logs/bot.log`)
- 실주문 명령 없음 (Phase 2로 분리)

**launchd 등록:**
```xml
<!-- com.aigeenya.stockbot.plist -->
<!-- 부팅 시 자동 시작, 크래시 시 재시작 -->
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
```

---

## 3. WORKFLOW.md 독립 검증 프로토콜

**추가할 섹션:**

```markdown
## 독립 검증 프로토콜 (Stage 11)

Stage 11은 반드시 새 대화창에서 진행한다.

### 검증관에게 전달할 것
- 구현된 코드 파일 경로
- 원래 요구사항 (plan_final.md)
- 테스트 실행 결과

### 전달하지 말 것
- 이전 세션 대화 내용
- 구현 과정에서의 결정 사항
- 개발자의 의도 설명

### 판정 기준
- PASS: 즉시 배포 가능
- CONDITIONAL: 조건부 통과 (경미한 수정 후 배포)
- FAIL: 재구현 필요
```

---

## 4. AGENTS.md 정리 내용

**제거:**
- `kakao_sender.py` 관련 내용
- 구버전 경로

**추가:**
- `telegram_sender.py`, `telegram_bot.py` 설명
- `state_manager.py` 설명
- `orchestrator.py` 설명
- 새 경로 반영

---

## 파일 변경 요약

| 구분 | 파일 | 작업 |
|------|------|------|
| 신규 | `morning_report/state_manager.py` | 새로 작성 |
| 신규 | `morning_report/telegram_bot.py` | 새로 작성 |
| 신규 | `morning_report/orchestrator.py` | 새로 작성 |
| 신규 | `~/Library/LaunchAgents/com.aigeenya.stockbot.plist` | 새로 작성 |
| 수정 | `morning_report/morning_report.py` | state 쓰기 2줄 추가 |
| 수정 | `morning_report/intraday_report.py` | state 읽기/쓰기 추가 |
| 수정 | `morning_report/closing_report.py` | state 읽기/쓰기 추가 |
| 수정 | `morning_report/stock_discovery.py` | state 읽기 추가 |
| 수정 | `WORKFLOW.md` | 독립 검증 프로토콜 섹션 추가 |
| 수정 | `AGENTS.md` | 전면 업데이트 |

---

## 구현 순서 (Stage 8)

1. `state_manager.py` 구현 + 테스트
2. 기존 5개 스크립트에 state 연동 추가
3. `orchestrator.py` 구현
4. `telegram_bot.py` 구현
5. launchd plist 등록
6. `WORKFLOW.md` + `AGENTS.md` 업데이트

---

*다음 단계: Stage 8 구현*

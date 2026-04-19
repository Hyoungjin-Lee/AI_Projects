# 🤝 stockpilot — Handoff 문서

> 최종 업데이트: 2026-04-19 (v2.1 장초기 실시간 종목 발굴 완료)
> 목적: 새 대화창에서 즉시 작업을 이어받을 수 있도록 현재 상태 전달

---

## 1. 프로젝트 개요

한국투자증권(KIS) Open API 기반 주식 자동화 시스템.
평일 자동 브리핑 + **텔레그램 양방향 명령** 지원.

- **프로젝트 경로:** `/Users/geenya/projects/AI_Projects/stockpilot`
- **Python 환경:** `venv/` (Python 3.14)
- **실행 방법:** `venv/bin/python3 morning_report/[스크립트].py`

---

## 2. 자동 실행 스케줄 (launchd, 평일 기준)

| 시각 | 스크립트 | 내용 |
|------|----------|------|
| 08:20 | `watchlist_sync.py` | KIS HTS 관심종목 → watchlist.json + state 기록 |
| 08:30 | `morning_report.py` | 모닝 브리핑 텔레그램 전송 + state 기록 |
| 09:03 | `intraday_discovery.py --round 1` | 장초기 1차 수집 (거래량/체결강도/등락률 상위 30) ← NEW |
| 09:05 | `intraday_discovery.py --round 2` | 2차 수집 → 교집합 → 점수 산정 → 텔레그램 전송 ← NEW |
| 09:10 | `intraday_report.py` | 장초기 현황 텔레그램 전송 + state 기록 |
| 20:30 | `closing_report.py` | 장마감 결산 텔레그램 전송 + state 기록 |
| 23:30 | `stock_discovery.py` | 야간 종목 발굴 텔레그램 전송 + state 기록 (월~토) |
| 상시 | `telegram_bot.py` | 텔레그램 명령 수신 (부팅 시 자동 시작) |

---

## 3. 핵심 파일 구조

```
stockpilot/
├── morning_report/
│   ├── morning_report.py       # 모닝 브리핑 (state 기록 포함)
│   ├── intraday_report.py      # 장초기 브리핑 (state 기록 포함)
│   ├── closing_report.py       # 장마감 결산 (state 기록 포함)
│   ├── stock_discovery.py      # 야간 종목 발굴 (state 기록 포함)
│   ├── watchlist_sync.py       # 관심종목 동기화 (state 기록 포함)
│   ├── telegram_sender.py      # 텔레그램 단방향 전송
│   ├── telegram_bot.py         # 텔레그램 봇 데몬 (양방향 수신)
│   ├── orchestrator.py         # 명령 라우팅 (/잔고 /상태 /발굴 /도움말)
│   ├── state_manager.py        # 에이전트 간 공유 상태 관리
│   ├── intraday_discovery.py   # 장초기 실시간 종목 발굴 (교집합 필터) ← NEW
│   ├── keychain_manager.py     # macOS Keychain 인증정보 관리
│   └── setup_telegram.py       # 텔레그램 최초 설정 도우미
├── .skills/
│   ├── kis-api/scripts/kis_client.py
│   ├── stock-analysis/
│   └── trading-report/
├── data/
│   ├── watchlist.json          # 관심종목
│   ├── daily_state.json        # 에이전트 간 공유 상태 ← NEW
│   └── cache/                  # KIS 토큰 캐시
├── docs/
│   ├── 07_intraday_discovery/  # 장초기 종목 발굴 설계 문서 ← NEW
│   │   ├── technical_design.md # API 파라미터/흐름/스키마 상세
│   │   └── implementation_prompt.md  # Codex 구현 지시서
│   ├── 06_agent_architecture/  # v2.0 에이전트 설계 문서
│   ├── 05_qa_release/          # QA 리포트
│   └── api/                    # KIS API xlsx 문서
├── logs/
│   ├── stockbot.log            # telegram_bot.py stdout ← NEW
│   └── stockbot_error.log      # telegram_bot.py stderr ← NEW
└── ~/Library/LaunchAgents/
    ├── com.aigeenya.stockbot.plist              # 봇 데몬 (상시)
    ├── com.aigeenya.stockreport.plist           # morning 08:30
    ├── com.aigeenya.stockreport.intraday.plist  # intraday 09:10
    ├── com.aigeenya.stockreport.closing.plist   # closing 20:30
    ├── com.aigeenya.stockreport.discovery.plist # 야간 발굴 23:30
    ├── com.aigeenya.stockreport.watchlist.plist # watchlist 08:20
    ├── com.aigeenya.stockreport.discovery1.plist # 장초기 1차 09:03 ← NEW
    └── com.aigeenya.stockreport.discovery2.plist # 장초기 2차 09:05 ← NEW
```

---

## 4. 보안 구조 (Keychain 통합)

### Keychain 저장 항목 (서비스명: `AI주식매매`)

| 키 | 내용 |
|----|------|
| `KIS_APP_KEY` | KIS API 앱키 |
| `KIS_APP_SECRET` | KIS API 앱시크릿 |
| `KIS_ACCOUNT_NO` | 계좌번호 |
| `KIS_HTS_ID` | MTS 로그인 ID |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 chat_id |

### 모든 스크립트 공통 진입점
```python
from keychain_manager import inject_to_env
inject_to_env()  # Keychain → os.environ 자동 주입
```

---

## 5. v2.1 구현 현황 (2026-04-19 완료)

### 구현된 기능

| 구성요소 | 파일 | 상태 |
|---------|------|------|
| 공유 상태 | `state_manager.py` + `data/daily_state.json` | ✅ 완료 |
| 5개 스크립트 state 연동 | morning/intraday/closing/discovery/watchlist | ✅ 완료 |
| 텔레그램 명령 수신 | `telegram_bot.py` | ✅ 완료 |
| 명령 라우팅 | `orchestrator.py` | ✅ 완료 |
| 봇 데몬 launchd | `com.aigeenya.stockbot.plist` | ✅ 완료 |
| AGENTS.md 문서화 | `AGENTS.md` | ✅ 완료 |
| WORKFLOW.md 독립검증 프로토콜 | 섹션 10 | ✅ 완료 |
| **장초기 실시간 종목 발굴** | `intraday_discovery.py` | ✅ 완료 ← NEW |
| launchd 2개 등록 | discovery1(09:03) + discovery2(09:05) | ✅ 완료 ← NEW |
| 기술 설계 문서 | `docs/07_intraday_discovery/` | ✅ 완료 ← NEW |

### 사용 가능한 텔레그램 명령어

```
/잔고    — KIS 잔고 즉시 조회
/상태    — 오늘 시장/시그널 요약
/발굴    — 야간 종목 발굴 즉시 실행
/도움말  — 명령어 목록
```

### daily_state.json 구조

```json
{
  "date": "2026-04-21",
  "market": { "us_sentiment": "...", "usd_krw": 0, "fear_greed": "..." },
  "holdings": { "종목코드": { "signal": "BUY/SELL/HOLD", "pnl_pct": 0.0 } },
  "alerts": { "intraday": "...", "vol_spike": [] },
  "discovery": { "candidates": [], "top_pick": "..." },
  "watchlist_changed": false,
  "intraday_discovery": {
    "round1_at": "09:03",
    "round2_at": "09:05",
    "candidates_r1": ["종목코드", ...],
    "final_picks": [{"code": "...", "name": "...", "score": 0, "reason": "..."}]
  }
}
```

---

## 6. 등록 완료된 launchd 에이전트

모든 plist가 `~/Library/LaunchAgents/`에 등록되어 있습니다.

```bash
# 전체 등록 상태 확인
launchctl list | grep aigeenya
```

예상 출력:
```
PID   Status  Label
XXXXX  0  com.aigeenya.stockbot               ← 상시 실행
-      0  com.aigeenya.stockreport            ← 08:30
-      0  com.aigeenya.stockreport.watchlist  ← 08:20
-      0  com.aigeenya.stockreport.discovery1 ← 09:03 ← NEW
-      0  com.aigeenya.stockreport.discovery2 ← 09:05 ← NEW
-      0  com.aigeenya.stockreport.intraday   ← 09:10
-      0  com.aigeenya.stockreport.closing    ← 20:30
-      0  com.aigeenya.stockreport.discovery  ← 23:30
```

### 부팅 후 봇 재시작 확인

```bash
launchctl list | grep stockbot
tail -20 /Users/geenya/projects/AI_Projects/stockpilot/logs/stockbot_error.log
```

---

## 7. 다음 세션에서 할 작업

> **현재 상태: v2.1 장초기 실시간 종목 발굴 완료 ✅**
> **월요일(2026-04-21) 장 시작 후 09:03/09:05 실제 API 동작 검증 예정**

### 🔴 우선 확인 (2026-04-21 오전)
- [ ] 09:03 `intraday_discovery.py --round 1` 실행 확인
  - `tail -f logs/intraday_discovery.log`
- [ ] 09:05 `intraday_discovery.py --round 2` + 텔레그램 전송 확인
- [ ] `FID_INPUT_ISCD=2001` 거래량순위 API 지원 여부 확인
  - 에러 시 fallback(`FID_INPUT_ISCD=0000`) 자동 전환 확인
- [ ] HTS조회상위 TR_ID 실제 테스트 (실패 시 건너뜀 동작 확인)

### 운영 모니터링 (지속)
- [ ] `morning_report.py` 08:30 자동 실행 확인
- [ ] `/잔고`, `/상태` 명령 텔레그램에서 테스트
- [ ] `closing_report.py` 20:30 자동 실행 + state 기록 확인

### 다음 프로젝트 후보
- [ ] intraday_discovery 조건 고도화 (이격도 실시간 필터 강화)
- [ ] stock_discovery 스크리닝 조건 고도화 (기술적 지표 추가)
- [ ] 보유 종목 자동 매도 시그널 (Phase 2 — 실주문 포함)
- [ ] 텔레그램 `/매수`, `/매도` 명령 구현 (Phase 2)

---

## 8. 주요 명령어 모음

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트 (전송 없이)
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run
venv/bin/python3 morning_report/intraday_report.py --dry-run

# 장초기 발굴 수동 테스트 (dry-run)
venv/bin/python3 morning_report/intraday_discovery.py --round 1 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run

# 봇 1회 테스트 (텔레그램 명령 수신 확인)
venv/bin/python3 morning_report/telegram_bot.py --once

# 공유 상태 확인
venv/bin/python3 morning_report/state_manager.py

# Keychain 확인
venv/bin/python3 morning_report/keychain_manager.py

# 봇 데몬 상태 확인
launchctl list | grep aigeenya

# 로그 확인
tail -50 logs/stockbot_error.log
tail -50 logs/intraday_discovery.log
tail -50 logs/intraday_discovery_error.log
tail -50 logs/closing_report.log

# GitHub 업로드 (보안 검사 포함)
aigit_upload  # ~/.zshrc alias
```

---

## 9. 전체 작업 히스토리 (누적)

1. 장마감 시간 변경: 16:00 → 20:30
2. watchlist 자동 동기화: KIS HTS 관심종목 API 연동
3. macOS Keychain 보안 통합
4. closing_report.py: OHLCV + 거래량 + 내일 전략 + 매매일지
5. 스케줄러 5개 launchd 등록 완료
6. 운영자/사용자 매뉴얼 작성
7. Opus 보안 검증 완료
8. AGENTS.md (구 CLAUDE.md) 생성
9. **카카오톡 → 텔레그램 전환 완료** (v1.0.0 — 2026-04-18)
10. **closing_report 총자산/정산현황/예수금 섹션 분리**
11. **morning_report / intraday_report 예수금 섹션 통일**
12. **프로젝트 경로 재구조화**: `project/stockpilot` → `projects/AI_Projects/stockpilot`
13. **GitHub 저장소 연결**: `Hyoungjin-Lee/AI_Projects` 최초 push
14. **v2.0 에이전트 아키텍처 완료** (2026-04-19):
    - `state_manager.py` — 에이전트 간 공유 상태
    - 5개 스크립트 state 연동
    - `telegram_bot.py` — 텔레그램 명령 수신 데몬
    - `orchestrator.py` — 명령 라우팅 (`/잔고` `/상태` `/발굴`)
    - `com.aigeenya.stockbot.plist` — 부팅 시 자동 시작
    - AGENTS.md 전면 재작성 (v2.0 반영)
    - WORKFLOW.md 독립 검증 프로토콜 추가 (섹션 10)
15. **Telegram 봇 안정화** (2026-04-19):
    - TELEGRAM_BOT_TOKEN Keychain 로드 누락 → `_TELEGRAM_KEYS` 별도 처리
    - 시작 시 기존 메시지 24개 중복 수신 → startup offset 초기화
    - `=` 구분선 두 줄 렌더링 → `―――――――――――――――` 변경
16. **scripts/git_upload.sh + aigit_upload alias** (2026-04-19):
    - 보안 검사 (.env, 토큰 파일)
    - 커밋 메시지 자동 생성
    - y/N 승인 후 push
17. **v2.1 장초기 실시간 종목 발굴** (2026-04-19):
    - `intraday_discovery.py` — KIS 거래량/체결강도/등락률 교집합 필터
    - `--round 1`: 09:03 1차 수집, `--round 2`: 09:05 교집합+텔레그램
    - ETF/ETN 제외, 이격도 120 이상 과열 필터
    - launchd plist 2개 (discovery1, discovery2) 등록
    - 기술 설계서 + Codex 구현 지시서 작성
    - `docs/07_intraday_discovery/` 문서화

---

*자동 생성 | stockpilot v2.1 — AI 주식 자동화 시스템*

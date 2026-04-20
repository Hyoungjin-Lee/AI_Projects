# 🤝 stockpilot — Handoff 문서

> 최종 업데이트: 2026-04-21 (v2.5 — Phase 1 발굴 성과 추적 DB + 메시지 개선)
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
| 09:03 | `intraday_discovery.py --round 1` | 장초기 1차 수집 (거래량/체결강도/등락률 상위 30) |
| 09:05 | `intraday_discovery.py --round 2` | 2차 수집 → 교집합 → 점수 산정 → 텔레그램 전송 |
| 09:10 | `intraday_report.py` | 장초기 현황 텔레그램 전송 + state 기록 |
| 20:30 | `closing_report.py` | 장마감 결산 텔레그램 전송 + state 기록 |
| 23:30 | `stock_discovery.py` | 야간 종목 발굴 텔레그램 전송 + state 기록 (월~토) |
| 상시  | `telegram_bot.py` | 텔레그램 명령 수신 (부팅 시 자동 시작) |

---

## 3. 핵심 파일 구조

```
stockpilot/
├── morning_report/
│   ├── morning_report.py       # 모닝 브리핑 (대응포인트 3단계 분석 포함)
│   ├── intraday_report.py      # 장초기 브리핑
│   ├── intraday_discovery.py   # 장초기 실시간 종목 발굴 (교집합 필터)
│   ├── closing_report.py       # 장마감 결산
│   ├── stock_discovery.py      # 야간 종목 발굴
│   ├── watchlist_sync.py       # 관심종목 동기화
│   ├── check_price.py          # 종목 현재가 즉시 조회 (발굴가 대비 증감 표시)
│   ├── data_fetcher.py         # 글로벌 지수 (yfinance 기반 — S&P500, 나스닥)
│   ├── telegram_bot.py         # 텔레그램 봇 데몬 (양방향 수신)
│   ├── orchestrator.py         # 명령 라우팅
│   ├── state_manager.py        # 에이전트 간 공유 상태
│   └── keychain_manager.py     # macOS Keychain 인증정보 관리
├── data/
│   ├── watchlist.json          # 관심종목
│   ├── daily_state.json        # 에이전트 간 공유 상태 (런타임)
│   └── strategy_config.json    # 매매 전략 수치 중앙 관리 ← NEW
├── docs/
│   ├── STRATEGY.md             # 매매 전략 문서 (추세추종 B+C 조합) ← NEW
│   └── api/                    # KIS API xlsx 문서
└── logs/
```

---

## 4. 보안 구조 (Keychain)

```python
from keychain_manager import inject_to_env
inject_to_env()  # 반드시 첫 줄에 호출
```

절대 규칙:
- API키/계좌번호/토큰 코드·로그 평문 노출 금지
- `KIS_ALLOW_LIVE_ORDER=1` 없으면 실주문 절대 불가

---

## 5. v2.2 변경사항 (2026-04-20)

### ✅ 완료된 작업

| 항목 | 내용 |
|------|------|
| intraday_discovery 디버깅 | API 필드명 버그 수정 (`_get_code()`, `cttr→tday_rltv`) |
| 글로벌 지수 수정 | yfinance로 교체 (S&P500 None 수정 + 나스닥 추가) |
| 모닝리포트 대응포인트 | "추가 분석 필요" → 3단계 실제 분석으로 고도화 |
| 주봉 분석 버그 수정 | `isinstance(data, list)` 처리 |
| 자산증감 왜곡 감지 | ±5% 초과 시 경고 + 이체금액 역산 로직 |
| check_price.py 포맷 개선 | 발굴가 대비 현재가 증감 명확히 표시 |
| **매매 전략 확정** | 추세추종 B+C 조합 → `data/strategy_config.json` 중앙 관리 |
| **분할매매 로직 설계** | 5:3:2 분할, 평단 기준 하드스탑, 자동가격 계산 정의 |

### 오늘 발굴 성과 (2026-04-20)

- 이수페타시스: +7.2%(발굴) → +13.13%(장마감) **+5.9%p**
- 에코프로머티리얼즈: +5.4%(발굴) → +7.06%(장마감)

---

## 6. 확정된 매매 전략 (strategy_config.json)

### 진입 조건 (3개 모두 충족)

| 조건 | 기준 |
|------|------|
| 주봉 추세 | 주봉 SMA5 > SMA10 |
| SMA20 지지 | 현재가 > 일봉 SMA20 |
| RSI 범위 | 일봉 RSI 40~60 |

### 매도 조건 (우선순위 순)

| 우선순위 | 조건 | 기준 |
|---------|------|------|
| ① | 하드 스탑 | 평단 -3% 무조건 손절 |
| ② | 트레일링 스탑 | 평단 +2% 활성화 → 5일 고가 -3% 이탈 청산 |
| ③ | 목표가 익절 | 평단 +5% 도달 |
| ④ | 보류 청산 | 5일 경과 + 최고가 평단 +2% 미달 |

---

## 7. 분할매매 설계 (Phase 2 구현 대상)

### 분할 진입 구조

```
1차 매수: 목표 수량 50%  (진입 조건 3개 모두 충족 시)
2차 매수: 목표 수량 30%  (평단 -1~-2% 눌림 + SMA20 위 + 1일 경과)
3차 매수: 목목 수량 20%  (강한 지지 확인 시만)
```

**핵심 원칙: 하드스탑 기준 = 항상 현재 평단 (분할 후 재계산)**

### 자동 가격 계산

```
진입가 (돌파) = 5일 고가 × 1.005
진입가 (눌림) = SMA20 × 1.005
하드스탑      = 평단 × 0.97
목표가        = 평단 × 1.05
트레일링 활성 = 평단 × 1.02 돌파 시
```

### strategy_config.json 확장 예정 구조

```json
"position": {
  "split_entry": {
    "max_splits": 3,
    "weights": [0.5, 0.3, 0.2],
    "add_condition": {
      "dip_from_avg_pct_min": -2.0,
      "dip_from_avg_pct_max": -1.0,
      "require_sma20_above": true,
      "min_days_after_entry": 1
    }
  },
  "entry_price": {
    "breakout": { "method": "5d_high", "buffer_pct": 0.5 },
    "dip":      { "method": "sma20",   "buffer_pct": 0.5 }
  }
}
```

### 분할 매도 (전량 청산)

텔레그램 `/매도` 명령은 **전량 청산** 방식으로 확정.
(시장가 전량 매도 — 분할 매도 없음)

---

## 8. v2.3 변경사항 (2026-04-21)

### ✅ 완료된 작업

| 항목 | 내용 |
|------|------|
| **체결강도 실시간 조회** | `kis_client.get_ccnl()` 추가 (FHKST01010300) → check_price.py에서 발굴 시 vs 현재 체결강도 비교 표시 |
| **`/발굴` 라우팅 수정** | 장중(09:00~15:30) → intraday_discovery round1+2 실행 / 장외 → stock_discovery (관심종목 스크리닝) |
| **`/잔고` 보유종목 상세** | 현재가·수량·평단·손익금액·수익률 모두 표시 |
| **`/상태` 시그널 개선** | 종목명·한글 시그널·현재가(실시간)·평단·손절/목표가 표시 |
| **`/상태` 매수/매도 타점 코멘트** | 현재가와 SMA20·5일고가·평단 비교 → 상황별 코멘트 자동 생성 |

#### 타점 코멘트 상황별 분기

| 매수 상황 | 출력 |
|-----------|------|
| 현재가 < SMA20 | 🚫 추가매수 금지 + 손절가 안내 |
| SMA20 ~ SMA20×1.02 | ✅ 눌림지지 확인됨 X원~Y원 매수 |
| SMA20×1.02 ~ 5일고가 | ⏳ 돌파 대기, 🚫 추격 금지 |
| 5일고가 돌파 +1% 이내 | ✅ 돌파추세 확인됨 X원~Y원 매수 |
| 5일고가 돌파 +1% 초과 | 🚫 과열 구간, 눌림 재진입 대기 |

| 매도 상황 | 출력 |
|-----------|------|
| 손절가 이탈 | 🚨 즉시 전량 손절 |
| 손실 구간(손절가~평단) | ⚠️ 추가매수 금지 + 분할 정리 구간 |
| 수익 구간(평단~목표가) | 📊 트레일링 대기 + 분할 익절 구간 |
| 목표가 도달 | 🎯 X원~Y원 대 1/3씩 단계 익절 |

#### 핵심 구조 변경

- `closing_report.py`: holdings_signals 저장 시 `name`, `cur_price`, `avg_price`, `entry_low`, `entry_high`, `exit_low`, `exit_high` 추가
  - `entry_low` = `SMA20 × 1.005` (캐시 일봉에서 직접 계산)
  - `entry_high` = `5일고가 × 1.005` (캐시 일봉에서 직접 계산)
  - `exit_low` = `평단 × 0.97` (하드스탑)
  - `exit_high` = `평단 × 1.05` (목표가)
- `orchestrator.py`: `_build_action_comment()` 함수 추가 (상황 판단 로직 분리)

---

## 8-1. 완료된 이슈 (v2.4~v2.5, 2026-04-21)

### ✅ 이슈 2 — stock_discovery 스크리닝 조건 완화 (완료)
- `_MIN_VOL_RATIO` 0.8 → 0.5 완화
- `_screen_stock()` HOLD confidence 기준 0.5 → 0.4 완화

### ✅ 이슈 3 — closing_report 총자산 로직 동기화 (완료)
- `display_net` 기준을 `tot_evlu_amt`(총평가금액)로 변경
- 자산증감 ±5% 초과 시 `⚠️` 경고 + 이체금액 역산 로직 이식

### ✅ Phase 1 — intraday_discovery 고도화 (완료, Stage 11 검증 통과)
- 필터 강화: 체결강도 110 미만 제외, 등락률 2% 미만 제외
- 발굴 성과 추적 DB: `data/discovery_log.json` 자동 기록
- closing_report 장마감 시 종가·수익률 자동 업데이트
- 텔레그램 메시지 4~5위 "추가 관심 후보" 섹션 추가
- 설계 문서: `docs/08_phase1_intraday/`
- 최종 검증: `docs/notes/final_validation.md`

---

## 9. Phase별 로드맵

| Phase | 내용 | 상태 |
|-------|------|------|
| **Phase 1** | intraday_discovery 고도화 | ✅ 완료 |
| **Phase 1.5** | 모닝 리포트에 전날 발굴 성과 요약 추가 | 🔜 데이터 쌓인 후 |
| **Phase 2** | 텔레그램 `/매수` `/매도` 명령 구현 + 별도 계좌 분리 | 🔜 다음 |
| **Phase 3** | 보유 포지션 평단 관리 자동화 | 🔜 Phase 2 후 |
| **Phase 4** | 웹 UI (전략 설정 화면) | 🔜 마지막 |

---

## 9. 다음 세션에서 할 작업

### 🔴 Stage 12 QA — Phase 1 실제 운영 검증
- [ ] 내일 장 시작(09:03~09:05) round1 → round2 실행 후 `data/discovery_log.json` 생성 확인
- [ ] 20:30 closing_report 실행 후 `close_price`, `return_pct` 업데이트 확인
- [ ] 텔레그램 메시지에 "추가 관심 후보" 섹션 정상 표시 확인

### 🟡 Phase 2 준비 — 텔레그램 매수/매도 명령
- [ ] strategy_config.json에 `position.split_entry` 구조 추가
- [ ] 별도 계좌 분리 설계 (Keychain에 `KIS_TRADING_ACCOUNT_NO` 추가)
- [ ] `/매수 종목코드 수량` 명령 구현
- [ ] `/매도 종목코드` 전량 청산 명령 구현

---

## 10. 주요 명령어 모음

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 1 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --debug

# 현재가 즉시 조회
venv/bin/python3 morning_report/check_price.py

# 상태 확인
venv/bin/python3 morning_report/state_manager.py
venv/bin/python3 morning_report/keychain_manager.py
launchctl list | grep aigeenya

# 로그 확인
tail -50 logs/intraday_discovery.log
tail -50 logs/closing_report.log
tail -50 logs/stockbot_error.log

# GitHub 업로드
aigit_upload
```

---

## 11. 전체 작업 히스토리 (누적)

1. 장마감 시간 변경: 16:00 → 20:30
2. watchlist 자동 동기화: KIS HTS 관심종목 API 연동
3. macOS Keychain 보안 통합
4. closing_report.py: OHLCV + 거래량 + 내일 전략 + 매매일지
5. 스케줄러 5개 launchd 등록 완료
6. 운영자/사용자 매뉴얼 작성
7. Opus 보안 검증 완료
8. AGENTS.md 생성
9. **카카오톡 → 텔레그램 전환 완료** (v1.0.0 — 2026-04-18)
10. closing_report 총자산/정산현황/예수금 섹션 분리
11. morning_report / intraday_report 예수금 섹션 통일
12. 프로젝트 경로 재구조화
13. GitHub 저장소 연결: `Hyoungjin-Lee/AI_Projects`
14. **v2.0 에이전트 아키텍처 완료** (2026-04-19)
15. Telegram 봇 안정화 (startup offset, 구분선 렌더링)
16. scripts/git_upload.sh + aigit_upload alias
17. **v2.1 장초기 실시간 종목 발굴** (2026-04-19)
19. **v2.3 텔레그램 명령 개선 + 타점 코멘트** (2026-04-21):
    - check_price.py 체결강도 실시간 조회 (FHKST01010300 `get_ccnl()`)
    - `/발굴` 장중/장외 자동 분기 (intraday_discovery ↔ stock_discovery)
    - `/잔고` 보유종목 수량·평단·손익 상세 표시
    - `/상태` 종목명·한글 시그널·현재가(실시간)·매수/매도 타점 코멘트
    - `_build_action_comment()` 상황별 5단계 매수 / 4단계 매도 분기
18. **v2.2 전략 확정 + 분할매매 설계** (2026-04-20):
    - intraday_discovery API 필드명 버그 수정 (종목 0개 → 정상 발굴)
    - 글로벌 지수 yfinance 교체 (S&P500 None 수정, 나스닥 추가)
    - 모닝리포트 대응포인트 3단계 분석 고도화
    - 자산증감 이체금액 역산 로직
    - check_price.py 발굴가 대비 증감 표시
    - 추세추종 B+C 매매 전략 확정 → strategy_config.json
    - 분할매매 로직 설계 (5:3:2, 평단 기준 하드스탑, 전량 매도 확정)

---

*자동 생성 | stockpilot v2.3 — AI 주식 자동화 시스템*

---

## 📋 다음 세션 시작 프롬프트

> 아래 내용을 복사해서 새 대화창에 붙여넣으면 바로 이어서 작업 가능합니다.
> 마지막 갱신: 2026-04-21 (v2.5)

```
stockpilot 프로젝트 이어서 진행해줘.
HANDOFF.md 와 CLAUDE.md 파일을 먼저 읽어줘.
경로: /Users/geenya/projects/AI_Projects/stockpilot/

현재 상태 요약:
- v2.5 완료 (2026-04-21)
- [Phase 1 완료] intraday_discovery 고도화 (Stage 9~11 검증 통과)
  - 발굴 성과 추적 DB: data/discovery_log.json 자동 기록
  - closing_report 장마감 시 종가·수익률 자동 업데이트
  - 텔레그램 메시지 4~5위 추가 관심 후보 섹션 추가
  - 설계 문서: docs/08_phase1_intraday/
- CLAUDE.md에 워크플로우 역할 규칙 및 협업 체크포인트 추가
  - Stage 1 브레인스토밍: 형진님과 대화하며 방향 잡기 (혼자 작성 금지)
  - Stage 4 완료 후: 형진님 승인 필수, 승인 없이 Stage 5 진입 금지

다음 할 작업:
1. [Stage 12 QA] Phase 1 실제 운영 검증
   - 장 시작(09:03~09:05) round1→round2 후 discovery_log.json 확인
   - 20:30 closing_report 후 close_price, return_pct 업데이트 확인
2. [Phase 2] 텔레그램 /매수 /매도 명령 구현 (Stage 1 브레인스토밍부터 시작)

참고 사항:
- 새 기능 개발 시 반드시 WORKFLOW.md Stage 1~7 순서 준수
- Stage 1은 형진님과 대화로 시작, Stage 4 승인 후 Stage 5 진입
- 수정 후 반드시 venv/bin/python3 -m py_compile 문법 검사

어디서부터 시작할까?
```

# Stage 2: 계획 초안 — Phase 2 텔레그램 승인형 매수 + 자동 매도

> 날짜: 2026-04-22 | 담당: Claude Sonnet | Effort: Medium
> 입력: `01_brainstorm.md` (Stage 1 승인 완료, 형진님 재검토 없이 Stage 2 진입 지시)
> 산출물 경로: `docs/11_phase2_trading/02_plan_draft.md`

---

## 프로젝트 개요

이 프로젝트의 목표는 stockpilot을 **관찰·브리핑 시스템**에서 **승인형 매매 시스템**으로 확장하는 것이다. 구체적으로는 장중 `intraday_discovery` round 2/4/6/8의 발굴 결과를 텔레그램 "매수 제안"으로 자동 송출하고, 형진님의 `/매수함` 한 번에 실전 소액계좌에서 실주문이 체결되도록 한다. 매도는 승인 없이 자동 실행하여 반응성을 확보한다. 핵심 제약은 "형진님의 인지부하를 늘리지 않는다" — 봇이 운전자, 형진님은 승인자(게이트키퍼).

---

## 목표

### 주요 목표

- 발굴 → 제안 → 승인 → 체결 루프를 텔레그램 한 화면에서 완결
- 자동 매도(손절/트레일링/익절/장마감)로 수동 감시 부담 제거
- AT_Project v0.1/v0.2 실전 자산을 이식하되, stockpilot 에이전트 구조에 맞게 재설계

### 부차 목표

- `strategy_config.json`에 `trading` 섹션을 추가하고, 텔레그램에서 수치 조정 가능
- 분할 매수(5:3:2) 평단 가중평균 자동 계산
- 일일 손실·매매 횟수 한도 초과 시 `sys.exit` 대신 "주문 기능 차단"으로 전환

### 성공 기준

- `/매수함` 수신 후 5초 이내 주문 제출, 10초 이내 체결 확인 텔레그램 도착
- 가격 이탈 ±3% 가드로 지연 체결 0건
- 1주일 연속 운영 시 오발주 0건, 제어 불능 0건
- MAX_DAILY_LOSS 초과 상황 발생 시 주문 차단 동작 + 자정 자동 해제 1회 이상 검증

---

## 사용자 문제 정의

현재 상황: `intraday_discovery`가 09:03~14:33 사이 8회 실행되어 우수 종목을 텔레그램으로 알림. 형진님은 알림을 보고 HTS/MTS를 열어 직접 매수/매도. 장중에 알림·HTS 조작을 병행하기 어려움. 자동 손절이 없어 손실이 커지는 순간 놓칠 위험.

원하는 상황: 봇이 1위 종목을 근거와 함께 "매수?" 제안 → 형진님은 `/매수함` or `/매수안함`만 결정 → 봇이 수량 계산·주문 제출·체결 보고 전부 처리. 보유 종목은 봇이 상시 감시하여 자동 손절·익절·장마감 청산.

stockpilot 컨텍스트:
- 평일 4회 브리핑 + round 1~8 장중 발굴이 이미 자동화됨
- 텔레그램 bot 데몬(상시)과 orchestrator가 명령 라우팅 중
- Keychain 인증정보, launchd 스케줄, `KIS_ALLOW_LIVE_ORDER=1` 가드 패턴은 이미 확립

---

## 핵심 기능

### 반드시 포함 (Must-Have, P0)

1. **매수 제안 자동 트리거** — round 2/4/6/8 종료 직후 1위 종목을 텔레그램 전송 (근거·점수·체결강도·등락률 포함)
2. **텔레그램 승인 명령** — `/매수함`, `/매수안함`, `/종목변경 <1~5>` 3종
3. **수량 자동 계산** — `주문가능금액 - (총자산 × 10% 유보)`를 `5:3:2` 분할, 시장가 floor 수량
4. **가격 이탈 가드** — `/매수함` 수신 시 현재가 재조회 후 권유가 대비 ±3% 초과 시 매수 보류 + 알림
5. **재권유 상태머신** — 무응답 시 3분 간격 최대 3회, 분할 단계별(최초 / 1차추가 / 2차추가) 독립 카운터
6. **자동 매도** — 하드스탑 -3%(평단 기준) / 트레일링(+2% 활성 → 5일 고가 -3% 이탈) / 목표 +5% / 장마감 강제청산, 승인 불필요
7. **체결 사후 통지** — 매수·매도 체결 결과를 텔레그램에 즉시 송출 (손익 포함)
8. **안전장치 중앙화** — `validate_order(action, ticker, qty) → (ok, reason)` 단일 preflight로 `COOLDOWN`, `MAX_DAILY_LOSS`, `MAX_TRADES_PER_DAY`, 잔고, 실전 가드 통합
9. **MAX_DAILY_LOSS 차단 모드** — v0.1의 `sys.exit(0)` 폐기. 주문 기능만 차단 + 텔레그램 알람 + 자정 자동 해제
10. **별도 실전 계좌 분리** — Keychain `KIS_TRADING_ACCOUNT_NO` 신규, 기존 조회 계좌와 완전 분리
11. **분할 가중평단 영속화** — `data/position_state.json`에 포지션·평단·분할 단계·최고가 기록, 봇 재시작 시 복구
12. **초기 운영 검증 절차** — 첫 주문은 최소 수량(1주) 시범 체결 → 체결 흐름·로그·통지 확인 후 정상 운영 전환

### 향후 개선 (Nice-to-Have, P1~P2)

- **P1 — 2차/3차 분할매수 자동 제안**: 평단 -1~-2% + SMA20 위 + 1일 경과 조건 충족 시 봇이 추가매수 제안
- **P1 — 런타임 설정 수정**: `/설정 <key.path> <value>` 명령으로 `strategy_config.json.trading` 수정 + 리로드
- **P1 — 동시 보유·종목당 최대 한도**: 시드 규모 결정 후 구체값 설정
- **P2 — 주문 슬리피지 추적**: 시장가 체결가 vs 제출 시점 현재가 차이를 `closing_report`에 요약
- **P2 — 일일 매매 리포트**: 당일 체결·손익·차단 이력 자동 요약

---

## 제외 범위

- 이 프로젝트는 **자동 매수**(시그널 → 즉시 체결)를 포함하지 않는다 — Phase 3로 연기
- 이 프로젝트는 **지정가 주문**을 포함하지 않는다 — 시장가 고정, ±3% 가드로 대체
- 이 프로젝트는 **분할 매도**를 포함하지 않는다 — `/매도`는 전량 청산
- 이 프로젝트는 **모의투자 서버 지원**을 포함하지 않는다 — AT_Project v0.1에서 검증 완료
- 이 프로젝트는 **웹 UI 및 백테스팅 엔진**을 포함하지 않는다 — Phase 4 범위
- 이 프로젝트는 **다계정 지원**을 포함하지 않는다 — 실전 소액계좌 1개

---

## 예상 사용자 흐름

### 시나리오 A: 정상 매수 → 자동 익절

```
09:05  봇 → "📢 매수 제안: 삼성전자 — 점수 85, 체결강도 125, +3.2%. /매수함?"
09:05  형진님 → /매수함
09:05  봇 → (현재가 재조회, 권유가 대비 +0.4% → 이탈 가드 통과)
          (validate_order 통과: 잔고 OK, COOLDOWN OK, 손실한도 OK)
          시장가 매수 50주 체결 → position_state.json 기록
09:05  봇 → "✅ 체결: 삼성전자 50주 @ 87,200원 (1차 50%)"
09:45  현재가 91,560원 (+5.0% 도달) → 자동 익절 전량 매도 → 사후 통지
```

### 시나리오 B: 승인 거절 + 다음 round 재제안

```
09:05  봇 → "📢 매수 제안: LG화학"
09:05  (형진님 응답 없음)
09:08  봇 → "📢 재권유 (1/3): LG화학" (3분 타임아웃)
09:08  형진님 → /매수안함
       (해당 제안 최초진입 카운터: declined, 폐기)
09:33  round 4 종료 → 다른 1위 종목 새 제안 시작
```

### 시나리오 C: 가격 이탈 가드 동작

```
09:05  봇 → "📢 매수 제안: 현대차 @ 235,000원"
09:07  (급등 진행 중)
09:08  형진님 → /매수함
09:08  봇 → (현재가 재조회 → 243,500원, +3.6% → 가드 작동)
          "⚠️ 권유가 235,000원 → 현재 243,500원 (+3.6%), 매수 보류"
```

### 시나리오 D: 자동 손절

```
10:30  보유 삼성전자 현재가가 평단 -3.1% 도달
10:30  position_monitor 감지 → validate_order 통과 → 시장가 전량 매도
10:30  봇 → "🚨 손절: 삼성전자 -3.1% 전량 청산"
```

### 시나리오 E: 일일 손실한도 초과

```
14:00  daily_pnl = -500,000원 도달 (MAX_DAILY_LOSS 위반)
14:00  봇 → "🛑 일일 손실한도 초과. 오늘 신규 주문 차단. 00:00 자동 해제"
14:33  round 8 1위 제안 시도 → validate_order 거절 → 제안 스킵
00:00  자정 타이머 → 차단 해제 + 카운터 리셋 → 텔레그램 복구 알림
```

---

## 기술적 주의사항 (계획 단계 수준)

### 아키텍처 뼈대

```
telegram_bot.py (상시 데몬)
    ↕ Decision 큐
position_monitor.py (신규 데몬) — 10초/60초 이중 루프
    ↕
orchestrator.py (validate_order 중앙 preflight 호출)
    ↓
kis_client.order_buy / order_sell
    ↓
position_state.json, trading_state.json, pending_proposals.json
```

### 신규 파일

| 경로 | 책임 |
|---|---|
| `morning_report/position_monitor.py` | 데몬 루프, 보유 종목 손절/익절 판정, 권유 상태머신 관리 |
| `morning_report/validator.py` | `validate_order()` 중앙 preflight (COOLDOWN/손실한도/잔고/실전가드/가격이탈) |
| `data/position_state.json` | 보유 포지션, 분할 가중평단, 최고가, 진입 단계 |
| `data/trading_state.json` | `daily_pnl`, `daily_trade_count`, COOLDOWN 타임스탬프, 주문 차단 플래그 |
| `data/pending_proposals.json` | 재권유 상태머신 (제안별 카운터·마지막 전송 시각·상태) |

### 수정 파일

| 경로 | 변경 요점 |
|---|---|
| `morning_report/telegram_bot.py` | `/매수함`, `/매수안함`, `/종목변경`, (P1)`/설정` 파서 추가 |
| `morning_report/orchestrator.py` | 매매 명령 라우팅, `validate_order` 호출, 체결 후 사후 통지 |
| `morning_report/intraday_discovery.py` | round 2/4/6/8 종료 시점에 "1위 종목 매수 제안" enqueue |
| `morning_report/closing_report.py` | 장마감 강제청산 트리거, 당일 체결 결과 반영 |
| `morning_report/keychain_manager.py` | `KIS_TRADING_ACCOUNT_NO` 로드 추가 |
| `data/strategy_config.json` | `trading` 섹션 신설 (reserve_ratio, split weights, 타임아웃, 한도 등) |
| `.skills/kis-api/scripts/kis_client.py` | `order_buy()`, `order_sell()`, `inquire_psbl_order()` 추가 (v0.1 이식 + 실전 TR 재검증) |
| launchd plist | `com.aigeenya.stockreport.position_monitor.plist` 신규 등록 (KeepAlive) |

### 데이터 플로우

1. `intraday_discovery --round {2,4,6,8}` → 상위 5 산출 → 1위 종목을 `pending_proposals.json`에 enqueue
2. `position_monitor` 루프가 새 제안 감지 → `telegram_bot`에 메시지 전송 → pending 상태 = `pending`
3. 형진님 `/매수함` → `orchestrator` 수신 → `validator.validate_order()` → 가격 재조회 → `kis_client.order_buy()` → `position_state.json` 업데이트 → 체결 통지
4. 무응답 3분 경과 → `position_monitor`가 재권유 발송 (카운터++), 3회 소진 시 `exhausted`
5. 보유 포지션 존재 시 `position_monitor` 10초 루프로 현재가 조회 → 손절/트레일링/목표가/장마감 판정 → 조건 충족 시 자동 매도

### 외부 의존성 / 환경 제약

- KIS Open API (실전 계좌 TR 코드는 v0.1 기준 재확인 필요)
- 텔레그램 bot API (polling 방식 유지)
- macOS Keychain, launchd KeepAlive
- Python 3.14 + 기존 venv

---

## 리스크 & 완화

| 리스크 | 완화 방법 |
|---|---|
| **오발주** (잘못된 종목·수량 매수) | `validate_order` 중앙 preflight + `KIS_ALLOW_LIVE_ORDER=1` 가드 + 첫 운영 1주일 1주 시범 |
| **지연 체결** (3분 타임아웃 내 급변) | `/매수함` 시점 현재가 재조회 + ±3% 이탈 가드 |
| **MAX_DAILY_LOSS 도달 시 시스템 다운** | `sys.exit` 폐기, 주문 차단 플래그로 전환, 자정 자동 해제 |
| **봇 다운 시 포지션 소실** | `position_state.json`·`pending_proposals.json` 영속화, launchd KeepAlive |
| **파일 I/O 경쟁** (monitor·bot·orchestrator 동시 쓰기) | 단일 쓰기 에이전트 or 파일 락 (Stage 5에서 확정) |
| **인증정보 노출** | Keychain 유지, 계좌번호·토큰 로그 마스킹 |
| **중복 권유 / 중복 체결** | 분할 단계별 독립 카운터, 상태 = `pending/accepted/declined/exhausted` |
| **장마감 시각 체결 실패** | 15:20경 주문 제출(체결 여유 10분) — Stage 5에서 정확한 시각 확정 |
| **시간외·휴장 주문 시도** | `is_market_open()` 게이트, 비장중 주문 호출 자체 차단 |

---

## Stage 3~5 이관 메모

- Stage 3 검토에서 집중 볼 것: 테스트 전략, 로그 정책, 파일 I/O 경쟁, MAX_DAILY_LOSS 단위, 장마감 시각 구체화
- Stage 5에서 확정할 것: position_monitor 분리 vs 통합 / `/설정` 문법 / 동시 보유 상한 / 초기 시드·종목당 한도 / pending 다건 우선순위 / 파일 동시성 제어 방식

---

*자동 생성 | stockpilot Phase 2 Stage 2 — Plan Draft*

# Stage 4: 계획 통합 (최종 확정 계획) — Phase 2 텔레그램 승인형 매수 + 자동 매도

> 날짜: 2026-04-22 | 담당: Claude Sonnet | Effort: Medium
> 입력: `02_plan_draft.md` + `03_plan_review.md` (수정 제안 16건)
> 산출물: 이 문서 — Stage 5 기술 설계의 단일 기반

---

## 프로젝트 개요

Phase 2는 stockpilot을 **관찰·브리핑 시스템**에서 **승인형 매매 시스템**으로 확장한다. 장중 `intraday_discovery` round 2/4/6/8이 선정한 1위 종목을 텔레그램에 근거와 함께 "매수?"로 제안하고, 형진님의 `/매수함` 한 번에 실전 소액계좌에서 실주문이 체결되도록 한다. 매도(하드스탑·트레일링·목표·장마감)는 승인 없이 자동 실행하여 반응성을 확보한다. 봇이 운전자, 형진님은 승인자(게이트키퍼). 별도 실전 소액계좌(`KIS_TRADING_ACCOUNT_NO`)만을 대상으로 하며, 기존 조회 계좌는 침범하지 않는다.

---

## 목표

### 주요 목표

1. 발굴 → 제안 → 승인 → 체결의 텔레그램 단일 화면 루프 완성
2. 자동 매도(손절 / 트레일링 / 목표 +5% / 장마감)로 수동 감시 부담 제거
3. AT_Project v0.1/v0.2 실전 자산 이식 + stockpilot 에이전트 구조 재설계

### 부차 목표

- `strategy_config.json`에 `trading` 섹션 추가 (수치 중앙 관리)
- 분할 매수(5:3:2) 가중평단 자동 계산 및 영속화
- 일일 한도(손실·매매 횟수) 초과 시 `sys.exit` 폐기 → "주문 차단 플래그"로 전환 + 자정 자동 해제

### 성공 기준 (정량화)

| # | 기준 | 측정 방법 |
|---|---|---|
| 1 | `/매수함` → 주문 제출 5초, 체결 통지 10초 이내 | 텔레그램 타임스탬프 vs KIS 주문 응답 |
| 2 | 지연 체결 0건 (±3% 가격 이탈 가드) | `logs/trading.log` 매수 전 재조회 기록 |
| 3 | 오발주 0건 (의도하지 않은 종목·수량·방향) | 1주일 운영 로그 전수 검토 |
| 4 | `validate_order` 우회 체결 0건 | 모든 주문 호출이 preflight 통과 기록 보유 |
| 5 | 봇 재시작 후 pending 복구 오류 0건 | 재시작 10회 테스트 |
| 6 | 주문 타임아웃 발생 시 정상 복구율 100% | pending 복귀 + 알람 모두 전달 |
| 7 | MAX_DAILY_LOSS 차단 → 00:00 자동 해제 | 테스트 환경에서 최소 1회 검증 |

---

## 사용자/사용 시나리오

### 일상 (매수 승인)

```
09:05  봇: "📢 매수 제안: 삼성전자 (005930)
        점수 85 / 체결강도 125 / +3.2% / 교집합 ⭐
        권유가 87,200원 · 1차 50% 수량 기준 50주
        /매수함 · /매수안함 · /종목변경 [2~5]"
09:05  형진님: /매수함
09:05  봇: (재조회 +0.4% → 가드 통과)
        (validate_order: 잔고 OK · COOLDOWN OK · 손실한도 OK · 실전가드 OK)
        "✅ 체결: 삼성전자 50주 @ 87,200원 (1차 50%)"
```

### 일상 (자동 매도)

```
10:30  position_monitor: 삼성전자 -3.1% 감지
10:30  봇: "🚨 손절: 삼성전자 50주 @ 84,550원 (-3.1%, 실현 -132,500원)"
```

### 엣지 1 — 가격 이탈 가드

```
09:08  형진님: /매수함 (권유 후 3분)
09:08  봇: "⚠️ 권유가 235,000 → 현재 243,500 (+3.6%), 매수 보류. 다음 round 대기."
```

### 엣지 2 — 일일 손실한도 도달

```
14:00  실현손익 누적 -500,000원 → MAX_DAILY_LOSS 위반
14:00  봇: "🛑 일일 손실한도 초과. 오늘 신규 주문 차단. 00:00 자동 해제."
14:33  round 8 제안 시도 → validate_order 거절 → 제안 자체 스킵
00:00  position_monitor 자정 틱: 차단 해제 + 카운터 리셋 → "🔓 일일 한도 해제 완료."
```

### 엣지 3 — 봇 재시작 후 놓친 손절 복구

```
10:15  position_monitor 크래시, launchd KeepAlive로 10:15:08 재시작
10:15  재시작 직후 보유 종목 전수 현재가 조회
        → 삼성전자 -3.4% 확인 (차단 중 이탈)
10:15  즉시 청산 + "🚨 재시작 후 놓친 손절 감지 → 삼성전자 -3.4% 청산"
```

---

## 핵심 기능

### P0 (Phase 2 Must-Have)

| # | 기능 | 비고 |
|---|---|---|
| 1 | round 2/4/6/8 종료 직후 1위 종목 자동 제안 | 임계치 미달·COOLDOWN 중 종목은 스킵 |
| 2 | `/매수함`, `/매수안함`, `/종목변경 <1~5>` 3종 명령 | 최단 문법 |
| 3 | 수량 자동 계산 (주문가능금액 − 총자산×10% 유보) × {0.5, 0.3, 0.2} | 시장가 floor |
| 4 | `/매수함` 시 현재가 재조회 → ±3% 이탈 시 매수 보류 | 가격 이탈 가드 |
| 5 | 재권유 상태머신: 3분 타임아웃 × 최대 3회, 분할 단계별 독립 카운터 | `pending_proposals.json` |
| 6 | 자동 매도 4종 | 하드스탑 -3%(평단) / 트레일링(+2% 활성 + 5일고가 -3%) / 목표 +5% / 장마감 |
| 7 | 체결 사후 통지 (매수·매도, 손익 포함) | 텔레그램 즉시 |
| 8 | `validate_order(action, ticker, qty) → (ok, reason)` 중앙 preflight | COOLDOWN·손실한도·매매횟수·잔고·실전가드·가격이탈·시장시간 |
| 9 | **MAX_DAILY_LOSS 차단 모드** (v0.1의 `sys.exit` 폐기) | 절대금액(원) + **실현손익만** 기준 |
| 10 | 별도 실전 계좌 분리 (Keychain `KIS_TRADING_ACCOUNT_NO`) | 조회 계좌와 완전 분리 |
| 11 | 분할 가중평단 영속화 (`position_state.json`) | 재시작 복구 |
| 12 | 초기 시범 체결 (1주 × 1종목) | Phase 2 가동 첫날 |
| 13 | **`trading --dry-run` 모드** | 실주문 차단, 가짜 체결로 전체 루프 검증 (단위·통합 테스트 대체) |
| 14 | **재시작 직후 "놓친 손절" 복구 스캔** | 보유 종목 현재가 즉시 조회 + 판정 |
| 15 | **로그 정책**: `logs/trading.log` JSON 구조 + 계좌번호 마스킹 `******1234` | 민감정보 보호 |
| 16 | **텔레그램 메시지 throttle**: 초당 1건 큐 | rate limit 보호 |

### P1 (Phase 2.1 / Phase 3 승격 후보)

- `/설정 <key.path> <value>` 런타임 수치 수정 (SIGHUP 리로드)
  - 초기에는 config 직접 편집 + position_monitor 프로세스 재시작으로 대체 가능
- 2차·3차 분할매수 자동 제안 (평단 −1~−2% + SMA20 위 + 1일 경과)
- 동시 보유 종목 수 상한 / 종목당 최대 한도 (시드 규모 확정 후)
- 주문 슬리피지 추적 (제출 시점 현재가 vs 체결가)
- 일일 매매 리포트 자동 요약 (`closing_report`에 합류)

### P2 (Nice-to-Have)

- 시간외(NXT) 지원 — **Phase 2는 KRX 정규장 09:00~15:30만 대상**
- 웹 UI, 백테스팅, 다계정 — Phase 4 이후

---

## 제외 범위

- 이 프로젝트는 **자동 매수**(시그널 → 즉시 체결)를 포함하지 않는다 (Phase 3)
- 이 프로젝트는 **지정가 주문**을 포함하지 않는다 (시장가 고정 + ±3% 가드)
- 이 프로젝트는 **분할 매도**를 포함하지 않는다 (전량 청산만)
- 이 프로젝트는 **모의투자 서버 지원**을 포함하지 않는다
- 이 프로젝트는 **웹 UI / 백테스팅 엔진 / 다계정 지원**을 포함하지 않는다
- 이 프로젝트는 **NXT(시간외)를 포함하지 않는다** — 장 시간 외의 자동 동작 전부 비활성

---

## 기능 우선순위 & Phase 계획

### Phase 2 (MVP, 통합 릴리스)

P0 16개를 하나의 마일스톤으로 묶어 릴리스. 단, 가동 첫날은 "시범 체결 1주 × 1종목"으로 전체 흐름 검증 → 이상 없으면 정상 분할 수량 운영.

**내부 마일스톤 (개발 순서 권장, 공식 서브페이즈 분할은 아님)**:
1. 계좌 분리 · Keychain 키 · kis_client 주문 함수 (P0 10, 기반)
2. `validate_order` · `trading_state.json` · MAX_DAILY_LOSS 차단 모드 (P0 8·9)
3. `position_state.json` · 분할 가중평단 · 영속화 (P0 11)
4. `pending_proposals.json` · 재권유 상태머신 (P0 5)
5. `position_monitor` 데몬 + 이중 루프 + 자동 매도 (P0 6)
6. 텔레그램 명령 3종 · 가격 가드 · 수량 계산 (P0 2·3·4)
7. 발굴 연동 · 제안 스킵 조건 (P0 1)
8. 사후 통지 · throttle (P0 7·16)
9. 로그 정책 · 마스킹 (P0 15)
10. dry-run 모드 (P0 13)
11. 재시작 복구 스캔 (P0 14)
12. 시범 체결 1주 검증 (P0 12)

### Phase 2.1+ (후속)

P1 5개, P2 순차 도입.

---

## 운영 / 기술 제약

| 제약 | 설명 | 영향 |
|---|---|---|
| Python 3.14 / macOS | 기존 venv | 신규 의존성 추가 시 `pip --break-system-packages` |
| KIS Open API | 실전 TR 코드 필요 | v0.1의 `VTTC0802U`/`VTTC0801U`은 모의 TR. 실전 TR 재확인 필요 (Stage 5) |
| Telegram bot | polling | 초당 1건 throttle 필요 |
| launchd | KeepAlive | `position_monitor` 재시작 지연 최대 10초 → 재시작 후 즉시 복구 스캔 |
| Keychain | 인증정보 | 평문 로그 금지, 계좌번호 마스킹 |
| 실전 계좌 가드 | `KIS_ALLOW_LIVE_ORDER=1` 미설정 시 주문 불가 | 모든 실주문 경로에 가드 |
| 장 시간 | KRX 09:00~15:30만 | `is_market_open()` 게이트, 이외 시간 주문 호출 자체 차단 |
| 장마감 시각 | 정규장 15:30, 동시호가 15:20~15:30 | **15:15 시장가 청산** → 미체결 시 **15:25 동시호가 재시도** |
| 자정 리셋 | `trading_state.json` 초기화 | **position_monitor 자정 틱 단일 책임** |

---

## 데이터 플로우

```
[intraday_discovery round 2/4/6/8 종료]
      │
      ▼
pending_proposals.json에 1위 enqueue
(임계치 미달·COOLDOWN 중 종목은 스킵)
      │
      ▼
[position_monitor 루프 감지 → telegram_bot 메시지 전송]
      │
      │  (사용자 /매수함)
      ▼
[orchestrator → validator.validate_order → 가격 재조회]
      │
      ▼
[kis_client.order_buy → 응답 + 잔고 조회 2단 확인]
      │
      ▼
position_state.json 가중평단 갱신 + 체결 통지
      │
      ▼
[position_monitor 10초 루프: 손절/트레일링/목표/장마감 감시]
      │
      ▼
자동 매도 → trading_state.json daily_pnl/count 갱신 + 사후 통지
```

**무응답 경로**: `pending` 상태에서 `last_sent` 3분 경과 → 재권유 (1/3 → 2/3 → 3/3) → 소진 시 `exhausted`.

**재시작 경로**: 봇/monitor 재시작 → `pending` 중 `last_sent > 5분` 항목 즉시 `expired` 처리 → 보유 종목 전수 현재가 조회로 놓친 손절 판정.

---

## 파일 구조 / 책임

### 신규

| 경로 | 책임 | 쓰기 권한 |
|---|---|---|
| `morning_report/position_monitor.py` | 데몬 루프(10초/60초 이중), 손절/익절 판정, 권유 상태머신, 자정 리셋 | **단독 쓰기** |
| `morning_report/validator.py` | `validate_order()` 중앙 preflight | 읽기만 |
| `data/position_state.json` | 보유 포지션, 분할 가중평단, 최고가, 진입 단계 | monitor 전용 |
| `data/trading_state.json` | daily_pnl, daily_trade_count, COOLDOWN 타임스탬프, 주문 차단 플래그 | monitor 전용 |
| `data/pending_proposals.json` | 재권유 상태머신 (제안별 카운터·마지막 전송·상태) | monitor 전용 |
| `logs/trading.log` | 주문·체결·검증 실패·알람 JSON 라인 | monitor + orchestrator |
| launchd plist | `com.aigeenya.stockreport.position_monitor.plist` (KeepAlive) | - |

### 수정

| 경로 | 변경 요점 |
|---|---|
| `morning_report/telegram_bot.py` | `/매수함`, `/매수안함`, `/종목변경` 파서 추가, 초당 1건 throttle 큐 |
| `morning_report/orchestrator.py` | 매매 명령 라우팅, `validate_order` 호출, 체결 후 통지, monitor에 "주문 요청" 전달 |
| `morning_report/intraday_discovery.py` | round 2/4/6/8 종료 시점에 "1위 종목 매수 제안" monitor에 요청 (임계치 통과·COOLDOWN 배제) |
| `morning_report/closing_report.py` | 장마감 강제청산 트리거 연동 (15:15 시장가 / 15:25 동시호가 재시도) |
| `morning_report/keychain_manager.py` | `KIS_TRADING_ACCOUNT_NO` 로드 추가 |
| `data/strategy_config.json` | `trading` 섹션 신설 (reserve_ratio, split weights, 타임아웃, 한도, 장마감 시각) |
| `.skills/kis-api/scripts/kis_client.py` | `order_buy()`, `order_sell()`, `inquire_psbl_order()`, `inquire_balance()` 추가 (실전 TR 코드 Stage 5에서 확정) |

### 파일 쓰기 동시성 — 단일 쓰기 프로세스 원칙

- **`position_monitor`만이 3종 JSON(`position_state`, `trading_state`, `pending_proposals`)에 쓰기 가능**
- `telegram_bot`, `orchestrator`, `intraday_discovery`는 **읽기 전용**
- 쓰기를 원하는 모듈은 **내부 큐(파일 또는 메모리)로 요청**하고, monitor가 루프에서 소비
- 파일 락 불필요 (단일 쓰기자), 단 monitor 내부에서 쓸 때는 임시 파일 → rename 원자적 교체

---

## 리스크 및 완화

| 리스크 | 완화 방법 | 담당 (Stage) |
|---|---|---|
| 오발주 (종목·수량·방향 오류) | `validate_order` 중앙 preflight + `KIS_ALLOW_LIVE_ORDER` 가드 + 첫 운영 1주 시범 + dry-run 선행 | Stage 5 설계 + Stage 8 구현 |
| 지연 체결 (권유~승인 사이 급변) | `/매수함` 시점 현재가 재조회 + ±3% 가드 | Stage 5 |
| MAX_DAILY_LOSS 도달 시 시스템 다운 | `sys.exit` 폐기, 차단 플래그 전환, 자정 자동 해제 | Stage 5 |
| 봇/monitor 다운 시 자동 손절 누락 | launchd KeepAlive + 재시작 직후 현재가 전수 조회로 놓친 손절 판정 | Stage 5 |
| 파일 I/O 경쟁 | 단일 쓰기 프로세스 원칙 (monitor 단독), 원자적 교체 | Stage 5 확정 |
| 주문 실패 · API 타임아웃 | 주문 타임아웃 5초, 재시도 없음, 실패 시 pending 복귀 + 텔레그램 알람 | Stage 5 |
| 부분 체결 / 체결 미확정 | 주문 응답 + 잔고 조회 2단 확인 | Stage 5 |
| 중복 권유 · 중복 체결 | 분할 단계별 독립 카운터, 상태 `pending/accepted/declined/exhausted/expired` | Stage 5 |
| 봇 재시작 중 pending 만료 처리 | 재시작 시 `last_sent > 5분`이면 즉시 만료, 다음 round 대기 | Stage 5 |
| 시간외·휴장 주문 시도 | `is_market_open()` 게이트, 장외 시간 주문 호출 자체 차단 | Stage 5 |
| 장마감 체결 실패 | 15:15 시장가 → 15:25 동시호가 재시도의 2단 청산 | Stage 5 |
| 인증정보 노출 | Keychain 유지, 계좌번호 마스킹, JSON 구조 로그 | Stage 5 / 8 |
| 텔레그램 rate limit | 초당 1건 throttle 큐 | Stage 5 |

---

## 주요 가정

1. KIS Open API 실전 주문 TR 코드는 v0.1 모의(`VTTC0802U`/`VTTC0801U`)와 다르다. Stage 5에서 `docs/api/` xlsx 전수 확인.
2. 실전 소액계좌 개설 및 Keychain 등록은 **형진님이 사전 준비**. 코드는 `KIS_TRADING_ACCOUNT_NO` 존재 시에만 동작.
3. 형진님은 초기 1주일 매일 장중 텔레그램 반응 가능 (시범 운영 검증 동의).
4. 현금 유보율 10%는 초기 기본값, `/설정` 또는 config 직접 편집으로 조정.
5. COOLDOWN 5분(300초)은 초기값, 실전 경험으로 조정.
6. NXT는 Phase 2 범위 밖. `is_market_open()`이 장외 시간을 모두 차단.

---

## 설계 단계(Stage 5) 전달 메모

### 아키텍처 제약

- **단일 쓰기 프로세스 원칙**은 확정. monitor만 3종 JSON에 쓴다.
- `validate_order`는 단일 함수 시그니처 `(action, ticker, qty, price_ref) → (ok, reason)`로 통일. 내부에 모든 안전장치 체크 포함.
- 자동 매도·자정 리셋·재시작 복구는 모두 `position_monitor` 안에 위치. 외부로 흩뿌리지 않음.
- 주문 TR 코드는 Stage 5 초입에 `docs/api/` 문서 확인하여 실전 계좌용으로 재지정.

### 특별 고려사항

1. **분할 가중평단 계산** — v0.1은 덮어쓰기. 5:3:2 가중평균 로직 신규 작성. 단계 기록·최고가 기록도 같이 담는다.
2. **재권유 상태머신의 5상태** — `pending / accepted / declined / exhausted / expired`. expired는 재시작 복구용.
3. **장마감 2단 청산** — 15:15 시장가 → 15:25 동시호가. 시각은 config화하여 테스트 시 앞당길 수 있도록.
4. **dry-run 모드** — `kis_client.order_buy/sell`이 `DRY_RUN=1` 환경변수에서 실제 호출 대신 가짜 응답 반환. 전체 상태머신·로그·통지는 정상 동작. 실전 가드와 독립.
5. **재시작 복구 스캔** — monitor 부팅 첫 틱에서 보유 종목 전수 현재가 조회 + 손절 판정 + pending 만료 처리를 원자적으로 실행.
6. **메시지 throttle** — `telegram_bot` 내부 큐, 초당 1건 전송 상한.

### 팀 제약

- 구현(Stage 8, 10)은 Codex 위임. Claude는 Stage 5에서 Codex가 바로 쓸 수 있는 브리프 작성.
- `docs/api/한국투자증권_오픈API_전체문서_*.xlsx` 주문 관련 TR 확인은 Stage 5 착수 시 첫 작업.

### Stage 5에서 확정할 열린 질문 (Stage 3 리뷰 반영 후 남은 것)

1. ~~position_monitor 분리 vs 통합~~ → **분리 확정** (단일 쓰기 프로세스 원칙상 독립 데몬이 자연스러움)
2. `/설정` 명령 세부 문법 — P1이므로 Stage 5에서는 훅 포인트만 남겨두고 구현은 연기
3. 동시 보유 종목 수 상한 — 시드 규모 확정 전까지 "상한 없음 + 유보금 10% 가드만"으로 Stage 5 진행
4. 초기 시드 / 종목당 최대 한도 — 동일하게 시드 확정 후
5. pending 다건 우선순위 — "먼저 들어온 것부터 FIFO, 동일 시각이면 점수 높은 것" 기본 규칙, Stage 5에서 구현

---

## 체크리스트 (Stage 5 진입 전)

- [x] Stage 3 리뷰 16개 수정 제안 중 1~12번 반영
- [x] 13~16번 반영 (throttle, /설정 대안, 성공 기준 정량화, 서브페이즈 처리)
- [x] MAX_DAILY_LOSS 단위 확정 (절대금액, 실현손익)
- [x] 장마감 시각 확정 (15:15 / 15:25 2단)
- [x] 자정 리셋 책임자 확정 (position_monitor)
- [x] 파일 쓰기 원칙 확정 (monitor 단독)
- [x] 테스트 전략 확정 (dry-run 모드)
- [x] 로그 정책 확정 (trading.log JSON + 마스킹)
- [x] Phase 2 범위 확정 (KRX 정규장만)
- [ ] **형진님 최종 승인** 🔴 — 이 체크리스트가 완료되어야 Stage 5 진입 가능

---

*자동 생성 | stockpilot Phase 2 Stage 4 — Plan Final*

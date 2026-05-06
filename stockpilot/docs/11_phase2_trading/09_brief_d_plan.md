# Brief D Stage 4 — 텔레그램 명령 + 주문 요청 파이프라인 (계획 초안)

> 날짜: 2026-04-23 | 담당: Claude (Opus) | 상위 문서: `04_plan_final.md`
> Brief C 완료 직후 착수. Stage 4 승인 후 Stage 5 기술 설계로 진입.

---

## Brief D의 범위

Brief A (인프라), Brief B (상태 계층), Brief C (position_monitor 패시브 감지)는 모두 완료. Brief D는 **사용자 접점 + 주문 실행 파이프라인**을 완성한다. 즉 발굴이 제안을 만들고 → 텔레그램이 형진님에게 질의하고 → 응답이 들어오면 실제 KIS 주문이 나가고 → 체결 결과가 `position_state`에 반영되는 루프 전체를 닫는다.

Brief C가 "보고 있는 사람"이었다면 Brief D는 "질문하고 응답받아 실제로 주문을 내는 사람"이다.

### Brief D 안에서 다루는 5가지

1. **intraday_discovery → 제안 enqueue**
   - round 2/4/6/8 종료 직후 1위 종목을 `pending_proposals.json`에 `pending`으로 등록
   - 단일 라이터 원칙: 이 enqueue도 기술적으로 position_monitor가 대신 한다 (intraday_discovery는 `discovery_result.json` 같은 중간 파일에 1위 종목을 쓰기만 하고, position_monitor가 이를 보고 enqueue)
   - 임계치 미달/COOLDOWN 종목은 스킵

2. **매수 제안 질의 (position_monitor + telegram_bot 협업)**
   - position_monitor 5초 틱에서 `pending` 제안 중 `last_sent`가 비었거나 3분 지난 것을 발견하면 텔레그램 카드 전송 요청
   - telegram_bot은 send_text() 호출 전에 "throttle 큐"(초당 1건)를 거친다
   - 카드 내용: 종목명·코드·점수·권유가·수량·TOP5 후보 목록 + 응답 옵션 안내
   - `count` 3회까지 재권유, 초과 시 `exhausted`로 전이

3. **텔레그램 명령 3종 + 강제청산 응답 2종**
   - `/매수함` `/매수안함` `/종목변경 <1~5>` → 매수 승인 플로우
   - `/청산함 <종목코드>` `/청산안함 <종목코드>` → 강제청산 응답
   - orchestrator가 명령 해석 + chat_id 검증 + `buy_request.jsonl` / `sell_request.jsonl` 발행
   - 발행 후 "접수했습니다" 즉시 응답, 실제 체결 결과는 position_monitor가 별도 통지

4. **request 큐 소비 (position_monitor 확장)**
   - position_monitor 5초 틱에 `_tick_process_requests()` 추가
   - `buy_request.jsonl` / `sell_request.jsonl` 의 미처리 라인을 읽어 validator.validate_order 통과 시 KIS 주문 실행
   - 성공 시 position_state 갱신 + proposal을 `accepted`로 전이 + 텔레그램 체결 통지
   - 실패 시 `trading.log`에 이유 기록 + 텔레그램 실패 통지 + proposal은 `pending`로 유지

5. **강제청산 3분 질의 플로우**
   - Brief C에서 손실한도 도달 시 `block_new_orders=True`만 flip했다. Brief D는 여기에 "3분 질의" 절차를 얹는다
   - position_monitor가 손실한도 도달 순간 텔레그램으로 "🚨 강제청산 여부를 3분 안에 결정해주세요" 질의
   - 3분 내 `/청산함 <코드>` 수신 시 `sell_request.jsonl` 발행 → 매도 체결
   - 3분 무응답 또는 `/청산안함` 시 아무 매도 안 함 (보유 유지, block_new_orders만 True 유지)

---

## 데이터 플로우 (Brief D 추가분)

```
[intraday_discovery round 2/4/6/8]
      │
      │  1위 종목을 data/discovery_result.jsonl 에 append
      ▼
[position_monitor 틱]
      │  discovery_result.jsonl 라인 감지 → pending_proposals 에 enqueue
      ▼
[position_monitor 틱]
      │  pending 제안 감지 → telegram_sender.queue(card)
      │                      ↓
      │              [telegram_bot throttle 큐] (초당 1건)
      ▼
[사용자 응답: /매수함 or /매수안함 or /종목변경 2]
      │
      ▼
[telegram_bot → orchestrator.handle_command]
      │  chat_id 검증 → buy_request.jsonl 에 라인 append
      │  즉시 "접수" 응답
      ▼
[position_monitor 틱]
      │  buy_request.jsonl 새 라인 감지 → validator.validate_order
      │      통과: KIS 주문 → position_state 갱신 + proposal accepted
      │      실패: trading.log + 텔레그램 실패 통지 (proposal은 pending 유지)
      ▼
[텔레그램 체결 통지]
```

강제청산 플로우도 동일한 request 큐(sell_request.jsonl)를 재사용한다.

---

## 파일 구조

### 신규

| 경로 | 책임 | 쓰기 권한 |
|---|---|---|
| `data/discovery_result.jsonl` | intraday_discovery → position_monitor enqueue용 중간 큐 | discovery(append), monitor(read/truncate) |
| `data/buy_request.jsonl` | orchestrator → position_monitor 매수 요청 큐 | orchestrator(append), monitor(read) |
| `data/sell_request.jsonl` | orchestrator → position_monitor 매도 요청 큐 | orchestrator(append), monitor(read) |
| `data/request_cursor.json` | monitor의 request 파일 처리 위치 (byte offset + 마지막 처리 시각) | monitor 전용 |
| `morning_report/request_queue.py` | 3개 JSONL 파일 append/tail 유틸 | - |
| `morning_report/proposal_notifier.py` | position_monitor가 호출하는 "매수 제안 카드 포맷터" | - |

### 수정

| 경로 | 변경 요점 |
|---|---|
| `morning_report/intraday_discovery.py` | round 2/4/6/8 종료 시 1위를 discovery_result.jsonl에 append |
| `morning_report/orchestrator.py` | 5개 명령(`/매수함` `/매수안함` `/종목변경` `/청산함` `/청산안함`) 라우팅 + request 파일 발행 |
| `morning_report/telegram_bot.py` | 인수 파싱 개선 (기존은 whitespace split만) + throttle 큐 송신 래퍼 |
| `morning_report/telegram_sender.py` | 초당 1건 throttle 큐 추가 (기존 send_text를 감쌈) |
| `morning_report/position_monitor.py` | `_tick_ingest_discovery_result()`, `_tick_notify_pending_proposals()`, `_tick_process_requests()`, `_notify_loss_limit()` 4개 tick 추가 |
| `morning_report/validator.py` | 현재 9-check 유지 (Brief B에서 완성됨, Brief D는 호출만) |

### 단일 라이터 원칙 유지

- position_state, trading_state, pending_proposals 3종 JSON은 계속 **position_monitor만 쓰기**
- orchestrator는 request JSONL 파일(append-only)만 쓰기 → append는 원자적이므로 락 불필요
- intraday_discovery는 discovery_result.jsonl만 append
- position_monitor는 request/discovery 파일을 "읽기 + cursor 전진"만 함 (파일 삭제는 자정 리셋 때 한꺼번에)

---

## 텔레그램 UX 상세

### 매수 제안 카드 (발송)

```
📢 매수 제안 — 삼성전자 (005930)
Round 2 · 1위 · Stage ⭐교집합
점수 85 / 체결강도 125 / 당일 +3.2%
권유가 87,200원 · 수량 50주 (1차 50%)

📋 TOP5 대안
  1. 삼성전자 (005930)  ← 현재 제안
  2. LG전자 (066570)
  3. 네이버 (035420)
  4. 카카오 (035720)
  5. 현대차 (005380)

응답:
  /매수함         (현재 제안 승인)
  /매수안함       (거절)
  /종목변경 2~5   (TOP5 중 다른 종목 선택)

⏱ 3분 내 응답 없으면 재권유 (최대 3회)
```

### 매수 명령 응답 (즉시)

```
✅ 접수: /매수함 — 삼성전자 50주
   주문 실행 중... (체결 결과는 잠시 후 통지)
```

### 체결 통지 (position_monitor 발송)

```
✅ 체결: 삼성전자 50주 @ 87,300원
   평단: 87,300원 · 실현손익 0원
   (validate_order: 잔고 OK · COOLDOWN OK · 손실한도 OK · 실전가드 OK)
```

### 강제청산 질의

```
🚨 강제청산 질의 — 삼성전자 (005930)
현재가 83,900원 · 평단 87,200원 · -3.78%
일일 실현손실 누적 -487,000원 (한도 -500,000원까지 -13,000원)

⏱ 3분 안에 응답해주세요
  /청산함 005930      (전량 시장가 청산)
  /청산안함 005930    (보유 유지)

※ 3분 무응답 = 청산 안 함 (기본)
```

---

## 재권유 상태머신 (기존 pending_proposals와 일치)

- 상태: `pending` → `accepted` / `declined` / `exhausted` / `expired`
- `count`: 재권유 발송 횟수 (0→1→2→3)
- `last_sent`: 마지막 텔레그램 전송 시각
- 전이 규칙:
  - `pending` + `count < 3` + `last_sent`가 비어있거나 3분 경과 → 재전송 + `count += 1`
  - `pending` + `count >= 3` → `exhausted`로 전이 (더 이상 질의 안 함)
  - `/매수함` 수신 + 주문 성공 → `accepted`로 전이
  - `/매수안함` 또는 `/종목변경` 수신 → `declined`로 전이 (변경 선택 시 새 proposal을 top5 기반으로 생성)
  - 자정 리셋 시 `pending` 모두 `expired`로 청소 (Brief C에 이미 구현됨)

---

## 주요 설계 결정

1. **UX: 인라인 키보드 vs 텍스트 명령** → 텍스트 명령 유지 (`04_plan_final.md` 결정 준수)
   - 이유: 기존 telegram_bot.py가 urllib 기반이라 inline keyboard callback을 다루려면 구조 변경이 큼. 텍스트 명령이 심플하고 충분.

2. **request 큐 포맷: JSONL append-only**
   - 이유: 원자적 append로 락 불필요. cursor 파일로 재시작 시에도 처리 위치 복원 가능. 감사 로그 겸용.

3. **discovery → proposal enqueue 경유지 (`discovery_result.jsonl`)**
   - 이유: 단일 라이터 원칙 유지. discovery 프로세스가 pending_proposals.json을 직접 건드리지 않도록.

4. **throttle 위치: telegram_sender**
   - 이유: 모든 송신 경로(position_monitor·orchestrator·intraday_discovery)가 공유하는 지점이 telegram_sender. 여기에 내부 큐 하나 두면 전체 초당 1건 제한 달성.

5. **강제청산: 자동 청산 없음 (보수적)**
   - 이유: 사용자 답변 ("무응답 = 청산 안 함"). 규칙 위반 방지, 의도치 않은 매도 0건 보장.

6. **종목변경 시 새 proposal 생성 방식**
   - `/종목변경 2` 수신 시: 현재 proposal을 `declined`로 전이 + top5[1]을 기반으로 새 proposal을 `pending`으로 enqueue (count=0으로 리셋)
   - 이렇게 하면 "대체 종목도 3분 × 3회 재권유" 동일 규칙 적용

---

## 구현 작업 단위 (Stage 6 Codex 브리프 예고)

| # | 작업 | 예상 파일 | 비고 |
|---|---|---|---|
| D1 | `request_queue.py` 신설 + 단위 테스트 | 신규 | append/tail/cursor |
| D2 | `telegram_sender.py` throttle 큐 | 수정 | 초당 1건, 백그라운드 스레드 |
| D3 | `proposal_notifier.py` 카드 포맷터 + 단위 테스트 | 신규 | 순수 함수 |
| D4 | `orchestrator.py` 5개 명령 라우팅 + request 발행 | 수정 | 기존 명령 유지 |
| D5 | `telegram_bot.py` 인수 파서 강화 | 수정 | 미세 수정 |
| D6 | `position_monitor.py` 4개 tick 추가 | 수정 | Brief C 테스트 전부 그린 유지 |
| D7 | `intraday_discovery.py` discovery_result enqueue | 수정 | round 2/4/6/8 조건 |
| D8 | 통합 테스트: `tests/test_request_pipeline.py` | 신규 | Brief C+D 통합 |

---

## 체크리스트 (Stage 5 진입 전)

- [ ] **형진님 승인** 🔴 — 범위·UX·request 큐 접근법 확인
- [ ] 텔레그램 명령어 5종 최종 합의 (`/매수함` `/매수안함` `/종목변경` `/청산함` `/청산안함`)
- [ ] 매수 카드 포맷 최종 합의 (위 예시대로)
- [ ] 강제청산 기본 동작 = "무응답 = 청산 안 함" 확정
- [ ] 단일 라이터 원칙 유지 (request 큐 append-only) 확정
- [ ] Brief C (position_monitor) 수정 필요 범위 확인 (4개 tick 추가)

---

*Brief D Stage 4 초안 — 2026-04-23*

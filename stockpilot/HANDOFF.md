# 🤝 stockpilot — Handoff 문서

> 최종 업데이트: 2026-05-07 새벽 (v2.8.9 — NXT Stage2/3 + 회귀 검증)
> 다음 세션 시작 시: 본 문서 먼저 읽고 v2.8.9 상태 복원
> 다음 평일 (2026-05-07 목) 운영 검증 + 5/9(토)/5/10(일) 메시지 미발송 확인 우선
> 목적: 새 대화창에서 즉시 작업을 이어받을 수 있도록 현재 상태 전달

---

## 🆕 2026-05-07 (새벽) — v2.8.9: NXT Stage2/3 + 회귀 검증

### NXT 옵션 B WORKFLOW 진척
- **Stage 2 (plan_draft):** `docs/14_nxt_integration/02_plan_draft.md`
  - Task A~E 분해, 옵션 2 (N+X 듀얼) 권고 유지, 작업량 3.5h 추정
- **Stage 3 (plan_review, High effort 자체 검토):** `docs/14_nxt_integration/03_plan_review.md`
  - **R1~R10 보완점 10건 + 결정 5건**
  - 핵심 보완: R3 output2(예수금) 차이 비교, R4 v2.7.4 충돌 회피, R5 morning_report 보류, R7 balance_diff 모듈 분리
  - 작업량 재추정: 3.5h → **5h**
- **Stage 4 (plan_final):** 형진님 결정 5건 후 진입
  1. 옵션 2 채택 여부 (권고 ✅)
  2. morning_report X 모드 적용 (권고 ✗ 보류)
  3. balance_diff 별도 모듈 분리 (권고 ✅)
  4. v2.8.4 안내문 제거 시점 (권고: Task E 검증 후)
  5. 검증용 NXT 거래 의도 실행 (5/8 또는 5/9 NXT 매매 1건)

### 회귀 검증 (108개 테스트 PASS)
```
tests/test_market_calendar.py     24 PASS  (신규)
tests/test_kis_client_phase2.py    n PASS
tests/test_pattern_lifecycle.py    n PASS
tests/test_pending_proposals.py    n PASS
tests/test_position_monitor.py    11 PASS
tests/test_position_state.py      10 PASS
tests/test_risk_analyzer.py        3 PASS
tests/test_trading_state.py        8 PASS
tests/test_validator.py           16 PASS
─────────────────────────────────────────
Total                            108 PASS  (0.56s)
```

→ v2.8.5~v2.8.8 변경이 기존 Phase 2 모듈에 회귀 영향 없음.

### launchd plist 31개 전수 점검
- 시간 불일치 0건 ✅
- discovery5 (14:03) / discovery6 (14:05) status 0 정상화 확인
- 다른 plist 시간 버그 추가 검출 0건

### state_manager 분석 (discovery6 누락 가설 보강)
- `state.update()` (line 76): shallow merge로 round 키 단순 추가 — **로직 자체는 정상**
- `_load()` (line 110): 날짜 변경 시 초기화 트리거 (5/6 운영 중 트리거 안 됨)
- 5/6 운영 후 state 누락 round: **[5, 6, 9, 10, 11, 12, 13, 14]**
  - 5, 6 (14:03/14:05) = plist 버그로 미실행 → **정상 누락**
  - **9~14 (10:03~11:05) = 실행됐는데 state 미저장 — 미스터리**
- 가설:
  1. 동시 _save race condition (file lock 없음)
  2. 다른 프로세스(orchestrator/telegram_bot)가 state["intraday_discovery"]를 dict 통째로 덮어씀
  3. _load에서 _EMPTY_STATE deep_merge가 round 키를 누락
- **다음 평일(5/7) 운영 결과로 재현 여부 확인** — 재현 시 file lock 추가 또는 deep merge 검증

---

## 🆕 2026-05-06 (밤) — v2.8.8: NXT Stage1 + 5/5 정정 + 단위테스트 + requirements

---

## 🆕 2026-05-06 (밤) — v2.8.8: NXT Stage1 + 5/5 데이터 정정 + 단위테스트 + requirements

### 1. NXT 옵션 B Stage 1 (브레인스토밍) 완료
**문서:** `docs/14_nxt_integration/01_brainstorm.md`

**핵심 발견:** KIS `주식잔고조회`(TTTC8434R) 요청 헤더에 `AFHR_FLPR_YN` 파라미터 존재
- `N` (기본값) — 정규장 KRX
- `Y` — 시간외단일가
- **`X`** — **NXT 정규장 (프리마켓 + 메인 + 애프터마켓 통합)**

**구현 옵션 비교** (Stage 2에서 결정 예정):
1. `X` 모드 단일 호출 — 1시간, 가장 단순
2. **`N`+`X` 듀얼 호출 + 차이 표시** — 2~3시간, **권고** (NXT 차이 명시적 표시)
3. 시간대 분기 — 3~4시간, 복잡

**다음:** 형진님 검토 → 옵션 선택 → Stage 2 진입

### 2. 5/5 어린이날 휴장 데이터 정정
- `data/discovery_log.json` 5/5 레코드 10건의 `close_price`/`return_pct` 제거 + `holiday_skipped: true` 마커 추가
- 백업: `data/discovery_log.json.bak.20260506_235855`
- 효과: 다음 모닝 리포트(5/7)의 "어제 발굴 성과" 섹션이 깔끔하게 표시됨

### 3. market_calendar 단위 테스트 (24/24 PASS)
- 신규: `tests/test_market_calendar.py`
- 19개 시나리오 (영업일/주말/공휴일/대체공휴일/연휴) + 5개 previous_trading_day 케이스
- 실행: `venv/bin/python3 -m pytest tests/test_market_calendar.py -v`

### 4. requirements.txt 신규
- 누락됐던 핵심 의존성 명시 (holidays, openpyxl 포함)
- 새 환경 구축 시: `venv/bin/python3 -m pip install -r requirements.txt`

### 5. discovery6 round6 state 미저장 가설 (백로그)
**관찰:**
- 5/6 운영 후 state에 round 5/6/9~14 누락 (round 7/8 + 15~26은 정상)
- 14:05 round6 stderr는 정상: 텔레그램 발송 + `_save_discovery_log` 성공
- 그러나 `state.update("intraday_discovery", {"round6": ...})`가 반영 안 됨

**가설:**
- `state_manager.py`의 update가 deep merge가 아닌 shallow replace 가능성
- 또는 동시 실행 race condition (15:05에 round 26 + round 6 동시 실행 → 한쪽이 다른 쪽 덮어씀)

**우선순위:** 낮음 (5/6 plist 핫픽스로 동시 실행 충돌 해소). 다음 평일 5/7~5/8 운영 결과로 재현 여부 확인.

---

## 🆕 2026-05-06 (저녁) — v2.8.7: 휴장일(주말+한국 공휴일) 가드 통일

### 배경
- 5/5(화) 어린이날 운영 시 KIS API가 휴장 데이터를 정상 거래일처럼 반환 → 발굴 + 발송 진행됨 → 모닝 리포트 통계 오염
- 사용자 요구: 토요일/일요일/한국 공휴일에 모든 자동 텔레그램 메시지 미발송

### 신규 모듈
- **`morning_report/market_calendar.py`** — 한국 거래소 영업일 판정 공통 유틸
  - `is_trading_day(d=None) -> bool` — 토/일/한국 공휴일이면 False
  - `holiday_name(d=None) -> str | None` — 공휴일 이름 반환
  - `previous_trading_day(d=None) -> date` — 이전 영업일 (휴장 스킵)
  - `exit_if_holiday(script_name)` — 휴장이면 sys.exit(0) (entry point용)

### 의존성
- **`holidays` 라이브러리** — venv에 설치 (`venv/bin/python3 -m pip install holidays`)
- 미설치 시 weekday만으로 판정 (안전성 ↓ — 평일 공휴일 누락)
- requirements.txt 미관리 프로젝트 → 새 환경 구축 시 수동 설치 필요

### 7개 스크립트 가드 통일
| 스크립트 | 변경 |
|---|---|
| `morning_report.py` | 기존 `is_trading_day`/`_WEEKDAYS` 제거 → market_calendar import. `_previous_trading_day`도 위임 (대체공휴일 인식) |
| `intraday_discovery.py` | `_WEEKDAYS` 제거. line 163 가드 통일 + 공휴일 이름 표시 |
| `closing_report.py` | `_WEEKDAYS` 제거. line 55 가드 통일 |
| `intraday_report.py` | `_WEEKDAYS` 제거. line 43 가드 통일 |
| `stock_discovery.py` | "일요일만 건너뜀" → "휴장일 건너뜀". `force` 우회 보존 |
| `pattern_lifecycle.py` | entry point에 `exit_if_holiday()` 추가 (`--force`/`--dry-run` 우회) |
| `watchlist_sync.py` | entry point에 `exit_if_holiday()` 추가 (`--show`/`--force` 우회) |

### 검증 (8개 시나리오 100% 통과)
- 5/5 어린이날 (화) → False ✅
- 5/6 (수) → True ✅
- 5/9 (토) → False ✅
- 5/10 (일) → False ✅
- 5/11 (월) → True ✅
- 5/25 부처님 대체 (월) → False ✅
- 6/3 지방선거일 (수) → False ✅
- 12/25 성탄절 (금) → False ✅
- `previous_trading_day(2026-05-26)` → `2026-05-22` (5/25 대체공휴일 스킵) ✅

### 우회 옵션 (수동 호출/테스트)
- `stock_discovery.run(force=True)` — orchestrator 텔레그램 `/발굴` 명령
- `pattern_lifecycle.py --force` 또는 `--dry-run`
- `watchlist_sync.py --show` 또는 `--force`

### 다음 검증 일정
- **2026-05-07 (목, 영업일)** — 모든 스크립트 정상 실행 (모닝/발굴/클로징 텔레그램 도착)
- **2026-05-09 (토)** — 메시지 미발송 확인 (특히 23:30 stock_discovery)
- **2026-05-10 (일)** — 메시지 미발송 확인
- **2026-05-25 (월, 부처님 대체)** — 평일이지만 미발송 확인 (다음 평일 공휴일)

---

## 🆕 2026-05-06 (저녁) — v2.8.6: discovery5/6 plist 운영 시각 핫픽스

### 발견된 운영 영향
- **5/6(수) 14:03/14:05 미실행 + 15:03/15:05 충돌** — discovery5/6 plist의 화/수/목/금 항목 Hour가 14에서 15로 잘못 등록되어 있었음 (월요일만 정상)
- 14:05 발굴 텔레그램 통째로 누락 (사용자 텔레그램 메시지에 14:05 결과 없음 = 일치)
- 15:05에 round 26 + round 6 동시 실행 → round 6이 round5 데이터 만료로 exit 1 (`launchctl list discovery6 status 1` 흔적)

### 핫픽스 적용 (2026-05-06 저녁, PlistBuddy)
```
/usr/libexec/PlistBuddy -c "Set :StartCalendarInterval:{1,2,3,4}:Hour 14" \
  ~/Library/LaunchAgents/com.aigeenya.stockreport.discovery{5,6}.plist
```
- discovery5 5개 Weekday 모두 14:03 통일 ✅
- discovery6 5개 Weekday 모두 14:05 통일 ✅
- launchctl unload + load 재등록 완료 (status 0 확인)
- 검증: 다음 평일(5/7 목) 14:03/14:05 정상 실행 확인 필요

### 원인 추정
v2.7.1 "round 5~8 plist 시각 14:03 원복" (HANDOFF 8-2섹션) 작업 시 discovery7/8은 인라인 형식으로 통일됐으나 discovery5/6은 화~금 4개 dict의 Hour 수정이 누락된 채 봉합. 신규 시간대 추가(round 9~26) 시 15:03/15:05와 정확히 충돌하여 오늘 발현.

---

## 🆕 2026-05-06 (저녁) — v2.8.5: 휴장일 보호 + 안전장치

### 5/5 어린이날 휴장 진단
- 5/5 발굴 10건 모두 `disc_price == close_price` 패턴 (예: 232500 → 232500)
- KIS API가 휴장 시 전일 종가만 반환 → return_pct = 0.0 잘못 표기
- 09:05/15:05 발굴 종목이 정확히 동일 5건씩 = 휴장 패턴 확정 (한국 어린이날)

### 핫픽스 (3건)
| 파일 | 변경 |
|---|---|
| `closing_report.py` | `disc_price == close_price` 시 휴장 의심으로 판정 → 종가 갱신 스킵 |
| `morning_report.py` | `_build_yesterday_discovery_section` 필터 강화: 휴장 의심 자동 제외 + "발굴 N종목 — 휴장 의심 (KIS 데이터 전일종가 동일)" 안내 |
| `intraday_discovery.py` | `_load_today_other_period_discoveries` 미래시점 발굴 제외 안전장치 (정상 운영선 불필요, dry-run/재시뮬 보호) |

### 검증
- `py_compile` 통과
- 시뮬1: 12:05 시점에 13:05 미래 발굴 5건 자동 제외 (09:05 발굴 3건만 반환)
- 시뮬2: 5/5 휴장 데이터 10건 → "휴장 의심" 안내 정상 출력

---

## 🆕 2026-05-06 (저녁) — v2.8.4: 5/6 운영 검증 + NXT 안내문 핫픽스

### 5/6 (수) 운영 검증 결과 (텔레그램 메시지 기준)

| 검증 항목 | 결과 | 비고 |
|---|---|---|
| 08:30 모닝 — B1/B2 두 섹션 | ❌ 누락 | v2.8.3 코드 mtime 10:04 → 08:30 실행 시점 미적용 (예상 결과) |
| 09:05 발굴 — 한국어 시간/분리 | ❌ 옛 형식 | 코드 적용 전 실행 (예상 결과) |
| 12:05 발굴 — 한국어 시간/점심 표시 | ✅ | "🔍 12시 5분 발굴 (점심 신뢰도 ↓)" 정상 |
| 12:05 발굴 — 신규/재등장 분리 | ❌ 미작동 | 옛 형식 ("후보 7종목 → 상위 3종목 선정") |
| 13:05 발굴 — 한국어 시간 | ✅ | "🔍 1시 5분 발굴" 정상 |
| 13:05 발굴 — 신규/재등장 분리 | ❌ 미작동 | 옛 형식 |
| 13:05 발굴 — 15% 자동 제외 | ⚠️ | 삼전 +15.1% / 미래에셋 +21.1% 통과 |
| 15:05 발굴 — 신규/재등장 분리 | ✅ | "후보 3종목 → 신규 0 + 재등장 3" 정상 |
| 15:05 발굴 — 한국어 시간 | ✅ | "🔍 3시 5분 발굴" 정상 |
| 20:30 클로징 — 기본 동작 | ✅ | SK하이닉스 양봉/거래량/손절가 정상 |
| 20:30 클로징 — 평가손익 정확성 | 🔴 | NXT 정규외 거래 미반영 → 사용자 지적 |

### 핫픽스 (closing_report.py)
- 마지막 안내문에 1줄 추가:
  ```
  ※ NXT 정규외(프리장) 거래는 정규장 데이터에 미반영 — 평가손익 별도 확인 권고
  ```

### 진단 분석 (코드 점검 + dry-run 시뮬레이션)

**현재 코드(working tree)는 정상 작동 확인됨:**
- `_build_message` (intraday_discovery.py line 1709~1783): 분리 로직 정상 구현
- `_load_today_other_period_discoveries` (line 85): 시간대 비교 로직 정상
- 17:51 시점에 round18 (12:05) 데이터로 시뮬레이션 → "신규 0 + 재등장 7" 정상 출력
- `_MAX_FLC_PCT = 15.0` 부등호 `>=` (line 1663): 정상

**12:05/13:05 옛 형식 출력 원인 (미확정 가설):**
1. v2.8.3 작업이 git 미반영 상태에서 단계적으로 적용됨 → 12:05/13:05 실행 시점에는 _build_message가 옛 코드였을 가능성 (mtime은 마지막 수정 1회만 기록)
2. 13:05에 삼전 +15.1% 통과 = 점수 산정 시점엔 14.x%였다가 메시지 출력 시점에 15.1%로 갱신된 데이터 변동 가능성

**검증 방법:** 다음 평일(5/7 목) 08:30~15:05 자동 운영 결과 재모니터링.

### 발견 부수 사항
- **5/5 발굴 10건 모두 `return_pct=0.0`** — close_price는 정상이지만 등락률이 0%. closing_report 계산 또는 데이터 갱신 로직 점검 필요 (5/5 어린이날 휴장 가능성? — 그러나 _previous_trading_day는 weekday 기준이라 공휴일 미감지)
- **`_load_today_other_period_discoveries` 안전장치 부족** — 현재 시점보다 늦은 발굴도 시간대만 다르면 포함. 정상 운영에서는 영향 없으나 dry-run/재실행 시 오작동 가능. 백로그.

### 백로그 추가 (NXT 거래 통합 — Phase별)

| 옵션 | 작업량 | 효과 | 우선순위 |
|---|---|---|---|
| **A. 단기 안내문** | 5분 | 사용자 인지 (✅ 완료) | 완료 |
| **B. KIS NXT 거래 API 통합** | 1~2시간 + WORKFLOW Stage 1~7 | 정확한 평가손익 | 높음 (다음 세션 위임) |
| **C. closing_report 시각 변경** | plist 수정 + 데이터 시점 조정 | NXT 종가 기준 정합 | 중간 (옵션 B 검토 후 결정) |

### 다음 세션 작업
1. **5/7 (목) 자동 운영 모니터링** — 모든 시간대 v2.8.3 적용 확인
2. **5/5 return_pct=0.0 원인 점검** — closing_report `return_pct` 계산 로직 또는 5/5 휴장 여부 확인
3. **옵션 B 검토 시작** — `docs/api/한국투자증권_오픈API_전체문서.xlsx`에서 NXT 거래내역 조회 API 탐색 → WORKFLOW Stage 1 (브레인스토밍) 진입
4. **`_load_today_other_period_discoveries` 안전장치 추가** (낮은 우선순위) — `disc_t < current_time_str` 조건 추가

---

## 🆕 2026-05-06 (밤) — v2.8.3 발굴 필터 강화

**핫픽스 (intraday_discovery.py):**
- `_MAX_FLC_PCT = 15.0` — 등락률 +15% 이상 종목 발굴 자동 제외 (이미 큰 폭 상승 = 발굴 의미 없음)
- `_load_today_other_period_discoveries()` 헬퍼 — 오늘 다른 시간대 발굴 종목 로드
- `_split_new_and_repeat()` 헬퍼 — scored 결과를 신규/재등장 분리
- `_build_message` 4종 모두 업데이트:
  · 메인 섹션: 신규 발굴 종목만 (top 3)
  · "📋 추가 관심 후보": 신규 4-5위만 기준
  · 신규 섹션 "🔁 이전 발굴 재등장": 다른 시간대 발굴 종목 + 발굴 시각 + 현재 등락률
  · 요약: `후보 N종목 → 신규 X + 재등장 Y`

**버그 수정:** 모듈에 `import json` 누락 — 함수 내부에 `import json as _json` 추가 (silently 빈 결과 반환되던 문제)

**검증:**
- py_compile 통과
- _korean_hm / _get_time_thresholds / _split_new_and_repeat 단위 테스트 통과
- 실데이터 시뮬레이션 (오늘 17건 발굴 데이터) 정상 동작 확인

**예상 효과 (내일 운영):**
- 카카오뱅크/카카오페이 같이 9시 발굴됐던 종목이 12시/13시에 또 메인에 나오는 중복 표시 해소
- 미래에셋(+21.1%) 같은 +15% 이상 종목 자동 제외
- 메시지 가독성 ↑ (진짜 신규 발굴이 묻히지 않음)

---

## 🆕 2026-05-06 (저녁) — Briefing Enhancement v2.8.1~v2.8.2

**완료 (Claude 직접 핫픽스, 5건):**
- 발굴 필터 완화 (옵션 D): `_TOP_N` 30→50, 이격도 임계 120→130
- 작업 1 — 텔레그램 헤더 시간대 통일: `_korean_hm()` 헬퍼 + 4개 _build_message 헤더
- B1 — 모닝 리포트 "어제 발굴 성과" 섹션 (`_build_yesterday_discovery_section`)
- B2 — 모닝 리포트 "KOSPI 시장 레짐" 섹션 (yfinance ^KS11 → 추세장/횡보장/하락장)
- A2 — `_score_candidate()` 시간대별 임계값 차등 (9시 110/2.0 ~ 12시 125/3.0)
- A3 — `_time_header()` 12시 발굴 시 "(점심 신뢰도 ↓)" 자동 표시

**Codex 위임 3건 완료 (2026-05-06 저녁):**
- ✅ [Brief 13-A](docs/13_briefing_enhancement/06_codex_brief_a1.md) — A1 시간대 확장: intraday_discovery.py round 9~26 (18개) + dispatcher 26개 + _track_recent_picks 일반화. plist 18개 (Claude 직접 생성, Codex 샌드박스 권한 부재). launchctl 27개 등록 완료
- ✅ [Brief 13-B](docs/13_briefing_enhancement/07_codex_brief_b3.md) — B3 risk_analyzer.py + closing_report 통합 + KOSPI 스트레스 시나리오 5종 + strategy_config risk_analysis 섹션. 단위 테스트 3건 pass
- ✅ [Brief 13-C](docs/13_briefing_enhancement/08_codex_brief_c1.md) — C1 pattern_lifecycle.py + plist (20:35) 등록. 첫 dry-run: +24h 41건 / +72h 25건 추적 가능

**자동 실행 스케줄 확장 (평일 텔레그램 발송 8회 → 14회):**
| 시각 | 내용 |
|------|------|
| 08:30 | 모닝 브리핑 (B1+B2 추가됨) |
| 09:05/09:33 | 9시 발굴/재발굴 (기존) |
| **10:05/10:33** | **10시 발굴/재발굴 (신규)** |
| **11:05/11:33** | **11시 발굴/재발굴 (신규)** |
| **12:05/12:33** | **12시 발굴/재발굴 (신규, 점심 신뢰도 ↓)** |
| **13:05/13:33** | **13시 발굴/재발굴 (신규)** |
| 14:05/14:33 | 14시 발굴/재발굴 (기존) |
| **15:05** | **15시 발굴 (신규, 재발굴 없음)** |
| 20:30 | 클로징 리포트 (리스크 분석 옵션) |
| 20:35 | pattern_lifecycle 후속 추적 (NEW, 백그라운드) |
| 23:30 | 야간 종목 발굴 |

**관련 문서:**
- [docs/13_briefing_enhancement/04_plan_final.md](docs/13_briefing_enhancement/04_plan_final.md) — Stage 4 통합 plan (Q1=C, Q2=A, Q3=B 결정 반영)

**다음 작업:**
- Codex 위임 3건 호출 (Brief 13-A → 13-B → 13-C 순차)
- 각 brief 완료 후 Stage 9 코드 리뷰
- 통합 검증 후 HANDOFF v2.8.x 갱신

---

## 🆕 2026-05-06 (낮) — Pattern Integration v2.8.0

---

## 🆕 2026-05-06 업데이트 — Pattern Integration (5종 매매법 + 4개 외부 레포 차용)

**완료된 단계:** Stage 1 (brainstorm) → Stage 2 (plan_draft) → Stage 3 (review, 20건) → Stage 4 (plan_final, 형진님 승인) → Stage 5 Phase A (technical_design_A)

**핵심 결정:**
- 5종 매매법 (바닥/뚜껑/서치/공급/라인) — 6단 게이트로 통합
- 외부 레포 차용:
  · TradingAgents → R17 Bull/Bear 게이트 (2-stage)
  · Vibe-Trading → R18 ADX > 25 필터 + R19 VaR/CVaR/스트레스 시나리오
  · AutoHedge → 미채택 (정량 룰 부재)
  · QuantDinger → R21 별도 논의 (리스크 디폴트)
- 도입 순서: 서치(B) → 공급/라인+Bull/Bear(C) → 바닥/뚜껑(D) → 레짐+리스크분석(E)
- 신규 매수 강화: B+C + ADX + Bull/Bear 토론
- 단계적 롤아웃: Shadow → Alert → Trade-Small → Trade-Full

**선행 조건 (P0):** Phase 2 Brief A~F 구현 완료 + Trade-Small 검증 통과 = Phase A 착수 게이트

**문서:**
- `docs/12_pattern_integration/02_plan_draft.md`
- `docs/12_pattern_integration/03_plan_review.md` (R1~R21, 19건 + 결정 2)
- `docs/12_pattern_integration/04_plan_final.md` (✅ 형진님 승인)
- `docs/12_pattern_integration/05_technical_design_A.md` (Phase A 인프라 6모듈 + KIS 점검)

**다음 작업:**
- Phase 2 Brief A~F 구현 + Trade-Small 검증 → 통과 시 Phase A 착수
- Stage 8 Codex 위임: Brief A-1 (지표/캔들) → A-2 (라인/패턴 골격) → A-3 (라이프사이클/리스크/KIS점검)
- Phase B~E 기술 설계는 Phase A 검증 완료 후 후속 stage로 작성

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
| 09:30 | `intraday_discovery.py --round 3` | 장중 3차 수집 (09:30분대 재발굴용) |
| 09:33 | `intraday_discovery.py --round 4` | 4차 수집 → 재교집합 → 오전 발굴 추적 + 텔레그램 전송 |
| 09:10 | `intraday_report.py` | 장초기 현황 텔레그램 전송 + state 기록 |
| 14:03 | `intraday_discovery.py --round 5` | 오후장 1차 수집 (14:03분대 발굴용) |
| 14:05 | `intraday_discovery.py --round 6` | 2차 수집 → 교집합 → 오후장 텔레그램 전송 |
| 14:30 | `intraday_discovery.py --round 7` | 오후장 3차 수집 (14:30분대 재발굴용) |
| 14:33 | `intraday_discovery.py --round 8` | 4차 수집 → 재교집합 → 오후 발굴 추적 + 텔레그램 전송 |
| 20:30 | `closing_report.py` | 장마감 결산 텔레그램 전송 + state 기록 |
| 23:30 | `stock_discovery.py` | 야간 종목 발굴 텔레그램 전송 + state 기록 (월~토) |
| 상시  | `telegram_bot.py` | 텔레그램 명령 수신 (부팅 시 자동 시작) |

> ✅ **v2.7.2 (2026-04-21):** round 5~8 plist 시각 14:03 원복 완료 (15:03 임시변경 테스트 취소).
> 현재 등록 상태: discovery5 14:03 / discovery6 14:05 / discovery7 14:30 / discovery8 14:33.

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
3차 매수: 목표 수량 20%  (강한 지지 확인 시만)
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

## 8-1. 완료된 이슈 (v2.4~v2.7, 2026-04-21)

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

### ✅ Phase 1.1 — intraday_discovery round 3/4 (완료, Stage 11 검증 통과)
- `--round 3` 추가: 09:30분대 재발굴용 수집 state 저장
- `--round 4` 추가: 09:33 재교집합 분석 + `⭐재확인` 표시
- 오전 round2 발굴 종목 상위 5개 현재가 추적 섹션 추가
- launchd plist 추가: `com.aigeenya.stockreport.discovery3.plist`, `com.aigeenya.stockreport.discovery4.plist`
- Stage 11 Opus 검증 3건 수정: `_fetch_current_price()` 정리, round2 없을 때 경고 처리
- 설계 문서: `docs/09_round34/`

### ✅ Phase 1.2 — intraday_discovery round 5~8 (완료)
- `--round 5~8` 추가: 오후장 발굴/재발굴 사이클 분리
- round6 로그 기록 시 `session="afternoon"` 저장
- round8은 round6 상위 5개 종목 현재가 추적 + `⭐재확인` 표시
- launchd plist 추가: `com.aigeenya.stockreport.discovery5.plist` ~ `discovery8.plist`
- 설계 문서: `docs/10_round5678/`

### ✅ 핫픽스 — intraday_report.py 갭 방향 버그 수정
- **버그:** `prev_close = cur_price` (09:10 현재가를 전일종가로 착각 → 갭 방향 오계산)
- **수정:** `get_daily_chart()`로 실제 전일 종가(`stck_clpr`) 조회, fallback은 분봉 첫 시가
- **영향:** GS건설 등 상승출발 종목이 "하락출발"로 잘못 표시되던 문제 해결

---

## 8-2. v2.7.2 — round 5~8 plist 원복 (2026-04-21)

### ✅ 결정: 15:03 임시변경 테스트 취소, 14:03 원계획 유지

**경위:**
- v2.7.1에서 round 5~8 (14:03~14:33) plist 4개를 15:03~15:33으로 임시 변경 도중 세션 종료
- 재개 시 확인 결과: discovery5/6은 15:03/15:05로 변경된 상태, discovery7/8은 14:30/14:33 그대로
- 형진님 결정: 시간이 지나서 테스트 의미 없음 → 전부 14시대로 원복

**원복 완료 (PlistBuddy `:StartCalendarInterval:0:Hour` 사용):**
- discovery5 → 14:03 ✅
- discovery6 → 14:05 ✅
- discovery7 → 14:30 ✅ (변경 없음)
- discovery8 → 14:33 ✅ (변경 없음)
- launchctl unload/load 재등록 완료

**잔존 이슈 (낮은 우선순위):**
- `launchctl list | grep discovery` 결과에 번호 없는 `com.aigeenya.stockreport.discovery` 항목이 하나 떠 있음
- **→ 2026-04-22 재판정:** 오판이었음. `com.aigeenya.stockreport.discovery` 는 23:30 `stock_discovery.py` 의 정당한 plist.
  네이밍이 `discovery5~8`(intraday_discovery) 과 비슷해 혼동 발생. 삭제하지 않음. 네이밍 리네이밍은 백로그 (우선순위 낮음).

---

## 8-3. v2.7.3 — 핫픽스 3종 + Stage 12 QA (2026-04-22)

### ✅ 핫픽스 #1 — HTS capture-uplmt 404 비활성화

- **증상:** `intraday_discovery round 2/4/6/8` 실행 시 `[경고] API 호출 실패 (404): /uapi/domestic-stock/v1/quotations/capture-uplmt` 반복 출력
- **원인:** `_HTS_PATH = "/uapi/domestic-stock/v1/quotations/capture-uplmt"` (TR: `FHPST01830000`) 이 KIS API 문서에 **존재하지 않는 엔드포인트**
- **검증:** `docs/api/한국투자증권_오픈API_전체문서_20260417_030007.xlsx` 전수 조회 → 매칭 0건
- **조치:** `_fetch_hts_rank()` 함수 본문을 `return []` 로 비활성화, 시그니처/호출부는 보존 (향후 복구 대비)
- **복구 후보 API:**
  - 후보 1 (의미 정합): `/uapi/domestic-stock/v1/ranking/top-interest-stock` (TR: `FHPST01800000`) — 관심종목등록상위
  - 후보 2 (단순): `/uapi/domestic-stock/v1/ranking/hts-top-view` (TR: `HHMCM000100C0`) — HTS 조회상위
- **영향:** 온라인관심 가산점(`hts_rank`) 기능이 비활성화됨. 이미 5개 지표(거래량/체결강도/등락률/이격도/교집합) 로도 점수 산정 충분하므로 발굴 품질 저하 없음
- **운영 검증:** 04-22 round 3/4 실행 시 404 경고 **사라짐 확인 ✅**

### ✅ 핫픽스 #2 — stock_discovery "0원" 표시 버그

- **증상:** 23:30 stock_discovery 텔레그램 메시지에 `📗 삼성E&A(028050) 0원 BUY (67%)` 형태로 현재가가 "0원" 표시
- **원인:** `.skills/stock-analysis/scripts/analyze_swing.py` 의 반환 dict 에 `current_price` 키가 누락 → `stock_discovery.py` 261행 `analysis.get("current_price", 0)` 가 기본값 0 반환
- **조치:** `analyze_swing.py` `analyze()` 함수의 반환 dict 에 `"current_price": c` 추가 (c = 일봉 마지막 종가, 정규장 기준)
- **NXT 야간 종가 병표기 논의:** 형진님 선택 = 옵션 3 (정규장 + NXT 병표기). 현재는 정규장 종가만 표시 (핫픽스 #2로 확보), NXT 종가 병표기는 별도 기능으로 백로그 처리 (Task #11)
- **운영 검증:** 오늘 밤(04-22) 23:30 stock_discovery 실행에서 확인 예정

### ✅ 핫픽스 #3 — dry-run 데이터 오염 방지

- **증상:** 04-21 `discovery_log.json` 에 `disc_time: 10:13` (정식 스케줄 09:05 아님) 오염 데이터 1건. 04-22 QA 중에도 `--round 2 --dry-run` 테스트 실행 시 운영 state 및 discovery_log 변경됨
- **원인:** `intraday_discovery.py` 의 dry-run 분기가 **텔레그램 전송만 스킵**, `state.update()` / `_save_discovery_log()` 는 그대로 실행됨
- **조치:** 8개 round 전체에 dry-run 가드 적용
  - 홀수 round (1,3,5,7): 함수 시그니처에 `dry_run: bool = False` 추가 + `state.update()` 가드
  - 짝수 round 2,6: `state.update()` + `_save_discovery_log()` 둘 다 가드
  - 짝수 round 4,8: `state.update()` 가드 (discovery_log 저장 없음)
  - `run()` dispatcher 에서 모든 round 에 `dry_run` 전파
- **로그 메시지:** dry-run 실행 시 stderr 에 `[dry-run] roundN state 저장 스킵 (N종목)` 출력
- **검증 결과 (04-22):**
  - `BEFORE: 09:03` → 10:02 `--round 1 --dry-run` → `AFTER: 09:03` 완전 동일 ✅
  - round 2 dry-run 실행 후 discovery_log 건수 변화 없음 ✅
- **오염 데이터 청소:** 04-22 09:28 테스트로 추가된 1건은 로컬에서 제거 완료 (20:30 closing_report 통계 오염 방지)

### 🔴 Stage 12 QA 진행 상황

| 검증 항목 | 상태 |
|----------|------|
| 09:03~09:05 round 1~2 자동 실행 + discovery_log 생성 | ✅ 운영 확인 |
| 09:30~09:33 round 3~4 자동 실행 + ⭐재확인 표시 | ✅ 운영 확인 |
| 14:03~14:33 round 5~8 자동 실행 + 오후 추적 | 🔜 14:03 대기 (04-22 예정) |
| 20:30 closing_report 실행 + close_price/return_pct 업데이트 | 🔜 20:30 대기 |
| 23:30 stock_discovery 실행 + 핫픽스 #2 검증 (0원 → 실제 종가) | 🔜 오늘 밤 |

---

## 8-4. v2.7.4 — closing_report change_pct 핫픽스 + Phase 2 Stage 4 완료 (2026-04-22)

### ✅ 핫픽스 — closing_report.py 0.00% 버그

- **증상:** `closing_report.py` 실행 시 holdings_signals의 일부 종목 `change_pct`가 `0.00%`로 표시되는 버그
- **원인:** `change_pct`가 KIS API 응답의 `prdy_ctrt` 필드(어제 종가 대비 오늘 종가 등락률)에 의존했으나, 특정 시점 응답에서 해당 필드가 0.00으로 내려오는 케이스 존재
- **조치:** `change_pct`를 `today_close vs prev_close` 기반 **수동 계산**으로 전환
  - `change_pct = (today_close - prev_close) / prev_close × 100`
  - 일봉 차트에서 직접 당일 종가 · 전일 종가를 가져와 계산
- **부작용 복구 — 캔들 분석:** 수동 계산 과정에서 캔들 판정 로직에 side-effect 발생 → 도지(doji) 오탐 이슈. 정확한 캔들 판정 로직으로 복구.
- **운영 검증 (04-22 journal_20260422.md):**
  - GS건설: **-3.25%** ✅ (이전엔 0.00%)
  - LS ELECTRIC: **+5.14%** ✅
  - 삼성E&A: **-2.13%** ✅
  - 캔들 판정도 정상 (도지 오탐 사라짐)

### ✅ Phase 2 — 텔레그램 승인형 매수/자동 매도 계획 수립

- **Stage 1 브레인스토밍** 완료 (`docs/11_phase2_trading/01_brainstorm.md`)
  - Approval Workflow 전환: 봇 제안 → `/매수함` · `/매수안함` · `/종목변경` 3종 명령
  - 매매 계좌 분리: Keychain `KIS_TRADING_ACCOUNT_NO` 신규
  - 매도 자동 실행 (하드스탑 -3% / 트레일링 / 목표 +5% / 장마감)
  - MAX_DAILY_LOSS 위반 시 `sys.exit` 폐기 → 주문 차단 플래그 + 자정 자동 해제
- **Stage 2 계획 초안** 완료 (`docs/11_phase2_trading/02_plan_draft.md`)
- **Stage 3 계획 검토** 완료 (`docs/11_phase2_trading/03_plan_review.md`, 수정 제안 16건)
- **Stage 4 계획 통합 (plan_final)** 완료 (`docs/11_phase2_trading/04_plan_final.md`)
  - 주요 통합 결과:
    - MAX_DAILY_LOSS = 절대금액(원) + 실현손익만
    - 장마감 청산 = 15:15 시장가 → 15:25 동시호가 재시도 2단
    - 파일 I/O = **단일 쓰기 프로세스 원칙** (position_monitor 단독)
    - 테스트 전략 = `trading --dry-run` 모드 P0 추가
    - 로그 = `logs/trading.log` JSON + 계좌번호 마스킹 `******1234`
    - 텔레그램 throttle = 초당 1건 큐
    - 재시작 직후 "놓친 손절" 복구 스캔 P0 추가
    - Phase 2 범위 = KRX 정규장 09:00~15:30만, NXT 제외
    - 정량 성공 기준 7개
  - 신규 파일 계획: `position_monitor.py`, `validator.py`, `position_state.json`, `trading_state.json`, `pending_proposals.json`, `logs/trading.log`, position_monitor plist
- **✅ Stage 5 기술 설계 완료** (`docs/11_phase2_trading/10_codex_brief_D.md`, 1644줄)
  - 스키마 확장: Proposal (+qty_ref/top5/kind), TradingState (+liquidation_query_sent_at)
  - 신규 파일: `request_queue.py`, `proposal_notifier.py`, `tests/test_request_pipeline.py`
  - 수정: `telegram_sender.py`(throttle), `orchestrator.py`(5개 명령), `position_monitor.py`(4개 tick), `intraday_discovery.py`(enqueue)
  - **🔴 다음: 형진님 Brief D 검토 후 Codex 위임**

---

## 9. Phase별 로드맵

| Phase | 내용 | 상태 |
|-------|------|------|
| **Phase 1** | intraday_discovery 고도화 | ✅ 완료 |
| **Phase 1.1** | intraday_discovery round 3/4 | ✅ 완료 |
| **Phase 1.2** | intraday_discovery round 5~8 | ✅ 완료 |
| **Phase 1.5** | 모닝 리포트에 전날 발굴 성과 요약 추가 | 🔜 데이터 쌓인 후 |
| **Phase 2** | 텔레그램 승인형 매수 + 자동 매도 (별도 KIS 키 그룹) | 🟡 Stage 5 설계 + Brief A v2 완료 · 형진님 KIS 매매 전용 앱 등록 + Brief A 검토 대기 |
| **Phase 3** | 보유 포지션 평단 관리 자동화 | 🔜 Phase 2 후 |
| **Phase 4** | 웹 UI (전략 설정 화면) | 🔜 마지막 |

---

## 10. 다음 세션에서 할 작업

### 🔴 Stage 12 QA — Phase 1 실제 운영 검증
- [ ] 내일 장 시작(09:03~09:05) round1 → round2 실행 후 `data/discovery_log.json` 생성 확인
- [ ] 09:30~09:33 round3 → round4 실행 후 오전 추적 섹션/`⭐재확인` 표시 확인
- [ ] 14:03~14:33 round5 → round8 실행 후 오후 추적 섹션/`⭐재확인` 표시 확인
- [ ] 20:30 closing_report 실행 후 `close_price`, `return_pct` 업데이트 확인
- [ ] 텔레그램 메시지에 "추가 관심 후보" 섹션 정상 표시 확인

### 🟡 Phase 2 — Brief D Stage 5 완료, Codex 위임 준비 중
- [x] Stage 1~4 완료 (brainstorm → plan_final)
- [x] Stage 5 Phase 2 전체 기술 설계 (`05_technical_design.md`, 799줄)
- [x] Brief A v2 작성 (`06_codex_brief_A.md` — 인프라 3건 + KIS 키 그룹 분리)
- [x] Brief B 작성 (`07_codex_brief_B.md`)
- [x] Brief C 작성 (`08_codex_brief_C.md` — position_monitor 골격)
- [x] Brief D Stage 4 계획 (`09_brief_d_plan.md` — 형진님 승인)
- [x] Brief D Stage 5 기술 설계 (`10_codex_brief_D.md`, 1644줄)
  - 스키마 확장: Proposal (+qty_ref/top5/kind), TradingState (+liquidation_query_sent_at)
  - 신규: `request_queue.py`, `proposal_notifier.py`, `tests/test_request_pipeline.py`
  - 수정: `telegram_sender.py`(throttle큐), `orchestrator.py`(5개명령), `position_monitor.py`(4tick), `intraday_discovery.py`(enqueue)
- [ ] 🔴 **형진님 수동 작업**: KIS 개발자센터에서 매매 전용 앱 신규 등록 + 소액계좌 연결
  - APP_KEY / APP_SECRET 발급 (보관만, 등록은 Brief A Task 1 완료 후)
- [ ] 🔴 **Brief A Task 1 완료 후**: `venv/bin/python3 morning_report/keychain_manager.py --reset-trading`
  - 3종 일괄 입력(KIS_TRADING_APP_KEY/SECRET/ACCOUNT_NO) + 잔고조회 연결 테스트
- [ ] Stage 8 Codex 위임 — Brief A → B → C → D 순차
- [ ] Stage 9 Opus 코드 리뷰 (Brief 단위)
- [ ] Stage 10 Codex 수정 반영
- [ ] Stage 11 최종 검증 + Stage 12 QA

---

## 11. 주요 명령어 모음

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 1 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 3 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 4 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 5 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 6 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 7 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 8 --dry-run
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

## 12. 전체 작업 히스토리 (누적)

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
18. **v2.2 전략 확정 + 분할매매 설계** (2026-04-20)
19. **v2.3 텔레그램 명령 개선 + 타점 코멘트** (2026-04-21)
20. **v2.4~v2.7 Phase 1.1/1.2 + 핫픽스** (2026-04-21)
21. **v2.7.1 세션 중단 — plist 15:03 변경 테스트 미완료** (2026-04-21)
22. **v2.7.2 round 5~8 plist 14:03 원복 완료** (2026-04-21)
23. **v2.7.3 핫픽스 3종 + Stage 12 QA 진입** (2026-04-22)
24. **v2.7.4 closing_report change_pct 수동 계산 전환 + Phase 2 Stage 2~4 완료** (2026-04-22)
25. **v2.7.5 Phase 2 Stage 5 기술 설계 완료 + Codex Brief A v2 작성** (2026-04-23)
26. **v2.7.6 Brief D Stage 5 기술 설계 완료** (2026-04-23)
    - 10_codex_brief_D.md (1644줄) — 텔레그램 명령 + 주문 요청 파이프라인
    - 신규 파일: request_queue.py, proposal_notifier.py, tests/test_request_pipeline.py (13건)
    - 스키마 확장: Proposal (+qty_ref/top5/kind), TradingState (+liquidation_query_sent_at)
    - position_monitor 4개 tick: ingest/notify/process/notify_loss_limit
    - 05_technical_design.md (13섹션) — 형진님 승인 결정 4건 반영:
      · max_daily_loss = 소액계좌 당일 시작 주문가능금액 자동 (자정 스냅샷)
      · max_trades_per_day = 매수 기준 10건 (매도 한도 없음)
      · 시범 운영 = `/시범시작 [N]` / `/시범종료` 텔레그램 명령어 (자정 자동 해제)
      · **KIS 키 그룹 전체 분리** (APP_KEY/SECRET/ACCOUNT_NO 3종) + `KISClient(mode="trading")` 파라미터
    - 06_codex_brief_A.md v2 — 인프라 3건 구현 브리프:
      · Task 1: keychain_manager.py `_TRADING_ITEMS` 3종 + `--reset-trading` CLI
      · Task 2: kis_client.py `mode` 파라미터 + 토큰 캐시 분리 + DRY_RUN + `place_order` 가드
      · Task 3: strategy_config.json `trading` 섹션

---

*자동 생성 | stockpilot v2.7.5 — AI 주식 자동화 시스템*

---

## 📋 다음 세션 시작 프롬프트

> 아래 내용을 복사해서 새 대화창에 붙여넣으면 바로 이어서 작업 가능합니다.
> 마지막 갱신: 2026-04-23 (v2.7.6)

```
stockpilot 프로젝트 이어서 진행해줘.
CLAUDE.md → HANDOFF.md → WORKFLOW.md 순서로 읽고,
docs/11_phase2_trading/ 아래 01~10 문서도 확인해줘.
경로: /Users/geenya/projects/AI_Projects/stockpilot/

현재 상태 요약 (v2.7.6 · 2026-04-23):
- Phase 2 Brief D Stage 5 기술 설계 완료 (10_codex_brief_D.md, 1644줄)
- Brief A~C + D Stage5까지 설계 완료 → 구현 순서: A → B → C → D
- Brief D 핵심 설계:
  · Proposal 스키마 확장: qty_ref, top5, kind 필드 추가 (기존 테스트 자동 호환)
  · TradingState 스키마 확장: liquidation_query_sent_at 추가 (강제청산 질의 중복 방지)
  · 신규: request_queue.py (JSONL IPC), proposal_notifier.py (카드 포맷터)
  · telegram_sender.py: enqueue_text() + throttle worker (초당 1건)
  · orchestrator.py: /매수함 /매수안함 /종목변경 /청산함 /청산안함 5개 명령 추가
  · position_monitor.py: 4개 tick 추가 (ingest/notify/process/notify_loss_limit)
  · intraday_discovery.py: round 2/4/6/8 종료 시 discovery_result.jsonl enqueue
  · 통합 테스트: tests/test_request_pipeline.py 13건

다음 할 작업:
1. 🔴 형진님 수동 작업:
   · KIS 개발자센터(apiportal.koreainvestment.com) 로그인
   · 매매 전용 앱 신규 등록 (예: stockpilot-trading)
   · 해당 앱에 실전 소액계좌 연결
   · APP_KEY / APP_SECRET 안전 보관 (등록은 Brief A Task 1 구현 완료 후)
2. Codex에 Brief A 위임 (06_codex_brief_A.md v2):
   · Task 1: keychain_manager.py — _TRADING_ITEMS 3종 + --reset-trading CLI
   · Task 2: kis_client.py — mode 파라미터 + 토큰 캐시 분리 + DRY_RUN 분기
   · Task 3: strategy_config.json — trading 섹션 신설
3. Brief A 구현 완료 후:
   · 형진님: `venv/bin/python3 morning_report/keychain_manager.py --reset-trading` 실행
   · Claude: Opus Stage 9 코드 리뷰
4. Brief A 통과 → Brief B → Brief C → Brief D 순차

Brief 전체 구성 (Stage 8):
- Brief A (인프라): keychain + kis_client + strategy_config
- Brief B (상태·검증): position_state/trading_state/pending_proposals/validator
- Brief C (monitor 코어): position_monitor 골격 + 복구 + 자정리셋
- Brief D (입출력): request_queue + throttle + orchestrator + monitor 4tick ← 설계 완료
- Brief E (마감·배포): closing_report 섹션 + launchd plist
- Brief F (테스트): dry-run 통합 시나리오 5종

백로그 (우선순위 낮음):
- NXT 야간 종가 병표기
- launchctl 네이밍 리네이밍
- HTS 온라인관심 가산점 복구

참고 사항:
- 구현(Stage 8, 10)은 Codex 위임, Claude는 설계·검증만
- 수정 후 venv/bin/python3 -m py_compile 문법 검사
- 터미널 블록 맨 위 cd /Users/geenya/projects/AI_Projects/stockpilot 포함

어디서부터 시작할까?
```

# Codex 인계 백로그 — stockpilot

> 작성: 2026-05-07 (Claude 인계 → Codex 진행)
> 단일 정보원: 본 문서. HANDOFF.md는 운영 이력 / 본 문서는 진행 작업 목록.
> 형진님 승인이 필요한 항목은 🔴 표시. Codex는 승인 받기 전 Stage 5 이상 진입 금지.

---

## P0 — 즉시 진행 가능 (형진님 결정 후)

### 1. NXT 옵션 B 통합 (WORKFLOW Stage 4~13)
**상태:** Stage 1~3 완료. Stage 4 진입 대기.

**선행 결정 5건 (🔴 형진님):**
1. 옵션 2 (N+X 듀얼 호출) 채택 여부 — Claude 권고 ✅
2. `morning_report.py` X 모드 적용 여부 — 권고 ✗ 보류 (R5)
3. `balance_diff` 별도 모듈 분리 — 권고 ✅ (R7)
4. v2.8.4 안내문 제거 시점 — 권고: Task E 검증 후 (R10)
5. 검증용 NXT 거래 1건 의도 실행 (5/8 금 또는 5/9 토 NXT 매매)

**관련 문서:**
- `docs/14_nxt_integration/01_brainstorm.md` (Stage 1)
- `docs/14_nxt_integration/02_plan_draft.md` (Stage 2 — Task A~E 분해, 5h 추정)
- `docs/14_nxt_integration/03_plan_review.md` (Stage 3 — R1~R10 보완점)

**Codex 진행 순서:**
1. Stage 4 plan_final 작성 (형진님 결정 반영) → `docs/14_nxt_integration/04_plan_final.md`
2. Stage 5 technical_design 작성 → `docs/14_nxt_integration/05_technical_design.md`
3. Codex Brief 작성 → `docs/14_nxt_integration/06_codex_brief.md`
4. 구현 (Stage 8): Task A~E 순차
5. Claude 코드 리뷰 (Stage 9)
6. Stage 10 수정 → Stage 11 검증 → Stage 12 QA → Stage 13 배포

**핵심 코드 위치:**
- `.skills/kis-api/scripts/kis_client.py:288` `def get_balance()` (시그니처 확장)
- `morning_report/closing_report.py:565` v2.8.4 안내문 제거 대상

---

### 2. Phase 2 — 텔레그램 승인형 매수 + 자동 매도
**상태:** Stage 1~5 + Brief A~D 설계 완료. KIS 매매 전용 앱 등록 대기.

**🔴 형진님 수동 작업:**
- KIS 개발자센터 (apiportal.koreainvestment.com) 매매 전용 앱 등록
- 실전 소액계좌 연결
- APP_KEY / APP_SECRET 발급 (Brief A Task 1 완료 후 Keychain 등록)
- 등록 후: `venv/bin/python3 morning_report/keychain_manager.py --reset-trading`

**Codex 진행 순서 (KIS 등록 완료 후):**
1. Brief A: `docs/11_phase2_trading/06_codex_brief_A.md` (인프라)
   - keychain_manager `_TRADING_ITEMS` 3종 + `--reset-trading`
   - kis_client `mode` 파라미터 + 토큰 캐시 분리 + DRY_RUN
   - strategy_config trading 섹션 (이미 v2.8.x에 추가됨)
2. Brief B: `docs/11_phase2_trading/07_codex_brief_B.md` (상태/검증)
3. Brief C: `docs/11_phase2_trading/08_codex_brief_C.md` (position_monitor 코어)
4. Brief D: `docs/11_phase2_trading/10_codex_brief_D.md` (1644줄, 입출력 파이프라인)
5. Brief E: 마감/배포 — 별도 작성 필요 (closing_report 통합 + launchd plist)
6. Brief F: 통합 테스트 — `tests/` 안에 시나리오 5종 추가

**선행 조건:** Brief A 완료 + Trade-Small 검증 통과 → Pattern Integration Phase A 착수 가능.

---

### 3. Pattern Integration — 5종 매매법 + 외부 레포 차용
**상태:** Stage 1~5 Phase A 완료. 구현 대기.

**선행 조건:** Phase 2 Brief A~F 구현 완료 + Trade-Small 검증 통과.

**Codex 진행 순서:**
- Brief A-1 (지표/캔들) → A-2 (라인/패턴 골격) → A-3 (라이프사이클/리스크/KIS 점검)
- 관련 문서: `docs/12_pattern_integration/05_technical_design_A.md`

---

## P1 — 5/7 운영 결과 검증 후 진행

### 4. discovery6 round6 state 누락 미스터리
**증상:** 5/6 운영 후 state에 round [9, 10, 11, 12, 13, 14] 누락 (실행됐지만 state 미저장).

**가설 3건 (HANDOFF v2.8.9 기록):**
1. 동시 _save race condition (file lock 없음)
2. 다른 프로세스(orchestrator/telegram_bot)가 `state["intraday_discovery"]`를 통째로 덮어씀
3. `_load`의 `_deep_merge` 또는 `_EMPTY_STATE` 초기화가 round 키 누락

**Codex 진행:**
1. 5/7 운영 결과 확인 — 재현 여부
2. 재현 시 `state_manager.py`에 `fcntl.flock()` 추가 또는 atomic write 패턴
3. 단위 테스트 작성 (동시 update 시뮬레이션)

**관련 코드:**
- `morning_report/state_manager.py:76` `def update()` (shallow merge)
- `morning_report/state_manager.py:138` `def _save()` (file lock 없음)

---

### 5. v2.8.3 발굴 메시지 12:05/13:05 분리 누락 미스터리
**증상:** 5/6 12:05/13:05 메시지가 옛 형식 ("후보 N → 상위 3종목"), 15:05만 새 형식 ("신규 X + 재등장 Y").

**현재 코드는 정상 작동 확인 (시뮬레이션 통과). 5/7 운영 결과로 재현 여부 확인.**

**Codex 진행:**
- 5/7 12:05/13:05 메시지 확인
- 재현 시 launchd 환경 격리 점검 (cwd, PYTHONPATH 등)

---

### 6. 14:05 plist 핫픽스 효과 검증
**v2.8.6에서 discovery5/6 plist 화~금 시각 14:03/14:05로 정상화.**

**Codex 진행:**
- 5/7 14:05 발굴 텔레그램 도착 확인
- 14:33 round 8 정상 + state에 round 6 보존 확인

---

## P2 — 향후 (우선순위 낮음)

### 7. NXT 야간 종가 병표기 (closing_report)
**HANDOFF v2.7.3 백로그.**
- 정규장 + NXT 종가 동시 표시 (옵션 3 — 시간대 분기)
- NXT 옵션 B 완료 후 Phase 2 단계로 검토

### 8. launchctl 네이밍 리네이밍
**HANDOFF v2.7.2 백로그.**
- `com.aigeenya.stockreport.discovery` (23:30 stock_discovery, 단일) 와 `discovery1~26` (intraday_discovery) 혼동 가능
- 비파괴 작업: `discovery` → `discovery_nightly` 또는 `stock_discovery_night`

### 9. HTS 온라인관심 가산점 복구
**HANDOFF v2.7.3 핫픽스 #1 — `_fetch_hts_rank` 비활성화 상태.**
- 후보 1: `/uapi/domestic-stock/v1/ranking/top-interest-stock` (FHPST01800000)
- 후보 2: `/uapi/domestic-stock/v1/ranking/hts-top-view` (HHMCM000100C0)
- 발굴 점수에 가산점 1~2 추가

### 10. C2 통계 대시보드 (closing_report)
**HANDOFF 백로그.**
- pattern_lifecycle 데이터 1주 누적 후 진행
- 발굴→매수→매도 전체 라이프사이클 통계 섹션

### 11. risk_analysis 활성화
**HANDOFF 백로그.**
- portfolio_history 1주 누적 후 `strategy_config.risk_analysis.enabled=true`
- 현재 비활성. closing_report에 VaR/CVaR/MDD 섹션 추가

### 12. scenario-run-log skill 실제 파일 작성
**jOneFlow 프로젝트 영역. 별도 세션 권장.**

---

## 운영 안정성 모니터링 항목

### 매 평일 자동 검증 (Codex가 주기 점검)
- 08:30 모닝: B1 어제 발굴 성과 + B2 KOSPI 시장 레짐 표시 확인
- 09:05~15:05 발굴 13회: 한국어 시간 헤더 + 신규/재등장 분리 + 12시 점심 표시 + 15% 자동 제외
- 14:05 발굴 도착 (v2.8.6 핫픽스 효과)
- 20:30 클로징: NXT 안내문 표시 (v2.8.4 → 옵션 B 완료 시 제거)
- 20:35 pattern_lifecycle: `logs/pattern_lifecycle.log` 정상

### 매 휴일 검증 (5/9 토 / 5/10 일 / 5/25 부처님 대체 등)
- 모든 자동 텔레그램 발송 미실행 (v2.8.7 휴장 가드 효과)
- launchd 자체는 실행됐지만 코드에서 즉시 종료 (stderr 안내문 출력)

---

## Claude → Codex 인계 메모

- **commit/push 컨벤션**: heredoc 메시지 + `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` (or Codex 자체)
- **WORKFLOW 룰**: Stage 4 형진님 승인 없이 Stage 5 진입 금지
- **보안**: API 키/토큰/계좌번호 평문 노출 금지. Keychain 경유만
- **운영 데이터**: `data/discovery_log.json`, `data/watchlist.json`, `data/pending_proposals.json`, `data/portfolio_history.json`, `data/position_state.json`, `data/trading_state.json` 모두 `.gitignore` 처리됨
- **테스트**: `venv/bin/python3 -m pytest tests/ -v` 전체 108개 PASS 기준선
- **의존성**: `requirements.txt` 갱신 (holidays, openpyxl 포함)

**다음 인계 시 본 문서 + HANDOFF.md 같이 읽기.**

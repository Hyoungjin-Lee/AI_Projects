# stockpilot — Claude 운영 지침

> 이 파일은 Claude가 새 세션을 시작할 때 가장 먼저 읽는 핵심 지침이다.
> **읽기 순서: CLAUDE.md → HANDOFF.md → WORKFLOW.md → 관련 docs/**
> 현재 상태 및 다음 작업은 `HANDOFF.md` 참고.

---

## 1. 프로젝트 한 줄 요약

KIS Open API 기반 주식 자동화 시스템. 평일 자동 브리핑 + 텔레그램 양방향 명령 지원.

- **Python 환경:** `venv/bin/python3` (Python 3.14)
- **프로젝트 경로:** `/Users/geenya/projects/AI_Projects/stockpilot`
- **메인 스크립트:** `morning_report/` 폴더

---

## 2. 워크플로우 역할 규칙 (WORKFLOW.md 요약)

```
✅ 새 세션 시작 시 반드시 WORKFLOW.md 확인
✅ 기능 개발(새 기능·리팩토링)은 WORKFLOW.md Stage 1~13 준수
✅ Claude 역할: 기획(Stage 1~4) + 설계(Stage 5~7) + 검증(Stage 9, 11) + QA(Stage 12)
❌ Claude는 구현(Stage 8, 10) 직접 금지 → 반드시 Codex에 위임
```

작업 전 판단 기준:
- **핫픽스·수치조정·설정변경** → 직접 수정 가능 (실행 모드)
- **새 기능·로직 추가·리팩토링** → WORKFLOW.md Stage 1~7 문서 작성 후 Codex 위임

### 🔴 필수 협업 체크포인트 (혼자 진행 절대 금지)

| 단계 | 규칙 |
|------|------|
| Stage 1 브레인스토밍 | 형진님과 대화하며 방향 잡기 — Claude 혼자 작성 금지 |
| Stage 4 계획 통합 완료 후 | **형진님 승인 필수** → 승인 없이 Stage 5 진입 금지 |
| Stage 5 기술 설계 | Stage 4 승인 확인 후에만 작성 |

---

## 3. 절대 규칙 (보안)

```
❌ API키·계좌번호·토큰을 코드/로그에 평문 노출 금지
❌ KIS_ALLOW_LIVE_ORDER=1 없으면 실주문 절대 불가
✅ 모든 스크립트는 inject_to_env()로 Keychain에서 인증정보 로드
✅ 변경 전 반드시 --dry-run으로 먼저 확인
✅ 파일 생성·수정 후 python3 -m py_compile 로 문법 검사
```

### Keychain 인증정보 로드 패턴
```python
from keychain_manager import inject_to_env
inject_to_env()   # 반드시 첫 줄에 호출
```

---

## 4. 스크립트 실행

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트 (전송 없이)
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 1 --dry-run
venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run

# Keychain 상태 확인 / 재설정
venv/bin/python3 morning_report/keychain_manager.py
venv/bin/python3 morning_report/keychain_manager.py --reset

# 전체 launchd 등록 상태 확인
launchctl list | grep aigeenya

# 로그 확인
tail -50 logs/intraday_discovery.log
tail -50 logs/stockbot_error.log

# GitHub 안전 업로드
aigit_upload
```

---

## 5. 핵심 파일

| 파일 | 역할 |
|------|------|
| `morning_report/keychain_manager.py` | Keychain 관리, `inject_to_env()` 제공 |
| `morning_report/telegram_bot.py` | 텔레그램 봇 데몬 (부팅 시 자동 시작) |
| `morning_report/orchestrator.py` | 텔레그램 명령 라우팅 |
| `morning_report/state_manager.py` | 에이전트 간 공유 상태 |
| `morning_report/intraday_discovery.py` | 장초기 실시간 종목 발굴 |
| `.skills/kis-api/scripts/kis_client.py` | KIS API 클라이언트 |
| `data/watchlist.json` | 관심종목 목록 |
| `data/daily_state.json` | 에이전트 간 공유 상태 (런타임) |

---

## 6. 자동 실행 스케줄 (launchd, 평일)

| 시각 | 스크립트 |
|------|----------|
| 08:20 | `watchlist_sync.py` |
| 08:30 | `morning_report.py` |
| 09:03 | `intraday_discovery.py --round 1` |
| 09:05 | `intraday_discovery.py --round 2` |
| 09:10 | `intraday_report.py` |
| 20:30 | `closing_report.py` |
| 23:30 | `stock_discovery.py` (월~토) |
| 상시  | `telegram_bot.py` (봇 데몬) |

---

## 7. 스킬 참조

상세 작업은 해당 SKILL.md를 먼저 읽고 진행한다.

| 작업 | 참조 |
|------|------|
| KIS API 데이터 조회 | `.skills/kis-api/SKILL.md` |
| 기술적 분석 | `.skills/stock-analysis/SKILL.md` |
| 리포트/매매일지 | `.skills/trading-report/SKILL.md` |

---

## 8. 코드 검증 가이드

- 문법 검사: `venv/bin/python3 -m py_compile morning_report/<파일>.py`
- 복잡한 로직 변경 시: Opus 서브에이전트(high effort)로 검증
- KIS API 궁금한 점: `docs/api/` 폴더의 xlsx 파일 참고

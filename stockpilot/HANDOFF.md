# 🤝 AI 주식 매매 시스템 — Handoff 문서

> 최종 업데이트: 2026-04-19 (Stage 12~13 완료 — v1.0.0 배포 완료)
> 목적: 새 대화창에서 즉시 작업을 이어받을 수 있도록 현재 상태 전달

---

## 1. 프로젝트 개요

한국투자증권(KIS) Open API 기반 주식 자동화 시스템.
매일 평일 자동으로 **텔레그램**으로 브리핑 전송. (카카오톡 → 텔레그램 전환 완료)

- **프로젝트 경로:** `/Users/geenya/projects/AI_Projects/stockpilot`
- **Python 환경:** `venv/` (Python 3.14)
- **실행 방법:** `venv/bin/python3 morning_report/[스크립트].py`

---

## 2. 자동 실행 스케줄 (launchd, 평일 기준)

| 시각 | 스크립트 | 내용 |
|------|----------|------|
| 08:20 | `watchlist_sync.py` | KIS HTS 관심종목 → watchlist.json 동기화 |
| 08:30 | `morning_report.py` | 모닝 브리핑 텔레그램 전송 |
| 09:10 | `intraday_report.py` | 장초기 현황 텔레그램 전송 |
| 20:30 | `closing_report.py` | 장마감 결산 텔레그램 전송 |
| 23:30 | `stock_discovery.py` | 야간 종목 발굴 텔레그램 전송 (월~토) |

---

## 3. 핵심 파일 구조

```
stockpilot/
├── morning_report/
│   ├── morning_report.py       # 모닝 브리핑
│   ├── intraday_report.py      # 장초기 브리핑
│   ├── closing_report.py       # 장마감 결산 ← 오늘 대폭 개선
│   ├── stock_discovery.py      # 야간 종목 발굴
│   ├── watchlist_sync.py       # 관심종목 동기화
│   ├── telegram_sender.py      # 텔레그램 전송 모듈 (신규)
│   ├── setup_telegram.py       # 텔레그램 최초 설정 도우미 (신규)
│   ├── _kakao_sender.py        # 카카오톡 전송 모듈 (보관용)
│   ├── _setup_kakao.py         # 카카오 설정 (보관용)
│   ├── keychain_manager.py     # macOS Keychain 인증정보 관리
│   └── setup_scheduler.sh      # launchd 스케줄러 등록
├── .skills/
│   ├── kis-api/scripts/kis_client.py   # KIS API 클라이언트 ← 오늘 개선
│   ├── stock-analysis/                 # 기술적 분석 스킬
│   └── trading-report/                 # 보고서 생성 스킬
├── data/
│   ├── watchlist.json          # 관심종목 (LNG/건설 섹터)
│   └── cache/                  # 토큰 캐시
├── docs/
│   ├── api/                    # KIS 전체 API 문서 xlsx
│   └── manual/                 # 운영자/사용자 매뉴얼
├── reports/journal/            # 매매일지 자동 저장
├── logs/                       # 자동 실행 로그
└── .env                        # 환경변수 (민감정보는 Keychain)
```

---

## 4. 보안 구조 (Keychain 통합 완료)

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

## 5. 텔레그램 전환 현황 (2026-04-18 완료)

| Stage | 상태 | 산출물 |
|-------|------|--------|
| 1 브레인스토밍 | ✅ 완료 | `docs/01_brainstorm/brainstorm.md` |
| 2~4 기획 통합 | ✅ 완료 | `docs/02_planning/plan_final.md` |
| 5 기술 설계 | ✅ 완료 | `docs/03_design/technical_design.md` |
| 8 구현 (Codex) | ✅ 완료 | `morning_report/telegram_sender.py` |
| 9 코드 리뷰 | ✅ 완료 | `docs/04_implementation/code_review.md` |
| 10 수정 반영 | ✅ 완료 | `docs/04_implementation/revise_request.md` |
| 11 최종 검증 | ✅ 완료 | Opus XHigh — 배포 가능 판정 |

**텔레그램 봇:** `@geenya_stock_bot` (Stock Pilot)
**실제 전송 테스트:** ✅ 성공 확인 (2026-04-18 17:03)

---

## 6. 오늘(2026-04-18) 작업 히스토리

### 6-1. 텔레그램 봇 연동 완료
- BotFather에서 `@geenya_stock_bot` 생성
- `setup_telegram.py` 실행 → Keychain 저장 → 테스트 메시지 수신 확인
- 4개 보고서 스크립트 import 교체 완료 (`kakao_sender` → `telegram_sender`)

### 6-2. Stage 11 최종 검증 (Opus XHigh)
- 보안/기능/통합/에러처리/코드품질 전 항목 통과
- **판정: 즉시 배포 가능**

### 6-3. closing_report.py 결산 요약 섹션 대폭 개선
**변경 전:**
```
주식 평가액:  8,443,500원
예수금(현금): 4,751,541원
총자산:      13,195,041원  ← 잘못된 합산
```

**변경 후:**
```
💰 총자산
  총평가금액:   10,497,239원   ← API nass_amt 기준
  유가평가금액:  8,443,500원
  전일순자산:   10,623,671원
  🔴 자산증감:    -126,432원 (-1.19%)

📊 정산현황
  금일매수:      3,680,850원
  금일매도:      2,306,000원
  금일제비용:        5,382원
  🔴 평가손익합계: -250,350원 (-2.88%)

💵 예수금
  예수금(총):    4,751,541원
  D+1 정산:     3,433,971원
  D+2 정산:     2,053,739원
  주문가능:      2,008,118원   ← 앱과 정확히 일치
```

### 6-4. KIS API 필드 정확화 (엑셀 문서 기반)
- `TTTC8434R` output2 필드 전수 확인 → D+2 필드명 오류 수정 (`prvs_rcdl_excc_amt`)
- `TTTC0869R` (주식통합증거금현황) 추가 — `stck_itgr_cash100_ord_psbl_amt` 사용
- 주문가능: 현금 기준 보수적 표시 (미수/신용 미포함 정책 확정)
- 출금가능: KIS 공개 API 미제공 확인 → 항목 제외 결정

### 6-5. kis_client.py 개선
- `get_orderable_cash()` 메서드 추가 (TTTC0869R 호출)
- `stck_itgr_cash100_ord_psbl_amt` 우선, fallback `stck_cash_ord_psbl_amt`

---

## 7. 다음 세션에서 할 작업

> **현재 상태: v1.0.0 배포 완료 ✅ — 카카오→텔레그램 전환 프로젝트 전 스테이지 종료**

### 운영 모니터링 (다음 주)
- [ ] 월요일(2026-04-21) 장마감 후 `closing_report.py` 자동 실행 결과 확인
- [ ] `morning_report.py` dry-run 으로 리포트 품질 점검
- [ ] `stock_discovery.py` 텔레그램 전송 확인

### 다음 프로젝트 후보
- [ ] 텔레그램 양방향 명령 (`/잔고`, `/매수`, `/매도`) 구현
- [ ] stock_discovery 스크리닝 조건 고도화

---

## 8. 주요 명령어 모음

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트 (전송 없이)
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run
venv/bin/python3 morning_report/intraday_report.py --dry-run

# 텔레그램 직접 테스트
venv/bin/python3 morning_report/telegram_sender.py

# Keychain 확인
venv/bin/python3 morning_report/keychain_manager.py

# 로그 확인
tail -50 logs/closing_report.log
```

---

## 9. 전체 작업 히스토리 (누적)

1. 장마감 시간 변경: 16:00 → 20:30
2. watchlist 자동 동기화: KIS HTS 관심종목 API 연동
3. macOS Keychain 보안 통합 (KIS + 카카오 토큰)
4. 연결 테스트 흐름: 입력 → 잔고조회 → 관심종목조회 → 성공 시 저장
5. closing_report.py: OHLCV + 거래량 + 내일 전략 + 매매일지
6. 스케줄러 5개 launchd 등록 완료
7. 운영자/사용자 매뉴얼 작성
8. Opus 4.7 보안 검증 + P1~P5 전체 적용
9. CLAUDE.md 생성 — 핵심 지침 집약
10. morning_report/ 전 스크립트 py_compile 문법 검사 통과
11. **카카오톡 → 텔레그램 전환 완료** (Stage 1~11 전체)
12. **closing_report 결산 요약 섹션 개선** — 총자산/정산현황/예수금 분리
13. **KIS API 필드 정확화** — TTTC8434R + TTTC0869R 조합으로 주문가능 앱 일치
14. **morning_report / intraday_report 예수금 섹션 개선** — closing_report와 동일한 총자산/정산현황/예수금 분리 표시 통일
15. **Stage 12 QA & 릴리스** — 전 스크립트 문법검사 통과, 릴리스 노트 작성
16. **Stage 13 배포 & 아카이브** — v1.0.0 배포 완료, 산출물 아카이브

---

*자동 생성 | AI 주식 매매 시스템*

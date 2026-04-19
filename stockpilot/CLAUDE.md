# stockpilot — Claude 운영 지침

> 이 파일은 Claude가 새 세션을 시작할 때 가장 먼저 읽는 핵심 지침이다.
> 상세한 API/분석/리포트 작업 방법은 `.skills/*/SKILL.md` 를 참고한다.

---

## 1. 프로젝트 한 줄 요약

KIS Open API 기반 주식 자동화 시스템. 평일 4회 브리핑을 카카오톡으로 전송한다.

- **Python 환경:** `venv/bin/python3` (Python 3.14)
- **메인 스크립트:** `morning_report/` 폴더

---

## 2. 절대 규칙 (보안)

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

## 3. 스크립트 실행

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 테스트 (카카오 전송 없이)
venv/bin/python3 morning_report/morning_report.py --dry-run
venv/bin/python3 morning_report/closing_report.py --dry-run

# Keychain 상태 확인 / 재설정
venv/bin/python3 morning_report/keychain_manager.py
venv/bin/python3 morning_report/keychain_manager.py --reset

# 로그 확인
tail -50 logs/closing_report.log
```

---

## 4. 핵심 파일

| 파일 | 역할 |
|------|------|
| `morning_report/keychain_manager.py` | Keychain 관리, `inject_to_env()` 제공 |
| `morning_report/kakao_sender.py` | 카카오톡 전송 (Keychain 기반) |
| `.skills/kis-api/scripts/kis_client.py` | KIS API 클라이언트 |
| `data/watchlist.json` | 관심종목 목록 |
| `data/cache/` | KIS 토큰 캐시 |

---

## 5. 자동 실행 스케줄 (launchd, 평일)

| 시각 | 스크립트 |
|------|----------|
| 08:20 | `watchlist_sync.py` |
| 08:30 | `morning_report.py` |
| 09:10 | `intraday_report.py` |
| 20:30 | `closing_report.py` |
| 23:30 | `stock_discovery.py` (월~토) |

---

## 6. 스킬 참조

상세 작업은 해당 SKILL.md를 먼저 읽고 진행한다.

| 작업 | 참조 |
|------|------|
| KIS API 데이터 조회 | `.skills/kis-api/SKILL.md` |
| 기술적 분석 | `.skills/stock-analysis/SKILL.md` |
| 리포트/매매일지 | `.skills/trading-report/SKILL.md` |

---

## 7. 코드 검증 가이드

- 문법 검사: `venv/bin/python3 -m py_compile morning_report/<파일>.py`
- 복잡한 로직 변경 시: Opus 서브에이전트(high effort)로 검증
- KIS API 궁금한 점: `docs/api/` 폴더의 xlsx 파일 참고

---

*현재 상태 및 다음 작업은 `HANDOFF.md` 참고*

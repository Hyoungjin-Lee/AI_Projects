# Codex 구현 지시서 — intraday_discovery round 3/4

기술 설계 문서를 참고하여 아래 내용을 구현해주세요.

**설계 문서:** `docs/09_round34/technical_design.md`
**대상 파일:** `morning_report/intraday_discovery.py`
**신규 파일:** launchd plist 2개 (`~/Library/LaunchAgents/`)

구현 완료 후 반드시:
1. `venv/bin/python3 -m py_compile morning_report/intraday_discovery.py`
2. `venv/bin/python3 morning_report/intraday_discovery.py --round 3 --dry-run` (dry-run은 round 3에서 수집 후 종료)
3. `venv/bin/python3 morning_report/intraday_discovery.py --round 4 --dry-run`

문법 오류 없이 dry-run 정상 실행되면 완료입니다.

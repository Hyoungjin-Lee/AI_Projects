# Codex 구현 지시서 — intraday_discovery round 5~8 (오후장)

기술 설계 문서를 참고하여 아래 내용을 구현해주세요.

**설계 문서:** `docs/10_round5678/technical_design.md`
**대상 파일:** `morning_report/intraday_discovery.py`
**신규 파일:** launchd plist 4개 (`~/Library/LaunchAgents/`)

구현 완료 후 반드시:
1. `venv/bin/python3 -m py_compile morning_report/intraday_discovery.py`
2. `venv/bin/python3 morning_report/intraday_discovery.py --round 5 --dry-run`
3. `venv/bin/python3 morning_report/intraday_discovery.py --round 6 --dry-run`
4. `venv/bin/python3 morning_report/intraday_discovery.py --round 7 --dry-run`
5. `venv/bin/python3 morning_report/intraday_discovery.py --round 8 --dry-run`

문법 오류 없이 dry-run 정상 실행되면 완료입니다.

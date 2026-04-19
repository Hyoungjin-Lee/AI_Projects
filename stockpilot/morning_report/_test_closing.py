"""임시 테스트 스크립트 — 주말 체크 우회해서 closing_report 실행"""
import sys
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(_ROOT / ".skills" / "stock-analysis" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from keychain_manager import inject_to_env
inject_to_env()

# closing_report의 run() 함수에서 주말 체크만 제거하고 직접 호출
import closing_report as cr

# 주말 체크를 임시로 패치
import closing_report
_orig = closing_report.date

class _FakeDateModule:
    @staticmethod
    def today():
        class _FakeDate:
            @staticmethod
            def weekday():
                return 4  # 금요일로 속임
        return _FakeDate()

closing_report.date = _FakeDateModule

dry_run = "--dry-run" in sys.argv
cr.run(dry_run=dry_run)

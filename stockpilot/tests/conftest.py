"""pytest conftest: add project paths before any test module is imported."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

for _p in [
    str(_ROOT),
    str(_ROOT / "morning_report"),
    str(_ROOT / ".skills" / "kis-api" / "scripts"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

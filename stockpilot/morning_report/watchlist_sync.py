"""
watchlist_sync.py — KIS HTS 관심종목 → data/watchlist.json 자동 동기화

KIS HTS에서 설정한 관심종목 그룹을 API로 읽어와
data/watchlist.json을 자동으로 갱신합니다.

동작 방식:
  1. KIS API로 관심종목 그룹 목록 조회 (HHKB5023R)
  2. 각 그룹의 종목 목록 조회 (HHKB5024R)
  3. 현재 보유 종목도 자동 포함
  4. 중복 제거 후 watchlist.json 업데이트
  5. 섹터 정보는 기존 watchlist.json 값 유지 (신규 종목은 "기타"로 추가)

실행 방법:
  python3 watchlist_sync.py           # 동기화 실행
  python3 watchlist_sync.py --dry-run # 변경 내용만 출력 (파일 저장 안 함)
  python3 watchlist_sync.py --show    # 현재 watchlist.json 내용 출력

자동 실행:
  setup_scheduler.sh에 의해 매일 08:20 (모닝 브리핑 직전)에 실행됩니다.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from keychain_manager import inject_to_env
inject_to_env()

_WATCHLIST_FILE = _ROOT / "data" / "watchlist.json"

# 섹터 힌트 — 종목코드 기반 자동 매핑 (없으면 "기타")
# 필요에 따라 직접 추가하세요
_SECTOR_MAP: dict[str, str] = {
    "005930": "반도체",   "000660": "반도체",   "042700": "반도체",
    "035420": "인터넷",   "035720": "인터넷",   "259960": "인터넷",
    "006400": "2차전지",  "373220": "2차전지",  "096770": "2차전지",
    "051910": "화학",     "005490": "철강",     "000270": "자동차",
    "005380": "자동차",   "207940": "바이오",   "068270": "바이오",
    "326030": "바이오",   "003550": "금융",     "105560": "금융",
    "055550": "금융",     "032830": "금융",
}


def run(dry_run: bool = False, show: bool = False):
    if show:
        _show_current()
        return

    print("[watchlist] KIS 관심종목 동기화 시작...", file=sys.stderr)

    # ── 기존 watchlist 로드 (섹터 정보 보존용) ───────────────────────────────
    existing = _load_existing()
    existing_map = {s["code"]: s for s in existing}
    print(f"  기존 watchlist: {len(existing)}개 종목", file=sys.stderr)

    # ── HTS ID 확인 (없으면 입력 받아서 .env에 저장) ─────────────────────────
    _ensure_hts_id()

    # ── KIS API 연결 ──────────────────────────────────────────────────────────
    try:
        from kis_client import KISClient
        client = KISClient()
    except Exception as e:
        print(f"[오류] KIS 클라이언트 초기화 실패: {e}", file=sys.stderr)
        print("  → watchlist.json 변경 없이 종료합니다.", file=sys.stderr)
        return

    # 기존 watchlist를 기본값으로 시작 (HTS 실패해도 기존 목록 보존)
    new_stocks: dict[str, dict] = dict(existing_map)
    hts_ok = False

    # ── 1. HTS 관심종목 그룹 조회 ─────────────────────────────────────────────
    print("[1/2] HTS 관심종목 그룹 조회 중...", file=sys.stderr)
    try:
        groups = client.get_watchlist_groups()
        print(f"  관심종목 그룹 {len(groups)}개 발견", file=sys.stderr)

        hts_stocks: dict[str, dict] = {}
        for grp in groups:
            grp_code = grp.get("grp_code", "")
            grp_name = grp.get("grp_name", grp_code)
            if not grp_code:
                continue
            try:
                stocks = client.get_watchlist_stocks_by_group(grp_code, grp_name)
                print(f"  [{grp_name}] {len(stocks)}개 종목", file=sys.stderr)
                for s in stocks:
                    code = s.get("code", "").strip()  # P5: .get() + strip() 방어
                    name = s.get("name", code).strip()
                    if code:
                        hts_stocks[code] = {
                            "code":   code,
                            "name":   name,
                            # HTS 그룹명을 sector로 사용 (기존 값 우선 유지)
                            "sector": existing_map[code]["sector"] if code in existing_map else grp_name,
                        }
            except Exception as e:
                print(f"  ⚠️  그룹 [{grp_name}] 종목 조회 실패: {e}", file=sys.stderr)
                # P5: 한 그룹 실패해도 다른 그룹은 계속 진행

        if hts_stocks:
            # HTS 조회 성공 시에만 기존 목록을 HTS 목록으로 교체
            new_stocks = hts_stocks
            hts_ok = True
            print(f"  ✅ HTS 관심종목 {len(hts_stocks)}개 로드 완료", file=sys.stderr)
        else:
            print("  ⚠️  HTS 관심종목이 비어있음 — 기존 목록 유지", file=sys.stderr)

    except Exception as e:
        print(f"  ⚠️  관심종목 그룹 조회 실패: {e}", file=sys.stderr)
        print("  → KIS가 해당 TR을 지원하지 않는 것 같습니다.", file=sys.stderr)
        print("  → 기존 watchlist.json을 유지하고 보유 종목만 추가합니다.", file=sys.stderr)
        # P5: hts_ok=False 유지 → 기존 목록 보존 보장

    # ── 2. 현재 보유 종목 자동 추가 (기존 목록에 merge) ──────────────────────
    print("[2/2] 보유 종목 추가 중...", file=sys.stderr)
    try:
        balance_raw = client.get_balance()
        holdings = _parse_holdings(balance_raw)
        for h in holdings:
            code = h.get("code", "").strip()  # P5: .get() 방어
            name = h.get("name", code).strip()
            if not code:
                continue
            if code not in new_stocks:
                new_stocks[code] = {
                    "code":   code,
                    "name":   name,
                    "sector": _resolve_sector(code, name, existing_map),
                }
                print(f"  ➕ 보유 종목 추가: {name}({code})", file=sys.stderr)
            else:
                print(f"  ✓  보유 중 (이미 포함): {name}({code})", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠️  보유 종목 조회 실패: {e}", file=sys.stderr)
        # P5: 보유종목 실패해도 HTS 목록은 보존

    if not new_stocks:
        print("[주의] 동기화할 종목이 없습니다. watchlist.json을 변경하지 않습니다.", file=sys.stderr)
        return

    # ── 변경사항 계산 ─────────────────────────────────────────────────────────
    new_codes      = set(new_stocks.keys())
    existing_codes = set(existing_map.keys())
    added   = new_codes - existing_codes
    removed = existing_codes - new_codes

    # HTS 조회 실패 시 제거는 하지 않음 (기존 목록 보존)
    if not hts_ok:
        removed = set()

    final_list = sorted(new_stocks.values(), key=lambda x: x["code"])

    # ── 결과 출력 ─────────────────────────────────────────────────────────────
    print(f"\n[결과] 총 {len(final_list)}개 종목", file=sys.stderr)
    if added:
        print(f"  ➕ 추가: {', '.join(new_stocks[c]['name']+'('+c+')' for c in sorted(added))}", file=sys.stderr)
    if removed:
        print(f"  ➖ 제거: {', '.join(existing_map[c]['name']+'('+c+')' for c in sorted(removed))}", file=sys.stderr)
    if not hts_ok:
        print("  ℹ️  HTS TR 미지원 — 기존 목록 보존 + 보유 종목 추가만 수행", file=sys.stderr)
    if not added and not removed:
        print("  변경사항 없음", file=sys.stderr)

    if dry_run:
        print("\n[DRY-RUN] 파일 저장 생략. 최종 목록:", file=sys.stderr)
        for s in final_list:
            print(f"  {s['name']}({s['code']}) [{s['sector']}]", file=sys.stderr)
        return

    # ── watchlist.json 저장 ───────────────────────────────────────────────────
    _WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)

    # atomic write (손상 방지)
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", dir=_WATCHLIST_FILE.parent,
        delete=False, suffix=".tmp", encoding="utf-8"
    ) as tmp:
        json.dump(final_list, tmp, ensure_ascii=False, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, _WATCHLIST_FILE)

    print(f"[완료] watchlist.json 저장: {_WATCHLIST_FILE}", file=sys.stderr)
    print(f"       {datetime.now().strftime('%Y-%m-%d %H:%M')} 기준 {len(final_list)}개 종목", file=sys.stderr)


# ── HTS ID 설정 ──────────────────────────────────────────────────────────────

def _ensure_hts_id():
    """
    KIS_HTS_ID 환경변수가 없거나 비어있으면 터미널에서 입력받아 .env에 저장.
    이후 실행부터는 자동으로 읽힘.
    """
    import os as _os
    # .env 인라인 주석(# ...) 제거 후 실제 값만 추출
    hts_id = _os.getenv("KIS_HTS_ID", "").split("#")[0].strip()
    if hts_id:
        return  # 이미 설정됨

    print()
    print("=" * 50)
    print("📱 한국투자증권 로그인 ID 설정")
    print("=" * 50)
    print("관심종목 그룹 조회에 로그인 ID가 필요합니다.")
    print("MTS(앱) 또는 홈페이지 로그인 시 사용하는 ID를 입력하세요.")
    print("(카카오/네이버 소셜 로그인 사용 시 해당 계정 이메일 입력)")
    print()

    while True:
        hts_id = input("로그인 ID 입력: ").strip()
        if hts_id:
            break
        print("  ID를 입력해주세요.")

    # .env 파일에 저장
    try:
        from dotenv import set_key
        env_path = str(_ROOT / ".env")
        set_key(env_path, "KIS_HTS_ID", hts_id)
        # 현재 프로세스 환경변수에도 즉시 반영
        _os.environ["KIS_HTS_ID"] = hts_id
        print(f"✅ ID 저장 완료 (.env에 KIS_HTS_ID={hts_id[:3]}***)")
        print()
    except Exception as e:
        # set_key 실패해도 현재 실행은 계속
        _os.environ["KIS_HTS_ID"] = hts_id
        print(f"⚠️  .env 자동 저장 실패: {e}")
        print(f"   수동으로 .env에 추가하세요: KIS_HTS_ID={hts_id}")
        print()


# ── 헬퍼 함수들 ──────────────────────────────────────────────────────────────

def _show_current():
    """현재 watchlist.json 내용 출력."""
    stocks = _load_existing()
    if not stocks:
        print("watchlist.json이 비어있거나 없습니다.")
        print(f"경로: {_WATCHLIST_FILE}")
        return
    print(f"📋 관심 종목 목록 ({len(stocks)}개) — {_WATCHLIST_FILE}")
    print("=" * 40)
    by_sector: dict[str, list] = {}
    for s in stocks:
        by_sector.setdefault(s.get("sector", "기타"), []).append(s)
    for sector, items in sorted(by_sector.items()):
        print(f"\n[{sector}]")
        for s in items:
            print(f"  {s['name']}  ({s['code']})")


def _load_existing() -> list:
    if not _WATCHLIST_FILE.exists():
        return []
    try:
        data = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _resolve_sector(code: str, name: str, existing_map: dict) -> str:
    """섹터 결정 우선순위: 기존 watchlist → _SECTOR_MAP → 이름 기반 추정 → '기타'"""
    if code in existing_map:
        return existing_map[code].get("sector", "기타")
    if code in _SECTOR_MAP:
        return _SECTOR_MAP[code]
    # 이름 기반 간단 추정
    name_lower = name.lower()
    if any(k in name for k in ["반도체", "HBM", "웨이퍼"]):
        return "반도체"
    if any(k in name for k in ["배터리", "에너지솔루션", "SDI", "LFP"]):
        return "2차전지"
    if any(k in name for k in ["바이오", "셀트리온", "삼성바이오", "제약"]):
        return "바이오"
    if any(k in name for k in ["카카오", "네이버", "NAVER", "인터넷"]):
        return "인터넷"
    return "기타"


def _parse_holdings(balance_raw) -> list:
    if isinstance(balance_raw, list):
        raw_list = balance_raw
    elif isinstance(balance_raw, dict):
        raw_list = balance_raw.get("output1") or balance_raw.get("holdings") or []
    else:
        return []
    result = []
    for item in raw_list:
        if not item:
            continue
        code = str(item.get("pdno") or item.get("code") or "").strip()
        name = str(item.get("prdt_name") or item.get("name") or code).strip()
        qty  = int(str(item.get("hldg_qty") or item.get("qty") or 0).replace(",", "") or 0)
        if code and qty > 0:
            result.append({"code": code, "name": name})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KIS HTS 관심종목 → watchlist.json 동기화")
    parser.add_argument("--dry-run", action="store_true", help="파일 저장 없이 결과만 출력")
    parser.add_argument("--show",    action="store_true", help="현재 watchlist.json 내용 출력")
    args = parser.parse_args()
    run(dry_run=args.dry_run, show=args.show)

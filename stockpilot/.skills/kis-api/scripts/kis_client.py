"""
한국투자증권 Open API 클라이언트.

설계 원칙:
- 토큰은 파일 캐시. KIS는 1분당 1회 토큰 발급 제한이 있어 매번 새로 받으면 안 됨.
- 실제 주문(place_order)은 KIS_ALLOW_LIVE_ORDER=1 환경변수가 있어야만 동작.
- 모든 응답은 dict로 반환. 호출자가 후처리.
"""
from __future__ import annotations

import json
import os
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드 (.skills/kis-api/scripts/ 에서 3단계 위)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "kis_token.json"
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


class KISConfigError(RuntimeError):
    """필수 환경변수 누락."""


class KISAPIError(RuntimeError):
    """API 응답이 정상이 아님 (rt_cd != '0')."""


def _mask(value: str, show: int = 4) -> str:
    """민감정보 마스킹 — 앞 n자리만 표시. 로그/에러 메시지용."""
    if not value:
        return "(없음)"
    return value[:show] + "*" * max(0, len(value) - show)


class KISClient:
    def __init__(self) -> None:
        self.app_key = os.getenv("KIS_APP_KEY")
        self.app_secret = os.getenv("KIS_APP_SECRET")
        self.account_no = os.getenv("KIS_ACCOUNT_NO", "")
        self.hts_id = os.getenv("KIS_HTS_ID", "").split("#")[0].strip()  # 관심종목 조회에 필요

        missing = [k for k, v in {
            "KIS_APP_KEY": self.app_key,
            "KIS_APP_SECRET": self.app_secret,
            "KIS_ACCOUNT_NO": self.account_no,
        }.items() if not v]
        if missing:
            raise KISConfigError(
                f"환경변수 누락: {', '.join(missing)}. "
                f"프로젝트 루트의 .env 파일을 확인하세요."
            )

        if "-" not in self.account_no:
            raise KISConfigError(
                "KIS_ACCOUNT_NO 형식 오류. '12345678-01' 형태(8자리-2자리)여야 합니다."
            )
        self.cano, self.acnt_prdt_cd = self.account_no.split("-", 1)
        self.base_url = REAL_BASE_URL  # 사용자 결정: 실전만

        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 보수적 레이트 리밋 (KIS는 초당 20건이지만 안전 마진)
        self._min_interval = 0.06
        self._last_call = 0.0

    # ------------------------------------------------------------------ token
    def _load_cached_token(self) -> str | None:
        if not TOKEN_CACHE_PATH.exists():
            return None
        try:
            data = json.loads(TOKEN_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            # P4: 손상된 캐시 파일 삭제
            try:
                TOKEN_CACHE_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        # P4: expire_at 키 누락 방어
        expire_str = data.get("expire_at")
        if not expire_str:
            TOKEN_CACHE_PATH.unlink(missing_ok=True)
            return None
        try:
            expire = datetime.fromisoformat(expire_str)
        except ValueError:
            TOKEN_CACHE_PATH.unlink(missing_ok=True)
            return None
        # 만료 5분 전이면 무효 → 캐시 삭제
        if expire - datetime.now() < timedelta(minutes=5):
            TOKEN_CACHE_PATH.unlink(missing_ok=True)
            return None
        return data.get("access_token")

    def _save_token(self, token: str, expires_in: int) -> None:
        expire_at = datetime.now() + timedelta(seconds=expires_in)
        # P4: atomic write로 손상 방지
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=TOKEN_CACHE_PATH.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump({"access_token": token, "expire_at": expire_at.isoformat()}, f)
            os.replace(tmp_path, TOKEN_CACHE_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _get_token(self) -> str:
        cached = self._load_cached_token()
        if cached:
            return cached

        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise KISAPIError(f"토큰 발급 실패: {data}")
        self._save_token(data["access_token"], data.get("expires_in", 86400))
        return data["access_token"]

    # ----------------------------------------------------------------- header
    def _headers(self, tr_id: str, hashkey: str | None = None) -> dict[str, str]:
        h = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._get_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }
        if hashkey:
            h["hashkey"] = hashkey
        return h

    def _hashkey(self, body: dict[str, Any]) -> str:
        url = f"{self.base_url}/uapi/hashkey"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()["HASH"]

    # ----------------------------------------------------------------- request
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.time()

    def _get(self, path: str, tr_id: str, params: dict[str, Any]) -> dict:
        self._throttle()
        url = f"{self.base_url}{path}"
        resp = requests.get(url, headers=self._headers(tr_id), params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("rt_cd") != "0":
            raise KISAPIError(f"{tr_id} 실패: {data.get('msg_cd')} {data.get('msg1')}")
        return data

    def _post(self, path: str, tr_id: str, body: dict[str, Any]) -> dict:
        self._throttle()
        url = f"{self.base_url}{path}"
        hashkey = self._hashkey(body)
        resp = requests.post(url, headers=self._headers(tr_id, hashkey), json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("rt_cd") != "0":
            raise KISAPIError(f"{tr_id} 실패: {data.get('msg_cd')} {data.get('msg1')}")
        return data

    # ------------------------------------------------------------- public APIs
    def get_price(self, code: str) -> dict:
        """현재가 + 등락률 + 거래량."""
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )["output"]

    def get_ccnl(self, code: str) -> dict:
        """최근 체결 내역 + 당일 체결강도 (FHKST01010300).
        반환: output[0] dict — stck_prpr, tday_rltv, prdy_ctrt, cntg_vol 포함.
        체결강도(tday_rltv)는 배열 첫 번째 row가 현재 시점값.
        """
        resp = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-ccnl",
            tr_id="FHKST01010300",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        rows = resp.get("output", [])
        return rows[0] if rows else {}

    def get_orderbook(self, code: str) -> dict:
        """10단계 호가 + 잔량."""
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            tr_id="FHKST01010200",
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )

    def get_daily_chart(self, code: str, days: int = 60, adjusted: bool = True) -> list[dict]:
        """일봉 OHLCV. 최대 100건. days만큼 잘라서 리턴."""
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            tr_id="FHKST03010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start,
                "FID_INPUT_DATE_2": end,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
            },
        )
        return data["output2"][:days]

    def get_minute_chart(self, code: str, hhmm: str = "153000") -> list[dict]:
        """1분봉. hhmm을 기준으로 직전 30봉(약 30분)."""
        return self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            tr_id="FHKST03010200",
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": hhmm,
                "FID_PW_DATA_INCU_YN": "Y",
            },
        )["output2"]

    def get_balance(self) -> dict:
        """계좌 보유 종목 + 평가손익 + 예수금."""
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        return self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id="TTTC8434R",
            params=params,
        )

    def get_orderable_cash(self) -> int:
        """주식현금주문가능금액 조회 (TTTC0869R 주식통합증거금 현황).
        stck_cash_ord_psbl_amt = 앱 '주문가능' 표시 값과 동일.
        """
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "WCRC_FRCR_DVSN_CD": "02",       # 원화기준
            "FWEX_CTRT_FRCR_DVSN_CD": "02",  # 원화기준
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/intgr-margin",
            tr_id="TTTC0869R",
            params=params,
        )
        output = data.get("output") or {}
        try:
            # 통합증거금 100% 계좌: stck_itgr_cash100_ord_psbl_amt (앱 '주문가능'과 동일)
            # 일반 계좌 fallback: stck_cash_ord_psbl_amt
            val = output.get("stck_itgr_cash100_ord_psbl_amt") or output.get("stck_cash_ord_psbl_amt", 0)
            return int(float(val))
        except (TypeError, ValueError):
            return 0

    def get_watchlist_groups(self) -> list[dict]:
        """
        HTS 관심종목 그룹 목록 조회 [국내주식-204]
        TR: HHKCM113004C7  /uapi/domestic-stock/v1/quotations/intstock-grouplist
        반환: [{"grp_code": "001", "grp_name": "관심종목1"}, ...]
        KIS_HTS_ID 환경변수 필요.
        """
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/intstock-grouplist",
            tr_id="HHKCM113004C7",
            params={
                "TYPE":             "1",          # 관심종목구분코드 (필수)
                "FID_ETC_CLS_CODE": "00",         # 기타구분코드 (필수)
                "USER_ID":          self.hts_id,  # HTS ID (필수)
            },
        )
        rows = data.get("output2", []) or []
        result = []
        for r in rows:
            grp_code = str(r.get("inter_grp_code") or "").strip()
            grp_name = str(r.get("inter_grp_name") or grp_code).strip()
            if grp_code:
                result.append({"grp_code": grp_code, "grp_name": grp_name})
        if not result:
            # P3: HTS ID 마스킹하여 로그 노출 방지
            import sys as _sys
            print(f"  [watchlist] 그룹 없음 (USER_ID: {_mask(self.hts_id)})", file=_sys.stderr)
        return result

    def get_watchlist_stocks_by_group(self, grp_code: str, grp_name: str = "") -> list[dict]:
        """
        HTS 관심종목 그룹별 종목조회 [국내주식-203]
        TR: HHKCM113004C6  /uapi/domestic-stock/v1/quotations/intstock-stocklist-by-group
        grp_code: get_watchlist_groups()에서 얻은 inter_grp_code (예: "001")
        반환: [{"code": "005930", "name": "삼성전자"}, ...]
        엑셀 예시 참고: TYPE=1, FID_ETC_CLS_CODE=4, USER_ID=HTS_ID 입력
        """
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/intstock-stocklist-by-group",
            tr_id="HHKCM113004C6",
            params={
                "TYPE":             "1",
                "USER_ID":          self.hts_id,
                "DATA_RANK":        "",
                "INTER_GRP_CODE":   grp_code,
                "INTER_GRP_NAME":   grp_name,
                "HTS_KOR_ISNM":     "",
                "CNTG_CLS_CODE":    "",
                "FID_ETC_CLS_CODE": "4",
            },
        )
        rows = data.get("output2", []) or []
        result = []
        for r in rows:
            code = str(r.get("jong_code") or "").strip()
            name = str(r.get("hts_kor_isnm") or code).strip()
            if code:
                result.append({"code": code, "name": name})
        return result

    # ------------------------------------------------------------- order draft
    def build_order_payload(
        self, side: str, code: str, qty: int, price: int | None = None
    ) -> dict:
        """
        주문 JSON payload 생성. side ∈ {'BUY', 'SELL'}.
        price=None 이면 시장가, 아니면 지정가.
        실제 전송은 하지 않음. payload + tr_id + endpoint를 dict로 반환.
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if qty <= 0:
            raise ValueError("qty must be positive")

        tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
        ord_dvsn = "01" if price is None else "00"  # 01=시장가, 00=지정가
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": code,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0" if price is None else str(int(price)),
        }
        return {
            "endpoint": "/uapi/domestic-stock/v1/trading/order-cash",
            "method": "POST",
            "tr_id": tr_id,
            "body": body,
            "human_summary": (
                f"{'매수' if side == 'BUY' else '매도'} | 종목 {code} | "
                f"수량 {qty}주 | "
                f"{'시장가' if price is None else f'지정가 {price:,}원'}"
            ),
        }

    def place_order(self, side: str, code: str, qty: int, price: int | None = None) -> dict:
        """
        실제 주문 전송. 안전장치: 환경변수 KIS_ALLOW_LIVE_ORDER=1 필수.
        설정되어 있지 않으면 즉시 RuntimeError.
        """
        if os.getenv("KIS_ALLOW_LIVE_ORDER") != "1":
            raise RuntimeError(
                "실주문 전송이 차단됨. 환경변수 KIS_ALLOW_LIVE_ORDER=1 을 명시적으로 설정해야 함. "
                "현재는 build_order_payload()로 초안만 생성 가능."
            )
        draft = self.build_order_payload(side, code, qty, price)
        return self._post(draft["endpoint"], draft["tr_id"], draft["body"])


# ---------------------------------------------------------- save helper
def save_raw(name: str, code: str, data: Any) -> Path:
    """data/raw/<code>_<name>_<YYYYMMDD-HHMM>.json 으로 저장하고 경로 반환."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = RAW_DATA_DIR / f"{code}_{name}_{ts}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return path

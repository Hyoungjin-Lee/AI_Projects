from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KIS_SCRIPT_DIR = PROJECT_ROOT / ".skills" / "kis-api" / "scripts"
if str(KIS_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(KIS_SCRIPT_DIR))


@pytest.fixture
def kis_client_module():
    import kis_client

    return importlib.reload(kis_client)


@pytest.fixture
def mock_kis_env_observation(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "obs-app-key")
    monkeypatch.setenv("KIS_APP_SECRET", "obs-app-secret")
    monkeypatch.setenv("KIS_ACCOUNT_NO", "12345678-01")
    monkeypatch.setenv("KIS_HTS_ID", "obs-user")


@pytest.fixture
def mock_kis_env_trading(monkeypatch):
    monkeypatch.setenv("KIS_TRADING_APP_KEY", "trading-app-key")
    monkeypatch.setenv("KIS_TRADING_APP_SECRET", "trading-app-secret")
    monkeypatch.setenv("KIS_TRADING_ACCOUNT_NO", "87654321-01")


def test_default_mode_is_observation(kis_client_module, mock_kis_env_observation):
    client = kis_client_module.KISClient()

    assert client.mode == "observation"
    assert client.account_no == "12345678-01"
    assert client.hts_id == "obs-user"


def test_explicit_observation_mode_uses_observation_env(
    kis_client_module, mock_kis_env_observation
):
    client = kis_client_module.KISClient(mode="observation")

    assert client.mode == "observation"
    assert client.account_no == "12345678-01"
    assert client.cano == "12345678"
    assert client.acnt_prdt_cd == "01"


def test_invalid_mode_raises_value_error(kis_client_module):
    with pytest.raises(ValueError, match="observation' or 'trading"):
        kis_client_module.KISClient(mode="invalid")


def test_trading_mode_requires_trading_env(kis_client_module, monkeypatch):
    monkeypatch.delenv("KIS_TRADING_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_TRADING_APP_SECRET", raising=False)
    monkeypatch.delenv("KIS_TRADING_ACCOUNT_NO", raising=False)

    with pytest.raises(
        kis_client_module.KISConfigError,
        match=r"\[mode=trading\] 환경변수 누락",
    ):
        kis_client_module.KISClient(mode="trading")


def test_observation_cannot_place_order(kis_client_module, mock_kis_env_observation):
    client = kis_client_module.KISClient()

    with pytest.raises(kis_client_module.KISConfigError, match="mode='trading'"):
        client.build_order_payload("BUY", "005930", 1)


def test_assert_trading_mode(
    kis_client_module, mock_kis_env_observation, mock_kis_env_trading
):
    observation_client = kis_client_module.KISClient()
    trading_client = kis_client_module.KISClient(mode="trading")

    with pytest.raises(kis_client_module.KISConfigError, match="트레이딩 모드 전용"):
        observation_client.assert_trading_mode()
    assert trading_client.assert_trading_mode() is None


def test_observation_cannot_call_watchlist_in_trading_mode(
    kis_client_module, mock_kis_env_trading
):
    client = kis_client_module.KISClient(mode="trading")

    with pytest.raises(kis_client_module.KISConfigError, match="observation 모드 전용"):
        client.get_watchlist_groups()
    with pytest.raises(kis_client_module.KISConfigError, match="observation 모드 전용"):
        client.get_watchlist_stocks_by_group("001", "관심1")


def test_build_order_payload_buy_branch(kis_client_module, mock_kis_env_trading):
    client = kis_client_module.KISClient(mode="trading")
    payload = client.build_order_payload("BUY", "005930", 10, price=75000)

    assert payload["tr_id"] == "TTTC0802U"
    assert payload["body"]["ORD_DVSN"] == "00"  # 지정가
    assert payload["body"]["ORD_QTY"] == "10"
    assert payload["body"]["ORD_UNPR"] == "75000"
    assert payload["body"]["PDNO"] == "005930"


def test_build_order_payload_sell_branch(kis_client_module, mock_kis_env_trading):
    client = kis_client_module.KISClient(mode="trading")
    payload = client.build_order_payload("SELL", "005930", 5, price=85000)

    assert payload["tr_id"] == "TTTC0801U"  # 매도 TR
    assert payload["body"]["ORD_DVSN"] == "00"  # 지정가
    assert payload["body"]["ORD_QTY"] == "5"
    assert payload["body"]["ORD_UNPR"] == "85000"
    assert "매도" in payload["human_summary"]


def test_build_order_payload_market_order(kis_client_module, mock_kis_env_trading):
    client = kis_client_module.KISClient(mode="trading")
    payload = client.build_order_payload("SELL", "005930", 5, price=None)

    assert payload["body"]["ORD_DVSN"] == "01"  # 시장가
    assert payload["body"]["ORD_UNPR"] == "0"


def test_build_order_payload_rejects_invalid_qty(kis_client_module, mock_kis_env_trading):
    client = kis_client_module.KISClient(mode="trading")

    with pytest.raises(ValueError, match="qty must be positive"):
        client.build_order_payload("BUY", "005930", 0)
    with pytest.raises(ValueError, match="qty must be positive"):
        client.build_order_payload("BUY", "005930", -1)


def test_build_order_payload_rejects_invalid_side(kis_client_module, mock_kis_env_trading):
    client = kis_client_module.KISClient(mode="trading")

    with pytest.raises(ValueError, match="side must be BUY or SELL"):
        client.build_order_payload("HOLD", "005930", 1)


def test_dry_run_returns_mock(kis_client_module, mock_kis_env_trading, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("KIS_ALLOW_LIVE_ORDER", raising=False)

    client = kis_client_module.KISClient(mode="trading")
    resp = client.place_order("BUY", "005930", 1)

    assert resp["rt_cd"] == "0"
    assert resp["msg_cd"] == "DRY_RUN"
    assert resp["output"]["ODNO"].startswith("DRY")


def test_live_guard_still_works(kis_client_module, mock_kis_env_trading, monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("KIS_ALLOW_LIVE_ORDER", raising=False)

    client = kis_client_module.KISClient(mode="trading")

    with pytest.raises(RuntimeError, match="KIS_ALLOW_LIVE_ORDER"):
        client.place_order("BUY", "005930", 1)


def test_token_cache_paths_are_separate(
    kis_client_module, mock_kis_env_observation, mock_kis_env_trading, tmp_path
):
    observation_client = kis_client_module.KISClient(mode="observation")
    trading_client = kis_client_module.KISClient(mode="trading")

    observation_client._token_cache_path = tmp_path / "kis_token.json"
    trading_client._token_cache_path = tmp_path / "kis_token_trading.json"

    observation_client._save_token("obs-token", 3600)
    trading_client._save_token("trading-token", 3600)

    assert observation_client._token_cache_path != trading_client._token_cache_path
    assert observation_client._token_cache_path.name == "kis_token.json"
    assert trading_client._token_cache_path.name == "kis_token_trading.json"
    assert observation_client._load_cached_token() == "obs-token"
    assert trading_client._load_cached_token() == "trading-token"

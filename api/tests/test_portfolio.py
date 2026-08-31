from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from screener import api, portfolio, store
from screener.sources.crypto import CryptoQuote


def row(price=25):
    return {
        "cik": "0000000001",
        "ticker": "TEST",
        "name": "Test Company",
        "listed": "y",
        "price": price,
        "price_asof": "2026-08-28T20:00:00+00:00",
        "price_session": "REGULAR",
        "market_state": "REGULAR",
        "market_state_asof": "2026-08-28T20:01:00+00:00",
        "market_timezone": "America/New_York",
        "price_source": "yahoo",
        "ttm_eps": 2,
        "annual_eps": {"2023": 1, "2024": 2, "2025": 3},
        "bvps": 12,
        "tbvps": 10,
        "ncavps": 4,
        "recurring_dividend_per_share": 0.5,
        "owner_earnings": {
            "fiscal_year": 2025,
            "status": "ESTIMATE_ONLY",
            "annual_per_share": {"2025": {
                "per_share": None,
                "all_capex_floor_per_share": 2,
                "maintenance_estimate_per_share": 2.5,
                "free_cash_flow_per_share": 1.5,
            }},
        },
        "criteria": [
            {"n": 1, "status": "FAIL", "value": price / 2, "note": None},
            {"n": 2, "status": "PASS", "value": 2, "note": None},
            {"n": 3, "status": "PASS", "value": 0.5, "note": None},
            {"n": 4, "status": "PASS", "value": 1, "note": None},
            {"n": 5, "status": "PASS", "value": 2, "note": None},
            {"n": 7, "status": "FAIL", "value": price / 10, "note": None},
        ],
        "alignment": {
            "enterprising": {
                "verdict": "BLOCKED", "passed": 4, "total": 6, "unknown": 0,
                "tests": {},
            },
            "defensive": {
                "verdict": "BLOCKED", "passed": 5, "total": 6, "unknown": 0,
                "tests": {
                    "size": "PASS", "financial_position": "PASS",
                    "stability_10y": "PASS", "dividend_20y": "PASS",
                    "growth_10y": "PASS", "valuation": "FAIL",
                },
            },
        },
    }


def snapshot(fill_price):
    return portfolio.decision_snapshot(
        {"generated": "2026-08-28T12:00:00+00:00", "engine_version": 106},
        row(), fill_price, captured_at="2026-08-28T12:01:00+00:00",
    )


def trade(identifier, side, quantity, price, fees, when):
    return {
        "id": identifier,
        "portfolio_id": 1,
        "cik": "0000000001",
        "ticker": "TEST",
        "side": side,
        "quantity": str(quantity),
        "price": str(price),
        "fees": str(fees),
        "currency": "USD",
        "executed_at": when,
        "broker": "test",
        "account_label": None,
        "external_id": None,
        "note": None,
        "decision_snapshot": snapshot(price),
        "created_at": when,
    }


def test_trade_price_resettles_only_price_criteria_and_multiples():
    saved = snapshot(9)
    by_n = {criterion["n"]: criterion for criterion in saved["execution"]["criteria"]}

    assert by_n[1]["status"] == "PASS"
    assert by_n[1]["value"] == 4.5
    assert by_n[7]["status"] == "PASS"
    assert by_n[2] == row()["criteria"][1]
    assert saved["execution"]["valuation"]["pe3"] == 4.5
    assert saved["execution"]["valuation"]["owner_earnings_yield"] is None
    assert saved["execution"]["valuation"]["all_capex_floor_yield"] == pytest.approx(2 / 9 * 100)
    assert saved["execution"]["valuation"]["maintenance_estimate_yield"] == pytest.approx(2.5 / 9 * 100)
    assert saved["execution"]["valuation"]["free_cash_flow_yield"] == pytest.approx(1.5 / 9 * 100)
    assert saved["displayed"]["price"] == 25


def test_fifo_cost_basis_and_fees_are_exact():
    trades = [
        trade(1, "BUY", 10, 10, 1, "2026-01-01T10:00:00+00:00"),
        trade(2, "BUY", 5, 20, 1, "2026-02-01T10:00:00+00:00"),
        trade(3, "SELL", 12, 30, 2, "2026-03-01T10:00:00+00:00"),
    ]

    result = portfolio.build_portfolio(
        {"id": 1, "name": "Paper", "base_currency": "USD"},
        trades,
        {"0000000001": row(25)},
    )
    position = result["positions"][0]

    assert position["quantity"] == 3
    assert position["cost_basis"] == pytest.approx(60.6)
    assert position["average_cost"] == pytest.approx(20.2)
    assert position["market_value"] == 75
    assert position["unrealized_pnl"] == pytest.approx(14.4)
    assert position["realized_pnl"] == pytest.approx(216.6)
    assert position["quote_after_latest_trade"] is True
    assert position["price_session"] == "REGULAR"
    assert position["market_state"] == "REGULAR"
    assert position["price_source"] == "yahoo"
    assert result["summary"]["post_trade_quotes"] == 1
    assert result["summary"]["pre_trade_quotes"] == 0
    assert result["summary"]["fees"] == 4


def test_quote_before_latest_trade_is_disclosed_not_treated_as_post_purchase():
    current = row(25)
    current["price_asof"] = "2026-08-28T10:00:00+00:00"
    result = portfolio.build_portfolio(
        {"id": 1, "name": "Paper", "base_currency": "USD"},
        [trade(1, "BUY", 1, 9, 1, "2026-08-28T14:00:00+03:00")],
        {"0000000001": current},
    )

    assert result["positions"][0]["quote_after_latest_trade"] is False
    assert result["summary"]["pre_trade_quotes"] == 1
    assert result["summary"]["post_trade_quotes"] == 0


def test_hourly_quote_warning_reaches_the_portfolio_position():
    current = row(25)
    current["quote_refresh_warning"] = {
        "kind": "QUOTE_REFRESH_FAILED",
        "note": "the previous dated quote remains in use",
    }
    result = portfolio.build_portfolio(
        {"id": 1, "name": "Paper", "base_currency": "USD"},
        [trade(1, "BUY", 1, 9, 1, "2026-01-01T10:00:00+00:00")],
        {"0000000001": current},
    )

    assert result["positions"][0]["quote_refresh_warning"]["kind"] == "QUOTE_REFRESH_FAILED"


def test_all_asset_summary_keeps_manual_holdings_cash_and_stock_quotes_distinct():
    result = portfolio.build_portfolio(
        {"id": 1, "name": "Paper", "base_currency": "USD"},
        [trade(1, "BUY", 2, 9, 0, "2026-01-01T10:00:00+00:00")],
        {"0000000001": row(25)},
        [
            {"id": 1, "portfolio_id": 1, "asset_type": "BOND", "symbol": "UST-2030",
             "name": "Treasury note", "quantity": "10", "current_price": "98.5",
             "currency": "USD", "note": None, "created_at": "2026-08-29T00:00:00+00:00",
             "updated_at": "2026-08-29T00:00:00+00:00"},
            {"id": 2, "portfolio_id": 1, "asset_type": "CRYPTO", "symbol": "BTC",
             "name": "Bitcoin", "quantity": "0.1", "current_price": "60000",
             "currency": "USD", "note": None, "created_at": "2026-08-29T00:00:00+00:00",
             "updated_at": "2026-08-29T00:00:00+00:00"},
        ],
        {"amount": "500", "updated_at": "2026-08-29T00:00:00+00:00"},
    )

    assert result["summary"]["stock_value"] == 50
    assert result["summary"]["bond_value"] == 985
    assert result["summary"]["crypto_value"] == 6000
    assert result["summary"]["liquid_cash"] == 500
    assert result["summary"]["invested_assets"] == 7035
    assert result["summary"]["total_assets"] == 7535
    assert result["summary"]["holdings"] == 3
    assert result["assets"]["bonds"][0]["market_value"] == 985
    assert sum(item["weight_pct"] for item in result["allocation"]) == pytest.approx(100)


def test_all_asset_total_is_withheld_until_cash_is_entered():
    result = portfolio.build_portfolio(
        {"id": 1, "name": "Paper", "base_currency": "USD"}, [], {}, [], None)

    assert result["summary"]["stock_value"] == 0
    assert result["summary"]["liquid_cash"] is None
    assert result["summary"]["total_assets"] is None
    assert all(item["weight_pct"] is None for item in result["allocation"])


def test_sell_cannot_precede_or_exceed_buys():
    with pytest.raises(portfolio.PortfolioError, match="exceeds"):
        portfolio.build_portfolio(
            {"id": 1, "name": "Paper", "base_currency": "USD"},
            [trade(1, "SELL", 1, 10, 0, "2026-01-01T10:00:00+00:00")],
            {"0000000001": row()},
        )


def test_store_round_trips_trade_snapshot(tmp_path):
    conn = store.connect(tmp_path / "portfolio.db")
    selected = store.ensure_portfolio(conn)
    saved = snapshot(9)
    created = store.add_portfolio_trade(
        conn,
        portfolio_id=selected["id"],
        cik="0000000001",
        ticker="TEST",
        side="BUY",
        quantity=portfolio.canonical_decimal(Decimal("3")),
        price=portfolio.canonical_decimal(Decimal("9.25")),
        fees="1",
        currency="USD",
        executed_at="2026-08-28T12:00:00+00:00",
        broker="IBKR",
        decision_snapshot=saved,
    )

    assert created["price"] == "9.25"
    assert store.portfolio_trades(conn, selected["id"])[0]["decision_snapshot"] == saved
    assert store.delete_portfolio_trade(conn, selected["id"], created["id"])
    assert store.portfolio_trades(conn, selected["id"]) == []
    conn.close()


def test_store_round_trips_manual_assets_and_liquid_cash(tmp_path):
    conn = store.connect(tmp_path / "portfolio-assets.db")
    selected = store.ensure_portfolio(conn)
    created = store.add_portfolio_asset(
        conn,
        portfolio_id=selected["id"],
        asset_type="CRYPTO",
        symbol="BTC",
        name="Bitcoin",
        quantity="0.125",
        current_price="61234.56",
        currency="USD",
        note="cold wallet",
    )
    cash = store.set_portfolio_cash(conn, selected["id"], "1234.56")

    assert store.portfolio_assets(conn, selected["id"])[0]["quantity"] == "0.125"
    assert store.portfolio_cash(conn, selected["id"])["amount"] == "1234.56"
    updated = store.update_portfolio_asset(
        conn,
        portfolio_id=selected["id"],
        asset_id=created["id"],
        asset_type="CRYPTO",
        symbol="BTC",
        name="Bitcoin",
        quantity="0.25",
        current_price="62000",
        currency="USD",
        note=None,
    )
    assert updated["quantity"] == "0.25"
    assert cash["amount"] == "1234.56"
    assert store.delete_portfolio_asset(conn, selected["id"], created["id"])
    assert store.portfolio_assets(conn, selected["id"]) == []
    conn.close()


def test_portfolio_api_records_and_removes_a_trade(tmp_path, monkeypatch):
    original_connect = store.connect
    database = tmp_path / "api-portfolio.db"
    monkeypatch.setattr(api.store, "connect", lambda: original_connect(database))
    dashboard = {
        "generated": "2026-08-28T12:00:00+00:00",
        "engine_version": 106,
        "rows": [row()],
    }
    monkeypatch.setattr(api, "_portfolio_rows", lambda: (
        dashboard, {"0000000001": dashboard["rows"][0]}
    ))
    client = TestClient(api.app)
    selected = client.get("/portfolio").json()["portfolio"]

    response = client.post(f"/portfolio/{selected['id']}/trades", json={
        "cik": "0000000001",
        "side": "BUY",
        "quantity": "4",
        "price": "9",
        "fees": "1",
        "currency": "USD",
        "executed_at": "2026-08-28T14:30:00+03:00",
        "external_id": "paper-1",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio"]["summary"]["positions"] == 1
    assert body["portfolio"]["summary"]["cost_basis"] == 37
    trade_id = body["trade"]["id"]
    assert body["trade"]["decision_snapshot"]["execution"]["criteria"][0]["status"] == "PASS"

    # Portfolio reads the exact dashboard row used by Research. It does not make
    # a private live request that can give the two pages different prices.
    current = client.get("/portfolio").json()
    assert current["quote_refresh"] is None
    assert current["positions"][0]["current_price"] == 25

    duplicate = client.post(f"/portfolio/{selected['id']}/trades", json={
        "cik": "0000000001", "side": "BUY", "quantity": 1, "price": 9, "fees": 0,
        "currency": "USD", "executed_at": "2026-08-28T14:31:00+03:00",
        "external_id": "paper-1",
    })
    assert duplicate.status_code == 409

    removed = client.delete(f"/portfolio/{selected['id']}/trades/{trade_id}")
    assert removed.status_code == 200
    assert removed.json()["portfolio"]["summary"]["positions"] == 0


def test_portfolio_api_manages_manual_assets_and_liquid_cash(tmp_path, monkeypatch):
    original_connect = store.connect
    database = tmp_path / "api-portfolio-assets.db"
    monkeypatch.setattr(api.store, "connect", lambda: original_connect(database))
    dashboard = {"generated": "2026-08-28T12:00:00+00:00", "engine_version": 106,
                 "rows": [row()]}
    monkeypatch.setattr(api, "_portfolio_rows", lambda: (
        dashboard, {"0000000001": dashboard["rows"][0]}))
    client = TestClient(api.app)
    selected = client.get("/portfolio").json()["portfolio"]

    cash_response = client.put(
        f"/portfolio/{selected['id']}/cash", json={"amount": "2500.25"})
    assert cash_response.status_code == 200
    assert cash_response.json()["portfolio"]["summary"]["liquid_cash"] == 2500.25

    created = client.post(f"/portfolio/{selected['id']}/assets", json={
        "asset_type": "BOND", "symbol": "UST-2030", "name": "Treasury note",
        "quantity": "10", "current_price": "99.5", "currency": "USD",
    })
    assert created.status_code == 200
    body = created.json()
    assert body["portfolio"]["summary"]["bond_value"] == 995
    assert body["portfolio"]["summary"]["total_assets"] == 3495.25
    asset_id = body["asset"]["id"]

    changed = client.put(f"/portfolio/{selected['id']}/assets/{asset_id}", json={
        "asset_type": "BOND", "symbol": "UST-2030", "name": "Treasury note",
        "quantity": "20", "current_price": "99", "currency": "USD",
    })
    assert changed.status_code == 200
    assert changed.json()["portfolio"]["summary"]["bond_value"] == 1980

    wrong_currency = client.post(f"/portfolio/{selected['id']}/assets", json={
        "asset_type": "CRYPTO", "symbol": "BTC", "name": "Bitcoin",
        "quantity": "1", "current_price": "1", "currency": "EUR",
    })
    assert wrong_currency.status_code == 422

    removed = client.delete(f"/portfolio/{selected['id']}/assets/{asset_id}")
    assert removed.status_code == 200
    assert removed.json()["portfolio"]["assets"]["bonds"] == []


def test_portfolio_api_discovers_and_live_prices_crypto(tmp_path, monkeypatch):
    class FakeCrypto:
        price = Decimal("60000")
        failed = False
        last = None

        def products(self, currency):
            return [{"id": "BTC-USD", "symbol": "BTC", "name": "Bitcoin",
                     "display_name": "BTC/USD", "quote_currency": currency}]

        def quote(self, product_id):
            if self.failed:
                return None
            self.last = CryptoQuote(
                product_id=product_id,
                price=self.price,
                asof=datetime(2026, 8, 30, 18, 45, tzinfo=timezone.utc),
            )
            return self.last

        def cached_quote(self, _product_id):
            return self.last

    original_connect = store.connect
    database = tmp_path / "api-live-crypto.db"
    provider = FakeCrypto()
    monkeypatch.setattr(api.store, "connect", lambda: original_connect(database))
    monkeypatch.setattr(api, "_crypto", provider)
    monkeypatch.setattr(api, "_portfolio_rows", lambda: ({"rows": []}, {}))
    client = TestClient(api.app)
    selected = client.get("/portfolio").json()["portfolio"]
    client.put(f"/portfolio/{selected['id']}/cash", json={"amount": 0})

    products = client.get("/crypto/products?currency=USD")
    assert products.status_code == 200
    assert products.json()["products"][0]["name"] == "Bitcoin"

    created = client.post(f"/portfolio/{selected['id']}/assets", json={
        "asset_type": "CRYPTO", "symbol": "BTC-USD", "name": "Bitcoin",
        "quantity": "0.25", "currency": "USD",
    })
    assert created.status_code == 200
    crypto = created.json()["portfolio"]["assets"]["crypto"][0]
    assert crypto["current_price"] == 60000
    assert crypto["market_value"] == 15000
    assert crypto["price_live"] is True
    assert crypto["price_source"] == "coinbase"

    provider.price = Decimal("62000")
    refreshed = client.get("/portfolio").json()
    assert refreshed["assets"]["crypto"][0]["market_value"] == 15500
    assert refreshed["summary"]["crypto_value"] == 15500

    provider.failed = True
    fallback = client.get("/portfolio").json()["assets"]["crypto"][0]
    assert fallback["current_price"] == 62000
    assert fallback["price_live"] is False
    assert fallback["quote_refresh_warning"]["kind"] == "CRYPTO_QUOTE_REFRESH_FAILED"

    invalid = client.post(f"/portfolio/{selected['id']}/assets", json={
        "asset_type": "CRYPTO", "symbol": "NOPE-USD", "name": "Nope",
        "quantity": "1", "currency": "USD",
    })
    assert invalid.status_code == 422

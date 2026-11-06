from datetime import datetime, timedelta, timezone

import pytest

from backend.services import b2b_voice as voice


@pytest.fixture(autouse=True)
def _clean_live_db():
    voice.init()
    conn = voice.get_conn()
    try:
        for table in (
            "voice_calls",
            "voice_campaign_skips",
            "voice_campaigns",
            "voice_segments",
            "call_attempts",
            "voice_suppressions",
            "dnc_checks",
            "prospect_companies",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()
    yield

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)


def _company(phone="+12125550199", name="Acme Plumbing"):
    voice.import_licenses_csv(
        "company_name,phone,city,state,trade,license_status\n"
        f"{name},{phone},New York,NY,plumbing,active\n"
    )
    conn = voice.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM prospect_companies WHERE phone=?", (phone,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def test_live_dashboard_mostra_ativa_e_resumo():
    company = _company()
    campaign = voice.create_campaign(
        name="live-test",
        city="New York",
        trade="plumbing",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"trade": "plumbing", "quota": 1}],
    )
    call = voice.create_voice_call(
        company, campaign_id=str(campaign["id"]), trade_code="plumbing"
    )
    voice.update_voice_call(
        call["id"],
        status="in_call",
        answered_at=(NOW - timedelta(seconds=12)).isoformat(),
    )
    live = voice.live_dashboard(int(campaign["id"]))
    assert live["campaign"]["id"] == int(campaign["id"])
    assert len(live["active_calls"]) == 1
    assert live["active_calls"][0]["company"] == "Acme Plumbing"
    assert live["active_calls"][0]["elapsed_seconds"] >= 10


def test_voice_liquidity_separa_exact_e_desconta_7d():
    company = _company()
    conn = voice.get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO voice_segments "
            "(city_slug, trade_slug, city, state, trade_code, trade_label, "
            "total, callable, blocked, showcase_mode, showcase_exact, "
            "showcase_city_total, page_path, built_at) "
            "VALUES ('new-york','plumbing','New York','NY','plumbing','Plumbing',"
            "10,10,0,'dedicated',50,100,'/en/new-york/plumbing',?)",
            (NOW.isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()
    campaign = voice.create_campaign(
        name="liq-test",
        city="New York",
        trade="plumbing",
        max_calls=1,
        quota_total=1,
        trade_plan=[{"trade": "plumbing", "quota": 1}],
    )
    voice.create_voice_call(
        company, campaign_id=str(campaign["id"]), trade_code="plumbing"
    )
    data = voice.voice_liquidity("New York", "plumbing")
    row = next(r for r in data["rows"] if r["trade"] == "plumbing")
    assert row["exact"] is True
    assert row["used_7d"] == 1
    assert row["available"] == 9
    assert data["exact_available"] == 9


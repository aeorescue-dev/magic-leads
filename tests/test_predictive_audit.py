"""Auditoria preditiva: links da campanha e dia operacional.

Guardas:
  * a URL de cada cidade x nicho x passo tem exatamente os tokens esperados
    (nenhum lote pode sair com `city`/`niche` errados ou link partido);
  * tokens "estranhos" sao codificados, nunca concatenados crus;
  * cada e-mail de campanha tem um unico link com `?city=&niche=&step=`;
  * o dia operacional atravessa a mudanca de hora (EDT -> EST) sem buraco.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from backend.services import outbound_templates as t
from backend.services.timeutil import day_key, day_start_utc, next_day_start_utc

UTC = timezone.utc
CITIES = ("NYC", "CHICAGO", "DALLAS", "BOSTON")
CAMPAIGN_PREFIX = "https://www.magicleads.app/en?"


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_url_de_cada_cidade_e_nicho_tem_os_tokens_certos():
    for city in CITIES:
        for niche in sorted(t.NICHES):
            for step in (1, 2):
                url = t.sequence_url(city, niche, step)
                assert url.startswith(CAMPAIGN_PREFIX)
                assert _query(url) == {
                    "city": [city],
                    "niche": [niche],
                    "step": [str(step)],
                }


def test_url_codifica_tokens_em_vez_de_os_partir():
    url = t.sequence_url("new york city", "roofing & siding", 1)
    query = _query(url)
    assert query["city"] == ["NEW YORK CITY"]
    assert query["niche"] == ["roofing & siding"]
    assert " " not in url
    assert "&siding" not in url


def _context(city: str = "DALLAS", niche: str = "roofing") -> dict[str, str]:
    ctx = t.build_context(
        {
            "owner_name": "Acme Roofing",
            "address": "B2B contact - info@acme.com",
            "owner_email": "info@acme.com",
        },
        city,
        niche,
        50,
        contact={"company_name": "Acme Roofing", "email": "info@acme.com"},
    )
    return ctx


def test_cada_variante_tem_um_unico_link_de_campanha_com_os_tokens_do_lote():
    ctx = _context()
    ctx["url"] = t.sequence_url("DALLAS", "roofing", 1)
    for variant in t.COPY_VARIANT_TEMPLATES:
        body = t.render_copy_variant(variant, ctx)["body"]
        assert body.count(CAMPAIGN_PREFIX) == 1, variant
        assert ctx["url"] in body, variant
        assert _query(ctx["url"])["step"] == ["1"]


def test_passo2_leva_o_link_da_oferta_com_step_2():
    ctx = _context()
    ctx["url"] = t.sequence_url("DALLAS", "roofing", 2)
    body = t.render_sequence_email("step2_offer", ctx)["body"]
    assert body.count(CAMPAIGN_PREFIX) == 1
    assert ctx["url"] in body
    query = _query(ctx["url"])
    assert query["city"] == ["DALLAS"]
    assert query["niche"] == ["roofing"]
    assert query["step"] == ["2"]


def test_dia_operacional_atravessa_a_mudanca_de_hora():
    # 2026-11-01 e' o dia em que os relogios recuam: o dia comeca em EDT...
    assert day_start_utc("2026-11-01") == "2026-11-01 04:00:00"
    # ...e o seguinte ja' comeca em EST (05:00 UTC).
    assert day_start_utc("2026-11-02") == "2026-11-02 05:00:00"
    assert day_key(datetime(2026, 11, 2, 4, 59, tzinfo=UTC)) == "2026-11-01"
    assert day_key(datetime(2026, 11, 2, 5, 1, tzinfo=UTC)) == "2026-11-02"
    assert (
        next_day_start_utc(datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
        == "2026-11-02 05:00:00"
    )

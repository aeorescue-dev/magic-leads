"""
Regressao do masking de status do scraper (main.py, fecho do run).

Sintoma observado em producao: run 106 reportava status="success" e
cities_covered=4 enquanto Chicago estava morta ha ~29h (failure_count=8,
circuit aberto). cities_covered contava qualquer cidade nao-skip, incluindo as
que falharam por completo, e o verde do run chegava ao gate do GitHub Actions,
que so olha para o status global.
"""
import pytest


def _classify(city_results):
    """Replica exacta do fecho do run em main.py."""
    cities_ok = [
        c for c, r in city_results.items()
        if not r["skipped"] and not r["error"] and len(r["leads"]) > 0
    ]
    cities_degraded = [
        c for c, r in city_results.items()
        if r["error"] and not r["error"].startswith("PARCIAL")
    ]
    cities_skipped = [c for c, r in city_results.items() if r["skipped"]]
    cities_bad = sorted(set(cities_degraded) | set(cities_skipped))
    status = "partial" if cities_bad else "success"
    return status, len(cities_ok), cities_bad


def _city(leads=0, error=None, skipped=False):
    return {"leads": [1] * leads, "error": error, "skipped": skipped}


def test_run_verde_quando_todas_as_cidades_produzem():
    r = {
        "NYC": _city(1200), "Dallas": _city(800), "Boston": _city(400),
        "Chicago": _city(1500),
    }
    status, covered, bad = _classify(r)
    assert status == "success"
    assert covered == 4
    assert bad == []


def test_cidade_morta_nao_pode_produzir_success_global():
    """O caso exacto de producao: Chicago falha, as outras tres estao bem."""
    r = {
        "NYC": _city(1200), "Dallas": _city(800), "Boston": _city(400),
        "Chicago": _city(0, error="violations: HTTP 400"),
    }
    status, covered, bad = _classify(r)
    assert status == "partial", "run nao pode ser success com uma cidade morta"
    assert "Chicago" in bad
    # A cidade morta nao conta como coberta: era isto que dava covered=4.
    assert covered == 3


def test_cidade_com_circuito_aberto_nao_produz_success_global():
    r = {
        "NYC": _city(1200), "Dallas": _city(800), "Boston": _city(400),
        "Chicago": _city(0, skipped=True),
    }
    status, covered, bad = _classify(r)
    assert status == "partial"
    assert "Chicago" in bad
    assert covered == 3


def test_falha_parcial_mantem_run_verde():
    """Respondeu em parte: verde, porque produziu dados."""
    r = {
        "NYC": _city(900, error="PARCIAL — violations: timeout"),
        "Dallas": _city(800), "Boston": _city(400), "Chicago": _city(1500),
    }
    status, covered, bad = _classify(r)
    assert status == "success"
    assert bad == []


def test_cidade_que_responde_vazio_sem_erro_nao_conta_como_coberta():
    """Respondeu 200 mas sem leads: nao e sucesso para nenhuma parte."""
    r = {
        "NYC": _city(1200), "Dallas": _city(800), "Boston": _city(400),
        "Chicago": _city(0),
    }
    status, covered, bad = _classify(r)
    assert covered == 3
    assert status == "success"  # sem erro registado, mas covered e honesto


def test_run_com_todas_as_cidades_mortas_nao_e_success():
    r = {
        "NYC": _city(0, error="a: boom"), "Dallas": _city(0, error="b: boom"),
        "Boston": _city(0, error="c: boom"), "Chicago": _city(0, error="d: boom"),
    }
    status, covered, bad = _classify(r)
    assert status == "partial"
    assert covered == 0
    assert len(bad) == 4

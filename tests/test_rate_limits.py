"""Regressão dos rate limits de autenticação e da confiança no XFF.

Fechado por auditoria de go-live. Duas falhas reais encontradas em produção:

1. **Rate limits totalmente mortos no Railway**: o uvicorn só confia em
   X-Forwarded-For vindo de 127.0.0.1 (default), por isso via o pool de proxies
   interno do edge (`100.64.0.x`, um IP diferente por ligação) como "cliente".
   A chave do slowapi (`get_remote_address`) nunca repetia → nenhum 429 dispara
   em produção, embora tudo funcionasse em local (127.0.0.1 constante).
   Correção: `--forwarded-allow-ips='*'` no startCommand/CMD (seguro: o edge do
   Railway faz strip+rebuild do XFF e só ele alcança o contentor).
2. **`forgot-password`, `reset-password` e `demo` sem qualquer limite** —
   bomba de emails podia esgotar a cota diária do Resend e blocar resets
   legítimos; tokens de reset e a sessão demo podiam ser martelados.

Cada teste abaixo trava uma destas regressões.
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(monkeypatch):
    from backend import config
    from backend import main as main_mod

    # NOTA: LEADS_DB_PATH é definido pelo conftest ANTES do import do backend —
    # fazer setenv aqui não teria efeito (settings já está cacheado).
    monkeypatch.setattr(config.settings, "ADMIN_SECRET", "segredo-de-teste", raising=False)
    monkeypatch.setattr(main_mod.settings, "ADMIN_SECRET", "segredo-de-teste", raising=False)
    return TestClient(main_mod.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def janela_de_limite_fresca():
    """Janela de rate limit limpa antes e depois de cada teste.

    O limiter é singleton em memória partilhado por toda a sessão; sem este
    fixture os testes deste ficheiro envenenariam os limites dos restantes
    (e vice-versa).
    """
    from backend.main import limiter

    limiter._storage.reset()
    yield
    limiter._storage.reset()


def test_uvicorn_confia_no_xff_do_railway():
    """Regressão da causa-raiz: sem --forwarded-allow-ips os rate limits por IP
    ficam mortos em produção (chave = pool 100.64.0.x rotativo)."""
    start_cmd = json.loads((REPO / "railway.json").read_text(encoding="utf-8"))
    assert "--forwarded-allow-ips" in start_cmd["deploy"]["startCommand"], (
        "railway.json perdeu --forwarded-allow-ips — rate limits voltam a "
        "morrer em produção"
    )
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "--forwarded-allow-ips" in dockerfile, (
        "Dockerfile perdeu --forwarded-allow-ips no CMD"
    )


def test_login_devolve_429_na_6a_tentativa(client):
    body = {"email": "nao.existe.teste@gmail.com", "password": "senha-incorreta-123"}
    codes = [client.post("/api/auth/login", json=body).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5, f"inesperado antes do limite: {codes}"
    assert codes[5] == 429, f"6a tentativa de login devia ser 429, veio {codes[5]}"


def test_esqueci_password_limita_apos_10(client, monkeypatch):
    """10/hour — impede bomba de emails que esgotaria a cota do Resend."""
    from backend import main as m

    async def _token(email, expires_hours=1):
        return "tok-teste"

    async def _send(email, token):
        return None

    monkeypatch.setattr(m.db_service, "create_password_reset_token", _token)
    monkeypatch.setattr(m.db_service, "send_password_reset_email", _send)

    payload = {"email": "nao.existe.teste@gmail.com"}
    codes = [client.post("/api/auth/forgot-password", json=payload).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10, f"antes do limite: {codes}"
    assert codes[10] == 429, "11a chamada a forgot-password devia ser 429"


def test_reset_password_limita_apos_10(client):
    """10/hour — dificulta martelar tokens de reset.

    Payload válido mas com senhas distintas → o handler responde 422 antes de
    tocar na BD; o limiter conta na mesma (corre antes do handler).
    """
    payload = {
        "token": "token-invalido",
        "new_password": "senha-valida-123",
        "confirm_password": "outra-senha-456",
    }
    codes = [client.post("/api/auth/reset-password", json=payload).status_code for _ in range(11)]
    assert codes[:10] == [422] * 10, f"antes do limite: {codes}"
    assert codes[10] == 429, "11a chamada a reset-password devia ser 429"


def test_demo_login_limita_apos_10(client, monkeypatch):
    """10/hour — a sessão demo não pode ser martelada por scripts.

    O handler é neutralizado (BD bloqueada) para não poluir a BD partilhada de
    testes; o limiter corre antes do handler, por isso o teste é válido.
    """
    from backend import main as m

    async def _bloqueado(*_args, **_kwargs):
        raise RuntimeError("BD bloqueada em teste")

    monkeypatch.setattr(m.db_service, "get_user_by_email", _bloqueado)

    codes = [client.post("/api/auth/demo").status_code for _ in range(11)]
    assert codes[:10] == [500] * 10, f"antes do limite: {codes}"
    assert codes[10] == 429, "11a chamada a demo devia ser 429"

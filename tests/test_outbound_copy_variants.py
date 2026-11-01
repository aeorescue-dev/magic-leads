"""A/B de TEXTO do passo 1: gate de volume, rotacao e atribuicao.

Regras guardadas aqui:
  * abaixo do limiar diario (dia NY) nao ha A/B — tudo sai em `control`;
  * com o gate aberto, as quatro variantes rodam 1:1:1:1;
  * o texto de cada variante mantem o enquadramento da landing, o link com
    cidade/nicho e a conformidade CAN-SPAM;
  * a variante fica gravada na mensagem e aparece em `outbound_metrics`.
"""

from __future__ import annotations

from backend.services import outbound_engine as engine_module
from backend.services import outbound_templates as t

FORBIDDEN = (
    "311",
    "permit",
    "violation",
    "socrata",
    "open data",
    "public record",
    "government",
    "agency",
    "department of",
    "service request",
    "inspection",
    "city database",
    "city records",
    "municipal",
)


def _context(niche: str = "general_contractors", city: str = "NYC"):
    ctx = t.build_context(
        {
            "owner_name": "Acme Builders",
            "address": "B2B contact - info@acme.com",
            "owner_email": "info@acme.com",
        },
        city,
        niche,
        50,
        contact={"company_name": "Acme Builders", "email": "info@acme.com"},
    )
    ctx["url"] = t.sequence_url(city, niche, step=1)
    return ctx


# ------------------------------------------------------------------ gate


def test_gate_fechado_mantem_todas_as_mensagens_no_controlo():
    assert [t.pick_copy_variant(i, False) for i in range(6)] == ["control"] * 6


def test_gate_aberto_roda_as_quatro_variantes_um_para_um():
    seq = [t.pick_copy_variant(i, True) for i in range(8)]
    assert seq == ["control", "five_crews", "owner_asked", "limited_spots"] * 2


def test_control_e_a_copy_atual_e_as_tres_variantes_sao_conhecidas():
    assert t.COPY_VARIANTS[0] == "control"
    assert set(t.COPY_VARIANTS) == {"control", *t.COPY_VARIANT_TEMPLATES}
    for variant, tpl in t.COPY_VARIANT_TEMPLATES.items():
        assert len(tpl["subject"]) <= t.SUBJECT_MAX, variant


# ------------------------------------------------------------------ copy


def test_variantes_renderizam_em_ingles_sem_placeholders():
    ctx = _context()
    for variant in t.COPY_VARIANT_TEMPLATES:
        mail = t.render_copy_variant(variant, ctx)
        assert "{" not in mail["subject"] and "}" not in mail["subject"]
        assert "{" not in mail["body"] and "}" not in mail["body"]
        assert mail["body"].startswith("Hi Acme Builders team,")
        assert "$120" in mail["body"]
        assert t.SENDER_POSTAL_ADDRESS in mail["body"]
        assert "Unsubscribe:" in mail["body"]
        assert 'reply "unsubscribe"' in mail["body"]
        assert ctx["url"] in mail["body"]
        assert "city=NYC" in mail["body"]
        assert "niche=general_contractors" in mail["body"]
        assert "step=1" in mail["body"]


def test_variantes_nao_expoem_a_origem_dos_dados():
    ctx = _context()
    for variant in t.COPY_VARIANT_TEMPLATES:
        mail = t.render_copy_variant(variant, ctx)
        haystack = (mail["subject"] + "\n" + mail["body"]).lower()
        for term in FORBIDDEN:
            assert term not in haystack, f"{variant} expoe origem: {term!r}"


def test_variantes_nao_prometem_telefone_universal():
    """A landing so' promete telefone "quando encontramos" — o copy tambem."""
    mail = t.render_copy_variant("owner_asked", _context())
    assert "phone number when we find it" in mail["body"]
    assert "the number to call." not in mail["body"]


def test_variantes_adaptam_cidade_e_nicho():
    mail = t.render_copy_variant(
        "limited_spots", _context(niche="roofing", city="DALLAS")
    )
    assert "in Dallas this week" in mail["body"]
    assert "roofing projects" in mail["body"]
    assert "city=DALLAS" in mail["body"]
    assert "niche=roofing" in mail["body"]
    assert len(mail["subject"]) <= t.SUBJECT_MAX


# ------------------------------------------------------------------ db


def _svc():
    return engine_module.db_service._service


def test_enqueue_persiste_a_variante_e_metrics_atribui():
    svc = _svc()
    email = "variante-ab@example.com"
    msg = svc.enqueue_outbound_message(
        batch_id=None,
        contact_id=None,
        city="NYC",
        to_email=email,
        subject="s",
        body_hash="h",
        copy_variant="owner_asked",
    )
    assert msg is not None
    assert msg["copy_variant"] == "owner_asked"
    svc.update_outbound_message(
        msg["id"], status="sent", sent_at="2999-01-01 12:00:00"
    )

    metrics = svc.outbound_metrics(30)
    row = next(
        (r for r in metrics["by_copy_variant"] if r["variant"] == "owner_asked"),
        None,
    )
    assert row is not None
    assert row["sent"] >= 1
    assert "reply_rate" in row and "positive_rate" in row

    gate = metrics["copy_variants"]
    assert gate["min_sends"] >= 1
    assert gate["enabled"] in (True, False)
    assert "control" in gate["arms"]
    assert isinstance(gate["active"], bool)


def test_metrics_trata_linhas_antigas_sem_variante_como_controlo():
    svc = _svc()
    msg = svc.enqueue_outbound_message(
        batch_id=None,
        contact_id=None,
        city="NYC",
        to_email="variante-legado@example.com",
        subject="s",
        body_hash="h",
    )
    assert msg is not None and msg["copy_variant"] is None
    svc.update_outbound_message(
        msg["id"], status="sent", sent_at="2999-01-02 12:00:00"
    )
    metrics = svc.outbound_metrics(30)
    rows = {r["variant"]: r for r in metrics["by_copy_variant"]}
    assert "control" in rows

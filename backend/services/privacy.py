"""Higiene de texto voltado ao utilizador (regra de ouro de propriedade intelectual).

Nenhum termo das nossas fontes ou da arquitetura de dados (311, Socrata, CKAN,
DOB, HPD, scraper, API, Open Data, dataset, BBL/BIN, ...) pode chegar a um ecra,
push, email ou notificacao in-app. A limpeza vive aqui, num unico sitio, para nao
depender de cada componente se lembrar dela.

Principios:
- **Remover, nao traduzir**: as descricoes chegam em ingles; substituir "DOB" por
  "servicos municipais" criaria frases hibridas. Apagar o token preserva o sentido
  ("Water/Wastewater Line Locate - 311" -> "Water/Wastewater Line Locate").
- **Word-boundary para siglas**: `API` nao pode estragar `CAPITAL`; `311` nao pode
  estragar `3110`.
- **Campos de identificacao da fonte** (`source`, `department`, `source_type`) nao
  sao limpos, sao **removidos/anonimizados** na resposta ao cliente. O admin
  continua a ver tudo (endpoints proprios, nao passam por aqui).
"""
from __future__ import annotations

import re
from typing import Optional

# Ordem importa pouco (cada padrao e' independente), mas os nomes longos vem
# primeiro para o `\b` nao partir siglas dentro deles.
_BANNED = [
    r"\b311\b",
    r"\bSocrata\b",
    r"\bCKAN\b",
    r"\bOpen\s*Data\b",
    r"\bdata\.cityofnewyork\.us\b",
    r"\bdata\.cityofchicago\.org\b",
    r"\bdata\.boston\.gov\b",
    r"\bDOB\b",
    r"\bHPD\b",
    r"\bDOHMH\b",
    r"\bDSNY\b",
    r"\bDEP\b",
    r"\bBBL\b",
    r"\bBIN\b",
    r"\bscraper\b",
    r"\bscrapers\b",
    r"\bdataset\b",
    r"\bdatasets\b",
    r"\bAPI\b",
    r"\bAPIs\b",
    r"\bETL\b",
    r"\bSQL\b",
    r"\bJSON\b",
]

_BANNED_RE = re.compile("|".join(_BANNED), re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SPACES_RE = re.compile(r"\s{2,}")
# Restos de pontuacao quando o termo estava no inicio/fim ("- 311", "311 -").
_ORPHAN_SEP_RE = re.compile(r"^[\s\-–—·,;:/]+|[\s\-–—·,;:/]+$")

# Campo do lead que identifica a fonte -> nao sai para o cliente.
_HIDDEN_FIELDS = ("source", "department")

# `source_type` interno -> token neutro exposto ao cliente.
_SOURCE_TYPE_MAP = {
    "311": "service_request",
    "socrata_311": "service_request",
    "permit": "permit",
    "dob_violation": "building_notice",
    "hpd_violation": "housing_notice",
    "tax_delinquency": "property_record",
    "import_b2b": "partner_record",
}

# Campos de texto livre que podem conter termos da fonte.
_TEXT_FIELDS = (
    "issue_description",
    "case_title",
    "subject",
    "reason",
    "type",
    "queue",
    "closure_reason",
    "descriptor",
    "resolution_description",
    "case_status",
)


def scrub(text: Optional[str]) -> Optional[str]:
    """Remove termos proibidos de um texto, preservando o resto do sentido."""
    if text is None:
        return None
    cleaned = _URL_RE.sub(" ", str(text))
    cleaned = _BANNED_RE.sub(" ", cleaned)
    cleaned = _SPACES_RE.sub(" ", cleaned)
    cleaned = _ORPHAN_SEP_RE.sub("", cleaned)
    return cleaned.strip() or None


def neutral_source_type(source_type: Optional[str]) -> Optional[str]:
    """Token sem termos tecnicos para `source_type`."""
    if not source_type:
        return source_type
    return _SOURCE_TYPE_MAP.get(str(source_type).strip().lower(), "record")


def sanitize_lead(lead: dict) -> dict:
    """Devolve uma copia do lead pronta para o cliente (sem marca da fonte)."""
    out = dict(lead)
    for field in _TEXT_FIELDS:
        if field in out:
            out[field] = scrub(out.get(field))
    for field in _HIDDEN_FIELDS:
        if field in out:
            out[field] = None
    # O numero de registo e' opaco, mas se por acaso trouxer um termo da fonte
    # (ex.: id sintetico de teste), limpa-se. IDs reais nao sao tocados.
    if "external_id" in out:
        out["external_id"] = scrub(out.get("external_id"))
    if "source_type" in out:
        out["source_type"] = neutral_source_type(out.get("source_type"))
    # `neighborhood`/`ward`/`precinct` sao geografia real, nao fonte: mantem-se.
    return out


def contains_banned(text: Optional[str]) -> bool:
    """Usado nos testes/auditoria: True se o texto ainda tiver um termo proibido."""
    if not text:
        return False
    return bool(_BANNED_RE.search(str(text))) or bool(_URL_RE.search(str(text)))

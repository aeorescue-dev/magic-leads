"""Descoberta de dominio e validacao de e-mail corporativo a custo zero.

Este modulo contem apenas logica pura + I/O *injetavel* (`Resolver`, `Fetcher`,
`SmtpProber`), para poder ser testado sem rede. A orquestracao com a base de
dados vive em `discovery_engine.py`.

Camadas:
  L1  diretorios abertos em lote (OpenStreetMap/Overpass) -> dominio/email
  L2  heuristica `slug do nome -> DNS A/MX -> fetch HTTP -> corroboracao`
  L3  permutacao de padroes (info@, contact@, firstname@, ...)
  L4  validacao MX + SMTP RCPT (custo US$ 0) com deteccao de catch-all;
      EmailListVerify apenas como fallback (ver `discovery_engine`).

Regra de ouro: um dominio so' e' aceite com corroboracao (telefone igual ao do
lead, ou nome no titulo + cidade/CEP na pagina). Sem isso, enviar marketing a um
terceiro e' o unico erro com consequencia legal real.
"""

from __future__ import annotations

import logging
import random
import re
import smtplib
import string
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from .lead_filter import (
    classify_owner_name,
    norm_key,
    norm_space,
    parse_person,
    significant_tokens,
    strip_accents,
)

logger = logging.getLogger(__name__)

# Dominios que nunca sao "o site da empresa": diretorios, redes sociais,
# portais publicos, registradores e paginas de parking.
BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "yelp.com", "bbb.org", "yellowpages.com", "mapquest.com", "facebook.com",
    "linkedin.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "angi.com", "angieslist.com", "houzz.com", "homeadvisor.com", "thumbtack.com",
    "porch.com", "buildzoom.com", "manta.com", "chamberofcommerce.com",
    "opencorporates.com", "bizapedia.com", "dnb.com", "zoominfo.com",
    "indeed.com", "glassdoor.com", "crunchbase.com", "bloomberg.com",
    "loopnet.com", "zillow.com", "trulia.com", "realtor.com", "redfin.com",
    "apartments.com", "streeteasy.com", "rentcafe.com",
    "wikipedia.org", "wikimedia.org", "amazon.com", "ebay.com",
    "tripadvisor.com", "foursquare.com", "nextdoor.com", "mapcarta.com",
    "google.com", "bing.com", "duckduckgo.com", "yahoo.com", "msn.com",
    "mojeek.com", "ecosia.org", "brave.com", "startpage.com",
    "nyc.gov", "ny.gov", "chicago.gov", "dallascityhall.com", "boston.gov",
    "mass.gov", "illinois.gov", "texas.gov", "usps.com", "usa.gov",
    "whitepages.com", "spokeo.com", "beenverified.com", "truepeoplesearch.com",
    "fastpeoplesearch.com", "radaris.com", "nuwber.com", "cylex.us.com",
    "superpages.com", "citysearch.com", "hotfrog.com", "brownbook.net",
    "alignable.com", "merchantcircle.com", "bark.com",
    "godaddy.com", "sedo.com", "afternic.com", "dan.com", "hugedomains.com",
    "squarespace.com", "weebly.com", "jimdo.com", "webflow.io", "business.site",
    "linktr.ee", "wix.com", "wordpress.com", "blogspot.com", "godaddysites.com",
    "expertise.com", "threebestrated.com", "birdeye.com", "yellowbot.com",
    "cityfos.com", "ezlocal.com", "local.com", "opendi.us", "tupalo.com",
})
BLOCKED_SUFFIXES: tuple[str, ...] = (".gov", ".mil", ".edu")

# Provedores de parking/hospedagem de dominio estacionado. Um dominio com MX
# destes provedores nao e' uma empresa a operar.
PARKING_MX: tuple[str, ...] = (
    "above.com", "bodis.com", "parkingcrew.net", "sedoparking.com",
    "hugedomains.com", "afternic.com", "dan.com", "parklogic.com",
    "domainmarket.com", "uniregistry.com", "smartname.com", "domainsponsor.com",
    "rookmedia.net", "trellian.com", "ztomy.com", "fabulous.com",
    "namefind.com", "parked.com", "sedo.com",
)
PARKING_NS: tuple[str, ...] = (
    "above.com", "bodis.com", "parkingcrew.net", "sedoparking.com",
    "hugedomains.com", "afternic.com", "dan.com", "parklogic.com",
    "smartname.com", "domainsponsor.com", "trellian.com", "ztomy.com",
    "fabulous.com", "namefind.com", "parked.com", "sedo.com",
)
PARKING_PAT = re.compile(
    r"(domain (is )?for sale|buy this domain|this domain is parked|parkingcrew|"
    r"sedoparking|hugedomains|afternic|this page is parked|"
    r"account has been suspended|site not found|coming soon)",
    re.I,
)

# Locais genericos testados primeiro (norma em pequenas empresas dos EUA).
GENERIC_LOCALS: tuple[str, ...] = (
    "info", "contact", "office", "sales", "admin", "service",
)

TLDS: tuple[str, ...] = ("com", "net", "nyc", "us", "org")
MAX_SLUGS = 18
MAX_EMAIL_CANDIDATES = 6

TWO_LEVEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "com.br", "com.mx", "co.nz", "com.au", "co.jp",
})

# Respostas SMTP que provam inexistencia da caixa.
_SMTP_REJECT_CODES = frozenset({550, 551, 552, 553, 501, 503, 554})
_SMTP_GREY_CODES = frozenset({421, 450, 451, 452})
_SMTP_ACCEPT_CODES = frozenset({250, 251})


# --------------------------------------------------------------- resultados

@dataclass
class Resolver:
    """I/O de DNS injetavel (facilita testes offline)."""

    a_record: Callable[[str], bool]
    mx_records: Callable[[str], list[tuple[int, str]]]
    ns_records: Callable[[str], list[str]]


@dataclass
class Fetcher:
    """I/O HTTP injetavel. Devolve {"status","url","html"} ou None."""

    fetch: Callable[[str, float], Optional[dict]]


@dataclass
class SmtpProber:
    """Envio de RCPT TO real contra o MX. Devolve {"error", "codes"}."""

    probe: Callable[[str, list[str]], dict]


@dataclass
class DomainResult:
    domain: str
    source: str
    evidence: dict = field(default_factory=dict)
    title: str = ""
    mx: list[tuple[int, str]] = field(default_factory=list)
    ns: list[str] = field(default_factory=list)
    tried: int = 0

    def as_dict(self) -> dict:
        return {
            "domain": self.domain,
            "source": self.source,
            "evidence": self.evidence,
            "title": self.title,
            "mx": [[p, h] for p, h in self.mx],
            "tried": self.tried,
        }


@dataclass
class ValidationResult:
    domain: str
    mx_host: str = ""
    catch_all: Optional[bool] = None
    accepted: list[str] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    smtp_error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "domain": self.domain,
            "mx_host": self.mx_host,
            "catch_all": self.catch_all,
            "accepted": self.accepted,
            "attempts": self.attempts,
            "smtp_error": self.smtp_error,
        }


# --------------------------------------------------------------- normalizacao

def registrable_domain(host: str) -> str:
    """Extrai o dominio registavel (`www.foo.com` -> `foo.com`).

    Aceita tambem uma URL completa (`https://www.foo.com/x`) por conveniencia.
    """
    raw = (host or "").strip()
    if "://" in raw or "/" in raw:
        raw = urlparse(raw).netloc or raw.split("/")[0]
    raw = raw.lower().split(":")[0].strip(".")
    if not raw or "." not in raw:
        return ""
    parts = raw.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_blocked_domain(domain: str) -> bool:
    d = (domain or "").lower().strip(".")
    if not d or "." not in d:
        return True
    if d.endswith(BLOCKED_SUFFIXES):
        return True
    return any(d == b or d.endswith("." + b) for b in BLOCKED_DOMAINS)


def is_parking(mx: Iterable[tuple[int, str]], ns: Iterable[str],
               title: str, text: str) -> bool:
    """Detecta dominios estacionados/para venda (nao sao empresas a operar)."""
    for _prio, host in mx:
        if any(p in host for p in PARKING_MX):
            return True
    for host in ns:
        if any(p in host for p in PARKING_NS):
            return True
    return bool(PARKING_PAT.search(f"{title} {text[:3000]}"))


# --------------------------------------------------------------- corroboracao

def corroborate(lead: dict, title: str, text: str) -> dict:
    """Mede se a pagina pertence de facto a empresa do lead."""
    toks = significant_tokens(lead.get("owner_name") or "")
    phone = re.sub(r"\D", "", str(lead.get("owner_phone") or ""))
    zip_ = re.sub(r"\D", "", str(lead.get("zip_code") or ""))
    city = (lead.get("city") or "").strip().lower()
    blob = f"{title} {text}"
    return {
        "name_score": round(_tokens_in(blob, toks), 3),
        "title_score": round(_tokens_in(title, toks), 3),
        "phone_match": bool(phone) and len(phone) >= 10
        and phone[-10:] in re.sub(r"\D", "", text),
        "zip_match": len(zip_) == 5 and zip_ in text,
        "city_match": bool(city) and city in blob.lower(),
    }


def _tokens_in(haystack: str, needles: Iterable[str]) -> float:
    hay = strip_accents(haystack or "").upper()
    ns = [n for n in needles if len(n) >= 3]
    if not ns:
        return 0.0
    return sum(1 for n in ns if n in hay) / len(ns)


def is_corroborated(evidence: dict) -> bool:
    """Gate de aceitacao: telefone OU (nome no titulo + localizacao)."""
    if not evidence:
        return False
    if evidence.get("phone_match"):
        return True
    if evidence.get("title_score", 0) >= 0.5 and (
        evidence.get("zip_match") or evidence.get("city_match")
    ):
        return True
    if evidence.get("name_score", 0) >= 0.6 and evidence.get("zip_match"):
        return True
    return False


# --------------------------------------------------------------- heuristicas

def slug_candidates(name: str, city: str = "") -> list[str]:
    """Slugs plausiveis para `nome-empresa.com`, do mais para o menos provavel."""
    toks = significant_tokens(name)
    if not toks:
        return []
    out: list[str] = []

    def add(base: str) -> None:
        base = re.sub(r"[^a-z0-9-]", "", (base or "").lower())
        if 3 <= len(base) <= 63 and base not in out:
            out.append(base)

    joined = "".join(toks)
    add(joined)
    if len(toks) >= 2:
        add("-".join(toks))
        add("".join(toks[:2]))
        add("".join(toks[:3]))
        add("-".join(toks[:2]))
    # Nomes como "SCIAME CONSTRUCTION" moram em `sciame.com`.
    if len(toks[0]) >= 5:
        add(toks[0])
    if len(toks) >= 4:
        add("".join(toks[:4]))
    city_tok = re.sub(r"[^A-Za-z]", "", city or "").lower()
    if city_tok:
        add(f"{joined}{city_tok}")
        add(f"{'-'.join(toks)}-{city_tok}")
    return out[:MAX_SLUGS]


def email_patterns(owner_name: str, name_class: str) -> list[str]:
    """Permutacoes de e-mail por ordem de probabilidade."""
    pats: list[str] = list(GENERIC_LOCALS)
    if name_class == "person":
        first, last = parse_person(owner_name or "")
        f = re.sub(r"[^a-z]", "", first.lower())
        l = re.sub(r"[^a-z]", "", last.lower())  # noqa: E741
        if f and l:
            pats.extend([f"{f}.{l}", f"{f}{l}", f"{f[0]}{l}", f"{f}_{l}"])
        elif f:
            pats.append(f)
    seen: set[str] = set()
    out: list[str] = []
    for p in pats:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


# --------------------------------------------------------------- SMTP real

def _default_a_record(domain: str) -> bool:
    import dns.resolver

    try:
        return len(dns.resolver.resolve(domain, "A", lifetime=3.0)) > 0
    except Exception:
        return False


def _default_mx_records(domain: str) -> list[tuple[int, str]]:
    import dns.resolver

    try:
        ans = dns.resolver.resolve(domain, "MX", lifetime=4.0)
        return sorted(
            (int(r.preference), str(r.exchange).rstrip(".")) for r in ans
        )
    except Exception:
        return []


def _default_ns_records(domain: str) -> list[str]:
    import dns.resolver

    try:
        ans = dns.resolver.resolve(domain, "NS", lifetime=4.0)
        return [str(r).rstrip(".").lower() for r in ans]
    except Exception:
        return []


def default_resolver() -> Resolver:
    return Resolver(_default_a_record, _default_mx_records, _default_ns_records)


def default_fetch(url: str, timeout: float = 7.0, max_bytes: int = 300_000) -> Optional[dict]:
    """GET tolerante a falhas com leitura limitada (nao descarrega sites inteiros)."""
    import requests

    if timeout <= 0.5:
        return None
    try:
        r = requests.get(
            url,
            timeout=(min(4.0, timeout), timeout),
            headers={
                "User-Agent": "MagicLeadsBot/1.0 (+https://magicleads.app/bot)",
                "Accept-Language": "en-US,en;q=0.9",
            },
            allow_redirects=True,
            stream=True,
        )
        chunks, total = [], 0
        for chunk in r.iter_content(16384):
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        return {"status": r.status_code, "url": str(r.url), "html": b"".join(chunks)}
    except Exception:
        return None


def probe_rcpt(mx_host: str, recipients: list[str],
               sender: str = "postmaster@magicleads.app",
               timeout: float = 10.0) -> dict:
    """Faz RCPT TO real contra o MX. Nao envia mensagem (sem DATA)."""
    codes = {r: "unknown" for r in recipients}
    smtp = None
    try:
        smtp = smtplib.SMTP(timeout=timeout)
        smtp.connect(mx_host, 25)
        smtp.ehlo_or_helo_if_needed()
        code, _ = smtp.mail(sender)
        if code != 250:
            return {"error": f"MAILFROM_{code}", "codes": codes}
        for r in recipients:
            try:
                code, _ = smtp.rcpt(r)
            except Exception:
                break
            if code in _SMTP_ACCEPT_CODES:
                codes[r] = "accepted"
            elif code in _SMTP_REJECT_CODES:
                codes[r] = "rejected"
            elif code in _SMTP_GREY_CODES:
                codes[r] = "greylisted"
                break
            else:
                codes[r] = "unknown"
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__, "codes": codes}
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass
    return {"error": None, "codes": codes}


def default_prober() -> SmtpProber:
    return SmtpProber(probe_rcpt)


def extract_text(html: bytes) -> tuple[str, str]:
    """Devolve (title, texto visivel) de uma pagina HTML."""
    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return "", ""
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return title, soup.get_text(" ", strip=True)[:60_000]


# --------------------------------------------------------------- servico

class CompanyDiscovery:
    """Executa L2 (heuristica) e L4 (validacao) para um lead."""

    def __init__(
        self,
        resolver: Optional[Resolver] = None,
        fetcher: Optional[Fetcher] = None,
        prober: Optional[SmtpProber] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._resolver = resolver or default_resolver()
        self._fetcher = fetcher or Fetcher(default_fetch)
        self._prober = prober or default_prober()
        self._clock = clock

    # -------------------------------------------------------- dominio
    def heuristic_domain(self, lead: dict, deadline: float) -> Optional[DomainResult]:
        slugs = slug_candidates(lead.get("owner_name") or "", lead.get("city") or "")
        tried = 0
        for slug in slugs:
            for tld in TLDS:
                if self._clock() > deadline:
                    return None
                fqdn = f"{slug}.{tld}"
                tried += 1
                if not self._resolver.a_record(fqdn):
                    continue
                mx = self._resolver.mx_records(fqdn)
                if not mx:
                    continue
                for scheme in ("https", "http"):
                    remaining = min(7.0, max(1.0, deadline - self._clock()))
                    page = self._fetcher.fetch(f"{scheme}://{fqdn}/", remaining)
                    if not page or page.get("status", 0) >= 400:
                        continue
                    title, text = extract_text(page.get("html") or b"")
                    ns = self._resolver.ns_records(fqdn)
                    if is_parking(mx, ns, title, text):
                        break
                    evidence = corroborate(lead, title, text)
                    if is_corroborated(evidence):
                        return DomainResult(
                            domain=fqdn, source="heuristic", evidence=evidence,
                            title=title[:160], mx=mx, ns=ns, tried=tried,
                        )
                    break
        return None

    def domain_from_website(self, website: str, lead: dict) -> Optional[DomainResult]:
        """Converte um `website` de diretorio aberto no dominio da empresa."""
        host = registrable_domain(urlparse(website or "").netloc)
        if not host or is_blocked_domain(host):
            return None
        mx = self._resolver.mx_records(host)
        if not mx:
            return None
        return DomainResult(
            domain=host,
            source="open_directory",
            evidence={"directory_website": website},
            title=norm_space(lead.get("owner_name") or "")[:160],
            mx=mx,
        )

    # -------------------------------------------------------- e-mail
    def validate_domain(
        self,
        domain: str,
        lead: dict,
        mx: Optional[list[tuple[int, str]]] = None,
        max_candidates: int = MAX_EMAIL_CANDIDATES,
    ) -> ValidationResult:
        mx = mx or self._resolver.mx_records(domain)
        if not mx:
            return ValidationResult(domain=domain, smtp_error="no_mx")
        mx_host = mx[0][1]
        result = ValidationResult(domain=domain, mx_host=mx_host)

        # Prova de catch-all: uma caixa aleatoria que existe e' sinal de
        # dominio permissivo. Nesses casos o SMTP nao prova nada.
        random_local = "zz" + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=12)
        )
        probe_local = f"{random_local}@{domain}"
        probe = self._prober.probe(mx_host, [probe_local])
        if probe.get("error") is None:
            result.catch_all = probe["codes"].get(probe_local) == "accepted"
        if result.catch_all:
            for local in email_patterns(
                lead.get("owner_name") or "",
                classify_owner_name(lead.get("owner_name") or ""),
            )[:max_candidates]:
                result.attempts.append(
                    {"email": f"{local}@{domain}", "result": "catch_all_skip"}
                )
            return result

        cls = classify_owner_name(lead.get("owner_name") or "")
        locals_ = email_patterns(lead.get("owner_name") or "", cls)[:max_candidates]
        batch = [f"{lp}@{domain}" for lp in locals_]
        if not batch:
            return result
        res = self._prober.probe(mx_host, batch)
        result.smtp_error = res.get("error")
        for email in batch:
            outcome = (res.get("codes") or {}).get(email, "unknown")
            result.attempts.append({"email": email, "result": outcome})
            if outcome == "accepted":
                result.accepted.append(email)
                break
        return result

    def discover(self, lead: dict, timeout: float = 30.0) -> dict:
        """Pipeline L2+L4 para um lead. Devolve dict pronto a persistir."""
        started = self._clock()
        deadline = started + max(1.0, timeout)
        out: dict = {
            "domain": None, "domain_source": None, "evidence": {},
            "validation": None, "elapsed_s": 0.0,
        }
        found = self.heuristic_domain(lead, deadline)
        if found:
            out["domain"] = found.domain
            out["domain_source"] = found.source
            out["evidence"] = found.evidence
            validation = self.validate_domain(found.domain, lead, found.mx)
            out["validation"] = validation.as_dict()
        out["elapsed_s"] = round(self._clock() - started, 2)
        return out


def merge_osm_index(elements: Iterable[dict]) -> dict[str, dict]:
    """Constroi indice `chave_normalizada -> empresa` a partir do Overpass."""
    idx: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name") or ""
        if not name:
            continue
        key = norm_key(name)
        if not key:
            continue
        idx[key] = {
            "name": name,
            "website": tags.get("website") or tags.get("contact:website") or tags.get("url") or "",
            "email": tags.get("email") or tags.get("contact:email") or "",
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "kind": tags.get("craft") or tags.get("office") or tags.get("shop") or "poi",
            "lat": el.get("lat") or (el.get("center") or {}).get("lat"),
            "lon": el.get("lon") or (el.get("center") or {}).get("lon"),
        }
    return idx


def match_osm(index: dict[str, dict], owner_name: str) -> Optional[dict]:
    """Procura o nome no indice (exato e depois por tokens)."""
    key = norm_key(owner_name)
    if not key or not index:
        return None
    hit = index.get(key)
    if hit:
        return {**hit, "match": "exact"}
    toks = [t for t in key.split(" ") if len(t) >= 4]
    if not toks:
        return None
    best: Optional[tuple[float, dict]] = None
    for candidate_key, value in index.items():
        cand_toks = candidate_key.split(" ")
        common = len(set(toks) & set(cand_toks))
        if common >= 2 and common / max(len(toks), 1) >= 0.66:
            score = common / max(len(toks), len(cand_toks))
            if not best or score > best[0]:
                best = (score, value)
    if best and best[0] >= 0.66:
        return {**best[1], "match": f"fuzzy:{best[0]:.2f}"}
    return None

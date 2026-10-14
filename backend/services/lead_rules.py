"""Regras de dominio de um lead (Regra A e qualidade de endereco).

Fonte unica de verdade. Estas funcoes determinam se um lead e corporativo,
se o endereco e resolvivel e se a reserva consome credito. O backend usa-as na
reserva e na serializacao; o frontend consome o resultado ja calculado pelo
backend, em vez de reimplementar a regra em TypeScript. Divergencia entre as
duas linguagens passa a ser estruturalmente impossivel.

REGRA DE NEGOCIO (inviolavel)
-----------------------------
Entrega e cobranca sao dissociadas:

  * O lead e SEMPRE entregue e mostrado ao utilizador, mesmo incompleto,
    para que possa usar nome + local em carta ou visita presencial.
  * O credito so e debitado, e a cota diaria so e consumida, em sucesso
    TOTAL de dados (owner_name + owner_phone).
  * Leads corporativos e incompletos sao sempre de graca.

Por isso `charges_credit` significa "cobramos", nunca "entregamos".

Separacao Privado vs Institucional/Governamental:
  * Entidades publicas (AUTHORITY, DEPARTMENT, BOARD, EDUCATION, HOUSING,
    PARKS, COMMISSION, AGENCY...) nunca tem telefone de pessoa para vender.
    Uma consulta paga contra "NYC HOUSING AUTHORITY" devolve "No results" e
    custa $0.45. `is_institutional_name` deteta-as com antecedencia para o
    backend saltar a chamada paga (billed=0) e ainda entregar o lead com o
    nome + morada recolhidos pelas fontes gratuitas (carta ou visita).
"""

import re
from typing import Any, Mapping, Optional

# Avoid circular import: is_corporate_name lives in searchbug but also needed here.
try:
    from .searchbug import is_corporate_name  # type: ignore
except Exception:
    def is_corporate_name(name: Optional[str]) -> bool:
        if not name:
            return False
        upper = str(name).upper()
        for token in re.findall(r"[A-Z0-9]+", upper):
            if token in {
                "LLC", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY",
                "LTD", "LIMITED", "LP", "LLP", "PLLC", "PC", "PA", "TRUST", "HOLDING",
                "HOLDINGS", "REALTY", "PROPERTY", "PROPERTIES", "ASSOC", "ASSOCIATES",
                "ASSOCIATION", "PARTNERS", "PARTNERSHIP", "ENTERPRISE", "ENTERPRISES",
                "BANK", "FINANCIAL", "MGMT", "MANAGEMENT", "SERVICES", "SERVICE",
                "SOLUTIONS", "DEVELOPMENT", "INVESTMENTS", "CAPITAL", "CONSTRUCTION",
                "MAINTENANCE", "ESTATE", "ESTATES", "FUND", "FUNDING", "GROUP",
            }:
                return True
        compact = re.sub(r"[^A-Z]", "", upper)
        for suffix in ("LLC", "INC", "CORP", "LTD", "LP", "LLP", "PLLC", "PC", "PA"):
            if len(suffix) > 2 and compact.endswith(suffix):
                return True
        return False

# Nomes de campo usados nos logs e no payload de entrega incompleta.
MISSING_OWNER_NAME = "owner_name"
MISSING_CONTACT = "owner_phone_or_mailing_address"


def _present(value: Any) -> bool:
    """Campo preenchido e campo com conteudo. "  " nao e um nome de proprietario.

    Aplicado a todos os lados da Regra A pela mesma razao: se `is_corporate`
    ignorasse um owner_name de apenas espacos mas `missing_critical_fields` nao,
    esse lead seria vendido como gratuito e nao pagaria nada.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def address_is_resolvable(address: Optional[str]) -> bool:
    """Um endereco so com o numero ("9630") nunca vai resolver para um dono.

    parse_address exige numero E rua, logo estes leads nao tem enriquecimento
    possivel. Recusar aqui evita pagar por uma consulta garantidamente inutil.
    """
    if not address:
        return False
    parts = str(address).split(",")[0].strip()
    return len(parts.split()) >= 2


US_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")


def strip_city_state(
    address: Optional[str],
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> str:
    """Remove os segmentos finais que ja existem nas colunas city/state/zip.

    So remove segmentos INTEIROS que casem com a cidade/estado/zip, e nunca mais
    do que um segmento de cada. Nao faz stripping parcial nem por palavras
    soltas: "EAST NEW YORK AVENUE" tem de sobreviver intacto, mesmo quando a
    cidade e "New York" / "NYC".

    Alem dos valores exactos das colunas, reconhece o FORMATO do segmento: um
    ZIP dos EUA (12345 / 12345-6789) e removido mesmo quando `zip_code` esta
    vazio, e um codigo de 2 letras e removido quando casa com o `state` da linha.

    Funcao partilhada com o script de migracao (que a importa) para que a regra
    que limpa a base e a que limpa os dados novos nao divirjam.
    """
    parts = [p.strip() for p in str(address or "").split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return ""

    def up(v: Any) -> str:
        return str(v or "").strip().upper()

    city_u, state_u, zip_u = up(city), up(state), up(zip_code)

    wanted: set[str] = {v for v in (city_u, state_u, zip_u) if v}
    # "New York" -> "NEW YORK"; e o inverso, state="Texas" cobre o segmento "TX".
    if city_u:
        wanted.add(city_u.split()[0])
    if state_u:
        wanted.add(US_STATE_ABBR.get(state_u.lower(), state_u))

    def is_removable(segment: str) -> bool:
        if segment.upper() in wanted:
            return True
        if _ZIP_RE.match(segment):
            return True
        # "TX 75218" / "NY 11210" -> remove o estado e o zip a mesma.
        bits = segment.upper().split()
        if len(bits) == 2 and bits[0] in wanted and _ZIP_RE.match(bits[1]):
            return True
        return False

    while len(parts) > 1 and is_removable(parts[-1]):
        parts.pop()

    return ", ".join(parts)


def normalize_street(
    street: Optional[str],
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
) -> str:
    """Limpa a parte de rua de um endereco vindo de datasets abertos.

    Os datasets traem a mesma rua com espacos duplicados, virgulas a mais e
    caixa inconsistente ("  22  FRONT stagg  street, "). `parse_address` e
    `address_is_resolvable` so precisam de "numero + rua" legivel, portanto
    normalizar aqui evita que o resto do pipeline tenha de lidar com lixo.
    Nao inventa conteudo: se nao houver texto, devolve string vazia.

    city/state/zip sao OPCIONAIS e tem de ser passados quando a fonte sabe
    deles. Sem isso o dataset de Boston, cuja `full_address` vem como
    "257-259 Cambridge St  Allston  MA  02134, Boston, MA", gravava o sufixo
    ", Boston, MA" dentro de `address`; e como a coluna `city` voltava a ser
    juntada no frontend, o utilizador via "..., BOSTON, MA, BOSTON, MA".
    `address` guarda SO a rua: cidade/estado/zip vivem em colunas proprias.
    """
    if not street:
        return ""
    cleaned = re.sub(r"\s+", " ", str(street)).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    cleaned = re.sub(r"(?:,\s*)+$", "", cleaned).strip()
    cleaned = re.sub(r"^(?:,\s*)+", "", cleaned).strip()
    cleaned = cleaned.upper()
    # Só com city/state/zip é que se sabe o que é sufixo; sem eles o
    # endereço fica como veio, para não inventar nem perder rua.
    if city or state or zip_code:
        cleaned = strip_city_state(cleaned, city, state, zip_code)
    return cleaned


def is_corporate(lead: Mapping[str, Any]) -> bool:
    """Lead corporativo = tem owner_name + mailing_address, mas SEM owner_phone.

    owner_name e obrigatorio por definicao: sem ele o lead nao e corporativo.
    Exigir o mesmo campo nos dois sitios impede que a UI prometa "0 creditos"
    para algo que nem sequer tem nome de proprietario.
    """
    return bool(
        _present(lead.get("owner_name"))
        and not _present(lead.get("owner_phone"))
        and _present(lead.get("mailing_address"))
    )


def is_complete_delivery(lead: Mapping[str, Any]) -> bool:
    """Entrega com sucesso TOTAL de dados: owner_name E owner_phone.

    E o unico perfil que justifica debito de credito e consumo de cota.
    """
    return bool(_present(lead.get("owner_name")) and _present(lead.get("owner_phone")))


def missing_critical_fields(lead: Mapping[str, Any]) -> list[str]:
    """Campos em falta para o lead contar como entrega completa.

    Perfis de reserva (os tres sao entregues):
      1) Lead padrao      -> owner_name + owner_phone               -> debita credito
      2) Lead corporativo -> owner_name + mailing_address, sem phone -> 0 creditos
      3) Lead incompleto  -> sem owner_phone e sem mailing_address   -> 0 creditos

    A partir deste valor ja nao se decide SE o lead e entregue (e sempre), mas
    SIM o aviso a mostrar e se ha cobranca.
    """
    missing = []
    if not _present(lead.get("owner_name")):
        missing.append(MISSING_OWNER_NAME)
    if not _present(lead.get("owner_phone")) and not _present(lead.get("mailing_address")):
        missing.append(MISSING_CONTACT)
    return missing


def is_incomplete_delivery(lead: Mapping[str, Any]) -> bool:
    """Lead entregue sem sucesso total de dados, logo sem debito e sem cota.

    Nao e corporativo (falta-lhe a morada) e nao e completo (falta-lhe o
    telefone). A UI usa este sinal para mostrar um aviso discreto em vez de
    esconder a oportunidade.
    """
    return bool(missing_critical_fields(lead))


def is_unresolvable(lead: Mapping[str, Any]) -> bool:
    """Lead sem qualquer dado de contacto E com um endereco que nunca resolve.

    NAO bloqueia a entrega: o lead e entregue como qualquer outro incompleto,
    sem debito e sem consumir cota. O sinal existe para a UI mostrar o aviso
    certo ("dados protegidos") em vez do aviso generico de telefone em falta.
    """
    return bool(
        not _present(lead.get("owner_name"))
        and not _present(lead.get("owner_phone"))
        and not _present(lead.get("mailing_address"))
        and not address_is_resolvable(lead.get("address"))
    )


def charges_credit(lead: Mapping[str, Any]) -> bool:
    """Unico ponto de decisao sobre debito de credito na reserva.

    REGRA INVIOLAVEL: so se debita e so se consome cota em sucesso TOTAL de
    dados (owner_name + owner_phone). Todo o resto e entregue de graca:

      - corporativo (nome + morada, sem telefone) -> 0 creditos, 0 cota
      - incompleto  (nome, sem telefone nem morada) -> 0 creditos, 0 cota

    Entrega e cobranca sao coisas separadas: o lead e SEMPRE entregue ao
    utilizador (para carta ou visita); o credito so e cobrado quando ha
    telefone verificado para cobrar.
    """
    return is_complete_delivery(lead)


# ---------- Deteção de entidades governamentais/institucionais ----------
# Proprietários que são entidades públicas (agências, autarquias, escolas,
# universidades) NÃO têm telefone de pessoa para vender: uma consulta paga à
# Searchbug contra "NYC HOUSING AUTHORITY" devolve "No results" e custa $0.45.
# Detetá-los com antecedência permite entregar o lead (nome + morada das fontes
# gratuitas) sem gastar dinheiro nem créditos. A regra é deliberadamente
# generosa (enviesa para "institucional"): um falso positivo custa $0 (a chamada
# paga é saltada); um falso negativo custa $0.45 numa consulta que, na prática,
# não tem telefone para devolver.

_INSTITUTIONAL_PREFIXES = (
    "CITY OF", "COUNTY OF", "STATE OF", "TOWN OF", "BOROUGH OF", "VILLAGE OF",
    "UNITED STATES", "U.S. GOVERNMENT", "US GOVERNMENT", "GOVERNMENT OF",
    "NYC", "NEW YORK CITY", "NYCHA", "NYC HOUSING AUTHORITY",
    "PORT AUTHORITY", "TRANSIT AUTHORITY", "HOUSING AUTHORITY", "BOARD OF",
    "BOARD OF EDUCATION", "DEPARTMENT OF", "DEPT OF", "PUBLIC SCHOOL",
    "SCHOOL DISTRICT", "COMMUNITY BOARD", "DISTRICT OF COLUMBIA",
)

_INSTITUTIONAL_STRONG_TOKENS = frozenset({
    "AUTHORITY", "AGENCY", "AGENCIES", "GOVERNMENT", "GOVERNMENTAL",
    "MUNICIPAL", "MUNICIPALITY", "COMMISSION", "FEDERAL", "LEGISLATURE",
    "JUDICIARY", "DEPARTMENT", "DEPT", "BOROUGH", "COUNTY", "REGISTRY",
    "SCHOOL", "SCHOOLS", "UNIVERSITY", "UNIV", "COLLEGE", "EDUCATION",
    "HOUSING", "LIBRARY", "POLICE", "SANITATION", "TRANSIT",
})

# Palavras que também são apelidos comuns (PARKS, BOARD, FIRE): só contam em
# posição NÃO-final, para "JOHN PARKS" não ser tratado como institucional.
_INSTITUTIONAL_MEDIUM_TOKENS = frozenset({
    "BOARD", "PARKS", "FIRE",
})


def is_institutional_name(name: Optional[str]) -> bool:
    """True se `name` denota uma entidade pública/governamental/institucional.

    Três critérios, qualquer um casa:
      1) o nome COMEÇA por um prefixo público ("CITY OF", "NYC", "BOARD OF"...);
      2) contém um token FORTE de entidade pública como palavra inteira
         ("AUTHORITY", "AGENCY", "COMMISSION", "DEPARTMENT"...);
      3) contém um token de instituição (EDUCATION/BOARD/PARKS/HOUSING/...) em
         posição NÃO-final — evita falsos positivos de apelidos reais:
         "JOHN PARKS" não é institucional, mas "NYC PARKS AND RECREATION" é.

    A regra é generosa de propósito (ver discussão no fim do módulo): erros
    para o lado institucional custam $0; erros para o lado privado custam
    $0.45 de uma consulta que quase nunca tem telefone para devolver.
    """
    if not name:
        return False
    upper = re.sub(r"\s+", " ", str(name)).upper().strip(" .,-")
    if not upper:
        return False

    # 1) Prefixo público.
    if upper.startswith(_INSTITUTIONAL_PREFIXES):
        return True

    tokens = re.findall(r"[A-Z0-9]+", upper)

    # 2) Token forte de entidade pública em qualquer posição.
    for token in tokens:
        if token in _INSTITUTIONAL_STRONG_TOKENS:
            return True

    # 3) Token de instituição apenas em posição não-final.
    if len(tokens) >= 2 and tokens[-1] not in _INSTITUTIONAL_MEDIUM_TOKENS:
        for token in tokens[:-1]:
            if token in _INSTITUTIONAL_MEDIUM_TOKENS:
                return True

    return False


# Tri-estado para tipo de proprietário
OWNER_CLASS_UNKNOWN = "unknown"
OWNER_CLASS_INSTITUTIONAL = "institutional"
OWNER_CLASS_PRIVATE = "private"


def get_owner_class(name: Optional[str]) -> str:
    if not _present(name):
        return OWNER_CLASS_UNKNOWN
    if is_institutional_name(name):
        return OWNER_CLASS_INSTITUTIONAL
    return OWNER_CLASS_PRIVATE


def get_owner_kind(name: Optional[str]) -> str:
    if not _present(name):
        return "unknown"
    if is_corporate_name(name):
        return "company"
    if is_institutional_name(name):
        return "company"
    return "person"


def institutional_owner_name_where(alias: str = "") -> str:
    """Expressão SQL equivalente a `is_institutional_name`, para contagens.

    Vive nesta unidade para não divergir da regra Python: ambas usam os mesmos
    prefixos/tokens. A versão SQL usa LIKE por substring (aproximação da regra
    Python) — suficiente para COUNT(*) agregado; a classificação por-lead usa
    sempre a função Python.
    """
    prefix = f"{alias}." if alias else ""
    col = f"UPPER(COALESCE({prefix}owner_name, ''))"
    prefixes = " OR ".join(
        f"{col} LIKE '{p}%'" for p in _INSTITUTIONAL_PREFIXES
    )
    strong = " OR ".join(
        f"{col} LIKE '%{t}%'" for t in _INSTITUTIONAL_STRONG_TOKENS
    )
    return f"(({prefixes}) OR ({strong}))"


def classify(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Avalia um lead uma vez e devolve o veredito consumido pelo frontend."""
    name = lead.get("owner_name")
    return {
        "corporate": is_corporate(lead),
        "institutional": is_institutional_name(name),
        "address_resolvable": address_is_resolvable(lead.get("address")),
        "unresolvable": is_unresolvable(lead),
        "complete_delivery": is_complete_delivery(lead),
        "incomplete_delivery": is_incomplete_delivery(lead),
        "charged": charges_credit(lead),
        "owner_class": get_owner_class(name),
        "owner_kind": get_owner_kind(name),
    }

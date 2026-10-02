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
"""

import re
from typing import Any, Mapping, Optional

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


def normalize_street(street: Optional[str]) -> str:
    """Limpa a parte de rua de um endereco vindo de datasets abertos.

    Os datasets traem a mesma rua com espacos duplicados, virgulas a mais e
    caixa inconsistente ("  22  FRONT stagg  street, "). `parse_address` e
    `address_is_resolvable` so precisam de "numero + rua" legivel, portanto
    normalizar aqui evita que o resto do pipeline tenha de lidar com lixo.
    Nao inventa conteudo: se nao houver texto, devolve string vazia.
    """
    if not street:
        return ""
    cleaned = re.sub(r"\s+", " ", str(street)).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    cleaned = re.sub(r"(?:,\s*)+$", "", cleaned).strip()
    cleaned = re.sub(r"^(?:,\s*)+", "", cleaned).strip()
    return cleaned.upper()


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


def classify(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Avalia um lead uma vez e devolve o veredito consumido pelo frontend."""
    return {
        "corporate": is_corporate(lead),
        "address_resolvable": address_is_resolvable(lead.get("address")),
        "unresolvable": is_unresolvable(lead),
        "complete_delivery": is_complete_delivery(lead),
        "incomplete_delivery": is_incomplete_delivery(lead),
        "charged": charges_credit(lead),
    }

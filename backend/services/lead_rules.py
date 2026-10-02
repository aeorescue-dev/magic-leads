"""Regras de dominio de um lead (Regra A e qualidade de endereco).

Fonte unica de verdade. Estas funcoes determinam se um lead e corporativo,
se o endereco e resolvivel e o que falta para poder revelar dados do
proprietario. O backend usa-as na reserva e na serializacao; o frontend
consome o resultado ja calculado pelo backend, em vez de reimplementar a
regra em TypeScript. Divergencia entre as duas linguagens passa a ser
estruturalmente impossivel.
"""

from typing import Any, Mapping, Optional

# Nomes de campo usados nos logs e no payload 422 de "incomplete_lead_data".
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


def is_corporate(lead: Mapping[str, Any]) -> bool:
    """Lead corporativo = tem owner_name + mailing_address, mas SEM owner_phone.

    owner_name e obrigatorio por definicao: sem ele o lead nao e corporativo, e
    apenas incompleto, e a Regra A devolve 422. Exigir o mesmo campo nos dois
    sitios impede que a UI prometa "0 creditos" para algo que o backend vai
    rejeitar.
    """
    return bool(
        _present(lead.get("owner_name"))
        and not _present(lead.get("owner_phone"))
        and _present(lead.get("mailing_address"))
    )


def missing_critical_fields(lead: Mapping[str, Any]) -> list[str]:
    """Campos sem os quais a Regra A nao permite revelar (fail closed).

    Perfis de reserva validos:
      1) Lead padrao      -> owner_name + owner_phone            -> debita credito
      2) Lead corporativo -> owner_name + mailing_address, sem phone -> 0 creditos
    """
    missing = []
    if not _present(lead.get("owner_name")):
        missing.append(MISSING_OWNER_NAME)
    if not _present(lead.get("owner_phone")) and not _present(lead.get("mailing_address")):
        missing.append(MISSING_CONTACT)
    return missing


def is_unresolvable(lead: Mapping[str, Any]) -> bool:
    """Lead sem qualquer dado de contacto E com um endereco que nunca resolve.

    Reservar falha sempre com 422 e sem debito, por isso o backend sinaliza
    logo no feed para a UI poder desativar a accao e explicar o motivo, em vez
    de deixar o utilizador gastar um clique num beco sem saida.
    """
    return bool(
        not _present(lead.get("owner_name"))
        and not _present(lead.get("owner_phone"))
        and not _present(lead.get("mailing_address"))
        and not address_is_resolvable(lead.get("address"))
    )


def charges_credit(lead: Mapping[str, Any]) -> bool:
    """Unico ponto de decisao sobre debito de credito na reserva."""
    return not is_corporate(lead)


def classify(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Avalia um lead uma vez e devolve o veredito consumido pelo frontend."""
    return {
        "corporate": is_corporate(lead),
        "address_resolvable": address_is_resolvable(lead.get("address")),
        "unresolvable": is_unresolvable(lead),
    }

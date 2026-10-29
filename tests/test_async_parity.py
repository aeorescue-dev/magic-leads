"""Guarda de regressao: par sync/async do DatabaseService.

Historia real (3 ocorrencias nesta sessao):
  * `import_b2b_lead` sem os kwargs de nicho  -> TypeError em producao
  * `create_or_reuse_draft_batch` sem wrapper -> AttributeError em producao
  * `niche_key` aceite no sync mas nao no async

O padrao e' sempre o mesmo: um metodo novo e' escrito na classe sync e o
wrapper async (que e' o que `main.py` usa) fica para tras. Estes testes
falham antes do deploy.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

from backend.services.db import AsyncDatabaseService, DatabaseService

MAIN_PY = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"


def _public_methods(cls) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


def _awaited_methods_on(obj_name: str, source_path: pathlib.Path) -> set[str]:
    """Nomes chamados como `await <obj_name>.<method>(...)` no ficheiro."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == obj_name
        ):
            found.add(func.attr)
    return found


def test_every_awaited_db_method_exists_on_async_service():
    """Se `main.py` faz `await db_service.X(...)`, X tem de existir no async."""
    awaited = _awaited_methods_on("db_service", MAIN_PY)
    assert awaited, "nenhuma chamada a db_service encontrada (teste invalido?)"

    async_methods = _public_methods(AsyncDatabaseService)
    missing = sorted(awaited - async_methods)
    assert not missing, (
        "metodos chamados com await mas ausentes em AsyncDatabaseService: "
        f"{missing}"
    )


def test_async_wrappers_keep_the_same_parameters_as_sync():
    """Um wrapper async tem de aceitar os mesmos parametros do metodo sync.

    Apanha o caso em que o wrapper existe mas nao encaminha os kwargs novos.
    """
    sync_methods = _public_methods(DatabaseService)
    async_methods = _public_methods(AsyncDatabaseService)

    # Divergencias intencionais (documentadas). Qualquer outra e' bug.
    INTENTIONAL = {
        # O async faz pos-processamento proprio (phone lookup) e força
        # skip_daily_increment=True, por isso nao expoe esse parametro.
        "reserve_lead": "async forca skip_daily_increment=True",
    }

    problems: list[str] = []
    for name in sorted(sync_methods & async_methods):
        if name in INTENTIONAL:
            continue
        sync_sig = inspect.signature(getattr(DatabaseService, name))
        async_sig = inspect.signature(getattr(AsyncDatabaseService, name))
        async_params = list(async_sig.parameters)

        # Um wrapper que aceita **kwargs encaminha tudo: e' compativel.
        if any(
            p.kind is inspect.Parameter.VAR_KEYWORD
            for p in async_sig.parameters.values()
        ):
            continue

        sync_params = list(sync_sig.parameters)
        if sync_params != async_params:
            problems.append(f"{name}: sync={sync_params} async={async_params}")

    assert not problems, "wrappers async com assinatura divergente:\n" + "\n".join(problems)

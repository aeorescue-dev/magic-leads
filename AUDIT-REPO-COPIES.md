# AUDIT-REPO-COPIES.md — Auditoria de cópias + i18n (PT/EN/ES) — FECHADA

Data: 2026-09-21 · Método: descoberta read-only via **venv real** (`backend\venv\Scripts\python.exe`),
script `audit_repo_copies.py` (std lib, py_compile), saída JSON em temp. **EXIT=0.**

## 1. Cópias do repositório

| Item | Valor |
|---|---|
| Root varrido | `C:\Users\Fabio\Documents\Default Project\garimpador-leads` |
| **Copies (count)** | **1** |
| Backend real (Railway) | `C:\Users\Fabio\Documents\Default Project\garimpador-leads\backend` |
| Deploy | `Dockerfile` presente · venv própria em `backend\venv` |

Conclusão: não há cópias geminadas. A flutuação OK/FAIL recorrente era **resolução inconsistente de
path entre ferramentas** (`garimpador-leads` vs outros spellings do mesmo diretório), não duplicação de arquivos.

## 2. Compilação (py_compile na venv real)

| Arquivo | Resultado |
|---|---|
| `services/translations.py` | OK |
| `services/push_service.py` | OK |
| `services/notifier.py` | OK (corrigido IndentationError 75/83 — re-indent +4) |

## 3. Pontos de i18n no backend (verificados verbatim)

- `translations.py` — `tr()` (PT/EN/ES, fallback PT), grupos `new_lead`, `status_change`, `system`.
- `push_service.py` — `send_new_lead_alert` e `send_status_change_alert` localizados por usuário.
- `notifier.py` — `notify_users_for_lead` localiza por usuário (`tr()`/`normalize`).
- `db.py` (coluna `locale`), `schemas.py` (UserCreate/Update/Response), `main.py` register (`locale` fallback PT).

## 4. Pendência (próxima sessão — frontend)

Enviar `locale` no `register` + PATCH de idioma (i18n) no frontend — fechamento PT/EN/ES ponta a ponta.

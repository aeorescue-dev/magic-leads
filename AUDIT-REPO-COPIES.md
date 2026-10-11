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

- `translations.py` — `DEFAULT_LOCALE="en"`, `tr()` (PT/EN/ES, fallback PT), `render()` (templating
  por `msg_key`/`msg_params` → `{title, message}`), grupos `new_lead`, `status_change`, `system`,
  `digest`, `owner_enriched`, `enrichment_complete`.
- `alert_planner.py` — despacho localizado por utilizador (fair-equal + teto diário): push `new_lead`
  e push `digest` via `push_service.send_to_user` (título/corpo por `render()` no locale do user).
- `notifier.py` — fachada: `fanout_new_lead_batch` delega em `alert_planner.plan_and_dispatch`;
  `guard_silent_fanout` (Dead Man's Switch). `notify_users_for_lead` foi removido na migração.
- `push_service.py` — apenas `send_to_user` (gate `push_enabled`), `send_to_all` e debug. Os antigos
  `send_new_lead_alert`/`send_status_change_alert`/`send_to_category` foram removidos (dead code).
- `db.py` — colunas `locale`, `msg_key`/`msg_params`; `main.py` renderiza na leitura via
  `_localize_notification` (schemas `UserCreate/Update/Response` mantêm `locale`).

## 4. Pendência (próxima sessão — frontend)

Enviar `locale` no `register` + PATCH de idioma (i18n) no frontend — fechamento PT/EN/ES ponta a ponta.

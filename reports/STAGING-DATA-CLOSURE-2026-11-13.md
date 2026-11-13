# Fecho dos dados do staging — Managing Agent + ingestão preventiva

Data: 2026-11-13
Branch: `staging/opportunity-foundation`
Produção: `master` em `3b53962` — intocada.
Base: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\leads.db`

## 1. Managing Agent do HPD (persistido e exposto)

### O que foi feito
- **BD**: nova coluna `leads.managing_agent_json` (TEXT) no schema + migração idempotente
  em `_migrate_schema` (bases antigas ganham a coluna sem reset).
- **Escrita**: `db_service.update_managing_agent(lead_id, agent)` (sync + async).
- **Persistência no enriquecimento** em 6 pontos: inserção do scraper, reprocessamento de
  DLQ, reserva/reveal, `enrich_all_leads`, `enrich_single_lead` (admin) e fluxo de
  revelação de telefone. Helper único `_persist_managing_agent` evita divergência.
- **Flag de staging**: `HPD_AGENT_ENRICHMENT_ENABLED=true` no arranque do backend de staging.
- **Privacidade**: `privacy.public_managing_agent` normaliza e limpa o agente; só saem
  `name`, `contact_type`, `contact_description` e `business_address`. `registration_id` e
  `source` ficam internos. O JSON bruto (`managing_agent_json`) nunca chega ao cliente.
- **API**: `LeadResponse.managing_agent` (dict) preenchido em `_to_lead_response` **apenas
  com reveal ativo** (`_revealed`), tal como `owner_name`/`mailing_address`.
- **UI**: bloco “Gestor do imóvel” no detalhe do lead, com nome, descrição do contacto e
  morada comercial (PT/EN/ES).
- **Teste**: `test_managing_agent_is_persisted_and_sanitized_for_client` cobre persistência,
  limpeza, remoção de identificadores e o gate de reveal (`hidden` vs `shown`).

### Limite conhecido
A recolha automática continua dependente de o lead ter BBL/BIN e de a flag estar ligada.
Sem BBL (como nos leads do seed), o resolver devolve `None` — não inventa agente. O fluxo
está pronto para produção; os dados reais aparecem quando a fonte os fornecer.

## 2. Adaptador de ingestão preventiva

### O que foi feito
- **Serviço** `backend/services/preventive_ingestion.py`:
  - lê leads com `signal_type` em `open_request` / `legal_obligation` (configurável);
  - mapeia para `create_opportunity` com `source_kind='preventive'`;
  - **deduplica por `property_key`** (BBL/BIN/morada) — um imóvel nunca entra duas vezes;
  - preenche `description`, `owner_name`, `owner_type` (`company`/`institutional`/`unknown`),
    `inspection_status`, `received_at`, `compliance_deadline`, `severity`, `tags` e `timeline`;
  - guarda metadados internos em `source_payload` (a API já remove este campo).
- **Script** `scripts/ingest_preventive_from_leads.py` com guardas de staging
  (`ALLOW_STAGING_INGEST=1`, `LEADS_DB_PATH`, recusa o repositório de produção) e flags
  `--limit` / `--open-requests-only`.
- **Execução no staging**:
  - 3 leads analisados;
  - **2 criados** (`#43` 1420 Claremont Pkwy, `#44` 620 W 141st St);
  - **1 ignorado** por já existir (2419 W 60th St, duplicado por morada);
  - total preventivo: **14** (12 curados + 2 ingeridos).
- **Teste**: `test_preventive_ingestion_maps_lead_and_dedupes_by_property` valida o mapeamento
  completo e a deduplicação.

### Como fica em produção
Chamar `preventive_ingestion.ingest_from_leads()` depois do ciclo de ingestão (ou agendar
num job próprio). O staging usa o script; a função é a mesma.

## 3. Verificação

| Verificação | Resultado |
|---|---|
| `pytest tests/ -q` | **1678 passed, 1 skipped** (10 no ficheiro de workflow, +2 novos) |
| `ruff check backend tests` | limpo |
| `npx tsc --noEmit` | limpo |
| `npx eslint . --quiet` | limpo |
| `npm test -- --run` | 123 passed |
| API `kind=preventive` | 14 linhas; `source_payload` ausente |
| Linha ingerida | `description`, `owner_type=company`, `tags`, `timeline`, `deadline` presentes |
| UI | 14 cartões; drawer mostra “Empresa”, tags e datas |

Capturas: `pt-prevention-ingested.png` e `pt-drawer-ingested.png` em
`C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\shots\`.

## 4. Notas

- `job_value` fica `None` nos ingeridos (a fonte não traz valor de obra); o rail de “Multas
  em risco” soma apenas o que existe — sem números inventados.
- `received_at` dos ingeridos vem em ISO completo (`2026-11-12T19:11:50+00:00`); a UI mostra
  só a data.
- `owner_type` passou a tokens (`company`/`institutional`/`unknown`) traduzidos na UI; o seed
  foi normalizado (de “Empresa” para `company`).

Produção permanece em `master` `3b53962`, sem alterações, deploys ou migrações.

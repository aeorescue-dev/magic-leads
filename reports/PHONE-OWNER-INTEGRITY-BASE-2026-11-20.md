# Base de integridade do telefone do proprietário — 4 cidades

**Data:** 2026-11-20 · **Estado:** base implementada, `ruff`/`tsc` limpos, suíte completa validada, **nada publicado**.
**Âmbito:** NYC, Chicago, Boston, Dallas. `VOICE_FREEZE=1` mantido; frente BR intocada.
**Gate:** Fase A (gratuita) pode arrancar já; Fase B (paga) aguarda aprovação explícita.

---

## 1. O que foi implementado

### 1.1 Camada A — resolução do proprietário (1 contrato, 4 adapters)

`backend/services/owner_resolution/`

| Ficheiro | Papel |
|---|---|
| `base.py` | `OwnerRecord` (nome, `owner_kind`, `parcel_key`, `mailing_address`, `record_year`, `owner_occupied`, `confidence`, `match_method`, `match_score`, `stale`) + `classify_confidence` + `is_stale` |
| `nyc.py` | PLUTO por BBL; condomínio/co-op → `building`, nunca “dono da fração” |
| `chicago.py` | Cook County; `year` alimenta `stale` |
| `boston.py` | CKAN; sem fallback de candidato único |
| `dallas.py` | DCAD por `parcelid`/`appraisalyr` |
| `__init__.py` | `resolve_owner(address, city, bbl)` — o chamador escolhe a cidade, nunca o dataset |

Proveniência acrescentada ao `enrichment.py` sem quebrar a API existente:
`parcel_key`, `record_year`, `owner_occupied`, `match_method`, `match_score`.
O fallback Boston de “único candidato” foi **removido** (`enrichment.py`, `_match_ckan`).

**Proveniência persistida no lead** (novas colunas em `leads`):
`owner_parcel_key`, `owner_kind`, `owner_record_year`, `owner_match_method`,
`owner_confidence`, `owner_source_dataset`, `owner_resolved_at`.
- O clique e o worker reconstroem o `OwnerRecord` a partir daí, **sem repetir
  a consulta pública** e sem depender de memória do processo.
- Leads antigos sem proveniência ficam em `medium`: podem procurar, **nunca**
  saem como verificados.
- Se o dataset passar a devolver outro titular, a proveniência nova **não** é
  colada ao nome antigo (`names_equivalent`).
- O backfill de owners passou a gravar a proveniência.

### 1.2 Camada B — decisores de entidades (SOS)

`backend/services/corporate_officers.py`
- `resolve_officer(owner_name, city, state)` com provider OpenCorporates.
- **Fail-closed:** `SOS_OFFICERS_ENABLED=0` e sem chave → `None`.
- Sem match exacto de nome de empresa → `None` (não atribui homónimo).
- A política cai para `address_only` rotulado quando não há decisor.

> Limitação assumida: a ligação directa aos portais NY DOS / IL SOS / MA SOS / TX SOS
> fica como próximo incremento validado. Não se inventou scraping frágil.

### 1.3 Camada C — política única (`backend/services/phone_policy.py`)

Estados: `ready` · `in_progress` · `no_phone` · `blocked`.

Regras:
- `blocked` se registo `stale` (> `PHONE_STALE_YEARS`, default 5) e `PHONE_ALLOW_STALE=0`.
- `blocked` se confiança `low` (casamento só por substring de rua).
- `medium` (número exato, rua por LIKE/intervalo) **pode** ir a L2, mas **nunca** sai verificado.
- Entidade: `off` bloqueia; `address_only` exige `PHONE_L3_UNNAMED_ENABLED=1` e entrega **rotulado**; `officer` tenta SOS antes de cair para address-only.
- Absentee: tenta `mailing_address` primeiro; o imóvel só como fallback L3 (se ligado) e rotulado.

**Fórmula única do selo:**
```
verified = result.verified
           AND candidate.can_verify AND candidate.layer == "L2"
           AND owner.confidence == "high" AND not owner.stale
```

### 1.4 Camada D — entrega, cache e custo

- `phone_lookups` (BD): TTL **90 d hit / 7 d miss / 1 h erro**. Chave inclui `lead_id` + nome do dono + morada + ZIP.
- `phone_jobs` (BD): fila persistente, `cache_key UNIQUE` (single-flight), `trigger`, `quota_bucket`, backoff 1/5/15 min, máx. 3 tentativas.
- O clique (`/api/leads/{id}/reserve` e `/reveal-phone`) **não chama a Searchbug**. Lê cache; cache fria → enfileira e devolve `in_progress`.
- O worker (`phone_jobs.worker_loop`) é o único que chama o provider; corre fora do pedido HTTP.
- Falha definitiva (`no_results`, `name_mismatch`, `guard_skipped`) devolve a unidade; erro transitório faz retry.
- O clique verifica o **orçamento de tentativas** antes de consumir a cota: 30 tentativas/dia esgotadas → `attempt_limit`, sem cobrança e sem job.
- `/api/leads/{id}/reveal-phone` devolve `state=in_progress` na cache fria e `state=ready` quando o worker já entregou.
- `searchbug_calls.trigger` gravado (`user_click` / `validation` / `admin_manual`).
- `SUBTYPE=p` no `api_nape` (`SEARCHBUG_PHONE_ONLY=1`).
- Erros de credenciais deixam de ser `billed=1` → `auth_error`, custo 0.
- `subscription_reveals` deixou de usar `provider != "mock"` para `verified`.

### 1.5 Flags novas (`backend/config.py`)

| Flag | Default | Efeito |
|---|---|---|
| `SEARCHBUG_PHONE_ONLY` | `1` | `SUBTYPE=p` |
| `PHONE_STALE_YEARS` | `5` | bloqueia registo antigo |
| `PHONE_ALLOW_STALE` | `0` | override consciente |
| `PHONE_ENTITY_MODE` | `address_only` | `off`/`address_only`/`officer` |
| `SOS_OFFICERS_ENABLED` | `0` | fail-closed |
| `OPENCORPORATES_API_KEY` | `""` | provider SOS |
| `PHONE_JOB_WORKER_ENABLED` | `1` | worker da fila |
| `PHONE_JOB_POLL_SECONDS` | `15` | polling |

---

## 2. Testes

Novos/reescritos (todos a passar localmente):

- `tests/test_owner_resolution.py` — BBL, condomínio, Chicago velho/novo, Boston owner-occupied, Dallas absentee, regressão do fallback de Boston, confiança.
- `tests/test_phone_policy.py` — estados, stale, low/medium, entidade, absentee, fórmula `verified`, cache.
- `tests/test_phone_cache.py` — hit, chave muda com o dono, miss expira, single-flight.
- `tests/test_searchbug_integrity.py` — `SUBTYPE=p`, auth não faturada, `trigger`, outcomes.
- `tests/test_corporate_officers.py` — fail-closed, escolha de cargo, normalização.
- `tests/test_reserve_provider_path.py` — reescrito: clique não chama provider; worker entrega; quota estorna.
- `tests/test_quota_phase3.py` e `tests/test_reserve_atomic_quota.py` — adaptados ao fluxo assíncrono e a entidade real (LLC).

Validação estática:
- `ruff check backend tests --select=E,F,W,I --ignore=E501` → **limpo**.
- `npx tsc --noEmit` → **limpo**.
- `npm run lint` → **0 erros** (122 warnings pré-existentes).

Suíte completa:
- 1.ª passagem: **1772 passed, 4 failed** (2 fakes antigos em `owner_backfill`, 1 teste de orçamento síncrono, 1 flake de métricas).
- 2.ª passagem: **1776 passed, 1 failed** — só o flake de métricas (buffer global a drenar eventos de outro teste).
- Correções: testes adaptados ao contrato novo; orçamento de tentativas verificado **antes** de consumir a cota; contrato `in_progress` ordenado antes de `ready`; fixture de métricas passa a drenar o buffer antes/depois de cada teste.
- Re-execução dos ficheiros afetados: **43/43 passed**.
- 3.ª passagem (gate final): **1777 passed, 1 skipped, 0 failed** (314 s) —
  log `reports/pytest-phone-base-final2-2026-11-20.log`.

---

## 3. Dry-run real (sem chamadas pagas)

Comando (snapshot local, 8 leads/cidade, **sem** `--live`):
```bash
python -m backend.scripts.phone_validation --city all --limit 8
```

| Cidade | Amostra | `in_progress` | `blocked` | Motivo dominante | Tipos de dono | Confiança |
|---|---:|---:|---:|---|---|---|
| NYC | 8 | 2 | 6 | `entity_l3_disabled` (6) | 6 company / 2 person | 6 high / 2 medium |
| Chicago | 8 | 6 | 2 | `entity_l3_disabled` (2) | 2 company / 6 person | **8 medium** |
| Boston | 8 | 4 | 4 | `entity_l3_disabled` (3) + `owner_confidence_low` (1) | 3 company / 5 person | 2 high / 5 medium / 1 low |
| Dallas | 8 | 6 | 2 | `entity_l3_disabled` (2) | 2 company / 6 person | 8 high |

Leitura honesta:
- **Nenhum número foi entregue sem prova** — o dry-run não chama o provider.
- **NYC é dominado por empresas** no PLUTO: com L3 desligado, 6/8 ficam bloqueados. É o braço que a Fase B de entidades tem de medir.
- **Chicago veio 100% `medium`** neste snapshot: ou o casamento foi por número/LIKE, ou a resolução devolveu `None` e a confiança veio da proveniência ausente. É o primeiro ponto a investigar na Fase A.
- **Boston teve 1 `low`** (rua por substring) e foi corretamente bloqueado.
- **Dallas veio 8/8 `high`**, o que valida o caminho de parcela/endereço exato.
- A amostra local é pequena e **não é produção**; serve para provar o comportamento, não para concluir taxa de acerto.

---

## 4. Bateria de validação proposta (aguarda aprovação)

### Fase A — cobertura, sem custo (obrigatória)

```bash
python -m backend.scripts.phone_validation --city all --limit 50 \
  --output reports/phone-validation/fase-a
```

Mede, por cidade: `ready`/`in_progress`/`blocked`, `owner_kind`, `confidence`, `stale`, `absentee`.
**Critério:** 0 chamadas pagas para `low`/`stale`; nenhum `owner_name` inventado.

### Fase B — amostra paga, com teto duro (requer o seu OK)

```bash
# Pessoa + absentee (address-only desligado)
python -m backend.scripts.phone_validation --city all --limit 20 \
  --live --max-calls 80 --output reports/phone-validation/fase-b

# Braço separado para entidades, explicitamente rotulado
PHONE_L3_UNNAMED_ENABLED=1 PHONE_ENTITY_MODE=address_only \
python -m backend.scripts.phone_validation --city all --limit 10 \
  --live --max-calls 40 --output reports/phone-validation/fase-b-entidades
```

Custo máximo: **80 × $0,20 = $16** (primeiro braço) + **40 × $0,20 = $8** (entidades) = **$24**.
O harness nunca grava telefone em `leads` nem em `phone_lookups`.

### Revisão manual (obrigatória antes de escala)

Para cada linha do CSV, classificar:
1. **Dono correto** — nome e morada batem com o dataset.
2. **Mesmo apelido / pessoa diferente** — co-titular, familiar, homónimo.
3. **Inquilino/terceiro** — telefone do imóvel ocupado.
4. **Linha empresarial/gestora** — entidade sem decisor.
5. **Morto/errado** — número inválido.

### Critérios de go/no-go

| Métrica | Limite |
|---|---|
| Telefones entregues que são do dono/decisor | **≥ 90%** |
| Entregues com `verified=True` que falham revisão | **0** |
| `name_mismatch` entregue | **0** |
| Terceiro/inquilino entre os entregues | **≤ 5%** |
| Chamadas pagas sem telefone (`no_results`) | reportar, não esconder |
| Latência do clique | **0 ms** (cache/estado) |

Se < 90%, **não se abre em escala**. O relatório dirá exactamente onde falha (cidade, tipo de dono, método de casamento) e o ajuste necessário.

---

## 5. Riscos residuais que a base não resolve sozinha

1. **Cobertura de decisores de LLC** — depende do provider SOS; sem chave, fica `address_only` rotulado ou bloqueado.
2. **Condomínios NYC** — PLUTO não tem o dono da fração; a base marca `building` e não vende isso como dono da unidade.
3. **Registos antigos** — Chicago pode ter `year` muito antigo; a base bloqueia, mas o dado em si continua velho.
4. **SearchBug é people-search, não certidão** — a fórmula reduz o risco, não o elimina. Por isso a revisão manual da Fase B é obrigatória.
5. **Legacy credits** (`CREDITS_PHONE_ENABLED=0` por defeito) ainda tem um caminho síncrono dormente; não foi tocado para não misturar modelos de cobrança.
6. **Corrida reserva→job:** se o `reveal_lead` falhar depois de o job ser aceite, a unidade é devolvida mas o job pode ainda entregar. É raro (409/limite) e fica como item de robustez antes de escala.

---

## 6. O que preciso de si para a bateria

1. **OK para a Fase B paga** (teto $24, 120 chamadas máx., sem gravar telefones).
2. **Decisão sobre entidades:** manter `PHONE_L3_UNNAMED_ENABLED=0` (não entrega
   telefone de imóvel para LLC) ou autorizar o braço de validação com L3 ligado,
   sabendo que esses números são sempre rotulados e nunca verificados.
3. **Decisão sobre o provider SOS:** fornecer `OPENCORPORATES_API_KEY` para
   testar decisores de LLC, ou aceitar que, sem chave, entidades ficam
   `address_only`/bloqueadas.

Sem estes três pontos, a Fase A (gratuita) já pode correr; a Fase B não.

---

## 7. Segurança operacional

- `VOICE_FREEZE=1` **não foi alterado**.
- Frente BR (`feat/br-environmental-mvp`) **não foi tocada**.
- Nenhum deploy, nenhuma migração em produção, nenhuma publicação.
- As tabelas novas são criadas de forma idempotente no arranque; não há migração destrutiva.

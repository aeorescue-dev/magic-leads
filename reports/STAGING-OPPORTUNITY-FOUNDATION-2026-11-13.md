# Staging — fundação de oportunidades, consentimento e outcomes

**Data:** 2026-11-13  
**Branch:** `staging/opportunity-foundation`  
**Commit:** `49419e5`  
**Produção:** `master` continua em `3b53962`, sem alterações.

---

## 1. O que foi implementado

### 1.1 Consentimento obrigatório

**Backend**

- `POST /api/leads/{id}/reserve` rejeita `consent=false` com **400 `consent_required`**.
- Nenhuma reserva, cota ou chamada ao provider é executada sem consentimento.

**Frontend**

- O checkbox do modal “Reveal owner data” passou a ser controlado por estado.
- O botão “Reserve 1 Hour · Reveal” fica **desativado** até o aceite.
- O `confirmReveal` envia `consent` real, não mais `true` fixo.

### 1.2 Workflow aditivo de oportunidades

Novas tabelas:

| Tabela | Função |
|---|---|
| `opportunity_workflow` | evento/ciclo da oportunidade, sem escrever em `leads` |
| `property_locks` | trava transversal por `property_key` |
| `opportunity_outcomes` | `won` / `lost` / `no_decision`, valor e timestamps |

Garantias:

- `UNIQUE(source_kind, source_record_id)` para idempotência da fonte;
- índice parcial único para **um ciclo ativo por `property_key`**;
- nenhuma coluna existente de `leads` foi alterada;
- nenhum `DELETE`/`UPDATE` em `leads`.

Serviço: `backend/services/opportunity_workflow.py`.

Regras implementadas:

- reserva **60 min** e consumo atómico de 1 unidade da cota;
- “Ligou” → `contacted` + **48 h**;
- “Negociando” → `in_negotiation` + **48 h**;
- só avança quem tem reserva ativa (não se abre 48 h num lead `available`);
- re-clique não estica prazo;
- conversão terminal e libertação da trava;
- bloqueio `property_locked` quando outro ciclo ativo detém o imóvel;
- estorno da cota quando a reserva falha.

Endpoints de staging:

```
POST /api/opportunities/{id}/reserve
POST /api/opportunities/{id}/contact
POST /api/opportunities/{id}/negotiate
POST /api/opportunities/{id}/convert
POST /api/opportunities/{id}/outcome
POST /api/leads/{id}/outcome
```

`/api/leads/{id}/outcome` é aditivo: **não altera `/convert` nem `converted_at`**.

### 1.3 Outcomes

- `outcome`: `won`, `lost`, `no_decision`.
- `won_at`/`lost_at` são preenchidos só quando aplicável.
- `contract_value` opcional, `currency` default `USD`.
- `converted_at` continua estritamente no fluxo atual; a nova tabela não o substitui.

### 1.4 Managing Agent HPD (NYC)

Novo módulo: `backend/services/hpd_agent.py`.

- consulta `tesw-yqqr` (Multiple Dwelling Registrations);
- consulta `feu5-w2e2` (Registration Contacts);
- prefere `Agent`, depois `CorporateOwner`;
- devolve nome, tipo, morada business e `registration_id`;
- **não** tem telefone; o telefone continua on-demand.

Integração:

- flag `HPD_AGENT_ENRICHMENT_ENABLED` (default `False`);
- quando ligada, o enriquecimento de NYC anexa `managing_agent` ao resultado;
- não substitui `owner_name` automaticamente nesta fase.

---

## 2. Testes executados

| Verificação | Resultado |
|---|---|
| `pytest tests/ -q` | **1674 passed, 1 skipped** |
| `ruff check backend tests --select=E,F,W,I --ignore=E501` | **All checks passed** |
| `npx tsc --noEmit` | **Sem erros** |
| `npm run lint` | **0 erros**, 97 warnings pré-existentes |

Testes novos:

- lifecycle 1h → 48h → 48h + outcomes;
- idempotência de reserva;
- bloqueio de segunda oportunidade no mesmo imóvel;
- estorno de cota no bloqueio;
- outcome de lead sem alterar `converted_at`;
- agente HPD prefere `Agent` a `CorporateOwner`;
- consentimento obrigatório (testes antigos de `consent=false` atualizados).

---

## 3. O que ainda não está ligado

1. **UI de oportunidades:** o modal atual continua a chamar `/api/leads/{id}/reserve`. O endpoint de oportunidades está pronto, mas o adaptador `RevealTarget`/`reserveSubject` ainda não foi ligado ao dashboard.
2. **Ingestão de pré-inspeção:** nenhuma fonte HPD Complaints/311 nova foi adicionada nesta fase; as tabelas estão prontas para receber os eventos.
3. **Outcomes na UI:** a tabela e o endpoint existem; falta o passo visual “ganhou/perdeu/valor” após a conversão.
4. **Owner name via Managing Agent:** o resolver está pronto e testado; a substituição/priorização no fluxo de telefone fica para a fase de integração.
5. **Migração de produção:** não executada. As tabelas são criadas apenas no staging/test DB.

---

## 4. Como testar

```bash
cd "C:\Users\Fabio\Documents\Default Project\garimpador-staging-structure"
# testes completos
.venv\Scripts\python.exe -m pytest tests/ -q
# apenas a fundação nova
.venv\Scripts\python.exe -m pytest tests/test_opportunity_workflow_staging.py -q
```

Para o frontend, usar o `node_modules` do repositório principal ou instalar no worktree.

---

## 5. Produção

- `master` em `3b53962`, sem alterações.
- Nenhum deploy.
- Nenhuma migração executada em produção.
- Toda a implementação está no worktree `garimpador-staging-structure`, branch `staging/opportunity-foundation`.

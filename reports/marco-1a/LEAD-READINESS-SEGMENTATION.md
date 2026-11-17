# Segmentação de leads por prontidão — parecer técnico e proposta visual

**Data:** 2026-11-17  
**Âmbito:** aba Oportunidades do dashboard (freemium e assinatura legacy)  
**Pergunta:** dividir os leads em **Todos**, **Prontos para Carta/Visita** e **Com Telefone Disponível**, com performance e layout limpos.

---

## 1. Sumário executivo

**Veredicto:** a segmentação é **tecnicamente viável** — os campos-base já existem em `leads` — mas **não está pronta a produção tal como está**.

Três bloqueios reais:

1. `signal_ready` e `phone_ready` existem, mas são **criados pelo módulo de créditos e apenas preenchidos pelo seed de staging**. Nos leads reais estão a `0`.
2. A cobertura de dados é muito baixa: no snapshot local de **45.257 leads**, só **37 têm `mailing_address`** e **0 têm telefone verificado** (`phone_verified=1` + `owner_phone`). A aba “Carta” teria ~34 leads; a aba “Telefone” teria 0.
3. Não há índices de prontidão. Os planos de execução atuais fazem `SCAN` na tabela/índice de data, não num índice de `signal_ready`/`phone_ready`.

**Recomendação:** implementar as três abas como **filtros de prontidão** (não como buckets exclusivos), com:
- `signal_ready` / `phone_ready` materializados no `db.py`, com backfill e manutenção na escrita;
- índices parciais por prontidão;
- `readiness=all|letter|phone` na API e contagens no mesmo `WHERE`;
- aba “Com telefone” **feature-flagged / bloqueada com selo “Marco 1B”** até o enriquecimento existir;
- staging com seed populado (50 cartas; opcionalmente 10 telefones sintéticos para QA visual).

**Go/No-Go:**
- **Carta/Visita:** GO para 1A, desde que `signal_ready` seja materializado e a cobertura seja comunicada.
- **Com Telefone:** NO-GO como aba ativa até ao Marco 1B; GO como aba “em breve”/bloqueada.

---

## 2. Estado atual do modelo de dados

### 2.1 Colunas relevantes em `leads`

`backend/services/db.py` (tabela `leads`):

| Campo | Uso atual |
|---|---|
| `address`, `city`, `state`, `zip_code`, `lat`, `lng` | endereço/mapa |
| `owner_name` | proprietário/empresa |
| `owner_phone`, `phone_verified` | telefone e verificação |
| `mailing_address` | mailing do proprietário |
| `signal_type`, `signal_status` | tipo/estado do sinal |
| `is_junk`, `is_feed_ok`, `is_qualified` | qualificação materializada (Fase 22) |
| `lead_status`, `reserved_by` | disponibilidade |
| `owner_source`, `owner_kind`, `parcel_id`, `principal_name` | proveniência do owner |
| `signal_ready`, `phone_ready` | flags do Marco 1A |

### 2.2 Onde as flags são criadas

`backend/services/credits.py`:

```python
_add_column(conn, "leads", "signal_ready", "INTEGER DEFAULT 0")
_add_column(conn, "leads", "phone_ready", "INTEGER DEFAULT 0")
```

`credits.init()` corre no arranque (`backend/main.py`), **depois** de `db_service.init_db`. Não há backfill nem trigger para leads reais. O seed de staging é o único sítio que escreve `signal_ready=1`:

`backend/scripts/seed_staging_credits.py`:
```sql
..., signal_ready, phone_ready, ...
VALUES (..., 1, 0, ...)
```

### 2.3 Duas definições de “pronto” hoje

| Caminho | Predicado |
|---|---|
| Feed (`/api/leads/today`) | `is_feed_ok=1 AND signal_type IS NOT NULL AND lead_status != 'converted'` |
| Créditos (`/api/credits/leads`, reveal) | `signal_ready=1 AND is_junk=0` + no reveal: `owner_name`, `address`, `mailing_address`, `owner_source` confiável |

Isto significa que um lead pode aparecer no feed e **não** ser revelável, ou vice-versa. Para as abas, é obrigatório unificar a definição.

### 2.4 Índices existentes em `leads`

- `idx_leads_feed_order (is_feed_ok, date_reported DESC, id DESC)`
- `idx_leads_qualified_order (is_qualified, date_reported DESC, id DESC)`
- `idx_leads_qualified_city (is_qualified, city, issue_category)`
- `idx_leads_geo (...)` e `idx_leads_public_geo (...)` (parcial)
- `idx_leads_phone (owner_phone)` — não cobre `phone_verified`
- **Não existe** índice em `signal_ready` nem em `phone_ready`.

---

## 3. Medições (snapshot local `data/leads.db`)

Base: **45.257 leads**.

| Métrica | Valor |
|---|---:|
| `is_qualified=1` | 32.249 |
| `is_feed_ok=1` | 36.260 |
| Base ativa (`is_qualified=1`, `signal_type`, não fechado, não junk) | 32.247 |
| `owner_name` preenchido (na base ativa) | 24.245 |
| `mailing_address` preenchido (total) | 37 |
| **letter-ready** (base ativa + owner + mailing) | **34** |
| `phone_verified=1` + `owner_phone` | **0** |
| `owner_phone` preenchido (qualquer) | **1** |
| `signal_ready=1` | **0** |
| `phone_ready=1` | **0** |
| `owner_source` preenchido | **0** |
| Cidade com mailing | Chicago: 37 |

### 3.1 Planos de execução

```
EXPLAIN QUERY PLAN SELECT id FROM leads WHERE signal_ready=1 ORDER BY date_reported DESC LIMIT 60
  SCAN leads USING INDEX idx_leads_date_reported

EXPLAIN QUERY PLAN SELECT id FROM leads WHERE phone_verified=1 ORDER BY date_reported DESC LIMIT 60
  SCAN leads USING INDEX idx_leads_date_reported
```

Ou seja: as flags atuais **não aceleram nada**. O SQLite varre por data e filtra depois.

### 3.2 Staging

O seed cria **50 leads sintéticos** com `signal_ready=1`, `phone_ready=0` e `mailing_address` preenchido. Portanto:
- aba “Carta/Visita” fica populada no staging;
- aba “Com telefone” fica vazia (correto para 1A; precisa de estado vazio educado ou de 10 leads sintéticos de preview no 1B).

### 3.3 Leitura estratégica

> O gargalo **não é a query**. É a **cobertura de owner/mailing/telefone**.

A filtragem por prontidão é barata. O que faz a aba “Carta” parecer vazia é a falta de `mailing_address` (37/45k) e de `owner_source`. O que faz a aba “Telefone” parecer vazia é a ausência de enriquecimento (0/45k).

---

## 4. Definições propostas

### 4.1 Predicado-base único

```sql
-- base de elegibilidade, partilhada pelo feed, mapa e créditos
is_qualified = 1
AND signal_type IS NOT NULL
AND COALESCE(signal_status, 'unknown') <> 'closed'
AND COALESCE(is_junk, 0) = 0
AND lead_status != 'converted'
```

### 4.2 `letter_ready` (Carta/Visita)

```sql
letter_ready = 1  quando:
  base
  AND LENGTH(TRIM(address)) > 8
  AND TRIM(COALESCE(owner_name, '')) <> ''
  AND is_institutional_name(owner_name) = 0
  AND TRIM(COALESCE(mailing_address, '')) <> ''
```

No 1A, `mailing_address` preenchido é o sinal disponível. **Não chamar “verificado”** enquanto não existir `mailing_verified`. Copy recomendada: **“Pronto para carta”**, não “mailing verificado”.

### 4.3 `phone_ready` (Com telefone)

```sql
phone_ready = 1  quando:
  base
  AND phone_verified = 1
  AND TRIM(COALESCE(owner_phone, '')) <> ''
```

Distinção importante para o 1B:

| Flag | Significado | UI |
|---|---|---|
| `phone_ready=1` | telefone já verificado e disponível | aba “Com telefone” ativa, CTA $3,00 |
| `phone_eligible=1` | cumpre pré-condições para Searchbug, mas ainda sem telefone | sub-filtro “Elegíveis para enriquecer” (opcional) |

O pedido diz “elegíveis ou já enriquecidos”. Recomendo **não misturar** os dois na mesma aba: “Com telefone disponível” deve significar **telefone disponível**. Os elegíveis entram como segundo estado/sub-filtro no 1B.

### 4.4 As abas são vistas, não buckets exclusivos

Um lead com telefone normalmente também tem carta. Portanto:
- **Todos** = base;
- **Carta** = `letter_ready=1`;
- **Telefone** = `phone_ready=1`.

Os counts podem sobrepor-se. Na UI, uma nota curta: “Um lead pode aparecer em mais de uma aba.” Se o negócio exigir somas exatas, a alternativa é:
- Todos = base;
- Carta = `letter_ready=1 AND phone_ready=0`;
- Telefone = `phone_ready=1`.
Mas isto esconde leads de carta que também têm telefone. **Recomendo a sobreposição.**

---

## 5. Viabilidade técnica e performance

### 5.1 Veredicto por camada

| Camada | Viável? | Observação |
|---|---|---|
| Modelo de dados | ✅ | colunas-base já existem |
| Filtro por prontidão | ✅ | `WHERE signal_ready=1` / `phone_ready=1` |
| Performance atual | ⚠️ | sem índice; `SCAN` por data |
| Performance a 100k+ | ⚠️ | precisa de flags materializadas + índices parciais |
| Carta em produção | ⚠️ | 34/45k; gargalo de cobertura, não de SQL |
| Telefone em produção | ❌ 1A | 0/45k; só faz sentido no 1B |
| Property Masters | 🔜 1B | tabela canónica por BBL/BIN/address_key |

### 5.2 O que materializar

Mover `signal_ready`/`phone_ready` para o **núcleo** (`db.py`), não para `credits.py`:

1. Criar as colunas em `db.py` (migração idempotente).
2. Calcular no `_quality_set_clause()` (ou função `refresh_readiness()`).
3. Backfill no arranque para linhas existentes.
4. Recalcular em triggers de `owner_name`, `mailing_address`, `owner_phone`, `phone_verified`, `signal_type`, `signal_status`, `case_status`, `issue_category`, `address`.
5. Usar o **predicado bruto** dentro do `signal_ready` (não `is_qualified`), porque numa única `UPDATE` o SQLite avalia as expressões com os valores antigos. Ex.: `signal_ready = CASE WHEN (<_qualified_where()>) AND ... THEN 1 ELSE 0 END`.

### 5.3 Índices recomendados

```sql
-- Aba Carta / Visita
CREATE INDEX IF NOT EXISTS idx_leads_letter_ready
  ON leads (signal_ready, date_reported DESC, id DESC)
  WHERE signal_ready = 1;

CREATE INDEX IF NOT EXISTS idx_leads_letter_city_trade
  ON leads (signal_ready, city COLLATE NOCASE, issue_category, date_reported DESC)
  WHERE signal_ready = 1;

-- Aba Com telefone
CREATE INDEX IF NOT EXISTS idx_leads_phone_ready
  ON leads (phone_ready, date_reported DESC, id DESC)
  WHERE phone_ready = 1;

CREATE INDEX IF NOT EXISTS idx_leads_phone_city_trade
  ON leads (phone_ready, city COLLATE NOCASE, issue_category, date_reported DESC)
  WHERE phone_ready = 1;
```

Regras:
- usar `signal_ready=1` / `phone_ready=1` (nunca `COALESCE(...,0)=1`) para o índice parcial ser elegível;
- garantir `NOT NULL DEFAULT 0`;
- não incluir `is_junk` no predicado do índice (o `signal_ready` já implica não-junk).

### 5.4 API

Adicionar `readiness` ao feed:

```
GET /api/leads/today?readiness=all|letter|phone
GET /api/leads?readiness=all|letter|phone
GET /api/leads/neighborhoods?readiness=...
GET /api/opportunities/territories?readiness=...
GET /api/credits/leads?readiness=letter|all
```

Resposta (retrocompatível, campo opcional):

```json
{
  "total": 34,
  "page": 1,
  "per_page": 60,
  "counts": { "all": 8090, "letter": 34, "phone": 0 },
  "leads": [...]
}
```

`counts` tem de ser calculado com o **mesmo `WHERE` base** do filtro atual (cidade, ofício, zona, janela), não com o número de cartões da página. O frontend nunca deve derivar os counts de `filteredLeads.length`.

### 5.5 Corrigir queries existentes

`credits.list_leads` hoje:
```sql
WHERE COALESCE(l.signal_ready,0)=1 AND COALESCE(l.is_junk,0)=0
ORDER BY datetime(COALESCE(l.date_reported, l.created_at)) DESC
```
Problemas:
- `COALESCE(signal_ready,0)` impede o índice parcial;
- `datetime(COALESCE(...))` é não-sargável;
- `SELECT l.*` traz colunas que o cartão não usa.

Recomendação:
```sql
WHERE l.signal_ready = 1
ORDER BY l.date_reported DESC, l.id DESC
```
e selecionar apenas os campos do cartão.

### 5.6 Property Masters (1B)

Para o 1B, criar uma tabela canónica:

```sql
CREATE TABLE property_masters (
  property_key TEXT PRIMARY KEY,   -- BBL/BIN/address_key normalizado
  address TEXT, city TEXT, state TEXT, zip_code TEXT,
  owner_name TEXT, owner_source TEXT, owner_kind TEXT,
  mailing_address TEXT, mailing_verified INTEGER DEFAULT 0,
  mailing_source TEXT,
  phone TEXT, phone_verified INTEGER DEFAULT 0,
  phone_source TEXT, phone_last_checked_at TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

`leads` mantém `signal_ready`/`phone_ready` como **projeções denormalizadas** (para o feed ser rápido), sincronizadas por job/trigger quando o master muda. Benefícios:
- o mesmo prédio com várias ocorrências reutiliza owner/mailing/telefone;
- evita pagar Searchbug duas vezes pelo mesmo endereço;
- permite `mailing_verified` real;
- prepara a aba “Com telefone” sem acoplar a UI ao fornecedor.

### 5.7 Limite honesto

Mesmo com índices perfeitos, a aba “Carta” terá ~34 leads e a aba “Telefone” terá 0 no snapshot atual. **A percepção de valor depende de cobertura de dados, não de performance.** Antes de vender a segmentação como “SaaS premium”, é preciso:
- enrich de mailing/owner (1A/1B);
- `mailing_verified` real;
- Searchbug/Property Masters no 1B;
- estados vazios que expliquem cobertura, não “Sem leads”.

---

## 6. Proposta visual ideal

### 6.1 Princípio: prontidão é o filtro principal; origem é secundário

Hoje o `FeedToolbar` tem 4 abas de **origem** (`Todos`, `Reativos`, `Preventivos`, `Obras`). Acrescentar mais 3 abas no mesmo sítio criaria 7 pills e poluição.

**Recomendação:** separar em dois níveis.

```
┌──────────────────────────────────────────────────────────────────┐
│  Mapa NYC — bairros / zonas                   9.404 oportunidades │
├──────────────────────────────────────────────────────────────────┤
│  [ Todos · 8.090 ]  [ ✉️ Carta / Visita · 34 ]  [ 📞 Telefone · 1B ] │
│                                                                  │
│  Origem: [Todos ▾]   Cidade: [NYC ▾]   Ofício: [Todos ▾]  Filtros │
├──────────────────────────────────────────────────────────────────┤
│  cards...                                                        │
└──────────────────────────────────────────────────────────────────┘
```

- **Linha 1 (primária):** `Todos os leads` · `✉️ Carta / Visita` · `📞 Com telefone`.
- **Linha 2 (secundária):** origem (Reativos/Preventivos/Obras), cidade, ofício, busca e filtros.
- Em mobile, a linha 2 pode ir para o `Sheet` de filtros; a linha 1 fica sempre visível e scrollável.

Porquê:
- as três abas respondem à pergunta “o que posso fazer com este lead?”;
- a origem responde “que tipo de sinal é?”;
- são dimensões ortogonais; misturá-las numa só fila de pills confunde.

### 6.2 Aparência das abas

- Segmented control com fundo `var(--sd-surface-2)` e ativo em `var(--sd-accent-soft)` + texto `var(--sd-accent)`.
- Ícone + label curto + contador.
- `Com telefone` bloqueada no 1A:
  - ícone de cadeado;
  - label `📞 Telefone`;
  - badge `1B` em vez de `0`;
  - tooltip: “Telefone verificado chega no Marco 1B.”
- Nunca mostrar “0” vermelho como se fosse erro.

### 6.3 Indicadores nos cartões

Adicionar uma **readiness rail** discreta no cartão, em vez de mais 3 badges coloridos no topo:

```
✉️ Carta pronta        $1,50
📞 Telefone            $3,00 · 1B
```

- `✉️ Carta pronta` (verde suave) quando `letter_ready`.
- `📞 Telefone verificado` (azul) quando `phone_ready`; se não, `📞 $3,00 · 1B` em muted.
- Em “Todos”, mostrar as duas linhas; em “Carta”, só a primeira; em “Telefone”, só a segunda (e o CTA de telefone).
- Manter os badges existentes de tipo de sinal/owner no topo, mas **não** duplicar “owner identificado” com “carta pronta”.

### 6.4 Estados vazios (crítico para não parecer abandonado)

**Aba Carta com 0:**
> “Ainda não há leads prontos para carta nesta zona.  
> Vê todos os leads ou ajusta a cidade/oftício.”  
> [ Ver todos ]

**Aba Telefone no 1A:**
> “Telefone verificado chega no Marco 1B.  
> Entretanto, podes desbloquear endereço, owner e mailing por $1,50.”  
> [ Ver leads prontos para carta ]

**Aba Carta com poucos (ex.: 34):**
> “34 leads prontos para carta nesta zona.  
> Mostramos apenas endereço exato, owner e mailing.”

Nada de “Sem leads sintéticos” ou “0 oportunidades” sem contexto.

### 6.5 Freemium

No painel de créditos do modo gratuito:
- as mesmas três abas no topo;
- default **Carta / Visita** (é o que o reveal de $1,50 entrega);
- **Todos** mostra sinais mascarados com badges de prontidão;
- **Telefone** bloqueada com `1B`;
- o paywall modal continua a abrir sobre o dashboard.

### 6.6 O que evitar

- 7 pills na mesma linha.
- Aba “Telefone” vazia e clicável sem explicação.
- Contadores calculados no cliente (`filteredLeads.length`) que não batem com o total do servidor.
- Copy “mailing verificado” sem `mailing_verified`.
- Esconder a aba “Carta” quando o count é baixo; isso parece bug.

---

## 7. Fases, esforço e critérios de aceite

### Fase 1A — Segmentação de prontidão (Carta + Todos)

**Backend**
- mover `signal_ready`/`phone_ready` para `db.py`;
- backfill + triggers;
- índices parciais;
- `readiness` em `/api/leads/today`, `/api/leads`, neighborhoods/territories e credits;
- `counts` no `LeadsListResponse`;
- corrigir `credits.list_leads` (sem `COALESCE`/`datetime`).

**Frontend**
- segmented control de prontidão;
- origem como filtro secundário/dropdown;
- badges de prontidão nos cartões;
- estados vazios;
- telefone bloqueado `1B`;
- counts vindos da API.

**Staging**
- seed com 50 `signal_ready=1` (já existe);
- opcional: 10 leads sintéticos `phone_ready=1` apenas para QA visual do estado “telefone” (nunca em produção).

**Aceite**
- abas `Todos` e `Carta` devolvem listas e counts coerentes com o mesmo filtro;
- query plan usa `idx_leads_letter_ready` (sem `SCAN` da tabela);
- `credits` revela exatamente os leads da aba Carta;
- aba Telefone mostra estado “1B” e não permite compra;
- zero erros de TypeScript/ESLint; testes de créditos continuam verdes.

**Esforço estimado:** 3–5 dias backend + 2–3 dias frontend + 1–2 dias QA.

### Fase 1B — Telefone + Property Masters

- tabela `property_masters`;
- `mailing_verified`/`mailing_source`;
- Searchbug/Property Masters, `phone_ready`, `phone_eligible`;
- aba Telefone ativa, CTA $3,00;
- estados de erro/limite de chamadas.

**Esforço estimado:** 1–2 semanas, dependente da integração/contrato do fornecedor.

---

## 8. Decisões que precisam de validação do produto

1. **Telefone:** aba ativa com 0 leads ou bloqueada com “1B” até existir cobertura? Recomendo bloqueada.
2. **Elegíveis vs disponíveis:** “Com telefone” deve listar só verificados ou também elegíveis para enriquecer? Recomendo só verificados + sub-filtro “elegíveis”.
3. **Sobreposição:** Carta e Telefone podem sobrepor-se? Recomendo sim (são vistas de prontidão).
4. **Mapa:** deve seguir a aba ativa? Recomendo sim, com label “Mapa: Carta/Visita”; caso contrário os counts do mapa não batem com a lista.
5. **Copy:** “mailing verificado” só depois de `mailing_verified`; até lá, “pronto para carta”.
6. **Cobertura:** com 34/45k, aceitamos mostrar a aba com estado de cobertura ou só a ativamos acima de um limiar? Recomendo mostrar com estado explicativo e trabalhar o enrich em paralelo.

---

## 9. Conclusão

A segmentação é **simples de consultar** e **complexa de preencher**. O desenho certo é:

- **materializar prontidão** (não calcular no cliente nem em `COALESCE` por pedido);
- **índices parciais** por `signal_ready`/`phone_ready`;
- **API com `readiness` + counts** no mesmo filtro;
- **UI de dois níveis**: prontidão como abas principais, origem como filtro secundário;
- **telefone bloqueado no 1A** e ativado no 1B com Property Masters;
- **estados vazios honestos** e seed de staging populado.

Isto mantém o layout limpo, evita 7 pills e prepara o 1B sem refazer a interface.

# P0-0 — Experimento Searchbug (2026-10-29)

**Harness:** `docs/experiments/2026-10-29-p0-harness.py` · **Dados brutos:** `2026-10-29-p0-phone.jsonl`
**Chamadas:** 40 · **Cap:** $8,00 · **Telemetria:** 34 linhas `billed=1` (≈$6,80 assumidos; fatura por confirmar)
**Seed:** 20261030 · **Read-only sobre `leads`** · Telefones mascarados (últimos 4 dígitos)

---

## 1. Resultado em uma linha

| Achado | Evidência | Veredicto |
|---|---|---|
| **ZIP de 4 dígitos é rejeitado** | 5/5 chamadas Boston: `Please enter 5-digit ZIP Code` | **Correção obrigatória e determinística** |
| **Inversão LAST FIRST ajuda** | Pares: B ganha 4, A ganha 2, ambos 1, nenhum 3. Validados: B 3 vs A 1 | Direção positiva; **amostra insuficiente** (n=10) |
| **L3 sem nome é fraco** | 1/10 sucesso; 3 devolveram nome mas sem telefone | **Não serve** para o coorte de alta probabilidade |
| **Respostas não-JSON** | 19/40 (47,5%), ~150 ms, `billed=1` | **Problema crítico de transporte/faturação** |
| **Falsos positivos** | 4/10 sucessos brutos com `name_match=0` (pessoa errada) | **Validação por nome é obrigatória** |

---

## 2. Por braço

| Braço | n | Sucessos brutos | Validados (match ≥0,5) | Erros |
|---|---:|---:|---:|---|
| A — ordem atual | 10 | 3 | **1** | 6 não-JSON, 1 no_results |
| B — invertida | 10 | 5 | **3** | 5 não-JSON |
| C4 — ZIP 4 díg. | 5 | 0 | 0 | **5 rejeições de ZIP** |
| C5 — ZIP 5 díg. | 5 | 1 | 1 | 2 não-JSON, 2 no_results |
| D — L3 sem nome | 10 | 1 | n/a | 6 não-JSON, 3 no_results |

**Sucessos com nome devolvido (A/B):**

| Braço | Dono | Devolvido | match |
|---|---|---|---|
| A | HOXHA ELJON | JAMES DOHERTY | **0,0** (errado) |
| A | MELORE BARBARA | BARBARA MELORE | 1,0 |
| A | WILKINS MICAH | MAXINE GREEN | **0,0** (errado) |
| B | VOLKERS OSVALDO | OSVALDO VOLKERS | 1,0 |
| B | WILKINS MICAH | MAXINE GREEN | **0,0** (errado) |
| B | SARFARAZ QURESHI | PARAMJIT SINGH | **0,0** (errado) |
| B | STELLA GLASS | LUZAIC STELLA | 0,5 |
| B | BOUZAS BENIGNO | BENIGNO BOUZAS | 1,0 |

O caso A `MELORE BARBARA` devolveu `BARBARA MELORE` com match 1,0: **o provider é tolerante à ordem em parte dos registos**. A inversão não é uma bala de prata.

---

## 3. ZIP (o achado mais forte)

```
C4  zip=2119  -> "Please enter 5-digit ZIP Code ..."   (5/5)
C5  zip=02119 -> 1 sucesso, 2 no_results, 2 não-JSON
```

- Boston tem **7.966 leads com ZIP de 4 dígitos** na base. Todos falham por validação.
- A correção (`zfill(5)`) é determinística e não precisa de mais chamadas.
- **Risco de faturação:** o código marca `Status=ERROR` como `billed=1`; estas 5 rejeições
  de validação não deveriam ser cobradas. Confirmar na fatura.

---

## 4. L3 sem nome

- 1/10 sucesso (`MERRY H / MOORE`, Chicago).
- 3/10 devolveram **nome mas sem telefone** (`BINU THOMAS`, `KATHERINE MIHLFRIED`,
  `CORI STANKOWICZ`) — sinal de que o L3 identifica a pessoa, mas a cobertura de telefone é baixa.
- Sem nome do proprietário, não há como validar `name_match`. Não entra no badge
  "Telefone verificado / Alta probabilidade".

---

## 5. Anomalia de transporte (crítica)

19 de 40 chamadas retornaram **HTTP 200 com corpo vazio/não-JSON** em ~138–193 ms
(vs. 3–4 s das respostas válidas). O código as classifica como `error` e **`billed=1`**.

Hipóteses: rate limit do provider (~30 chamadas/min), WAF/challenge, ou instabilidade
da API. Em produção, 10 utilizadores × 10 revelações no mesmo minuto reproduziriam isto.

**Ações obrigatórias no P0-C1:**
1. Classificar como `transport_error`, **não** `billed` até prova em contrário.
2. Retry com backoff (1×) apenas em `transport_error`.
3. Intervalo mínimo entre chamadas + concorrência máxima 2.
4. Circuit breaker: 3 não-JSON consecutivos → pausa 60 s + alerta no Control Tower.
5. Confirmar com a Searchbug se respostas vazias são faturadas.

---

## 6. O que ficou provado — e o que não ficou

**Provado:**
- ZIP de 4 dígitos falha sempre; corrigir é obrigatório.
- O provider devolve telefone de **outra pessoa** com frequência (4/10 dos sucessos brutos).
  Sem `name_match`, a taxa de "sucesso" é ficção.
- `PHONE_TYPE`/`CARRIER`/`IS_CONNECTED` **não vêm** na resposta `api_nape` (todos `None`).
  A validação só pode ser `name_match` + NANP.
- Existe um modo de falha de transporte que hoje é contabilizado como chamada paga.

**Não provado:**
- Que a inversão global chega a 70–80%. O sinal é positivo (+2 validados), mas n=10 e
  19/40 chamadas perdidas. **Não se justifica flip global.**
- Que o L3 sem nome sustenta o produto. 1/10 é insuficiente.

**Leitura honesta da meta:** nos 21 chamadas com resposta válida, houve 10 telefones
brutos (48%), mas apenas **4 com nome compatível (19%)**. O gargalo da promessa de
70–80% é **validação**, não hit rate bruto. Sem resolver isso, subir a taxa bruta só
aumenta o número de telefones errados entregues.

---

## 7. Decisões para o P0-C1

| # | Decisão | Base |
|---|---|---|
| 1 | `zfill(5)` em todo o ZIP de 4 dígitos antes da chamada | 5/5 rejeições |
| 2 | Inversão **condicional** (3+ tokens com inicial final; 2 tokens em NYC/Boston/Dallas), com `name_match` obrigatório — **não global** | +2 validados, provider tolerante |
| 3 | L3 sem nome só como "sob consulta"; nunca badge de alta probabilidade | 1/10 |
| 4 | `transport_error` separado de `no_results`; não faturar; retry/backoff; circuit breaker | 19/40 |
| 5 | Badge "verificado" só com `name_match ≥ 0,6`; sem `PHONE_TYPE` | 4 falsos positivos |
| 6 | Reconciliar a fatura: 34 `billed=1` vs chamadas realmente cobradas | $6,80 assumidos |

**Próximo passo:** implementar 1–4 no P0-C1 e medir os primeiros **100 reveals de produção**
com `lead_id`, `owner_class`, `layer`, `name_match` e `transport_error`. A prova de 70–80%
vem dessa medição, não deste experimento.

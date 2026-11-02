# Investor Room (Fase 30 / 1A)

Rota: **`/admin/investor-room`** (link no header do `/admin`).
Read-only sobre `leads.db`/`analytics.db`; escreve apenas em `investor.db`.

## Preço — weekly pass

- **$120 / 7 dias / empreiteiro**.
- Normalização mensal **52/12** = **$520/mês**; **$6.240/ano**.
- **Nunca** usar 4 semanas/mês ($480), que subestima a receita.
- O painel separa:
  - **passes com acesso** (`users.plan_until` futuro);
  - **pro active** (podem ser grants/testes; não são cash);
  - **passes pagos verificados** (0 até reconciliação Stripe↔acesso);
  - **cash Stripe 30d** (fonte de dinheiro).

## Reconciliação

O Stripe é a fonte de cash; `plan_until` é a fonte de acesso. Estados:
`ok`, `access_without_verified_payment`, `stripe_events_without_checkout`,
`cash_without_mapping`, `pro_active_without_access`.

Snapshot guarda `reconciliation` e o CSV exporta os valores. Enquanto não houver
mapeamento, o MRR verificado é **0** e o run-rate de acesso é apresentado como
não verificado.

## Piso patrimonial

```
dados      = owners × ($0,50–$1,50)
IP         = (12–18 meses) × ($8k–$15k)
compliance = $10k–$25k
piso       = dados + IP + compliance
```
É **custo de substituição**, não valor de mercado. O ARR é o going concern;
o piso é o argumento de negociação.

## Proof of Truth

- Owner coverage, morada, frescura, proveniência.
- **Phone Truth — em remediação**: mostra `success`, `error` (incluindo
  cobrados), `no_results`, `name_mismatch`, `transport_error`, custo e
  custo/sucesso. Não declarar precisão sem amostra.
- E-mail: enviados, bounces, respostas, supressões.
- System Health 100/100.
- Anti-Angi: **Claims Register** pendente de URL/data/legal; sem preços
  hardcoded.

## Simulador

Inputs: empreiteiros, caixas, cidades, revelações/empreiteiro/mês, churn,
múltiplo, opex fixo. Outputs: WRR, MRR, ARR, COGS, margem bruta, margem
líquida, LTV, valuation 2×–8× e EV range com piso patrimonial.

O endpoint `POST /api/admin/investor/simulate` é puro e não escreve na BD.

## NDA, export e impressão

- **NDA em 1 clique** para dados avançados (aba Comprador, CSV, impressão).
- Aceite versionado em `nda_acceptances` com e-mail, timestamp, IP em hash e UA.
- **CSV** com colunas `viewer_email`, `exported_at`, `doc_id` em todas as linhas
  e log em `access_log`.
- **PDF** via Print-to-PDF do browser com watermark diagonal
  `CONFIDENTIAL · email · data · checksum` (Fase 1A). Gerador server-side na 1B.
- Aba Comprador mostra inventário de código, testes, cobertura, dívida técnica,
  portabilidade e transição 30/60/90; data room/ACL completo na 1B.

## Operação

- Snapshot diário na Control Tower (`05:05 UTC` + primeiro tick) e refresh
  manual (cache 60 s).
- `investor.db` separado; retenção de snapshots e access log sem PII.
- Variáveis: `INVESTOR_DB_PATH` (opcional), `STRIPE_API_KEY` (read-only para
  cash).
- Testes: `tests/test_investor.py`, `tests/test_admin_panel.py`; cobertura
  publicada em `docs/TEST-COVERAGE.md`.

## Fase 1B

- Aba Comprador completa e data room com ACL.
- PDF server-side com watermark forte.
- Links externos NDA para investidores/compradores.
- Reconcilição Stripe↔utilizador automática e remediação Searchbug.

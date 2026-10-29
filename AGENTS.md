# AGENTS — Magic Leads / Garimpador Leads

Contexto completo e números medidos: **`docs/PROJECT-MEMORY.md`**. Ler antes de alterar código.

## Invariantes que não podem ser quebrados

1. **Outreach é sempre em inglês.** Não passar `lang` do locale para `buildOutreachMessage`.
2. **Outreach nunca contém morada, número de porta, "311", "complaint", "violation",
   "report", "case" ou "denúncia".** O contexto preditivo vive só no briefing interno da
   dashboard, nunca na mensagem ao proprietário.
3. **Filtro "Tipo"**: `signal_type` ∈ {`legal_obligation`, `authorized_work`, `open_request`};
   `signal_status` ∈ {`open`, `closed`, `unknown`}. **311 nunca é `legal_obligation`.**
   Fechados fora do feed por defeito. Badges derivam de `signal_type`, não de `source_type`.
4. **Ciclo de vida**: reserva 60 min → contacto 48 h → negociação 48 h → conversão terminal.
   Watchdog em processo a cada 15 min.
5. **Telefone**: nunca chamar a Searchbug no clique. Cache em BD (`phone_lookups`, TTL 90 d).
   Placeholders (`UNAVAILABLE OWNER`, `TAXPAYER OF`, …) vão para `guard_skipped`.
6. **Contrato de API**: `lead.owner_phone` (topo) e `res.owner.phone` (reveal) não mudam de nome.
7. **Mapa**: `leads.address/city/state/zip_code/lat/lng` são a fonte. `owners`/`address_key`
   agrupam, não substituem a morada de exibição.
8. **WAL já está ativo** (`backend/services/db.py:875`) e o backup já usa a API de backup do
   SQLite (WAL-safe). Não reimplementar.
9. **`leads` = 1 linha por endereço/cidade.** Reincidência tem de ser guardada em
   `lead_case_history` (uma linha por ocorrência).
10. **Custo**: telefone é **on-demand**, nunca em lote. `ENRICH_MAX_CALLS_PER_DAY=0` por
    defeito. Toda a chamada paga exige `trigger` explícito (`user_click`/`admin_manual`/`batch`).
    Gate = **cota individual** (10 revelações/dia) + orçamento de tentativas por utilizador
    (30/dia, 3/min). **Sem tecto global diário/mensal bloqueante** — isso travaria clientes
    pagantes; o gasto global é só alerta. Só se chama quando o lead pode ser cobrado.
11. **Cache**: `phone_lookups` em BD (TTL 90 d hit / 7 d miss / 1 h erro). O dicionário em
    memória não é fonte de verdade. Negativo válido nunca gera segunda chamada.
12. **Fatura**: `no_results` pode ser cobrado. Preço real confirmado: **$0,20/chamada**
    (`SEARCHBUG_PRICE_PER_CALL_USD`). Reconciliar semanalmente; `credit_ledger.amount=0`
    não é auditoria de custo.
13. **Alertas — gate**: só `signal_type` permitido, nunca `closed`, nunca institucional,
    morada resolvível e ≤48 h **ou** `repeat_365 ≥ 2`. O planner lê o contexto por
    `get_leads_for_alert` (não o dict do insert).
14. **Alertas — nicho estrito**: `get_users_interested_in(..., strict=True)`.
    **Sem `user_interests` não há alerta individual** (só onboarding/digest).
15. **Alertas — distância**: é **informativa/ordenação**, nunca filtro. O default é
    **toda a cidade / sem limite**; um lead a 28 mi é notificado. Não criar raio bloqueante.
16. **Alertas — quiet hours**: 21:00–08:00 `America/New_York`. 311/obra não geram push
    (in-app sim); `legal_obligation` passa. Digest não nasce no silêncio.
17. **Alertas — entrega**: TTL **nunca 0** (lead 4 h, digest 12 h), `Urgency` por sinal e
    `send_to_all` respeita `push_enabled`. Web Push não suporta som personalizado por
    ficheiro: usar vibração (payload) e, no máximo, chime in-app.
18. **Alertas — 1 push por run**: ≥2 leads do mesmo run são coalescidos num resumo
    (“Ver oportunidades”); 1 lead vai individual. O digest não faz segundo push no
    mesmo run. Min-gap default 30 min (in-app continua sempre).
19. **Alertas — clique**: `nid` assinado por HMAC (`push_click`); o endpoint é público
    mas só aceita assinatura válida. Nunca expor dados no endpoint.
20. **Devices**: máx. **5** push subscriptions ativas por utilizador; desativar (não
    apagar) as antigas; poda >90 d mantém sempre a mais recente.
21. **Alertas — preferências**: `user_interests.push_enabled` desliga só o push daquele
    ofício (in-app completo); `digest_enabled` default **1**; `lifecycle_push_enabled`
    default **0**. Editar a seleção de ofícios **preserva** o estado dos sinos.
22. **Alertas — digest sem ofícios**: quem não escolheu nicho recebe **um** digest diário
    (nunca alerta individual), fora do silêncio e depois do onboarding.
23. **Lifecycle push**: opt-in; só `reveal_*`/`stage_*` com <45 min; o aviso crítico
    (`reveal_urgent`) é o único autorizado a furar as quiet hours. `pushed_at` garante
    idempotência; sem acesso vigente não há push.
24. **Geo**: distância de NYC vem de **BBL → PLUTO** (`geo_lookup`), nunca de APIs pagas.
    `bbl_coords` é cache (hit e miss); não inventar coordenadas quando o BBL falha.
    O PLUTO devolve BBL como número com decimais — normalizar para 10 dígitos.
25. **Chime**: só in-app, no máximo 1 vez por aumento de unread, nunca com a aba oculta.
    Ficheiro próprio em `public/sounds/`; o Web Push não escolhe som.
26. **A/B do digest**: bucket estável (paridade do id), variante fixada no primeiro digest
    do dia. Não declarar vencedor com <30 envios com push por braço.
27. **Regra de ouro de IP**: nenhum termo das fontes/arquitetura (`311`, Socrata, CKAN,
    DOB, HPD, scraper, API, Open Data, dataset, BBL/BIN) pode aparecer em UI, push,
    e-mail, sino in-app ou docs de cliente. Toda a limpeza passa por
    `backend/services/privacy.py` (`scrub`/`sanitize_lead`); `source`/`department`
    saem `None` para o cliente e `source_type` é mapeado para token neutro. O admin
    (interno) continua a ver os dados crus. `tests/test_privacy_terms.py` é o guarda.

## Verificação mínima antes de deploy
```bash
pytest tests/ -v
ruff check . --select=E,F,W,I --ignore=E501
cd frontend && npx tsc --noEmit
```
Deploy: Railway, serviço `magic-leads`, branch **`master`**.

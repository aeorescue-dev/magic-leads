# Dashboard — prontidão para o beta inicial (MVP operacional)

Data: 2026-11-13
Branch: `staging/opportunity-foundation`
Produção: `master` em `3b53962` — intocada.
Landing page: **congelada** (`git diff` vazio; nenhum ficheiro de marketing alterado).

## 1. Estado atual — verde

| Item | Estado |
|---|---|
| Landing page | congelada, sem alterações |
| Oportunidades preventivas | 14 |
| Leads reativos | 4 |
| Reservas ativas | 0 |
| Property locks | 0 |
| Revelações hoje | 0 / 10 |
| Erros de consola no dashboard | 0 |
| Servidores | backend 200 · frontend 200 |

Smoke test em `/en/dashboard` (sem consumir dados):
- 14 cartões na fila de pré-inspeção;
- drawer com timeline, proprietário, valor estimado e CTA;
- modal de consentimento com checkbox e botão de reserva;
- 0 erros.

O ciclo completo 1h → 48h → 48h (reserva → contacto → negociação → conversão) já foi
validado em staging; desde essa validação só houve alterações de dados e documentação, não
de código do dashboard.

## 2. O que está certificado para o beta

- Login, sessão e quota diária (0/10).
- Aba preventiva com 14 cartões, filtros e rail.
- Drawer lateral com todos os campos e tags.
- Modal de consentimento obrigatório.
- Reserva atómica de 1 hora; `PROPERTY_LOCKED` devolve 409 e estorna quota.
- Guia de ciclo de vida com contacto, negociação e conversão.
- PT / EN / ES completos.
- Erros por código estável com tradução.
- Landing congelada; produção isolada.

## 2.1 Ajustes de estabilidade aplicados

- **Feed atualiza sozinho** após reservar, contactar, negociar ou converter: um evento
  interno (`magic:opportunities-refresh`) faz o `PreventiveFeed` recarregar, mantendo o
  cartão e o rail coerentes sem refresh manual.
- **Datas do seed relativas**: prazos e `received_at` passam a ser calculados a partir do
  dia atual (ex.: +1/+2/+6 dias). O demo mantém-se fresco em qualquer dia de beta e a
  série de 10 dias dos KPI continua preenchida.
- **Script de contas beta**: `scripts/create_beta_tester.py` (guardado por
  `ALLOW_STAGING_SEED` + `LEADS_DB_PATH`) cria/renova conta, concede acesso por N dias e
  ativa os 16 ofícios. Suporta `--dry-run`.
- Smoke test repetido após os ajustes: 14 cartões, drawer, consentimento e 0 erros.

## 3. Limitações aceites para o beta (não bloqueiam)

- 1 worker uvicorn: suficiente para o volume inicial; otimização de 100+ fica para depois.
- Ingestão preventiva real ainda não agendada; o beta usa o seed de 14 oportunidades.
- Managing Agent depende de BBL na fonte; sem BBL não aparece.
- Sem testes de carga de grande escala nesta fase.

## 4. Plano de lançamento beta

### T-1 (véspera)
1. Reset controlado da base de staging e seed final (14 preventivos + 4 reativos).
2. Confirmar quota 0/10, 0 reservas, 0 locks.
3. Criar contas dos beta testers, conceder acesso e definir interesses.
4. Enviar guião de teste e canal de suporte.

### T0 (abertura)
5. Confirmar `/health`, `/api/scraper/status` e login.
6. Liberar acessos em lotes pequenos (ex.: 5 utilizadores por vez).
7. Monitorizar: erros 5xx, 409, quota, tempo de resposta, feedback.

### T+1 / T+7
8. Recolher feedback estruturado (formulário curto).
9. Corrigir apenas bloqueios críticos; nada de refactors.
10. Decidir go/no-go para o próximo lote com base em: conclusão do fluxo, erros e feedback.

## 5. Guião de aceitação do beta tester

1. Entrar em `/{locale}/auth` com a conta fornecida.
2. Abrir **Pré-inspeção** e confirmar os 14 cartões.
3. Filtrar por cidade, especialidade, gravidade e “somente com prazo”.
4. Abrir um cartão, ler a timeline e o proprietário protegido.
5. Clicar em **Revelar dados do proprietário**, aceitar o consentimento e reservar.
6. Confirmar o contador de 1 hora no guia.
7. Avançar para **Contactar** e **Negociar** (48h cada).
8. Confirmar a conversão e verificar o estado final.
9. Repetir em PT/EN/ES (pelo menos o onboarding e o drawer).

## 6. Critérios de go/no-go

**Go:** login estável, 14 preventivos visíveis, reserva + consentimento + guia funcionam,
contacto/negociação/conversão concluem, 0 erros críticos, feedback inicial positivo.

**No-go:** falha de login, perda de dados, reserva sem lock, erro não traduzido, quota
incorreta, crash no drawer/guia.

## 7. Operação

- Base: `C:\Users\Fabio\AppData\Local\Temp\opencode\staging-opportunity\leads.db`.
- Backend: `127.0.0.1:8010` com schedulers desligados.
- Frontend: `localhost:3000`.
- Credenciais de demonstração: `staging@magicleads.app` / `Staging123!`.
- Rollback: restaurar a base de staging a partir do seed; produção nunca é tocada.

Produção continua em `master` `3b53962`, intocada e isolada.

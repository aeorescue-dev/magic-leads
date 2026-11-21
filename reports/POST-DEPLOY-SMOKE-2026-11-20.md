# Pos-deploy: backfill, deploy e smoke (2026-11-21 UTC)

**Estado:** backfill aplicado (2.199 linhas), backend Railway em `67f034e`, frontend
Vercel `ooh8n7xzg` (alias `www.magicleads.app`), ambos Ready.
`VOICE_FREEZE=1` mantido; frente BR (`feat/br-environmental-mvp`) intacta.

---

## 1. Backup previo (obrigatorio)

O volume `/data` estava **100% cheio** (879 MB, 0 B livres), o que impedia
qualquer backup. Sequencia executada:

1. Backup completo verificado para `/tmp/leads.db.bak-20261121-042559`
   (415.166.464 B, `quick_check=ok`, **163.203 leads**, **10.501 oportunidades**).
2. Removido o backup obsoleto de 2026-11-15 (280 MB, 266 oportunidades).
3. `PRAGMA wal_checkpoint(TRUNCATE)` → WAL de 134 MB para 0.
4. Backup duravel comprimido em `/data/leads.db.bak-20261121-042559.gz`
   (74.330.966 B), verificado por hash apos descomprimir:
   `41482d9da2541e80ec37a9f8b23d3d91fe92332722bc05c3f1c99e18eaae9fea`.
5. Espaco livre apos backup: ~340 MB.

---

## 2. Backfill `source_kind` (--apply)

| Cidade | Tipo | Linhas |
|---|---|---:|
| Chicago | legal_obligation -> reactive | 561 |
| NYC | legal_obligation -> reactive | 150 |
| Boston | authorized_work -> permit | 590 |
| Dallas | authorized_work -> permit | 898 |
| **TOTAL** | | **2.199** |

Depois: `open_request` 8.302 (preventive) · `authorized_work` 1.488 (permit) ·
`legal_obligation` 711 (reactive). Zero alteracoes em preventivos.
Log: `reports/backfill-apply-2026-11-20.txt`.

---

## 3. Deploy

- Backend Railway: deployment `828bbc58`, commit **`67f034e`**, SUCCESS,
  `/health` = `{"status":"healthy"}`.
- Frontend Vercel: deployment `ooh8n7xzg`, Production, aliases
  `www.magicleads.app` / `magicleads.app`. Bundle contem `no_fine_data`,
  `deadline_within` e "No fine source for this city".
- Commits: `abf1359` (backend), `c29ddc6` (frontend), `67f034e` (docs).

### Nota — preview BR na Vercel

O push de `67f034e` disparou tambem um **preview** do projeto
`magic-leads-br-staging`, que falhou porque o projeto espera a Root Directory
`br/web` (nao existe no `master`). E um build de preview, nao a producao:
`www.magicleads.app` nao foi afetado e a branch `feat/br-environmental-mvp`
continua intacta. Se quiser, o preview pode ser desligado nas definicoes do
projeto para nao gerar ruido.

---

## 4. Smoke de producao (API real, codigo `67f034e`)

Janela 7d; chamadas `opportunity_workflow.list` + `insights` no contentor de
producao (read-only).

| Cidade | Abas (all/prev/react/permit) | Prazos 7d | Multas em risco | `fines_available` |
|---|---|---|---:|---|
| **NYC** | 469 / 319 / 150 / 0 | 52 (reactive) | $467.650 (98) | true |
| **Chicago** | 96 / 0 / 96 / 0 | 0 | $0 (fontes novas ainda nao ingeridas) | true |
| **Boston** | 548 / 336 / 0 / 212 | 393 (preventive) | $0 (idem) | true |
| **Dallas** | 545 / 41 / 0 / 504 | 6.855 (preventive, total) | $0 | **false** |

- **Dallas** devolve `fines_available=false` — a UI mostra `-` / "sem dados de
  multa" e desativa "Com multa". E o comportamento esperado.
- **Chicago/Boston** ficam com `fines_available=true`; as multas novas
  dependem da ingestao P1 (abaixo).

---

## 5. Incidente: ingestao P1 abortou por 503 transitorio

O primeiro `run_operational` devolveu `status=error` com
`The read operation timed out` e **nao escreveu nada** (10.501 antes e depois).
Causa: uma fonte externa falhou (Socrata devolveu 503/timeout) e o
`build_candidates` abortava **todas** as fontes.

**Correcao:** cada fonte passou a ser isolada (`collect(...)`), com erros
registados em `stats["source_errors"]`; o scheduler devolve `partial` em vez de
`error` e as restantes fontes continuam a entrar. Teste novo:
`test_one_failing_source_does_not_abort_the_run`.

---

## 6. Verificacao visual (pendente de sessao ativa)

O dashboard abre em **modo Free** com a conta demo (`demo@magicleads.app`,
`plan_until=2025-12-31` expirado): KPIs a zero, sem feed. Para a conferencia
na tela (abas, prazos/multas, `-`/sem dados, LIMPAR) e preciso um login com
acesso ativo em producao.

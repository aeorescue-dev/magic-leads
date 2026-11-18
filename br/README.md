# Radar Ambiental BR — protótipo isolado

Protótipo de validação para o mercado brasileiro de consultoria/engenharia ambiental.
**Não toca na produção US.** Tudo vive em `br/` e num worktree separado.

## Demo publicada

- **Staging:** https://magic-leads-br-staging.vercel.app
- **Landing:** `/`
- **Dashboard:** `/dashboard.html`
- **Código:** branch `feat/br-environmental-mvp` (worktree `garimpador-leads-br`)
- **Dados:** snapshot de 18/11/2026 — 1.360 oportunidades, 650 autos IBAMA, 450 licenças MG, 260 licenças federais SISLIC. **Condicionantes:** 497 extraídas em 111 processos (amostra de 348); 112 visíveis no dashboard em 22 oportunidades.
- **Cobertura:** federal em todo o Brasil + MG (WFS). PR tem fonte em PDF identificada; parser na fase 2.
- **Billing:** simulado (mock). Sem cobrança real.
## Deploy Vercel

- Projeto: `magic-leads-br-staging`.
- **Root Directory:** `br/web`.
- **Framework:** Other (estático).
- Produção manual: **não** usar `vercel --prod` a partir de `br/web` (o Root Directory `br/web` já está definido no projeto). Fluxo correto: push na branch → preview Git → `vercel promote <preview-url> --yes`.
- Preview Git: qualquer push em `feat/br-environmental-mvp` gera preview.
- **Domínio final:** `br.magicleads.app` exige CNAME no Porkbun; o preview Vercel está público.

## Estrutura

```text
br/
  ingest/        pipeline de dados (IBAMA, SISLIC, MG WFS, CNPJ)
  .cache/        downloads e cache (não versionar)
  web/           landing + dashboard estáticos (Leaflet)
    assets/      data.json, GeoJSON dos estados, municípios
```

## Pipeline

```bash
cd br/ingest
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python fetch_sources.py --all
python enrich_cnpj.py --limit 60
python fetch_conditions.py --limit 30        # amostra do dashboard
python fetch_conditions.py --source mg --offset 0 --limit 500 --workers 6
python build_demo.py
```

`fetch_conditions.py` combina duas fontes públicas do SLA:

1. **Relatório de Cumprimento de Condicionantes (XLSX)** — status, histórico e periodicidade.
2. **Parecer Técnico/Único (PDF, Anexo I)** — texto da condicionante e prazo.

Cada processo gera um registo em `br/data/conditions.json` (chave = número do processo),
com `frequencies` (semanal…anual, única, durante vigência), `status`, `source` e o
documento de origem. O resumo do ficheiro (`coverage`) mostra quantos processos foram
verificados e por que motivo não têm condicionantes extraíveis.

**Carga completa de MG:** 19.713 licenças; o extrator aceita `--source mg` com
`--offset/--limit` e `--workers`. O progresso é retomável (cache por `idSolicitacao`
em `br/.cache/conditions/`). Ritmo observado: ~0,8–1,5 processo/s com 3–6 workers.

Saída: `br/web/assets/data.json`.

## Demo local

```bash
cd br/web
python -m http.server 8088
# abrir http://localhost:8088
```

- `/` — landing Brasil
- `/dashboard.html` — dashboard com mapa, filtros, dossiê e planos

## Dados

- **IBAMA autos** — CSV diário, PJ, cancelados fora, CNPJ completo.
- **IBAMA SISLIC** — licenças federais, validade, sem CNPJ.
- **SEMAD-MG WFS** — licenças estaduais, validade, CNPJ truncado (raiz).
- **Receita/Minha Receita** — CNAE e contacto comercial (sem CPF).
- **IBGE** — malha dos estados e municípios.
- **Detalhe de licenciamento** — `br/data/license_details.json`, indexado pelo número do processo. Inclui enquadramento, atividades, ADA, atos autorizativos, documentos e `conditions`.
- **Condicionantes** — `br/data/conditions.json`, por processo, com periodicidade, status e fonte documental. Alimenta o KPI, os filtros de periodicidade/status e a tabela do dossiê.

## LGPD

- Nunca exibir CPF, nome de sócio ou telefone pessoal.
- Apenas dados de empresa/CNPJ e contacto comercial.
- Fonte e data em cada registo; opt-out na landing.
- Protótipo de staging; não usar com dados de clientes reais.

## Fora do escopo desta demo

- Prefeituras (5.570).
- SINAFLOR/CTF atrás de Cloudflare.
- Cobrança real (Pix/Stripe) — mock apenas.
- PR: fonte PDF identificada; parser na fase 2.

## QA desta demo

- Landing, dashboard, dossiê e planos navegáveis em desktop e mobile.
- Sem erros de consola; sem overflow horizontal em 390px.
- Dossiê LGPD: CNPJ/empresa/CNAE; sem CPF, nome de sócio, telefone ou e-mail pessoal.
- Filtros por UF, município, tipo, fonte, categoria, multa, validade, **periodicidade da condicionante** e **status da condição**.
- Reserva de 72h e checkout simulados.

## Próximos passos

1. Carga completa de MG em lotes (19.713 licenças) e relatório de cobertura por UF/atividade.
2. Parser PR (PDFs mensais do IAT) e cobertura PR.
2. Autenticação de consultoria + billing BRL/Pix (Asaas/Stripe BR).
3. Alertas por e-mail reais e WhatsApp opt-in (template aprovado).
4. Página de cobertura pública por UF e API de dossiê.
5. Revisão jurídica da LIA/DPA e política de retenção.

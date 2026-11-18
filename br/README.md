# Radar Ambiental BR — protótipo isolado

Protótipo de validação para o mercado brasileiro de consultoria/engenharia ambiental.
**Não toca na produção US.** Tudo vive em `br/` e num worktree separado.

## Demo publicada

- **Staging:** https://magic-leads-br-staging.vercel.app
- **Landing:** `/`
- **Dashboard:** `/dashboard.html`
- **Código:** branch `feat/br-environmental-mvp` (worktree `garimpador-leads-br`)
- **Dados:** snapshot de 18/11/2026 — 1.360 oportunidades, 650 autos IBAMA, 450 licenças MG, 260 licenças federais SISLIC.
- **Cobertura:** federal em todo o Brasil + MG (WFS). PR tem fonte em PDF identificada; parser na fase 2.
- **Billing:** simulado (mock). Sem cobrança real.
## Deploy Vercel

- Projeto: `magic-leads-br-staging`.
- **Root Directory:** `br/web`.
- **Framework:** Other (estático).
- Produção manual: `vercel --prod` a partir de `br/web`.
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
python build_demo.py
```

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
- Filtros por UF, município, tipo, fonte, categoria, multa e validade.
- Reserva de 72h e checkout simulados.

## Próximos passos

1. Parser PR (PDFs mensais do IAT) e cobertura PR.
2. Autenticação de consultoria + billing BRL/Pix (Asaas/Stripe BR).
3. Alertas por e-mail reais e WhatsApp opt-in (template aprovado).
4. Página de cobertura pública por UF e API de dossiê.
5. Revisão jurídica da LIA/DPA e política de retenção.

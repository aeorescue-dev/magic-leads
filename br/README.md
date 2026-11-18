# Radar Ambiental BR — protótipo isolado

Protótipo de validação para o mercado brasileiro de consultoria/engenharia ambiental.
**Não toca na produção US.** Tudo vive em `br/` e num worktree separado.

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

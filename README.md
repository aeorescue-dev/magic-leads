# 🏗️ GARIMPADOR PREDITIVO DE LEADS — MVP FULL-STACK (CUSTO $0)

SaaS para contractors que monitora APIs de 311 (reclamações municipais) em tempo real,
extrai leads pré-qualificados de proprietários com problemas imobiliários, e entrega
um dashboard para contactar clientes **antes da concorrência**.

> **Arquitetura custo $0** (sem cartão em lugar nenhum): SQLite + Vercel Serverless + GitHub Actions.
> Sem Supabase pago, sem Railway, sem certas. Leia [DEPLOYMENT.md](./DEPLOYMENT.md).

## Stack (custo $0)

- **Backend:** Python 3.12 + FastAPI (+ SQLite)
- **Frontend:** Next.js 14 (App Router) + Tailwind CSS
- **Banco:** SQLite (`data/leads.db`, versionado no repo)
- **Scraping:** GitHub Actions (cron a cada 6h)
- **Hosting:** Vercel (frontend + serverless API)
- **Auth:** sessão local (cookie + localStorage)
- **Pagamentos:** adiado (Stripe só quando monetizar)

## ✨ Já validado

- ✅ Backend importa e expõe `/`, `/health`, `/api/leads`, `/api/scraper/run`
- ✅ Scraper **NYC 311 funcionando com dados reais** (65+ leads/48h via SoQL API)
- ✅ `/api/leads` com filtro por categoria e paginação
- ✅ Frontend builda (typecheck + prerender)

## Estrutura

```
garimpador-leads/
├── .github/workflows/scraper-cron.yml
├── api/            # Serverless Functions (Vercel) — FastAPI
├── backend/        # FastAPI + scrapers + SQLite service
├── frontend/       # Next.js 14 + Tailwind
├── data/           # SQLite (leads.db) versionado
├── vercel.json     # Config deploy Vercel
├── docker-compose.yml
└── DEPLOYMENT.md
```

## Rodando Localmente

```bash
# Backend
cd backend
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000  # localhost:8000

# Frontend (outro terminal)
cd frontend
npm install
npm run dev  # localhost:3000
```

Testar end-to-end:
```bash
curl -X POST http://localhost:8000/api/scraper/run   # popula o SQLite
curl "http://localhost:8000/api/leads?city=NYC"      # lista leads
```

## Deploy (grátis)

Ver [DEPLOYMENT.md](./DEPLOYMENT.md). Resumo: subir pra GitHub, importar no Vercel,
$0 e sem cartão.

## Roadmap

1. **Validar com contractors** — leads do 311 já funcionando
2. **Adicionar** Building Permits + Tax Delinquency + skip tracing
3. **Monetizar** com Stripe (Stripe só tem custo quando você cobra)
git commit --allow-empty -m "chore: trigger vercel deploy"
git push origin master

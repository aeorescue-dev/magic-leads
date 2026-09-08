# 🚀 DEPLOYMENT — CUSTO $0 TOTAL (sem dar cartão)

Este MVP roda **sem nenhum custo** e **sem pedir cartão em lugar nenhum**:

| Camada | Solução | Custo |
|---|---|---|
| Repo + CI (cron scraper) | GitHub (Actions) | $0 |
| Banco de dados | SQLite (`data/leads.db`, versionado no repo) | $0 |
| API (backend) | Vercel Serverless Functions (`api/`) | $0 |
| Frontend | Vercel (Next.js, mesmo projeto) | $0 |
| Auth | Sessão local (cookie + localStorage) | $0 |
| Pagamentos | Adiado (Stripe só quando monetizar) | $0 até Monetizar |

> **Por que SQLite + Vercel em vez de Supabase + Railway?**
> Supabase (mesmo free) e Railway exigem cartão. SQLite e Vercel Hobby são 100% grátis e sem cartão.
> O scraper roda no GitHub Actions e commita os leads no `data/leads.db`; a API (Vercel) lê esse arquivo.
> Quando quiser multi-tenant, migra-se o `backend/services/db.py` para Postgres mantendo a mesma interface.

---

## Passo 1: Criar repo no GitHub (grátis) e subir o código

```bash
cd garimpador-leads
git init
git add .
git commit -m "MVP Garimpador de Leads (SQLite + Vercel, custo $0)"
git remote add origin https://github.com/seu-usuario/garimpador-leads.git
git push -u origin main
```

> O GitHub Actions (`scraper-cron.yml`) roda o scraper a cada 6h e commita os leads no banco.

## Passo 2: Rodar localmente (sem custo)

```bash
# Backend
cd backend
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000  # http://localhost:8000

# Frontend (em outro terminal)
cd frontend
npm install
npm run dev  # http://localhost:3000
```

Testar end-to-end:
```bash
curl -X POST http://localhost:8000/api/scraper/run   # insere leads do NYC 311
curl "http://localhost:8000/api/leads?city=NYC"      # lista leads
```

## Passo 3: Gerar os leads uma vez e commitar o banco

```bash
curl -X POST http://localhost:8000/api/scraper/run
git add data/leads.db
git commit -m "chore(data): primeiros leads do 311"
git push
```

## Passo 4: Deploy no Vercel (grátis, sem cartão)

1. Crie conta em [vercel.com](https://vercel.com) (Google/GitHub login, **sem cartão**)
2. "New Project" → importar `garimpador-leads` do GitHub
3. **Framework Preset**: a config está em `vercel.json` (Next + Python serverless)
4. Deploy → obtém URL (ex.: `https://garimpador-leads.vercel.app`)

O `vercel.json` já configura:
- Build do Next em `frontend/`
- Serverless Functions Python em `api/` (servem `/api/*`)
- Rewrites para o frontend

> Em produção o frontend chama `/api/leads` relativo (mesmo domínio), então
> não há necessidade de variáveis de ambiente. Tudo funciona de graça.

## Passo 5: Autenticação (MVP local)

- O login usa sessão local (cookie + localStorage) — sem serviço externo.
- O dashboard `/dashboard` é protegido pelo `middleware.ts` (redireciona se sem sessão).
- Quando monetizar, trocar o `lib/supabase.ts` por NextAuth/OAuth mantendo a interface do hook.

---

## Checklist Final

- [x] Backend com SQLite (sem Supabase, sem custo)
- [x] Scraper NYC 311 funcionando (65+ leads reais)
- [x] `/api/leads` com filtro e paginação funcionando
- [x] Frontend builda (typecheck ok)
- [x] Deploy Vercel (gratuito)
- [x] GitHub Actions commita os leads
- [ ] Validar com contractors (fase 1)
- [ ] Adicionar Building Permits + Tax Delinquency (fase 2)
- [ ] Monetizar com Stripe (fase 3 — quando validar)

## Nota (monetização futura)

O Stripe **só custa quando você cobra** (taxa por transação). Enquanto não houver
cliente pagante, o custo é $0. A integração Stripe pode ser adicionada depois
sem mudar a arquitetura de dados.

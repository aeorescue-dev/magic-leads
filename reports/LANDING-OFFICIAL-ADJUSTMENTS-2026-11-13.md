# Landing oficial — ajustes de conversão aplicados (pré-avaliação)

Data: 2026-11-13
Estado: **aplicado no staging, não publicado** — produção `master` em `3b53962` intocada.
Página: `frontend/app/[locale]/(marketing)/page.tsx` (landing oficial, sem página paralela).

## 1. Página paralela removida

Removidos os artefactos da abordagem anterior:
- `reports/landing-preview-2026-11-13.html`
- `reports/LANDING-VISUAL-PROPOSAL-2026-11-13.md`

O trabalho passou a ser feito **diretamente na landing oficial**, preservando estrutura,
componentes e identidade visual existentes.

## 2. Alterações aplicadas

### 2.1 Hero (copy)
- Eyebrow: “ENCONTRE A SUA OBRA E FATURE!” → **“ANTES DA MULTA · EXCLUSIVO POR 1 HORA ·
  MERCADO AO VIVO”**.
- Sub: passou a abrir com **“Chamados municipais e avisos de conservação chegam ao seu radar
  antes de virarem problema…”**.
- Novo pill âmbar no hero: **“Prevenção ativa · antes da multa”**.

O headline principal (“O dono acabou de pedir a reforma. Você é o único com o telefone.”)
foi mantido: já converte e não foi substituído.

### 2.2 Nova secção `#prevencao` (na landing oficial)
Inserida entre a faixa de autoridade e a cobertura:
- Eyebrow **“Antes da multa”**.
- H2 **“O aviso chega antes do problema.”**
- 3 cartões no estilo `bento-light` existente: **Sinal identificado → Janela de vistoria →
  Risco de multa**.
- Cartão escuro (`landing-dark`) com a mini-timeline, chip **“Prazo ≤ 7 dias”**,
  **“1 hora exclusiva”** e a nota “Sinais proprietários MagicLeads. Inteligência de mercado.”
- CTA **“Começar com preventivos”** abre o modal de signup já existente.

### 2.3 Navegação
- Novo item **“Prevenção”** na navbar, a apontar para `#prevencao` (PT/EN/ES).

### 2.4 Preço
- `planFeatures` ganhou a linha **“10 revelações diárias: contactos de proprietário”**,
  no cartão do plano já existente.

### 2.5 FAQ
- Nova pergunta **“O que é a pré-inspeção?”** com resposta sobre chamados municipais e
  avisos de conservação que ainda não viraram multa.

## 3. Regra de ouro do copy — verificação

- Texto renderizado em PT foi varrido por `HPD`, `DOB`, `311`, `Socrata`, `Open Data`,
  `dataset`, `scraper`, `BBL`, `BIN` → **0 ocorrências**.
- Vocabulário usado: “chamados municipais”, “avisos de conservação”, “sinais proprietários”,
  “inteligência de mercado”, “radar”.
- Sem “créditos”/“saldo”; usa-se “revelações diárias” e “contactos”.
- Números continuam a vir das métricas públicas; nada inventado.

## 4. O que NÃO mudou

- Layout, componentes e classes base da landing (apenas a nova secção e o novo pill).
- Preços, checkout, backend, base de dados, autenticação.
- Headline, painel ao vivo, simulador, comparativo, calculadora e templates.
- Nenhum ficheiro de produção foi tocado.

## 5. Validação

| Verificação | Resultado |
|---|---|
| `npx tsc --noEmit` | limpo |
| `npx eslint . --quiet` | limpo |
| `npm test -- --run` | 123 passed (inclui paridade i18n) |
| Browser PT/EN/ES | hero e secção renderizam; 0 erros de consola |
| Copy proibido no body PT | 0 ocorrências |
| FAQ nova + revelações no preço | presentes |

Capturas: `C:\Users\Fabio\AppData\Local\Temp\opencode\landing-official\`
- `pt-hero.png`, `pt-prevencao.png`, `pt-preco.png`, `pt-faq.png`
- `en-prevencao.png`, `es-prevencao.png`, `pt-prevencao-mobile.png`

## 6. Pré-avaliação

Validar no staging:
1. `http://localhost:3000/pt` (também `/en` e `/es`).
2. Hero: eyebrow, sub e pill de prevenção.
3. Navbar → **Prevenção** (secção nova).
4. CTA **Começar com preventivos** (abre signup).
5. Preço e FAQ com as novas linhas.

Após o “ok” explícito, o trabalho segue para commit/deploy de staging. **Nada vai para
produção sem nova autorização.**

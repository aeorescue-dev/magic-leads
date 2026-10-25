# Revisão de Arquitetura: Bootstrapped & Low-Cost Email Discovery

**Status:** PROPOSTA — STOP & REVIEW. Nenhum código de produção foi alterado.
**Orçamento Alvo:** US$ 20–30/mês.
**Foco:** Engenharia "Zero-Cost" / Bootstrapped.

---

## 1. Mudança de Paradigma: Custo Zero para Descoberta

Para atingir o teto de US$ 20–30/mês, eliminamos a dependência de APIs de descoberta (Brave Search API, Hunter, Snov.io). O foco migra para **crawling vertical** e **heurísticas de padrões**.

### Nova Matriz de Custo (Escala 400 envios/dia)

| Etapa | Ferramenta | Custo Estimado |
|---|---|---|
| Descoberta (Domínio) | Scraper próprio (Headless/HTTP) + DuckDuckGo/Bing (Free Tier) | $0 |
| Verificação | EmailListVerify (Pay-As-You-Go: $27/10k) | $20–30/mês |
| **Total** | | **$20–30/mês** |

---

## 2. Pipeline "Bootstrapped" (Desenho)

### Camada L1: Extração de Domínio (Custo Zero)
O sistema não compra dados. Ele os "colhe":
1. **Scraping Direto de Fontes Públicas:** Em vez de API, o worker de descoberta faz `GET` em resultados de busca (DuckDuckGo/Bing) para `site:"empresa.com"` ou diretórios locais públicos (ex: bibliotecas de licenças locais, associações comerciais).
2. **"Website-First" Crawling:**
   - Worker extrai links do diretório/busca.
   - Analisa o texto do título/meta/corpo para confirmar a correspondência do `owner_name`.
   - Extrai o domínio principal do link.

### Camada L2: Permutação de Padrões (Custo Zero)
Com o domínio `empresa.com` validado, o sistema gera uma lista de candidatos prováveis:
- `info@empresa.com`
- `contact@empresa.com`
- `sales@empresa.com`
- `{firstname}@empresa.com` (extraído do `owner_name`)
- `{firstname}.{lastname}@empresa.com`

### Camada L3: Verificação de Alta Eficiência (Custo Otimizado)
Em vez de usar APIs de busca (caras), usamos **apenas verificação** (barata) no EmailListVerify.
1. O sistema submete os candidatos gerados (ex: `info@`, `contact@`, `owner@`) para a API de `verifyEmail` do EmailListVerify.
2. Custo: 1 crédito por e-mail verificado.
3. Se 1.000 créditos = US$ 2,70, com $27 temos 10.000 verificações/mês.
4. Otimização: Cache de domínios (" catch-all" detectado → parar buscas naquele domínio).

---

## 3. Estratégia Técnica de Mitigação de Riscos

### 3.1 Rate Limits e Bloqueios
- **IP Rotation:** Uso de proxies residenciais de baixo custo (ou proxies gratuitos com rotação em ambiente de staging).
- **Politeness:** `robots.txt`, `User-Agent` real, rate-limiting estrito por domínio (espera > 2s entre reqs).
- **User-Agent:** Simulação de browser real.

### 3.2 Otimização de Créditos (Economia Extrema)
- **Priorização de Padrões:** Verificar `info@` primeiro. Se `valid`, parar e salvar.
- **Cache de Domínio:** Se o domínio é um `catch-all` (a API de verificação retorna isso), o sistema não precisa gastar mais créditos para testar permutações; ele já sabe que qualquer tentativa pode parecer válida.

---

## 4. Roteiro Simplificado (Bootstrapped)

1. **Fase 0 (Spike):** Testar a taxa de sucesso de "Google/DDG + Parse de domínio" para 100 leads. *Custo: $0.*
2. **Fase 1 (Crawler):** Construir o worker que extrai o site e valida o domínio via DNS/HTTP. *Custo: $0.*
3. **Fase 2 (Gerador de Padrões):** Integrar a lógica de permutação de e-mails corporativos. *Custo: $0.*
4. **Fase 3 (Validação Pura):** Integrar apenas a API `verifyEmail` do EmailListVerify (pay-as-you-go). *Custo: ≤ $30/mês.*

---

## 5. O que pedimos para avançar

1. **Aprovação da mudança:** Aceitam o abandono de APIs de descoberta (Brave/Hunter/Snov) em favor do scraper próprio?
2. **Validação do fornecedor:** Concordam em usar o EmailListVerify exclusivamente para verificação (Pay-As-You-Go)?
3. **Ambiente:** Podemos avançar para a Fase 0 (script de spike para medir taxa de sucesso da extração de domínios)?

**Estamos prontos para implementar a arquitetura de custo zero. Aguardamos sua autorização.**

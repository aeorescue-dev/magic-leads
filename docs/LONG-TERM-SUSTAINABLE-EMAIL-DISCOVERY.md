# Arquitetura de Longo Prazo: Motor de Outbound Híbrido, Multicanal e Sustentável ($0 APIs / $30 Teto)

**Estado:** PROPOSTA ANALÍTICA — STOP TOTAL DE EXECUÇÃO. Nenhum código ou script foi executado.
**Horizonte:** 12 a 24 meses (Perpétuo / Altamente Escalável).
**Orçamento Operacional:** Máximo de US$ 20–30/mês (Pay-As-You-Go estrito na validação final).

---

## 1. O Desafio Estrutural: Empresas Sem Website no Setor de Construção

No ecossistema de contratantes (General Contractors, Roofers, Plumbing, etc.), a premissa de que "toda empresa tem um domínio web" falha em **35% a 50% dos casos** (especialmente microempreiteiros, operadores locais independentes e subcontratados tradicionais). 

Se a arquitetura depender exclusivamente de `empresa.com`, perderemos metade do mercado e esgotaremos a base rapidamente. A solução exige uma **arquitetura de fontes híbridas e multicanal de custo zero**.

---

## 2. Estratégia de Extração Multicanal e Híbrida ($0 em APIs Pagas)

Para garantir autonomia e longevidade sem recorrer a APIs comerciais caras (Brave, Hunter, Snov), o motor cruza dados em **4 camadas nativas**:

### Camada A: Registos Públicos de Licenciamento (Socrata / CKAN / 311) — *Já Operacional no Core*
- **O que extrai:** Razão social (`owner_name`), morada do imóvel/projeto, categoria de ofício, telefone (`owner_phone` quando disponível em licenças DOB) e geolocalização.
- **Papel na arquitetura:** É a âncora de demanda. Define *quem* está a fazer obras agora na praça.

### Camada B: Diretórios Públicos Locais e Registos Municipais de Licenciados
- **Fontes:** Registos públicos estaduais de licenças de construção (ex: NY Department of State - Division of Corporations, NYC DCA Licensed Businesses, Illinois Department of Financial and Professional Regulation, etc.).
- **Mecanismo:** Os scrapers internos já existentes na base do projeto varrem estas páginas públicas (que são em HTML/JSON aberto) para correlacionar o nome exato da empresa (`owner_name`) com o seu registo legal oficial, obtendo dados secundários como **e-mails de registo cadastrados na prefeitura** (muitos contatadores deixam e-mails públicos obrigatórios para renovação de licença).

### Camada C: Perfis Corporativos Públicos e Diretórios de Negócios (Open Data / OSM / Motores de Busca Livres)
- **Fontes:** OpenStreetMap (Overpass API — gratuita), diretórios abertos locais e meta-tags de resultados públicos de busca (via motores que permitem parsing livre ou indexadores abertos).
- **Mecanismo:** Pesquisa textual cruzada (`"Nome da Empresa" AND "NYC" AND "General Contractor"`). Quando a empresa não tem site, estes diretórios frequentemente acumulam o **e-mail de contato público** inserido pelo próprio prestador anos atrás.

### Camada D: Derivação de Domínio e Permutação Sintética (Fallback)
- Se a empresa **possui** website (descoberto nas Camadas A-C ou via busca livre): extração do domínio e execução de permutação (`info@`, `contact@`, `owner_name@`).
- Se a empresa **não possui** website (o caso crítico): passa para a Estratégia de Derivação Sem Domínio (Secção 3).

---

## 3. Plano Técnico para Empresas Sem Website ("Zero-Domain Strategy")

Quando uma empresa opera apenas com razão social, morada, telefone e nome do responsável, mas **não tem domínio web próprio**, o sistema aplica um pipeline alternativo para encontrar ou derivar um canal de e-mail válido:

1. **Análise de E-mail Baseado em Provedores Genéricos / Comerciais:**
   - Pequenos empreiteiros frequentemente utilizam e-mails associados a provedores de banda larga local ou serviços legados (ex: `@verizon.net`, `@comcast.net`, `@aol.com`, `@gmail.com`, `@yahoo.com`).
   - O sistema cruza o `owner_name` e a morada com bases de dados públicas de registo de empresas para verificar se há rastos de e-mails pessoais/comerciais indexados em diretórios de licenças.

2. **Derivação via Número de Telefone (`owner_phone`):**
   - Em licenças municipais (como NYC DOB), o telefone do requerente é frequentemente obrigatório.
   - O sistema utiliza o telefone como chave primária secundária em buscas reversas em diretórios abertos públicos para descobrir se esse número está associado a um e-mail público em fóruns de classe ou registos de associados da construção civil.

3. **Validação Rigorosa por Camada de Teste (EmailListVerify):**
   - Mesmo sem site, se houver uma suspeita razoável de e-mail (ex: derivado do nome do dono `joaosilva@gmail.com` ou `joao@silvaconstruction.local`), a string é submetida diretamente à API de `verifyEmail` do EmailListVerify.
   - *Nota de Engenharia:* E-mails pessoais (`@gmail.com`) ou de provedores comuns que passam na verificação de entrega são aceites, mas rotulados com menor prioridade que e-mails corporativos, garantindo que o canal de outbound atinja o empreiteiro mesmo que ele não tenha um site na internet.

---

## 4. Análise de Saturação e Volume Volumétrico (12 a 24 Meses)

A grande preocupação de arquitetura é: *"O pipeline vai esgotar a base rapidamente?"*
A resposta técnica é **não**, desde que o motor opere como um **fluxo contínuo acoplado ao fluxo de novas licenças (real-time stream)**, e não como um dump estático.

### 4.1 Dinâmica de Renovação da Base (O Fluxo Perpétuo)
No setor de construção nas 4 praças (`SERVED_CITIES`: NYC, Chicago, Dallas, Boston):
- **Novas licenças e permissões de obras públicas** são emitidas diariamente (centenas de novos permits por dia por cidade).
- O scraper do sistema (`_scheduler_loop` / varreduras periódicas) injeta continuamente **novos leads** na tabela `leads`.
- Portanto, a base **nunca estagna**, porque a economia real gera obras novas todos os dias. O inventário de oportunidades renova-se organicamente a cada 24–48 horas.

### 4.2 Projeção de Crescimento e Consumo (12 a 24 Meses)

| Métrica | Estimativa Mensal | Estimativa Anual (12 Meses) |
|---|---|---|
| Novos leads brutos captados (4 praças) | ~15.000 a 25.000 leads/mês | ~180.000 a 300.000 leads |
| Leads com potencial de enriquecimento (`owner_name` ou `phone`) | ~8.000 a 12.000 / mês | ~100.000 a 140.000 / ano |
| E-mails descobertos e validados (yield 40%) | ~3.200 a 4.800 / mês | ~40.000 a 58.000 e-mails válidos/ano |
| Volume consumido pelo Outbound (`daily_send_cap` = 100/praça = 400/dia) | ~12.000 envios / mês | ~144.000 envios / ano |

### 4.3 Prevenção de Saturação (Anti-Esgotamento)
Para evitar que o sistema re-procure os mesmos leads ou esgote a praça:
- **Dedemocratização e Deduplicação Rígida:** A tabela `leads` usa restrições únicas (`UNIQUE(external_id, source_type)`, `UNIQUE(address, city)`).
- **Caches Negativos com TTL (Time-To-Live):** Leads que falharam na descoberta de e-mail recebem uma marcação de estado `domain_fail` / `email_fail` com TTL de 90 dias. Eles não consomem orçamento diário de processamento.
- **Rotação de Nichos:** O motor alterna os lotes entre os 16 ofícios e os 8 nichos de outbound, garantindo que o mesmo empreiteiro não receba estímulos excessivos e que o inventário seja distribuído ao longo do ano.

---

## 5. Viabilidade Orçamentária Estrita ($20–$30/mês)

Como o plano se mantém rigorosamente dentro do teto financeiro estabelecido?

1. **Descoberta de Domínio e Extração (Camadas A, B, C, D): Custo = US$ 0,00**
   - Todo o crawling de diretórios, parsing de HTML, análise de licenças públicas, cruzamento de dados locais e geração de permutações sintéticas roda 100% na infraestrutura própria (servidor backend existente / Railway / Docker), utilizando código Python assíndrico (`asyncio`, `httpx`, `BeautifulSoup`). **Nenhuma API de terceiros paga é consultada para descobrir o e-mail ou o site.**

2. **Validação Final (EmailListVerify Pay-As-You-Go): Custo controlado**
   - O orçamento é consumido **exclusivamente** na última etapa: quando um e-mail é gerado/encontrado e precisa de ser testado (`verifyEmail`).
   - Tabela de custos do EmailListVerify (Pay-As-You-Go sem mensalidade):
     - Pacote de 10.000 créditos = **US$ 27,00** (créditos que nunca expiram).
   - Com o teto de envio de 400 mensagens/dia (~12.000/mês), e aplicando um filtro rigoroso para só enviar para quem passou na descoberta, o consumo real será de **8.000 a 10.000 verificações mensais**, encaixando-se perfeitamente no bloco de US$ 27,00.

---

## 6. Conclusão e Próximos Passos

Esta arquitetura híbrida resolve o problema das empresas sem website, garante a sustentabilidade do fluxo de captação ao longo de anos (ligado ao fluxo perpétuo de obras públicas) e mantém o custo operacional estritamente ancorado no modelo **Bootstrapped ($27/mês em créditos de validação, $0 em APIs de descoberta)**.

Continuamos estritamente sob a diretiva de **STOP & REVIEW**. Nenhuma linha de código será escrita até que esta reavaliação seja formalmente aprovada. Aguardamos o vosso feedback e diretrizes para avançar.

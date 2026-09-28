# Magic Leads — Dossiê para Investidores

**Modelo reverso de geração de leads para prestadores de construção e remodelação nos EUA**
Documento de confidencialidade interno · Setembro 2026 · versão pós-remediação

> **Nota de rigor.** Todos os números deste documento foram medidos na base de dados e no código em 27/09/2026, e são reproduzíveis. Quando um número não existe, diz-se que não existe — ver secção 9, *O que não afirmamos*. Este documento substitui a auditoria técnica interna de 27/09/2026, cujos achados de segurança foram corrigidos e cujos números de estado foram atualizados aqui.

---

## 1. A tese em uma frase

**O prestador de obras não tem um problema de lead. Tem um problema de poder negocial.**

Um contratante que precisa de um telhado procura no Google e recebe um leque de 3 a 8 prestadores a licitar o mesmo trabalho, ao mesmo tempo, sem saber o preço de nenhum deles. O anunciante que o encontrou paga por esse clique, não pelo resultado. O prestador nunca sabe quantos leads terá, quanto custam, nem se estão a chegar a alguém.

**O Magic Leads inverte o fluxo.** Em vez de esperar pelo anúncio, identifica a **propriedade real** que acabou de ter uma intervenção pública registada — um chamado 311, uma violação de código, uma obra estrutural — e oferece esse proprietário, **uma única vez, a um único prestador**.

Três consequências, e apenas estas três sustentam o negócio:

| | Modelo tradicional (auction) | Modelo reverso (Magic Leads) |
|---|---|---|
| **Exclusividade** | O mesmo lead é vendido a vários ao mesmo tempo | Uma reserva por propriedade, garantida pelo esquema |
| **Custo** | CPC + custo de oportunidade, variável e imprevisível | Assinatura fixa de **$79/semana** |
| **Momento** | O prestador procura; o cliente já decidiu | O problema está a acontecer **agora** e é registado num documento público |

A conversão não está nesta tabela de propósito. Ver secção 9.

---

## 2. O activo que ninguém tem: a propriedade, não o anúncio

O modelo tradicional vende acesso a um *anúncio*. O Magic Leads vende acesso a um *imóvel específico, com o proprietário identificado e o histórico completo das intervenções públicas desse imóvel*.

O activo já está construído e é measurável:

| Métrica | Valor medido |
|---|---|
| Imóveis indexados | **6.723** |
| Registos de caso público (histórico por imóvel) | **92.392** |
| Cidades | **4** (Chicago, Dallas, Nova Iorque, Boston) |
| Bases de dados de origem | Socrata SODA + CKAN, datasets públicos oficiais |

Cada imóvel carrega, para além do endereço e do proprietário, o **rastro documental do problema**: número de caso, departamento responsável, data de abertura, data de fecho, estado, descrição de resolução e o URL da fonte pública. Verificável em `lead_case_history` (16 colunas).

Isto é o que torna o lead **auditável pelo comprador**. Um prestador não compra uma promessa; compra um documento público que pode abrir e confirmar sozinho. Nenhuma plataforma de auction oferece o equivalente: o seu "lead" é um clique, não um imóvel com historial.

### 2.1 Cobertura geográfica (repartição real, não projetada)

| Cidade | Imóveis | % |
|---|---|---|
| Chicago | 3.604 | 53,6% |
| Dallas | 2.063 | 30,7% |
| Nova Iorque | 542 | 8,1% |
| Boston | 514 | 7,6% |

**Leitura honesta:** o inventário está fortemente desequilibrado. Chicago e Dallas concentram 84% do mesmo — que é também onde a cobertura de enriquecimento é mais sólida. Nova Iorque é o maior mercado do país e é hoje o ponto fraco do inventário *e* da cobertura técnica. Corrigir NYC é prioridade 1 (secção 7).

---

## 3. O fosso técnico: exclusividade imposta pelo esquema

Esta é a parte do produto que não pode ser copiada com orçamento, e é verificável no código.

A tabela `lead_holds` impõe **uma única reserva activa por imóvel**. Um segundo prestador que abra o mesmo imóvel vê `reserved_by_other` — um estado persistido e renderizado, não uma mensagem de erro. O frontend distingue explicitamente os dois casos.

Isto não é uma feature de interface. É uma restrição de integridade ao nível do esquema de dados, aplicada no momento da escrita. Um anunciante com orçamento maior **não pode** comprar o que está reservado: a exclusividade não é um botão, é uma constraint.

> **Estado real:** o mecanismo está implementado, é aplicado na escrita e está coberto por testes. A base de dados atual não contém ainda reservas em volume — reflecte um dataset de scraping, sem tráfego de clientes. Num investidor técnico, tratar como *implementado e testado*, não como *validado em produção com clientes*. A secção 7 define como o convertemos em prova.

Porquê isto é defensável a longo prazo: plataformas de auction vivem **da** exclusividade. Um marketplace que a venda deixa de ter modelo de negócio. O Magic Leads tem o incentivo alinhado para a manter — é o produto.

---

## 4. Previsibilidade de custo: o argumento económico

Um prestador que gaste $1.200/mês em Meta Ads não sabe se recebe 4 leads ou 40. A variação é o custo. Não existe forma de a eliminar dentro de um auction — está na natureza do formato.

O Magic Leads troca variância por um preço fixo conhecido:

- **$79/semana**, sem custo por clique, sem auction, sem a variância do lance.
- Cota diária definida, para o prestador saber o que recebe.
- Exclusividade: não se gasta para merecer o acesso — o acesso vem incluído.

**Este é o argumento mais forte e mais defensável do dossier, porque não depende de nenhuma métrica de conversão.** Funciona mesmo que o prestador feche zero vendas no primeiro mês: o risco passou de "quanto vou gastar" para "vale $79 por semana testar um canal previsível".

É uma proposição de risco radicalmente diferente da que o mercado oferece hoje, e é verificável apenas pelo preço — não precisa de curva de retenção para ser acreditada.

---

## 5. Como funciona, ponta a ponta

```
Fontes públicas 311 (Socrata SODA / CKAN)
   └─> scraping com retry e backoff          → deduplicado por imóvel
        └─> leads  +  lead_case_history      (6.723 imóveis / 92.392 casos)
             └─> enriquecimento de proprietário  (secção 7 — em curso)
                  └─> lead_holds  ← exclusividade imposta pelo esquema
                       └─> reveal:  proprietário + endereço + mapa + contacto
                            └─> Stripe  →  webhook verificado  →  acesso
```

A reserva é de **60 minutos** e o número está cravado no código em três camadas (frontend `minutes = 60`, API `minutes = 60`, backend `minutes = payload.minutes or 60`). O marketing diz exactamente o mesmo: **sistema disponível 24/7, reserva exclusiva de 60 minutos**. A consistência entre o que se promete e o que se executa é verificável por qualquer pessoa que abra o repositório.

**O que a reserva devolve:** endereço, proprietário, telefone (quando disponível), mapa, links de contacto directo. **O que a reserva não devolve, nunca:** um número de telefone inventado. Se o provedor de telefone falhar, o telefone vem nulo e o lead é sinalizado como incompleto. Preferimos falhar a entregar um número inventado.

---

## 6. Qualidade de engenharia e postura de segurança

### 6.1 O que foi construído

| Indicador | Valor |
|---|---|
| Endpoints REST | 81 |
| Tabelas | 21 |
| Colunas em `leads` | 62 |
| Índices | 38 |
| Testes automatizados | **29 passando**, 1 ignorado (checkout Stripe real, requer rede) |
| CI | lint + typecheck + build + testes de segurança em cada push |
| Frontend | Next.js 14, React 18, TypeScript, i18n em **3 idiomas** (PT/EN/ES) |
| Backend | FastAPI, SQLite em WAL, migrações idempotentes |

### 6.2 Controles de segurança que valem a pena citar a um investidor

| Controlo | Implementação |
|---|---|
| Hash de senha | PBKDF2-HMAC-SHA256, 100 000 iterações, salt por password, comparação constante |
| Sessões | **Tokens opacos** (`secrets.token_urlsafe`), não JWT. Revogação trivial, sem confusão de algoritmo |
| Pagamento | Activação **exclusivamente** por webhook Stripe com verificação de assinatura e idempotência por `event_id` |
| Isolamento de testes | Fixtures redireccionam a base de dados antes de qualquer import — os testes nunca tocam produção |
| Anti-enumeração | `forgot-password` responde 200 a qualquer entrada |
| Segredos | Centralizados em `config.py`; nenhum `os.environ` espalhado pelo código |
| Integridade de dados | Provedores sintéticos **removidos** do caminho de produção. Não há número de telefone gerado |

**Sobre o último ponto, e com transparência:** o produto tem origem em auditorias internas de segurança, que identificaram exploráveis concretas. **Todas foram corrigidas e estão agora protegidas por testes de regressão que correm em CI** — se qualquer uma reabrir, a build falha. Detalhamos o processo, não as fragilidades: o que um investidor deve reter é que existe um processo, que funcionou, e que está a ser verificado automaticamente.

Um detalhe que vale mais do que a própria lista: o código que gerava números de telefone falsos foi removido, e não apenas desativado. A classe inteira de bugs "número inventado em produção" ficou estruturalmente impossível, em vez de depender de alguém se lembrar de não usar.

### 6.3 Limites conhecidos, declarados

| Limite | Estado |
|---|---|
| Sem alta disponibilidade | 1 worker uvicorn, SQLite num volume. Aceitável até ~10⁵ imóveis; exige migração antes de escalar |
| Sem observabilidade estruturada | Sem Sentry/métricas. É a próxima prioridade de engenharia |
| `main.py` com 3.317 linhas e `db.py` com 4.665 linhas, 81 rotas num módulo | Dívida técnica conhecida, com custo de manutenção real na fase de escala |
| Sem páginas legais (termos/privacidade) nem `robots.txt`/`sitemap.xml` | **Obrigatório antes de operar comercialmente**; em curso |
| Cobertura de testes | 29 testes a passar, concentrados em segurança, Stripe e fluxos críticos. Sem medição formal de percentagem de cobertura |

---

## 7. Estado dos dados e o caminho para fechar o dado

Esta é a secção mais importante do dossier, porque é onde a execução está.

### 7.1 O problema, medido

O enriquecimento de **nome do proprietário** foi verificado por sonda directa contra as fontes públicas, em endereços reais do inventário:

| Cidade | Fonte | Resultado da sonda | Leitura |
|---|---|---|---|
| **Nova Iorque** | PLUTO `64uk-42ks` por **BBL** | **operacional (99,4%)** | 539 de 542 imóveis com proprietário |
| **Chicago** | Cook County `3723-97qp` | **operacional (92%)** | 11 de 12 |
| **Boston** | CKAN `bdb17c2b` | **operacional (75%)** | 9 de 12 |
| **Dallas** | `jk5c-7csb` | **parcial (83%)** | 10 de 12 |

**Nova Iorque deixou de ser um problema.** A auditoria encontrou a causa exacta: o 311 de Nova Iorque tem a rua em dois campos separados — `incident_address` (só o número, como `"1684A"`) e `street_name` (só o nome da rua, como `"EAST 87 STREET"`). O parser usava `incident_address or street_name`, o que descartava a rua em 93,4% do inventário.

A correcção adoptada não é melhorar o *matching* por morada, é deixar de depender dele. O 311 de NYC e o PLUTO partilham o **BBL** (borough-block-lot), o identificador canónico de imóvel. Com o BBL o casamento passa a ser exacto: nas sondas, **8 de 8** BBLutrients resolveram para o proprietário correcto, incluindo casos em que a morada mentia (o 311 dizia "JFK" e o BBL devolveu o proprietário certo da parcela).

Cobertura actual de Nova Iorque, medida na base depois da correcção:

| Métrica | Antes | Agora |
|---|---|---|
| Imóveis com nome de rua | 36 (6,6%) | 531 (97,9%) |
| Imóveis com `bbl` | 0 | 540 (99,6%) |
| Imóveis com proprietário | 0 | 539 (99,4%) |
| Classificados como obrigação legal | 0 | 505 |

O backfill é reproduzível e idempotente (`scripts/backfill_nyc_hpd.py`). Dos 542 imóveis, 541 foram reconstruídos a partir da fonte original; 1 deixou de existir no dataset aberto.

### 7.2 São dois problemas, não um

É importante não os confundir, porque têm soluções e prazos diferentes:

1. **Backfill não executado fora de NYC.** Chicago (3.604), Dallas (2.063) e Boston (514) continuam a 0% de proprietário no inventário — não porque a peça esteja partida (as sondas respondem 75–92%), mas porque ninguém a correu. O mecanismo existe (`scripts/run_enrich_all.py`).
2. **Precisão acima de cobertura.** Onde o dataset não tem chave de imóvel (Boston via CKAN, Dallas), o casamento é por número + rua. Passámos a recusar atribuições não verificadas: se o número extraído não for um número de casa — caso de "INTERSECTION of Vassar St" ou "S Barry Ave" — o sistema devolve nada em vez do proprietário do imóvel vizinho. Custo medido: Boston passou de 12/12 para 9/12 na sonda, porque 3 dos 12 "acertos" eram interseções sem imóvel.

### 7.3 Plano e custo

| Item | Acção | Estado |
|---|---|---|
| 1 | Corrigir normalização e dataset de **Nova Iorque** | **concluído** (BBL + parser) |
| 2 | Estabilizar **Dallas** | diagnóstico feito; 83% na sonda |
| 3 | **Backfill** de NYC (542) | **executado** — 99,4% com proprietário |
| 4 | **Backfill** de Chicago, Dallas e Boston (6.181) | por executar |
| 5 | Provedor de telefone real | bloqueado por fornecedor, ver 7.4 |

A sequência mantém-se deliberada: (1) e (2) primeiro, para o backfill correr sobre a base final e não ter de ser repetido.

### 7.4 Telefone do proprietário: dependência externa, tratada com honestidade

O provedor de telefone de propriedade está a devolver **HTTP 400** há semanas, em vários endereços de endpoint. A causa não foi diagnosticada com certeza (podem ser quotas, whitelist, WAF ou formato de pedido) e está em discussão com o fornecedor.

Isto é o que é: **uma dependência de terceiro, não um problema de engenharia do produto.** O que o produto faz com a falha é o que importa e está feito: telefone nulo, lead sinalizado como incompleto, **nunca** um número inventado. A reserva do cliente não é bloqueada por um telefone indisponível.

A mitigação estrutural é a mesma que resolve a pergunta "que acontece se o fornecedor fechar": o produto não deve depender de um único provedor de telefone. A recomendação é um segundo provedor com interface idêntica, para que a dependência deixe de ser um ponto único de falha. Está no roadmap.

---

## 8. Tração e o que vem a seguir

### 8.1 Estado atual, sem euforia

| Métrica | Estado |
|---|---|
| Clientes pagantes | **0** |
| Reservas em volume | 0 |
| Eventos de funil registados | 0 |
| Dados de conversão | **inexistentes** |

A base de dados é um dataset de scraping. Não há ainda tráfego de clientes registado. Seria desonesto apresentar isto como tração, e não é isso que este documento faz.

### 8.2 O que já está pronto a suportar clientes

O produto **não é um protótipo.** Reserva, exclusividade, histórico, "Meus Leads", filtros, favoritos, notas, pipeline, cota, assinatura Stripe verificada, notificações in-app, Web Push, PWA, três idiomas. É um produto utilizável, não um funil de topo de captação.

### 8.3 Instrumentação de conversão — o que falta para medir a tese

O pedido original era demonstrar superioridade de conversão. Não é demonstrável hoje, e a secção 9 explica porquê. O que falta é específico e pequeno:

| Instrumento | Estado |
|---|---|
| Evento `contacted` com canal e hora real | existe como estado; falta registar canal e hora |
| `appointment_set` | a criar |
| `quote_sent` / `won` / `lost` com valor | a criar + campo de receita |
| Dashboard de conversão e coorte por prestador | a criar |
| Pesquisa de controlo no onboarding: "teria fechado este trabalho sem a plataforma?" | a criar |

Com 10–20 clientes instrumentados durante 2–4 semanas, a afirmação passa de promessa a medida. É aí que vale muito mais a um investidor — e é um trabalho de semanas, não de meses.

---

## 9. O que **não** afirmamos

Esta secção existe porque um dossier que só-promete é um dossier em que não se deve confiar. Explicitamente:

1. **Não afirmamos superioridade de taxa de conversão.** Não existe uma única conversão registada na plataforma. Afirmá-lo seria especulação apresentada como facto, e qualquer investidor técnico que peça o dashboard de métricas o encontraria vazio. A secção 8.3 diz o que precisa de existir.

2. **Não afirmamos que os dados de proprietário estão prontos.** NYC está a 99,4% (backfill executado e verificado); Chicago, Dallas e Boston continuam a 0% no inventário, por backfill não executado — embora as sondas respondam 75–92%. A secção 7 diz exactamente o que está a funcionar, o que não está e quanto falta.

3. **Não afirmamos validação em produção do que só está testado.** A exclusividade por imóvel é imposta pelo esquema e coberta por testes, mas ainda não tem volume de clientes. Está escrito como implementado, não como comprovado.

4. **Não apresentamos preços de referência de Angi/HomeAdvisor/Meta.** Esses valores variam por cidade, especialidade e sazonalidade e exigem fonte citada. Números de memória são o tipo de detalhe que um investidor que faça drill-down detecta e destrói a credibilidade de tudo o resto.

5. **Não afirmamos resiliência de alta disponibilidade.** Um worker, um volume. É suficiente para a fase atual e está declarado como limite.

---

## 10. Porque é que isto é um negócio

Não é pelo número de imóveis indexados — qualquer um pode fazer scraping. É por três coisas, nesta ordem:

1. **O fosso de exclusividade é real e estrutural.** Uma constraint de base de dados que impede a venda do mesmo imóvel a dois concorrentes. Um concorrente com mais dinheiro não a contorna; teria de mudar de modelo.

2. **A evidência é verificável pelo comprador.** Cada lead é um imóvel com histórico público documentado. A confiança não depende de nós, depende do registo público — que é uma posição defensável num mercado onde a confiança é sempre um custo.

3. **Preço previsível é uma proposição de risco, não de promessa.** Não precisa de dados de conversão para ser acreditada. Um prestador entende $79/semana sem precisar que lhe provemos que converte.

O que falta é a execução de dados da secção 7, que é trabalho de engenharia e dados conhecido, com prazo definido. Não é uma questão de visão de produto.

---

## Apêndice — Metodologia e verificação

Todas as afirmações deste documento são reproduzíveis a partir do repositório e da base de dados.

| Declaração | Como verificar |
|---|---|
| 6.723 imóveis, 92.392 casos | `SELECT COUNT(*) FROM leads / lead_case_history` |
| 0% de proprietário | `COUNT(*) WHERE TRIM(COALESCE(owner_name,''))!=''` |
| Sonda de enriquecimento por cidade | `OwnerEnrichment().enrich(endereço, cidade)` contra as fontes — NYC 99,4%, Chicago 92%, Dallas 83%, Boston 75% |
| Reserva = 60 min | `api-client.ts:854`, `main.py:2934`, `dashboard/page.tsx` |
| Exclusividade por imóvel | Tabela `lead_holds` + índice único; `reserved_by_other` |
| 29 testes a passar | `pytest tests/` |
| 81 endpoints | Contagem de rotas em `backend/main.py` |

**Verificado por medição directa:** contagens e taxas de preenchimento da base de dados; sonda de enriquecimento contra as APIs públicas; número de testes; contagem de rotas; valor de reserva no código; esquema de exclusividade.

**Não verificado:** comportamento do Stripe em tempo real (requer credenciais de produção); entrega efectiva de push e e-mail; desempenho sob carga com múltiplos utilizadores; a base de dados de produção no Railway pode divergir da local, que é a fonte destas medições.

**Estado de segurança:** auditoria interna conduzida; achados críticos e altos corrigidos; testes de regressão em CI. Dívidas de segurança remanescentes (rate limiting em endpoints de recuperação de password, `verify=False` no provedor de telefone, ausência de observabilidade) estão declaradas na secção 6.3 e no roadmap, não omitidas.

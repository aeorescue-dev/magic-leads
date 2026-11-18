# Condicionantes ambientais por empresa — auditoria e extrator (2026-11-18)

**Âmbito:** SLA/Sisema (MG), APIs públicas, documentos de licenciamento e condicionantes por processo.
**Amostra aleatória:** 348 processos de Minas Gerais (de 19.713), 111 com condicionantes extraídas, 497 condicionantes em 105 empresas.
**Veredito:** **é tecnicamente possível extrair condicionantes individuais por empresa** através dos documentos públicos do SLA. A cobertura não é 100%: depende de o processo ter Parecer Técnico e/ou Relatório de Cumprimento de Condicionantes anexado. Na amostra aleatória, **31,9%** dos processos tinham condicionantes extraíveis.

---

## 1. O que o SLA expõe (APIs reais)

Todas as chamadas abaixo são públicas e foram testadas com o processo **352/2025 (AVG Siderurgia)**.

| Dado | Endpoint | Observação |
|---|---|---|
| Cabeçalho + geometria | `GET /sla/processo/solicitacao/{idSolicitacao}/{atividade}` | CNPJ, razão social, fantasia, município, protocolo, `featureCollection` (ADA) |
| Enquadramento | `GET /sla/processo/enquadramentoProcesso/{id}` | Classe, fator locacional, modalidade, fase, tipo de solicitação |
| Atividades | `GET /sla/processo/atividadesProcesso/{id}` | Código, descrição, parâmetro, quantidade, unidade |
| Atos autorizativos | `GET /sla/processo/atosSolicitacaoProcesso/{id}` | Outorgas, entidade, número, protocolo |
| Documentos | `POST /sla/listarDocumentos/anexado/cidadao/{id}` | Lista tipos, nomes, classificação, `path`, IDs |
| Download | `GET /sla/anexarDocumento/downloadPath?path=...&nomeArquivo=...` | PDF/XLSX; **sem login** no caminho público |
| Perguntas | `GET /sla/processo/perguntasProcesso/{id}` | Retornou `[]` neste processo |
| Decisões/histórico | `GET /sla/historicoDecisao/{...}` (módulo interno) | Requer autenticação em alguns fluxos |

O resumo HTML **não** inclui condicionantes. Elas estão nos documentos.

---

## 2. Onde estão as condicionantes

### 2.1 Relatório de Cumprimento de Condicionantes (XLSX) — fonte rica

Para a AVG, o XLSX `Condicionantes Ambientais_Reporte 02-01-2025.xlsx` contém:

- **Folha `CONDICIONANTES`**: `ITEM`, `DESCRIÇÃO`, `ORIGEM`, `PRAZO`, `PERIODICIDADE`, `RESPONSÁVEL`, `SITUAÇÃO`, `OBSERVAÇÃO` + histórico de formalizações.
- **Folha `AVG`**: resumo por tipo, classificação e situação.
- **Folha `LISTA`**: vocabulário de periodicidade (`SEMANAL`, `MENSAL`, `BIMESTRAL`, `TRIMESTRAL`, `QUADRIMESTRAL`, `SEMESTRAL`, `ANUAL`, `CONSTANTE`, `ÚNICA`).

**AVG:** 11 condicionantes no XLSX; 3 semestrais, 1 trimestral, 2 anuais, 4 únicas; 7 cumpridas conforme periodicidade, 3 cumpridas, 1 em atendimento.

### 2.2 Parecer Técnico/Único (PDF) — fallback universal

O Parecer Técnico traz o **Anexo I — Condicionantes** com `Item`, `Descrição`, `Prazo`. O `pdfplumber` extrai a tabela.

**AVG:** 5 condicionantes do novo parecer (2025), somadas às 11 do relatório de cumprimento → **16 condicionantes** no dossiê.
**NEXA (1473/2022):** 3 condicionantes extraídas do Parecer de LAS.

### 2.3 Limites

- **233/348** processos (67%) não tinham documento de condicionantes.
- **23/348** (6,6%) tinham documento, mas era formulário/protocolo ou PDF sem tabela parseável.
- O **CLIC Condicionantes** (`CLIC_URL`) devolveu **503** no teste; não foi usado.
- Alguns PDFs são digitalizações; exigem OCR (não implementado).

---

## 3. Amostra de 348 processos (MG)

Amostra aleatória determinística sobre as 19.713 licenças do WFS (`random.Random(42)`), para evitar viés de região/data.

| Métrica | Valor |
|---|---:|
| Processos analisados | **348** |
| Com condicionantes extraídas | **111** (31,9%) |
| Condicionantes extraídas | **497** |
| Empresas distintas | **105** |
| Fonte XLSX (status/histórico) | **1** processo (11 condicionantes) |
| Fonte Parecer Técnico | **110** processos (486 condicionantes) |
| Sem documento de condicionantes | **233** (67,0%) |
| Documento sem condições parseáveis | **23** (6,6%) |
| Erros de rede/parse | **0** |

### Distribuição por periodicidade (497 condicionantes; uma condição composta conta em mais de uma)

| Periodicidade | Ocorrências |
|---|---:|
| Durante vigência | **211** |
| Única | **189** |
| Anual | **86** |
| Semestral | **34** |
| Constante | **6** |
| Trimestral | **3** |
| Mensal | **3** |
| Diário | **2** |
| Não classificada | **36** (7,2%) |

**Semanal e quinzenal:** **0 ocorrências** na amostra. O filtro já suporta as duas; a carga completa pode encontrar casos noutros processos.

### Distribuição por situação

| Situação | Ocorrências |
|---|---:|
| Não informado (Parecer) | **486** |
| Cumprida conforme periodicidade | **7** |
| Cumprida | **3** |
| Em atendimento | **1** |

**Leitura:** o Parecer dá a obrigação e o prazo, mas não o estado de cumprimento. O XLSX dá o estado; por isso os dois são combinados.

---

## 4. Modelo de dados

`br/data/conditions.json` — chave por **processo**, não por empresa, para preservar o vínculo com a licença:

```json
{
  "summary": {
    "checked": 348,
    "with_conditions": 111,
    "with_compliance_xlsx": 1,
    "without_documents": 233,
    "document_without_parsed_conditions": 23,
    "errors": 0,
    "total_in_file": 111
  },
  "coverage": {
    "215895": { "process": "352/2025", "company": "AVG SIDERURGIA LTDA", "status": "ok", "checked_at": "..." }
  },
  "processes": {
    "352/2025": {
      "company": "AVG SIDERURGIA LTDA",
      "cnpj": "20.176.160/0002-84",
      "status": "ok",
      "compliance_document": "Condicionantes Ambientais_Reporte 02-01-2025.xlsx",
      "parecer_document": "SEI_2090.01.0003692_2025_94 AVG 16-04-25.pdf",
      "summary": {
        "total": 16,
        "by_frequency": { "trimestral": 2, "semestral": 4, "anual": 4, "unica": 7, "diario": 1 },
        "by_status": { "cumprida_conforme_periodicidade": 7, "cumprida": 3, "em_atendimento": 1, "nao_informado": 5 },
        "by_source": { "compliance_xlsx": 11, "parecer_tecnico": 5 }
      },
      "conditions": [
        {
          "item": 1,
          "description": "Executar o Programa de Automonitoramento...",
          "origin": "Condicionante nº 01 da Renovação da Licença de Operação nº 116/2020",
          "deadline": "180 dias",
          "periodicity_raw": "TRIMESTRAL / SEMESTRAL",
          "frequencies": ["trimestral", "semestral"],
          "frequency_group": "composta",
          "responsible": "MEIO AMBIENTE",
          "status": "cumprida_conforme_periodicidade",
          "observation": "",
          "source": "compliance_xlsx"
        }
      ]
    }
  }
}
```

**Regras:**
- `frequencies`: lista; uma condição pode ser trimestral **e** semestral.
- `frequency_group`: `composta` quando há mais de uma.
- `status`: `cumprida`, `cumprida_conforme_periodicidade`, `em_atendimento`, `cumprida_parcialmente`, `descumprida`, `nao_informado`.
- `responsible`: apenas área/equipe; nomes de pessoas são mascarados (`Equipe (nome não exibido)`).
- `source`: `compliance_xlsx` ou `parecer_tecnico`.
- `coverage`: um registo por `idSolicitacao` já verificado (retomável e auditável).

### 4.1 Agregado por empresa

`br/ingest/aggregate_conditions.py` gera `br/data/conditions_by_company.json`:

- chave por **CNPJ** (14 dígitos) ou, na falta dele, por nome normalizado;
- lista de processos e documentos de origem;
- lista completa de condicionantes com periodicidade e status;
- `by_frequency` e `by_status` por empresa;
- ordenação por número de condicionantes.

Estado atual: **105 empresas**, **497 condicionantes**.

---

## 5. Filtro no dashboard

Adicionados dois filtros no sidebar:

1. **Periodicidade da condicionante** — semanal, quinzenal, mensal, bimestral, trimestral, quadrimestral, semestral, anual, única, constante.
2. **Status da condição** — cumprida, cumprida conforme periodicidade, em atendimento, cumprida parcialmente, descumprida.

O filtro cruza com UF, município, tipo, fonte, categoria, multa, validade e busca. O contador mostra quantas oportunidades têm condicionantes.

**Dossiê:** tabela com item, descrição, origem, prazo, periodicidade, status e observação; badges de resumo por frequência e status; fonte do documento.

---

## 6. O que mais conseguimos extrair (enriquecimento extremo)

### Do SLA/Sisema
- **Cabeçalho:** CNPJ, razão social, nome fantasia, empreendimento, município, UF, protocolo, status.
- **Enquadramento:** classe, fator locacional, modalidade, fase, tipo de solicitação.
- **Atividades:** código, descrição, parâmetro, quantidade, unidade.
- **ADA/geometria:** `FeatureCollection` com polígonos; permite cruzamento espacial.
- **Atos autorizativos:** outorgas, entidade, número, protocolo.
- **Documentos:** nome, tipo, classificação, data, autor, histórico, download.
- **Parecer Técnico/Único:** texto integral, condicionantes, prazos, fundamentação.
- **Relatório de Cumprimento:** condições, status, observações, histórico de protocolos.
- **Certificado:** documento final (gerado; pode ser obtido pelo fluxo autenticado).

### Do IBAMA
- Autos de infração, embargos, SISLIC (licenças federais), SINAFLOR (autorizações florestais).
- Multa, categoria, gravidade, processo, CNPJ, município, coordenadas.

### Da Receita/CNPJ
- CNAE principal/secundário, natureza jurídica, porte, capital social, situação cadastral, QSA (mascarado), telefone/e-mail comercial.

### Do território
- IBGE: município, UF, bioma, população, PIB, mesorregião.
- IDE-Sisema: APP, unidades de conservação, recursos hídricos, cobertura vegetal, áreas contaminadas, barragens.
- CNAE/IBGE: classificação da atividade.

### Cruzamentos de alto valor
- Condicionante **vencida** ou **em atendimento** × proximidade do vencimento da licença.
- Condicionante **semestral/anual** × multa/auto de infração.
- ADA × APP/UC/bioma → risco de licenciamento.
- Atividade (CNAE) × classe × histórico de autos.
- Grupo económico (raiz CNPJ) × múltiplos processos.
- **Carga de condicionantes por empresa** × plano comercial (quem tem mais obrigações tem mais urgência de software).

---

## 7. Escala nacional

- MG tem **19.713 licenças**; o extrator faz **1 POST + até 2 downloads + parsing** por processo.
- Ritmo medido: **0,5–1,1 processo/s** com 3–6 workers (o servidor do SLA abranda em lotes grandes).
- Carga completa de MG: ~5–11 horas, executável em lotes retomáveis:
  - cache por `idSolicitacao` em `br/.cache/conditions/`;
  - `--offset`/`--limit` para lotes de 300–1.000;
  - `--workers` 4–6; pausa natural entre chamadas;
  - `coverage` no ficheiro final permite medir falhas por lote.

```bash
python fetch_conditions.py --source mg --offset 0    --limit 500 --workers 6
python fetch_conditions.py --source mg --offset 500  --limit 500 --workers 6
# ...
python fetch_conditions.py --reclassify      # recalcula periodicidade sem rede
python aggregate_conditions.py               # agregado por empresa
python build_demo.py                         # snapshot do dashboard
```

**Projeção com base na amostra:** ~31,9% de 19.713 ≈ **6.300 processos** com condicionantes, ~**28.000 condicionantes** (média de 4,5 por processo).

---

## 8. LGPD e qualidade

- **Exibir:** CNPJ, empresa, atividade, condicionante, prazo, periodicidade, status, fonte.
- **Não exibir:** CPF, nome de sócio, telefone/e-mail pessoal, nome de responsável técnico.
- **Mascarar:** nomes de pessoas no campo “responsável” → `Equipe (nome não exibido)`.
- **Proveniência:** documento, processo, data de extração e link oficial.
- **Retenção:** 12–24 meses; revisão.
- **Risco:** PDFs e XLSX podem conter dados pessoais; o pipeline deve remover/mascarar antes de indexar.
- **Qualidade:** condições do Parecer podem duplicar as do XLSX; deduplicar por descrição/origem; marcar `also_in_parecer`.
- **Classificação:** 92,8% das condicionantes da amostra têm periodicidade atribuída; as restantes (36) ficam como `nao_classificada` em vez de serem inventadas.

---

## 9. Recomendação

1. **Rodar a carga completa de MG em lotes** e medir cobertura real por cidade/atividade. A amostra já permite estimar ~6.300 processos com condicionantes.
2. **Usar XLSX quando existir** (status/histórico) + **Parecer** (condicionantes da licença).
3. Manter o filtro por periodicidade/status e o dossiê por processo.
4. Adicionar OCR para PDFs digitalizados só depois de medir a proporção (6,6% na amostra).
5. Expandir o mesmo extrator para outros estados que publiquem documentos de licença; onde não houver, manter apenas o que o WFS/CSV oferece.

**Conclusão:** sim, é possível entregar condicionantes individuais por empresa com dados públicos. A amostra de 348 processos produziu **497 condicionantes em 105 empresas**, com periodicidade classificada em 92,8% dos casos. O limite é documental, não técnico: processos sem Parecer/Relatório anexado não têm condicionantes extraíveis.

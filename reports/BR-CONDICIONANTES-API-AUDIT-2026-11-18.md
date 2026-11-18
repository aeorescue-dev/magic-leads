# Condicionantes ambientais por empresa — auditoria e extrator (2026-11-18)

**Âmbito:** SLA/Sisema (MG), APIs públicas, documentos de licenciamento e condicionantes por processo.
**Piloto:** 30 processos de Minas Gerais; 19 com condicionantes extraídas; 93 condicionantes.
**Veredito:** **é tecnicamente possível extrair condicionantes individuais por empresa**, via documentos públicos do SLA. A cobertura não é 100%: depende de o processo ter Parecer Técnico e/ou Relatório de Cumprimento de Condicionantes anexado.

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

- **6/30** processos não tinham documento de condicionantes.
- **5/30** tinham documento, mas era formulário/protocolo ou PDF sem tabela parseável.
- O **CLIC Condicionantes** (`CLIC_URL`) devolveu **503** no teste; não foi usado.
- Alguns PDFs são digitalizações; exigem OCR (não implementado).

---

## 3. Piloto de 30 processos (MG)

| Métrica | Valor |
|---|---:|
| Processos analisados | **30** |
| Com condicionantes extraídas | **19** (63%) |
| Condicionantes extraídas | **93** |
| Fonte XLSX (status/histórico) | **1** processo |
| Fonte Parecer Técnico | **18** processos |
| Sem documento de condicionantes | **6** |
| Documento sem condições parseáveis | **5** |

### Distribuição por periodicidade (condicionantes; uma condição composta conta em mais de uma)

| Periodicidade | Ocorrências |
|---|---:|
| Única | **44** |
| Durante vigência | **27** |
| Anual | **15** |
| Semestral | **9** |
| Trimestral | **2** |
| Mensal | **1** |
| Diário | **1** |
| Constante | **1** |
| Não classificada | **3** |

**Semanal e quinzenal:** **0 ocorrências** no piloto. O filtro já suporta as duas; a busca completa pode encontrar casos noutros processos.

### Distribuição por situação

| Situação | Ocorrências |
|---|---:|
| Não informado (Parecer) | **82** |
| Cumprida conforme periodicidade | **7** |
| Cumprida | **3** |
| Em atendimento | **1** |

**Leitura:** o Parecer dá a obrigação e o prazo, mas não o estado de cumprimento. O XLSX dá o estado; por isso os dois são combinados.

---

## 4. Modelo de dados

`br/data/conditions.json` — chave por **processo**, não por empresa, para preservar o vínculo com a licença:

```json
{
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
- Grupo econômico (raiz CNPJ) × múltiplos processos.

---

## 7. Escala nacional

- MG tem **19.713 licenças**; o extrator precisa de **2 chamadas + 1 download + parsing** por processo.
- Com cache e 2–5 req/s, uma carga completa leva **algumas horas**; recomenda-se rodar em lotes de 500–1.000, com:
  - cache por `idSolicitacao`;
  - retries/backoff;
  - pausa entre chamadas;
  - monitor de falhas;
  - QA amostral.
- Cobertura do piloto: **63%**. O número nacional depende de quantos processos têm Parecer Técnico e/ou XLSX.
- Para empresas com vários processos, agregar por CNPJ/raiz e manter a lista por processo.

---

## 8. LGPD e qualidade

- **Exibir:** CNPJ, empresa, atividade, condicionante, prazo, periodicidade, status, fonte.
- **Não exibir:** CPF, nome de sócio, telefone/e-mail pessoal, nome de responsável técnico.
- **Mascarar:** nomes de pessoas no campo “responsável” → `Equipe (nome não exibido)`.
- **Proveniência:** documento, processo, data de extração e link oficial.
- **Retenção:** 12–24 meses; revisão.
- **Risco:** PDFs e XLSX podem conter dados pessoais; o pipeline deve remover/mascarar antes de indexar.
- **Qualidade:** condições do Parecer podem duplicar as do XLSX; deduplicar por descrição/origem; marcar `also_in_parecer`.

---

## 9. Recomendação

1. **Rodar a carga completa de MG em lotes** e medir cobertura real por cidade/atividade.
2. **Usar XLSX quando existir** (status/histórico) + **Parecer** (condicionantes da licença).
3. Manter o filtro por periodicidade/status e o dossiê por processo.
4. Adicionar OCR para PDFs digitalizados só depois de medir a proporção.
5. Expandir o mesmo extrator para outros estados que publiquem documentos de licença; onde não houver, manter apenas o que o WFS/CSV oferece.

**Conclusão:** sim, é possível entregar condicionantes individuais por empresa com dados públicos, e o piloto já mostra 19 empresas e 93 condicionantes. O limite é documental, não técnico: processos sem Parecer/Relatório anexado não têm condicionantes extraíveis.

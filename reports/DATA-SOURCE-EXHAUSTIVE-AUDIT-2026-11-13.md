# Auditoria exaustiva de fontes e enriquecimento de dados

Data: 2026-11-13
Âmbito: todas as fontes públicas já usadas e disponíveis para NYC, Chicago, Boston e Dallas.
Produção: `master` em `3b53962` — intocada. Landing congelada.
Natureza: relatório técnico; **nenhuma alteração de código** foi feita.

## 1. Sumário executivo

O "poço" de dados é muito maior do que o pipeline atual consome. Hoje usamos uma fração:
311 + HPD Violations + DOB Violations + DOB Permits + Chicago 311/Permits + Dallas
311/Permits + Boston 311/Permits, e apenas parte dos campos.

O que está disponível e ainda não é explorado inclui:

- **NYC HPD Complaints** (`ygpa-z7cr`): ~15.321 problemas abertos/7 dias — a verdadeira fila
  de pré-inspeção.
- **Prazos HPD** (`wvxf-dwi5`): 61.712 violações abertas com prazo/30 dias; hoje só 3 têm
  `sla_target_dt` na base.
- **NYC ECB** (`6bgk-3dad`): 13.310 violações/90 dias e **US$ 32,2 M de saldo de multas**.
- **NYC BIC** (`upii-frjc`): 179 violações/30 dias e US$ 635.875 em multas.
- **NYC DOB Safety** (`855j-jady`): 16.502 violações/30 dias.
- **NYC Housing Litigations** (`59kj-x8nc`): 1.530 casos/90 dias; **Vacate Orders**
  (`tb8q-a3ar`): 180/90 dias.
- **Chicago Building Violations** (`22u3-xenr`): 11.320/90 dias — inspeções falhadas.
- **Chicago Ordinance Violations** (`awqx-tuwv`): 116/30 dias e **US$ 85.000 em multas**.
- **Chicago Vacant/Abandoned** (`kc9i-wq85`), **Scofflaw** (`crg5-4zyp`) e **Foreclosed
  Rental** (`yhcw-iu53`, com nome/telefone/e-mail do agente de gestão).
- **Boston Building & Property Violations** (CKAN `800a2663…`): 621 casos abertos; hoje não
  é ingerido.
- **Boston Property Assessment** (184.552 registos): owner, valores, unidades, condição.
- **PLUTO, Property Valuation, ACRIS** em NYC: owner, tipo, áreas, valores, transações.
- **Valores de obra** em permits: `estimated_job_costs` (NYC), `reported_cost` (Chicago),
  `declared_valuation` (Boston), `value` (Dallas, esparso).

**Teto de valor:** o sistema pode entregar, por prestador, um dossiê completo do imóvel —
dono, agente, telefone, histórico de violações, prazos, multas, valor de obra, licenças,
litígios e sinais preventivos. O limite de volume continua a ser **10 revelações/dia
(3.650/ano)** e a oferta por cidade/ofício. O limite financeiro não é receita garantida:
é a informação disponível para o prestador decidir.

## 2. Método e restrições

- Catálogo Socrata (`api.us.socrata.com`) e CKAN Boston; schemas reais via
  `/api/views/{id}.json` e `datastore_search`.
- Volumes de 7/30/90 dias medidos em 12–13/11; quando o filtro de data não é homogéneo,
  está indicado "aprox.".
- O pipeline atual usa apenas um subconjunto de campos; a coluna "hoje" indica o que já
  entra.
- Restrições: Socrata sem app token tem throttling; paginação de 5.000 × 10 páginas por
  run; cadência de 6 h; Boston CKAN muda de recurso; alguns datasets têm datas em formatos
  diferentes.
- Regra de ouro: nomes de agências/fontes e termos técnicos nunca vão para a UI; o lineage
  fica interno. Telefone é on-demand, com consentimento.

## 3. Matriz mestre — o que existe e o que fazemos

### 3.1 NYC

| Dataset | ID | Hoje | Campos-chave disponíveis | Volume recente | Valor | Fase |
|---|---|---|---|---|---|---|
| 311 Service Requests | `erm2-nwe9` | usado (subconjunto) | `unique_key`, `created_date`, `closed_date`, `agency`, `complaint_type`, `descriptor`, `descriptor_2`, `incident_address`, `incident_zip`, `status`, `due_date`, `resolution_description`, `bbl`, `borough`, lat/lng | 22.454 abertos/7d | pedido + prazo (raro: 0,3% com due date) | 0 (usado) |
| HPD Violations | `wvxf-dwi5` | usado (sem prazos) | `violationid`, `buildingid`, `registrationid`, `class`, `inspectiondate`, `originalcertifybydate`, `originalcorrectbydate`, `newcertifybydate`, `newcorrectbydate`, `novdescription`, `novissueddate`, `currentstatus`, `rentimpairing`, `bbl`, `bin` | 61.712 abertas com prazo/30d | prazo legal, classe, histórico | **1** |
| HPD Complaints | `ygpa-z7cr` | **não usado** | `received_date`, `problem_id`, `complaint_id`, `building_id`, `type`, `major_category`, `minor_category`, `problem_code`, `complaint_status`, `problem_status`, `status_description`, `problem_duplicate_flag`, `complaint_anonymous_flag`, `bbl`, `bin` | 15.321 OPEN/7d | fila de pré-inspeção real | **1** |
| HPD Registrations | `tesw-yqqr` | usado (agente) | `registrationid`, `buildingid`, `bbl`, `bin`, `lastregistrationdate`, `registrationenddate` | — | liga ao agente | 1 |
| HPD Contacts | `feu5-w2e2` | usado (agente) | `registrationid`, `type`, `contactdescription`, `corporationname`, `title`, `firstname`, `lastname`, `business*` | — | managing agent | 1 |
| DOB Violations | `3h2n-5cm9` | usado | `violation_number`, `issue_date`, `violation_category`, `violation_type`, `description`, `disposition_date`, `ecb_number`, `bin`, `bbl` | 20.410 leads na base; 40% Unclassified | violação e gravidade | 1 (melhorar categoria) |
| DOB Complaints | `eabe-havv` | **não usado** | `complaint_number`, `status`, `date_entered`, `complaint_category`, `inspection_date`, `disposition_date`, `bin` | 3,15 M total (série histórica) | queixa antes da violação | 2 |
| DOB Permits (NOW Build) | `rbx6-tga4` | usado (sem valor) | `job_filing_number`, `work_type`, `job_description`, `estimated_job_costs`, `owner_name`, `owner_business_name`, `owner_street_address`, `expired_date`, `permit_status`, `bbl`, `bin` | 3.903/30d | **valor da obra + owner mailing** | **1** |
| DOB Permit Issuance (legacy) | `ipu4-2q9a` | não usado | `permittee_s_phone__`, `permittee_s_business_name`, `owner_s_*`, `permit_type`, `job_start_date`, `expiration_date`, `bbl` | 3,99 M total | telefone do empreiteiro (não do dono) | 2 (grafo de contratantes) |
| DOB ECB Violations | `6bgk-3dad` | **não usado** | `ecb_violation_number`, `severity`, `violation_type`, `violation_description`, `penality_imposed`, `amount_paid`, `balance_due`, `hearing_date`, `hearing_status`, `respondent_name`, `respondent_*`, `bbl` | 13.310/90d; **US$ 32,2 M** balance | **multas reais + audiências** | **1** |
| DOB Safety Violations | `855j-jady` | não usado | `violation_issue_date`, `violation_type`, `violation_remarks`, `violation_status`, `device_type`, `cycle_end_date`, `bbl` | 16.502/30d | risco de segurança | 2 |
| BIC Issued Violations | `upii-frjc` | não usado | `maximum_fine`, `fine_amount`, `date_fine_paid`, `type_of_violation`, `violation_disposition`, `account_name`, `violation_account_address`, `bbl` | 179/30d; **US$ 635.875** | multas reais | 1/2 |
| Housing Litigations | `59kj-x8nc` | não usado | `casetype`, `caseopendate`, `casestatus`, `casejudgement`, `findingofharassment`, `penalty`, `respondent`, `bbl` | 1.530/90d | litígio/harassment | 2 |
| Order to Repair/Vacate | `tb8q-a3ar` | não usado | `vacate_order_number`, `primary_vacate_reason`, `vacate_type`, `vacate_effective_date`, `actual_rescind_date`, `number_of_vacated_units`, `bbl` | 180/90d | risco extremo | 2 |
| PLUTO | `64uk-42ks` | não usado | `ownername`, `ownertype`, `bldgclass`, `unitsres`, `unitstotal`, `yearbuilt`, `assessland`, `assesstot`, `bldgarea`, `latitude`, `longitude`, `bbl` | 1 linha/imóvel | perfil do imóvel | 1/2 |
| Property Valuation | `8y4t-faws` | não usado | `owner`, `curmkttot`, `curtxbtot`, `units`, `yrbuilt`, `bldg_class`, `gross_sqft`, `zip_code`, `bbl` | base anual | valor e atributos | 2 |
| ACRIS Master | `bnx9-e6tj` | não usado | `document_id`, `doc_type`, `document_date`, `document_amt`, `recorded_borough`, `crfn` | diário | transações/histórico | 2 |
| ACRIS Parties | `636b-3b5g` | não usado | partes, nomes, percentagens | diário | proprietário/comprador | 2 |
| ACRIS Legals | `8h5j-fqxa` | não usado | BBL, bloco, lote | diário | ligação ao imóvel | 2 |
| DOF Property Abatement | `rgyu-ii48` | não usado | `parid`, `taxyr`, `rsnbl_cost`, `installcost`, `appliedabt`, `net_taxes` | — | incentivos/custo | 3 |
| Rodent Inspection | `p937-wjvj` | não usado | `inspection_date`, `inspection_type`, `result`, `observations`, `bbl` | — | sinais de roedores | 2 |
| Construction/Demolition Registrants | `cspg-yi7g` | não usado | `account_name`, `trade_name`, `phone`, `email`, `bbl`, `expiration_date` | — | grafo de contratantes | 2/3 |

### 3.2 Chicago

| Dataset | ID | Hoje | Campos-chave | Volume | Valor | Fase |
|---|---|---|---|---|---|---|
| 311 | `v6vf-nfxy` | usado (subconjunto) | `sr_number`, `sr_type`, `created_date`, `last_modified_date`, `closed_date`, `status`, `duplicate`, `parent_sr_number`, `street_address`, `zip_code`, lat/lng | 9.514/7d | pedido | 0 |
| Building Permits | `ydr8-5enu` | usado (sem valor) | `reported_cost`, `total_fee`, `street_*`, `work_description`, `contact_1..15_name`, `pin_list`, `zip_code` | 2.817/30d; 2.207 com custo = **US$ 942,9 M** | **valor + contactos** | **1** |
| Building Violations | `22u3-xenr` | **não usado** | `violation_date`, `violation_code`, `violation_status`, `violation_description`, `inspection_status`, `inspection_category`, `address`, lat/lng | 11.320/90d (10.470 FAILED) | inspeção falhada | **1** |
| Ordinance Violations (Buildings) | `awqx-tuwv` / `6br9-quuz` | não usado | `imposed_fine`, `admin_costs`, `hearing_date`, `case_disposition`, `respondents`, `violation_description` | 116/30d; **US$ 85.000** | **multas reais** | **1** |
| Vacant/Abandoned | `kc9i-wq85` | não usado | `total_fines`, `total_paid`, `current_amount_due`, `last_hearing_date`, `violation_type` | 5.012 total | multas e risco | 1/2 |
| Building Code Scofflaw | `crg5-4zyp` / `rz4d-qp2m` | não usado | `defendant_owner`, `address`, `circuit_court_case_number` | 701 | flag de proprietário | 2 |
| Foreclosed Rental | `yhcw-iu53` | não usado | `owner_name`, `owner_management_agent_name`, **`owner_notices_agent_phone`**, **`owner_notices_agent_email`** | 586 | contacto do agente | 2 |
| Micro-Market Recovery | `ujwc-724r` | não usado | `inspection_*`, `violation_*`, `violation_code_book_text`, `mmrp_zone` | 275.664 total | programa de recuperação | 3 |

### 3.3 Boston

| Dataset | Recurso CKAN | Hoje | Campos-chave | Volume | Valor | Fase |
|---|---|---|---|---|---|---|
| 311 (novo) | `254adca6…` | usado | `case_id`, `open_date`, `case_topic`, `service_name`, `case_status`, `close_date`, `target_close_date`, `full_address`, `zip_code`, lat/lng | 1.029/7d | pedido | 0 |
| 311 (legado) | `1a0b420d…` | usado (dual-read) | `case_enquiry_id`, `open_dt`, `sla_target_dt`, `closed_dt`, `case_title`, `subject`, `reason`, `type`, `queue`, `department` | — | prazo | 0 |
| Permits | `6ddcd912…` | usado (sem valor) | `declared_valuation`, `total_fees`, `occupancytype`, `sq_feet`, `applicant`, `parcel_id`, `property_id`, `issued_date`, `expiration_date` | 2.710/30d | **valor da obra** | **1** |
| Building & Property Violations | `800a2663…` | **não usado** | `case_no`, `status`, `status_dttm`, `code`, `value`, `description`, `violation_*`, `contact_addr1`, `sam_id`, lat/lng | 17.508 total; **621 OPEN** | violação e contacto | **1** |
| Property Assessment | `ee73430d…` | não usado | `OWNER`, `MAIL_*`, `TOTAL_VALUE`, `GROSS_TAX`, `RES_UNITS`, `YR_BUILT`, `STRUCTURE_CLASS`, `OVERALL_COND`, `parcel_id` | 184.552 | perfil e valor | 2 |

### 3.4 Dallas

| Dataset | ID | Hoje | Campos | Volume | Valor | Fase |
|---|---|---|---|---|---|---|
| 311 | `d7e7-envw` | usado (subconjunto) | `service_request_type`, `overall_service_request_due_date`, `status`, `outcome`, `priority`, `created_date`, `closed_date`, `address` | 3.470/7d | pedido/prazo | 0/1 |
| Building Permits | `e7gq-4sah` | usado (sem valor) | `value`, `contractor`, `work_description`, `land_use`, `issued_date`, `zip_code` | 7.845/30d; **25 com value = US$ 38,2 M** | valor esparso | 1 |
| Code Violations | `yvha-at84` / `x9pz-kdq9` | **não usado** | `type`, `status`, `created`, `completed_date`, `department`, `str_*` | 712.998 total, **atualizado 2019** | histórico, não live | — (descartar até nova fonte) |
| Active Contractors | `jhgk-eg9m` | não usado | `contractor`, `phone`, `address` | atualizado 2017 | sem validade | — |

## 4. O que é viável extrair **de imediato** (fase 1)

1. **HPD Complaints** (`ygpa-z7cr`) — pré-inspeção real, com `complaint_id`/`problem_id` para
   dedupe, BBL/BIN, categoria, estado e duplicados.
2. **Prazos e classes HPD** (`wvxf-dwi5`) — `originalcorrectbydate`, `newcorrectbydate`,
   `originalcertifybydate`, `newcertifybydate`, `class`, `inspectiondate`, `rentimpairing`.
3. **Chicago Building Violations** (`22u3-xenr`) — inspeção falhada, descrição, estado.
4. **ECB NYC** (`6bgk-3dad`) — `penality_imposed`, `amount_paid`, `balance_due`,
   `hearing_date`, `hearing_status`, `severity`.
5. **Chicago Ordinance Violations** (`awqx-tuwv`) — `imposed_fine`, `admin_costs`,
   `respondents`, `hearing_date`.
6. **Valores de permits** — `estimated_job_costs` (NYC), `reported_cost` (Chicago),
   `declared_valuation` (Boston), `value` (Dallas quando > 0).
7. **Boston Building & Property Violations** (`800a2663…`) — 621 abertos; descrição, código,
   contacto e parcela.
8. **Owner/agent** — já existe HPD registration/contacts; persistir e expor.
9. **PLUTO** — owner, tipo, unidades, ano, valore avaliação por BBL.

## 5. O que é viável estruturar numa fase seguinte (fase 2)

- DOB Complaints (`eabe-havv`), DOB Safety (`855j-jady`), BIC (`upii-frjc`), Housing
  Litigations (`59kj-x8nc`), Vacate Orders (`tb8q-a3ar`).
- Chicago Vacant/Abandoned (`kc9i-wq85`), Scofflaw (`crg5-4zyp`), Foreclosed Rental
  (`yhcw-iu53`) — este último tem **telefone/e-mail do agente**.
- Boston Property Assessment (`ee73430d…`) — owner, valores, condição, unidades.
- NYC Property Valuation (`8y4t-faws`), ACRIS Master/Parties/Legals — histórico de
  propriedade e transações.
- Rodent Inspection (`p937-wjvj`) e Construction/Demolition Registrants (`cspg-yi7g`).

## 6. O que fica para fase 3 / investigação

- ACRIS completo (grafo de propriedade, compradores, hipotecas).
- DOF Property Abatement / tax liens / incentivos.
- Micro-Market Chicago e programas de recuperação.
- Fotos, documentos e plantas (quando existirem URLs públicas).
- Modelos preditivos de risco/multa e de valor de obra para sinais sem permit.
- Identidade de proprietário multi-cidade/portfólio.
- Postgres/read replicas para volume e concorrência.

## 7. Roadmap definitivo de enriquecimento

### Fase 1 — 2 a 3 semanas (maior impacto imediato)
- Ingestão HPD Complaints + deadlines HPD.
- Chicago Building Violations + Ordinance fines.
- ECB balance/hearing.
- Valores de permits (4 cidades).
- Boston violations.
- Persistir owner/agent e PLUTO.
- Dedupe por BBL/BIN/parcela; timeline única por imóvel.
- Expor no drawer: valor de obra, multa real, histórico, prazo legal.

### Fase 2 — 4 a 8 semanas (dossiê do imóvel)
- DOB Complaints/Safety/BIC/Litigations/Vacate.
- Chicago vacant/scofflaw/foreclosed.
- Boston assessment.
- NYC Property Valuation/ACRIS.
- Risco e histórico agregado; alertas de portfolio.

### Fase 3 — 8 a 12 semanas (inteligência proprietária)
- ACRIS completo, abatement/liens.
- Grafo de contratantes e proprietários.
- Modelos de valor e risco; previsão de multa.
- Postgres e SLA de dados.

## 8. Teto de valor por prestador

### Volume
- Limite de produto: **10 revelações/dia = 3.650/ano**.
- Oferta anual = `min(3.650, oferta_diária × 365)`.
- Exemplos: NYC Plumbing 213/dia → 3.650 (limite de quota); NYC Roof 1,4/dia → ~511;
  NYC Mold 5,6/dia → ~2.044; Boston Plumbing 1,4/dia → ~511; Dallas Structure 30/dia →
  3.650; Chicago Plumbing 55/dia → 3.650.
- Preventivo: HPD Complaints ~2.189/dia + Chicago violations ~126/dia + ECB ~148/dia —
  mais do que suficiente para o teto de 10/dia por prestador, mas concentrado em NYC e em
  Heating/Plumbing/Unsanitary.

### Informação (por lead)
Dono + tipo + agente + telefone (on-demand) + e-mail (raro) + BBL/BIN/parcela + unidades/ano/
classe/valor avaliado + histórico de violações + queixas + inspeções + prazos + multas
impostas/pagas/saldo + audiências + litígios/vacate/scofflaw + permits (valor/empreiteiro/
descrição) + timeline + risco.

### Financeiro
Não é receita garantida. O teto é a **informação disponível** para o prestador decidir.
Valores de obra só existem em permits; multas reais só em ECB/BIC/Chicago Ordinance.
Para HPD/311 sem permit, o valor deve ficar nulo ou marcado como estimativa.

## 9. Riscos, qualidade e conformidade

- **Deduplicação:** HPD complaints tem `problem_id` por problema; agrupar por
  `complaint_id`/`building_id`; 311 e HPD podem duplicar o mesmo imóvel.
- **Endereços:** normalização e BBL/BIN/parcela; Dallas/Boston usam identificadores
  diferentes.
- **Datas:** formatos mistos (ISO, MM/DD/YY, epoch); validar por dataset.
- **Qualidade:** descrições corrompidas, campos vazios, owners institucionais; scrub e
  classificação.
- **Frescura:** Socrata diário; PLUTO/assessment anual; Boston CKAN com rotação; monitorizar
  `rowsUpdatedAt` e alertar.
- **Privacidade:** nomes/moradas são registos públicos; telefone/e-mail só com base legal e
  consentimento; nunca expor termos de fonte na UI.
- **Custos:** Socrata app token; chamadas de telefone on-demand; sem enriquecimento em lote.

## 10. O que **não** vale a pena ingerir

- NYC parking/camera violations, NYPD, restaurant inspections, film permits.
- Chicago food inspections, speed/red-light cameras, lobbyists.
- Dallas code violations (parado em 2019) e Active Contractors (2017).
- Qualquer dataset sem data de atualização fiável ou sem ligação ao imóvel.

## 11. Decisão de escopo

Este é o teto técnico atual. A fase 1 sozinha já multiplica o valor por lead (prazos reais,
multas reais, valor de obra, owner/agent, fila preventiva). A fase 2 transforma o lead num
dossiê de imóvel; a fase 3 cria inteligência de portfolio e risco.

Produção continua em `master` `3b53962`, intocada.

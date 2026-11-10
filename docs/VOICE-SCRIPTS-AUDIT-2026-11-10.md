# Auditoria de scripts de voz — 2026-11-10

Consulta read-only à produção (`/data/voice.db` + módulo em execução) e ao
repositório. Hora da extração: **10/11/2026 ~10:20 ET**.

## 1. Modo em produção

| Item | Valor |
|---|---|
| `VOICE_SCRIPT_MODE` | `static` |
| Motor | `gather_using_speak` (TTS + DTMF 2) — **não** usa AI Assistant |
| Voz | `Telnyx.Ultra.00a77add-48d5-4ef6-8157-71e5437b282d` |
| Assistant partilhado | `assistant-f688c3cb-f641-4912-9863-0810159d52da` (não usado no modo static) |
| `VOICE_GUARD_SCOPES` | `exact,city` |
| `VOICE_MIN_SHOWCASE_ITEMS` | 5 |
| `VOICE_SHOWCASE_MAX_AGE_HOURS` | 72 |
| Base de dados | `/data/voice.db` |

No modo `static` o texto falado é **apenas** `rendered["greeting"]`
(`telnyx_voice.py::_start_static_script_for_call`, `payload=greeting[:3000]`).
O campo `disclosure` e o bloco `TOOL_GUIDANCE` **não** são sintetizados neste
modo.

## 2. Script ativo nas campanhas de NY (campanhas 14–24)

Fonte: `voice_scripts.DEFAULT_TEMPLATE` (v4, 532 caracteres), replicado em
`voice_scripts` para os 15 trades. Byte-idêntico ao ficheiro do repositório
(sha256 `feb7aa81768602fa91332e1504c131f00d5a37fcaf35389829cd17c36bafcbdb`).

Texto exato (placeholders substituídos por chamada):

> Hi {{company | Contractor}}. This is an automated message from Magic Leads in
> New York. We just unlocked {{count}} active opportunities in your trade right
> now on magicleads.app. While shared lead apps sell the same contact to five
> local contractors and eat into your margins, we give you the owner's direct
> name, verified address, and job details 5 to 7 days before anyone else in
> your area. You just call, visit, or send a letter, and close the deal before
> your competitors do. Go to magicleads.app right now. To opt out, press 2.

Em texto corrido (como é sintetizado):

```
Hi {COMPANY}. This is an automated message from Magic Leads in New York. We just unlocked {COUNT} active opportunities in your trade right now on magicleads.app. While shared lead apps sell the same contact to five local contractors and eat into your margins, we give you the owner's direct name, verified address, and job details 5 to 7 days before anyone else in your area. You just call, visit, or send a letter, and close the deal before your competitors do. Go to magicleads.app right now. To opt out, press 2.
```

Substituições:
- `{{company | Contractor}}` → nome da empresa (`_clean_company`); fallback
  `Contractor`.
- `{{count}}` → contagem exata do trade na cidade, formatada com vírgulas
  (`f"{count:,}"`), ex.: `31`, `416`, `4,018`.
- Não há outras variáveis no corpo atual.

## 3. Scripts ativos em Dallas (campanha 12)

A campanha 12 (Dallas) está `paused` com **2 chamadas em falta**. Para a cidade
de Dallas existem 15 overrides aprovados, com **2 variantes de texto**:

### 3a. Variante com `{{count}}` — remodeling e plumbing (529 caracteres)

> Hi {{company | Contractor}}. This is an automated message from Magic Leads in
> Dallas. We just released {{count}} active opportunities in your niche right
> now on magicleads.app. While shared lead apps sell the same contact to 5
> local contractors and destroy your margins, we give you the owner's direct
> name, verified address, and job details 5 to 7 days before anyone else in
> your area. You just call, visit, or send a letter, and close the deal before
> your competitors do it. Go to magicleads.app right now. To opt out, press 2.

### 3b. Variante com `{{showcase_line}}` — outros 13 trades (424 caracteres)

> Hi {{company | Contractor}}. This is an automated message from Magic Leads in
> Dallas. We have {{showcase_line}} on MagicLeads.app right now. While shared
> lead apps sell the same contact to multiple contractors, we give you the
> owner's direct name, verified address, and job details before anyone else in
> Dallas. You just call, visit, or send a letter, and close the deal. Go to
> magicleads.app right now. To opt out, press 2.

`{{showcase_line}}` é gerado pelo guard (contagem + trade + cidade), ex.:
`88 active plumbing opportunities in Dallas this week`.

## 4. Outros áudios sintetizados

| Gatilho | Texto | Onde |
|---|---|---|
| Fallback (website redirect, modo AI) | `You can visit MagicLeads.app to see this week's active opportunities. Have a great day!` | `voice_scripts.py:59` / MP3 `backend/static/voice_fallback.mp3` |
| DTMF 2 (opt-out) | `You've been removed from our list. Goodbye.` | `telnyx_voice.py:760` e `:876` |
| DTMF 1 (só modo AI) | `Visit MagicLeads dot app to see this week's active opportunities.` | `telnyx_voice.py:911` |

No modo `static` só o dígito **2** é aceite (`valid_digits="2"`); o texto de
DTMF 1 não é alcançável.

## 5. Versões e histórico

| Versão | Estado | Data (ET) | Tam. | Texto |
|---|---|---|---:|---|
| v1 | draft (nunca aprovada) | 02/11 18:31 | 1.680–1.758 | Script de AI assistant com preço, email, objeções |
| v2 | aprovada | 03/11 01:04 / 01:36 | 551 | "Opening & Pitch", pede email, press 1 |
| v3 | aprovada | 04/11 14:41 | 514 | "Stop wasting money…", website-only, press 2 |
| **v4** | **aprovada / ativa** | **06/11 21:39** | **532** | **Atual (secção 2)** |

- 75 registos em `voice_script_versions`; todos com `created_by=0` (seed
  automático). Não há edições manuais registadas (`updated_by=0` em todas as
  linhas).
- Overrides de Dallas: 15 linhas, `approved_by=0`, criados em 07/11
  (01:39–05:05 UTC). Nenhum override de estado ou de outra cidade.
- `voice_meta.scripts_template_version = 2026-11-06.1`.

### Commits relevantes (`backend/services/voice_scripts.py`)

| Commit | Data (ET) | Alteração |
|---|---|---|
| `4f3f16c` | 05/11 20:07 | Muda `DEFAULT_TEMPLATE` v3→v4 e `TEMPLATE_VERSION` para `2026-11-06.1` |
| `93c83b8` | 06/11 20:36 | Limita city scope e empacota seed Dallas |
| `7716e9c` | 06/11 20:43 | Corrige "over over" na `showcase_line` (city/bundle) |
| `f28fe84` | 06/11 12:56 | Seed dos overrides de Dallas |

Depois de 06/11 20:43 **não houve mais alterações** ao ficheiro.

### Diff material v3 → v4

- v3: `Hi {{company | Contractor}}, this is an automated assistant from Magic
  Leads. We have {{showcase_line}}… Stop wasting money competing with 5 to 8
  other contractors… To remove your number from our list, press 2 now. Have a
  great day!`
- v4: passa a `Hi {{company | Contractor}}. This is an automated message from
  Magic Leads in New York. We just unlocked {{count}} active opportunities…`;
  remove "Stop wasting money", remove "5 to 8", remove "Have a great day",
  adiciona `{{count}}` e a cidade fixa "New York".

## 6. Prova de integridade do áudio (CDR 09/11)

- 43 chamadas atendidas não-máquina ↔ **43 registos TTS**, emparelhados 1:1
  por timestamp (diferença **1,3–6,2 s** após `answered_at`).
- Para cada par, `number_of_characters = 532 − 24 − 9 + len(company) + len(count)`.
- Comprimentos implícitos do `count`: **2, 3 ou 5 caracteres**, coerentes com as
  contagens atuais do guard (remodeling 31→2; electrical 416→3; plumbing
  4.018→5; hvac 2.668→5; painting 1.449→5; windows 509→3).
- Conclusão: o texto sintetizado é **exatamente** o template v4 com
  `company`+`count`; não há texto extra, append ou truncagem.

## 7. Ficheiros e caminhos

| O quê | Caminho |
|---|---|
| Template e registry | `backend/services/voice_scripts.py` |
| Template (fonte única) | `voice_scripts.py:27-37` (`DEFAULT_TEMPLATE`) |
| Discurso / fallback | `voice_scripts.py:23` (`DISCLOSURE`), `:59` (`FALLBACK_SCRIPT`) |
| Versão do template | `voice_scripts.py:25` (`TEMPLATE_VERSION`) |
| Seed da BD | `voice_scripts.py:99-143` (`_apply_template`) e `:188` (`init`) |
| Render por chamada | `voice_scripts.py:866` (`render`) e `:90` (`opening_for_greeting`) |
| TTS em produção | `backend/services/telnyx_voice.py:550-610` (`_start_static_script_for_call`) |
| Dados | `/data/voice.db` → `voice_scripts`, `voice_script_versions`, `voice_script_overrides`, `voice_meta` |
| MP3 fallback | `backend/static/voice_fallback.mp3` (253.056 bytes; commit `122399f`, 03/11 11:18 ET) |

Produção executa o ficheiro com sha256
`bbee6952968e019a1c60b938e36b01f76388b68e6ac0577e52692c2a8d0cdca3`, que é
**exatamente** `master:e1b5ed3` (o ficheiro local difere apenas por CRLF).

## 8. Alertas

1. **"in New York" está fixo no template global.** Qualquer cidade sem override
   (fora de Dallas) ouvirá "New York". Hoje só há campanhas NY + Dallas, mas é
   um risco para futuras cidades.
2. **`{{count}}` é dinâmico e pode ser grande** (ex.: `4,018`). A frase "We just
   unlocked 4,018 active opportunities in your trade" é falada literalmente.
3. **Overrides de Dallas continuam ativos.** Se a campanha 12 retomar, usa-os.
   Se for criada uma nova campanha em Dallas, herda estes textos.
4. **Guard sem inventário hoje:** `roofing` (4 < 5), `landscaping` (0),
   `signage` (0) e `general_contractor` (0) estão `insufficient_trade_inventory`.
   Chamadas nesses trades falham no render e desligam após atendimento (sem
   TTS). A campanha 14 e seguintes incluem roofing/landscaping.
5. **Modo static não usa `DISCLOSURE` nem `TOOL_GUIDANCE`.** O único aviso
   falado é o do corpo ("This is an automated message… To opt out, press 2.").
6. **Sem audit log dedicado.** O histórico é `voice_script_versions`; edições
   futuras via `PUT /api/admin/voice/scripts/{trade}` só ficam registadas se
   `created_by`/`updated_by` forem preenchidos (hoje ficam 0).

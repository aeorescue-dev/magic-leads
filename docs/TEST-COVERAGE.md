# Cobertura de testes — baseline (02/11/2026)

Comando:

```bash
pytest tests -q --cov=backend --cov-report=json:coverage.json
```

- **Total backend: 69,7%** (14 235 / 20 418 statements).
- **1 302 pytest**, **109 vitest**; CI verde.
- O CI gera `coverage.json` e publica-o como artifact `backend-coverage`.

## Módulos fortes

| Módulo | Cobertura |
|---|---:|
| `models/schemas.py` | 98,6% |
| `services/privacy.py` | 100% |
| `services/boston_address.py` | 96,6% |
| `services/mailbox_guard.py` | 94,0% |
| `services/outbound_templates.py` | 93,9% |
| `services/auto_ramp.py` | 92,7% |
| `services/b2b_voice.py` | 85,7% |
| `services/showcase.py` | 88,6% |
| `services/auto_dialer.py` | 76,5% |
| `services/unsubscribe.py` | 93,3% |
| `services/niche_classifier.py` | 94,1% |

## Módulos a melhorar (com impacto no negócio)

| Módulo | Cobertura | Ação |
|---|---:|---|
| `services/inbox_sync.py` | 50,0% | testes de dedupe por message-id, bounce/complaint, sync HTTP |
| `services/enrichment.py` | 50,2% | fixtures CKAN/Socrata para owner/telefone |
| `services/control_tower.py` | 51,6% | queue_age, backup, tokens, freshness |
| `main.py` | 52,7% | endpoints admin/investor/analytics (auth, erros, export) |
| `services/investor.py` | novo | valuation, reconcilição Stripe, NDA, CSV |
| `services/telnyx_voice.py` | 67,7% | webhook Ed25519, retries e estados de chamada |
| `services/voice_scripts.py` | 70,2% | CRUD, preview e sync Telnyx |
| `services/enrichment_queue.py` | 36,3% | retry/backoff e estados |
| `services/phone_lookup.py` | 46,4% | outcomes Searchbug e billing |
| `services/inbox_sync.py` | 50,0% | parser DSN/ARF e supressão |

Alvo: **≥80%** em `investor.py`, `inbox_sync.py`, `enrichment.py`, `control_tower.py` e `main.py` antes da Fase 1B.

## Notas

- A cobertura mede linhas, não qualidade; testes de contrato (auth, PII, idempotência, watermark) valem mais do que o número.
- O Investor Room publica este baseline e a data de medição; não declara “100%”.
- `coverage.json` é artifact de CI e está no `.gitignore`.

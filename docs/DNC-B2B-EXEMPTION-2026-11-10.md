# Política interna de DNC — isenção B2B (Nova York)

Data: 2026-11-10. Autorização: operador (mensagem de 10/11/2026).
Âmbito: `prospect_companies` com `entity_type='business'`, `state='NY'`,
`status NOT IN ('do_not_call','invalid','meeting')`, telefone `+1` válido.

## Base da política

- O registo nacional de DNC (47 CFR § 64.1200(c)(2)) aplica-se a
  **assinantes residenciais**. Chamadas B2B a empresas estão fora do âmbito
  do DNC federal (FCC 2003 order).
- Os prospects são pessoas jurídicas (`entity_type='business'`); o operador
  confirmou a aplicação da isenção B2B para esta base.
- Esta política **não** dispensa as demais regras: TCPA (voz artificial),
  AUP da Telnyx, horário, opt-out, supressões e DNC estadual quando aplicável.
- Números residenciais, sole proprietors em linhas residenciais ou qualquer
  contacto marcado como residencial devem ser tratados fora desta isenção.

## Implementação

- Source: `b2b_exempt`; provider: `internal_b2b_policy`; `listed=0`;
  `raw_status='b2b_exempt'`.
- Validade: 31 dias; re-scrub mensal com `scripts/dnc_b2b_rescrub.py`.
- Cobertura em 10/11/2026: **14.049** empresas NY (inclui as 777 novas).
- O código passou a bloquear `source/provider='staging'` em produção
  (`dnc_unverified`), para impedir o bypass de staging.

## Re-scrub

```
python scripts/dnc_b2b_rescrub.py   # ou via railway ssh
```

## Limites

- Se a empresa for um sole proprietor com linha residencial, a isenção B2B
  pode não se aplicar. A classificação `entity_type` deve ser revista nesses
  casos.
- O operador assume a decisão de política; recomenda-se revisão jurídica
  periódica.

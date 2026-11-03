# Auditoria de custos Telnyx — 2026-11-03

Conta: `magicleadsus@gmail.com` (trial). Fonte: API v2 da Telnyx
(`/balance`, `/charges_summary`, `/charges_breakdown`, `/usage_reports`).

## Saldo

| Item | Valor |
|---|---:|
| Saldo disponível | **$1.78** |
| Crédito de boas-vindas | **$5.00** |
| `grand_total` do período (01–04/11) | **$3.07** |
| `new_otc` (número) | $1.00 |
| `new_mrc` (número, pro-rata) | $0.93 |
| Surcharges / other | $0.00 |

**Não existe um crédito de $25 nesta conta.** A única linha de crédito é
`Welcome Credit = $5.00` (o trial Telnyx dá $5 de crédito de teste). Se houve
uma promo de $25, não está aplicada a esta conta/organização.

## Uso por produto (01–04/11)

| Produto | Custo |
|---|---:|
| `ai-voice-assistant` | **$1.000** |
| `sip-trunking` | $0.130 |
| `noise-suppression` | $0.060 |
| `recording` | $0.040 |
| `call-control` | $0.040 |
| `messaging` (SMS de verificação) | $0.017 |
| **Total de usage** | **$1.287** |
| `text-to-speech` | $0.000 |
| `inference` | $0.000 |
| `amd` | $0.000 |
| `speech-to-text` | $0.000 |

## Número

- Número local `+15189429910`, comprado em `2026-11-03T04:59:06Z`.
- OTC: $1.00.
- MRC pro-rata: $0.93.
- HD Voice: $0.00.
- TeXML Applications (10 criadas/apagadas): sem custo visível.

## Chamadas falhadas por D60

Não há linha separada de penalização por D60. As chamadas falhadas aparecem
apenas em `call-control` ($0.04) e `sip-trunking` ($0.13), valores residuais.
O D60 não explica o consumo do saldo.

## Leitura

O consumo real é aproximadamente:

```text
número (OTC + MRC)      $1.93
AI voice assistant      $1.00
SIP trunking            $0.13
noise suppression       $0.06
recording               $0.04
call control            $0.04
SMS verificação         $0.02
------------------------------
total                   $3.22
```

$5.00 − $3.22 ≈ $1.78, exatamente o saldo atual. A diferença para o
`grand_total` de $3.07 é arredondamento/pro-rata.

## Observações

- O maior custo de usage é o **AI voice assistant** ($1.00), não as chamadas
  SIP. Com ~20 chamadas de teste, é ~$0.05/chamada.
- O número ($1.93) pesa mais do que todas as chamadas juntas.
- `text-to-speech` (MP3 de fallback), `amd`, `speech-to-text` e `inference`
  aparecem a $0.00 neste período.
- A gravação está ligada no assistant (`recording_settings.enabled=true`);
  desligar poupa uma fração por chamada, mas não é o problema.
- Para operação real: carregar saldo, definir spend limits e só depois subir
  para os 9.870 contactos.

## Atualização 2026-11-03 (noite)

- Número NYC `+1 929 256 2550`: $1 ativação + $1/mês. O antigo `+1 518 942 9910`
  fica como backup; o caller ID da campanha #3 passa a ser o 929.
- Chamada de teste #34 (voicemail, AMD `machine`): 2c.
- Saldo disponível após a compra e os testes: ~$9,02.

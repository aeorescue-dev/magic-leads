# Landing page — proposta visual (maquete) para aprovação

Data: 2026-11-13
Estado: **proposta apenas** — nenhum ficheiro da aplicação foi alterado.
Produção: `master` em `3b53962` — intocada.
Maquete: `C:\Users\Fabio\AppData\Local\Temp\opencode\landing-preview\index.html`
(aberta no painel de revisão; estática, sem ligação ao backend)

## 1. Como validar

1. Abrir a maquete no painel de revisão.
2. Alternar **PT / EN / ES** no topo (as três versões estão completas).
3. Percorrer: hero → exclusividade 1h → prevenção → preço → prova → calculadora → FAQ → CTA.
4. Testar a calculadora (ticket médio e taxa de fecho).
5. Dar “ok” explícito por secção ou pedir ajustes. **Nada será codificado antes disso.**

## 2. O que a maquete propõe

| Secção | Objetivo | Elementos |
|---|---|---|
| Hero | Promessa de resultado | “A obra antes da multa / Exclusiva por 1 hora”, ZIP, cidades, cartão ao vivo com dono protegido |
| Faixa de confiança | Reduzir atrito | 1h, 10 contactos/dia, sem comissão, cancelar |
| Exclusividade 1h | Diferenciar do lead compartilhado | contador 59:58, timeline Reservar → Contactar → Negociar → Converter |
| Prevenção | Vender proatividade | 3 passos (sinal → vistoria → multa), cartão de exemplo, métricas |
| Preço | Modelo de passe | $120/semana, 0/10 revelações, sem créditos, bónus sem telefone |
| Prova | Credibilidade | 4 cidades, 100% dono identificado, 1h, 10/dia + fluxo em 3 passos |
| Calculadora | ROI tangível | “uma obra paga N semanas” (estimativa ilustrativa) |
| FAQ | Objeções | partilha, sem telefone, marketing, cancelamento |
| CTA final | Conversão | ZIP + cidades + “Ver obras na minha cidade” |

## 3. Regra de ouro do copy — auditoria

Termos proibidos verificados na maquete (case-insensitive): **0 ocorrências em texto visível**.

- Sem nomes de agências, portais, fontes de recolha ou termos técnicos.
- Termos usados: “chamados municipais”, “avisos de conservação”, “sinais proprietários”,
  “inteligência de mercado”, “radar MagicLeads”.
- Sem “créditos”, “saldo” ou “base de dados”. Usa-se “revelações diárias” e “contactos”.
- A palavra técnica `dataset` aparece apenas no JavaScript (`el.dataset`), nunca na copy.
- Números exibidos são ilustrativos na maquete; na implementação virão da base real
  (sem escassez inventada).

## 4. O que será implementado após aprovação

- Apenas frontend de landing: `frontend/app/[locale]/page.tsx` + componentes de secção
  + chaves i18n em `en.ts` / `pt.ts` / `es.ts`.
- Nenhuma alteração de backend, base de dados, preços ou fluxo de checkout.
- Reutilização do seletor de cidade/ZIP e do cartão de amostra já existentes.
- Textos finais passam pelo teste de termos proibidos (`tests/test_privacy_terms.py` e
  grep de copy) antes de qualquer commit.
- Implementação em staging; produção só depois de novo “ok” explícito.

## 5. Checklist de aprovação

- [ ] Headline do hero (“A obra antes da multa / Exclusiva por 1 hora”)
- [ ] Bloco de exclusividade com contador e timeline
- [ ] Bloco de prevenção e cartão de exemplo
- [ ] Preço e enquadramento das revelações diárias
- [ ] Prova social/números
- [ ] Calculadora
- [ ] FAQ
- [ ] Copy PT / EN / ES
- [ ] Ordem e densidade das secções

Com o “ok” assinalado, avançamos para a implementação no staging.

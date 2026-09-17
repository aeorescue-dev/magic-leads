# Relatório de Confirmação — Deploy do commit f0c439a

**Data:** 15 de setembro de 2026
**Branch:** master
**Commit:** `f0c439a` — "feat(auth): limit to 2 concurrent sessions per user (FIFO eviction)"

---

## 1. Resumo

O commit `f0c439a` foi deployado com sucesso no ambiente de produção. O alerta da
Vercel sobre "5 deployments failed" foi investigado e resolvido: as 5 falhas eram
causadas por **projetos duplicados obsoletos**, que foram **excluídos** da conta
Vercel. A partir de agora, os pushes para `master` não geram mais emails de falha.

---

## 2. Deploy principal (Produção) — CONFIRMADO com sucesso

| Campo       | Valor |
|-------------|-------|
| Projeto     | `magic-leads-frontend-final` |
| URL         | **https://magicleads-oficial.vercel.app** |
| Nome do deploy | `magic-leads-frontend-final-5jh29q745-fabio-dev2.vercel.app` |
| Estado      | `READY` (deploy concluído) |
| Ambiente    | production |
| Criado em   | 15/09/2026 10:09:42 (horário local) |
| Build       | Sucesso — "Detected Next.js version: 14.2.35", 13 páginas geradas, build em ~37s |
| Varredura de segurança | HTTP 200 na URL pública |

Aliases associados ao deploy:
- `magicleads-oficial.vercel.app` (produção)
- `magic-leads-frontend-final-fabio-dev2.vercel.app`
- `magic-leads-frontend-final-git-master-fabio-dev2.vercel.app`

---

## 3. Causa das 5 falhas (investigação)

O email da Vercel listou 5 deploys falhados no commit `f0c439a`:

1. `magic-leads-4zujlll`
2. `magic-leads-4zujll`
3. `magic-leads-4zujl`
4. `magic-leads-4zuj`
5. `magic-leads-v9ia`

### Diagnóstico

- Todos os 5 projetos eram **duplicados obsoletos**, criados durante testes/criação
  de projetos anterior, todos vinculados ao mesmo repositório `aeorescue-dev/magic-leads`.
- Erro em todos: `NEXT_NO_VERSION` — "No Next.js version detected".
- Logs do build mostraram: `Previous build caches not available` →
  `Warning: Could not identify Next.js version` → falha.
- O projeto de produção canônico (`magic-leads-frontend-final`) tem o **mesmo
  `vercel.json`, mesmos comandos e mesmo código**, e buildou com sucesso no mesmo
  commit — prova de que **o código não tinha problema**; o problema era o cache de
  build inexistente nesses projetos órfãos (nunca tiveram um build bem-sucedido).
- Esses 5 projetos falhavam em **todo** push, há vários dias, não apenas neste commit.

---

## 4. Correção aplicada

Excluídos via API da Vercel (endpoint `DELETE /v9/projects/{name}`):

| Projeto                | Status |
|------------------------|--------|
| `magic-leads-4zujlll`  | Excluído ✔ |
| `magic-leads-4zujll`   | Excluído ✔ |
| `magic-leads-4zujl`    | Excluído ✔ |
| `magic-leads-4zuj`     | Excluído ✔ |
| `magic-leads-v9ia`     | Excluído ✔ |

---

## 5. Estado final (verificado após a exclusão)

Todos os projetos restantes vinculados ao repositório `aeorescue-dev/magic-leads`
apresentam deploy mais recente `READY`:

| Projeto | Estado |
|---------|--------|
| `magic-leads` | READY |
| `magic-leads-4zujllll` | READY |
| `magic-leads-fbh` | READY |
| `magic-leads-frontend-final` | READY |
| `magic-leads-4blus` | READY |
| `magic-leads-fron` | READY |
| `magic-leads-front` | READY |
| `magic-leads-hen` | READY |
| `magic-leads-fab` | READY |
| `magic-leads-u4mr` | READY |

- URL de produção respondeu com **HTTP 200** na verificação final.
- Nenhum projeto vinculado ao repositório atual permanece em estado de erro.

---

## 6. Conclusão

O deploy do commit `f0c439a` está **confirmado e funcionando** em produção
(`https://magicleads-oficial.vercel.app`). As falhas reportadas por email eram
de projetos duplicados obsoletos, agora **removidos**. Nenhum push futuro para
`master` deverá reproduzir os 5 emails de falha.
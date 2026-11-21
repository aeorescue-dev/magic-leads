# Auditoria de domínios de email — 2026-11-21

**Modo:** somente leitura em produção (`/data/leads.db`). Apenas domínios e
contagens; nenhum email, nome ou empresa individual foi exposto.

---

## 1. Totais

| Métrica | Valor |
|---|---:|
| Contas registadas | **126** |
| Domínios distintos | 11 |
| Genéricos (Gmail/Hotmail/Outlook) | **111** (88,1%) |
| Domínios próprios/empresariais | **15** (11,9%) em 8 domínios |
| Domínios descartáveis | **0** |
| Email verificado | **0** (coluna existe; fluxo de verificação ainda desligado) |

> Nota: o pedido falava em “+400 emails”; a tabela `users` tem **126** contas.
> As ~400 podem ser leads/contactos B2B, não utilizadores registados.

## 2. Genéricos

| Domínio | Contas | Verificados |
|---|---:|---:|
| gmail.com | 107 | 0 |
| hotmail.com | 3 | 0 |
| outlook.com | 1 | 0 |
| **Total** | **111** | **0** |

## 3. Domínios próprios/empresariais (15)

| Domínio | Contas | Observação |
|---|---:|---|
| magicleads.app | 4 | interno/teste |
| gmqil.com | 4 | provável gralha de gmail.com |
| example.com | 2 | teste |
| hcdjdbc.com | 1 | aleatório (teste?) |
| gmwil.com | 1 | provável gralha de gmail.com |
| gmial.com | 1 | provável gralha de gmail.com |
| dsjbfjsvbb.com | 1 | aleatório (teste?) |
| bsdbrng.com | 1 | aleatório (teste?) |

**Leitura:** depois de excluir interno, testes e gralhas de Gmail, **não há
domínios empresariais reais** na base. O perfil é quase todo consumidor/individual
(Gmail), o que reforça o bónus free como porta de entrada.

## 4. Planos (contexto)

| Plano / estado | Contas |
|---|---:|
| free / expired | 95 |
| free / inactive | 12 |
| free / trial | 7 |
| pro / active | 10 |
| free / active | 1 |
| free / trialing | 1 |
| **Acesso ativo (`plan_until` futuro)** | **4** |

## 5. Implicações para o bónus

- Com 88% Gmail, a normalização de aliases (`+tag`/pontos) é o gate mais
  importante; o de domínio próprio quase não se aplica.
- **0 verificados**: quando a flag ligar, a verificação de email passa a ser o
  primeiro filtro real — hoje ninguém está verificado.
- Sem domínios descartáveis registados; a lista de bloqueio fica preventiva.

# Landing oficial — relatório de reversão e nova proposta (copy-only)

Data: 2026-11-13
Produção: `master` em `3b53962` — intocada.
Estado do código: **revertido ao original** (nenhuma alteração pendente na landing).

## 1. Reversão executada

Todos os ajustes rejeitados foram revertidos com `git restore` nos ficheiros da landing
oficial:

- `frontend/app/[locale]/(marketing)/page.tsx`
- `frontend/lib/i18n/en.ts`
- `frontend/lib/i18n/pt.ts`
- `frontend/lib/i18n/es.ts`

Resultado: `git diff` **vazio** para o código da aplicação. A home voltou exatamente à
estrutura original:
- hero original (“O dono acabou de pedir a reforma…”);
- eyebrow/sub originais;
- sem secção `#prevencao`, sem pill extra, sem item “Prevenção” na navbar;
- preço e FAQ originais;
- inventário interativo à direita **intacto** (mesmo componente, mesmas props).

Também foi removido o relatório da tentativa rejeitada. A página paralela
(`landing-preview`) já tinha sido apagada no commit anterior, conforme pedido.

## 2. Sobre o inventário interativo à direita

O painel **não foi alterado** em nenhum momento. A prova:

- `LiveTradeGrid.tsx` é o mesmo; o hero continua a renderizar
  `preview`, `featuredLimit={12}` e o bloco de conversão.
- O estado vazio que aparece no staging (“Nenhuma especialidade tem 10+ obras ativas neste
  ZIP agora”) vem da regra `MIN_ACTIVE = 10` em `LiveTradeGrid.tsx` e dos dados de staging:
  a API pública devolve **2 sinais ativos em New York** (1 Heating + 1 Elevator), abaixo do
  limiar de 10.
- Em produção, com volume real, o painel preenche as categorias e o bloco de conversão.
- A captura `current-landing.png` (tirada **antes** dos ajustes) mostra exatamente o mesmo
  estado vazio — logo, não houve regressão de UI.

Se quiserem validar o painel preenchido no staging, podemos semear 10+ sinais num único ZIP
(apenas dados de demonstração; nenhuma alteração de código).

## 3. Nova proposta — cirúrgica, só copy, sem tocar no layout

Regras aplicadas:
- **Zero** menções a órgãos públicos, “municipal”, “prefeitura”, “governo”, portais ou
  qualquer pista de origem.
- Vocabulário: “radar MagicLeads”, “sinais proprietários”, “antes da multa”, “gravidade e
  prazo”, “inteligência de mercado”.
- Nenhuma secção nova, nenhum item de menu, nenhum pill, nenhuma mudança de grelha.
- Apenas substituição de strings existentes (e, no máximo, uma pergunta de FAQ).

### 3.1 Recomendado — uma frase no bloco escuro existente (`landing.problemSub`)

É o encaixe mais natural: o bloco já fala em “chegar primeiro”.

**PT**
> Toda semana tem dono precisando de reparo a 20 minutos de você. O dinheiro não está no
> anúncio. Está em ser o primeiro a ligar com o nome e o endereço certo. **O radar MagicLeads
> mostra o sinal, a gravidade e o prazo antes de virar multa.**

**EN**
> Every week an owner needs a repair 20 minutes from you. The money is not in the ad. It is
> in being the first to call with the right name and address. **The MagicLeads radar shows
> the signal, severity and deadline before it becomes a fine.**

**ES**
> Cada semana un dueño necesita un arreglo a 20 minutos de ti. El dinero no está en el
> anuncio. Está en ser el primero en llamar con el nombre y la dirección correctos. **El
> radar de MagicLeads muestra la señal, la gravedad y el plazo antes de que se convierta en
> multa.**

### 3.2 Opcional — sub do hero (`landing.heroSub`)

**PT**
> A sua próxima obra começa agora. **Chegue antes do risco**, conecte-se ao dono e garanta o
> contrato hoje mesmo.

**EN**
> Your next job starts now. **Arrive before the risk**, connect with the owner and secure the
> contract today.

**ES**
> Tu próxima obra empieza ahora. **Llega antes del riesgo**, conéctate con el dueño y asegura
> el contrato hoy mismo.

### 3.3 Opcional A/B — eyebrow (`landing.heroEyebrow`)

- PT: “ENCONTRE A SUA OBRA ANTES DO RISCO E FATURE!”
- EN: “FIND YOUR JOB BEFORE THE RISK AND GET PAID!”
- ES: “¡ENCUENTRA TU OBRA ANTES DEL RIESGO Y GANA!”

### 3.4 Opcional — uma pergunta no FAQ existente

Pergunta: “Como a prevenção funciona?”
Resposta: “O radar MagicLeads identifica sinais de risco antes de virarem multa e mostra
gravidade e prazo. Você age primeiro, com o contacto do proprietário.”

(Se preferirem não acrescentar itens, esta opção fica de fora.)

## 4. O que não será tocado

- Hero, painel ao vivo, simulador, comparativo, calculadora, templates, preço e CTA.
- Nenhum componente novo, nenhuma secção nova, nenhuma alteração de navegação.
- Backend, base de dados, checkout e autenticação.

## 5. Processo

1. Escolher **apenas** as linhas aprovadas (3.1 é a recomendada).
2. Aplicar as strings na landing oficial, no staging.
3. Mostrar captura antes/depois e o diff exato.
4. Só depois do “ok” final: commit no staging. Produção apenas com nova autorização.

Produção continua em `master` `3b53962`, sem alterações, deploys ou migrações.

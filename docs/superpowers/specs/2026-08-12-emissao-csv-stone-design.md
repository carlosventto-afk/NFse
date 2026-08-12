# Emissão de NFS-e a partir do relatório CSV de recebimentos da Stone

Data: 2026-08-12

## Contexto

O plano anterior (`docs/superpowers/specs/2026-08-11-nfse-stone-webhook-design.md`)
previa emissão automática via webhook `charge.paid` da API Connect da Stone.
Essa via foi **adiada**: o acesso à API Connect exige cadastro no Stone
Partner Program, que tem custo — programa desenhado para software houses que
atendem muitos lojistas Stone, não para um lojista único acessando o próprio
webhook. Scraping do portal da Stone para contornar essa restrição foi
avaliado e descartado (risco real de suspensão de uma conta de instituição
de pagamento, da qual o negócio depende para faturar).

Alternativa adotada agora: a Stone já oferece, como recurso oficial do
portal, um **relatório de recebimentos em CSV** — o usuário baixa
manualmente e sobe no sistema, que emite as notas correspondentes. Não é
scraping (é um export que a própria Stone disponibiliza), e não depende de
nenhum acesso além do que o lojista já tem hoje.

O webhook automático (spec anterior) permanece como evolução futura — nada
neste documento invalida o que já foi construído (worker, numeração,
tomador opcional, portal). Esta é uma nova via de **entrada** de dados, que
reaproveita todo o pipeline de emissão já existente.

## Objetivo

Permitir que o usuário suba o relatório CSV de recebimentos da Stone e o
sistema gere uma NFS-e para cada venda paga do período, com uma prévia de
conferência (contagem de notas e valor total) antes de qualquer nota ser
efetivamente disparada para emissão.

## Formato do arquivo de entrada

Relatório oficial "recebimentos" da Stone: CSV separado por `;`, codificado
em **UTF-8 com BOM**. Colunas relevantes (nomes exatos do cabeçalho):

| Coluna | Uso |
|---|---|
| `CATEGORIA` | só linhas `Venda` geram nota |
| `DATA DA VENDA` | data/hora da venda (`dd/mm/aaaa HH:MM:SS`) — competência da nota = mês desse valor |
| `STONE ID` | identificador da transação — usado como chave de deduplicação |
| `QTD DE PARCELAS` / `Nº DA PARCELA` | quando `QTD DE PARCELAS` > 1, linhas da mesma venda são agrupadas |
| `VALOR BRUTO` | valor da nota (decimal com vírgula, ex: `27,980000`) — **não** `VALOR LÍQUIDO` (esse já vem descontado da taxa da Stone, que é custo operacional do lojista, não desconto do serviço) |
| `ÚLTIMO STATUS` | só linhas `Pago` geram nota |

O relatório não traz nenhum dado do cliente (CPF/CNPJ/nome) — consistente
com o tomador opcional já implementado.

## Regras de leitura e agrupamento

1. Ignorar linhas com `ÚLTIMO STATUS` ≠ `Pago` (motivo: `status_nao_pago`).
2. Ignorar linhas com `CATEGORIA` ≠ `Venda` (motivo: `categoria_nao_venda`).
3. Das linhas restantes:
   - `QTD DE PARCELAS` = 1 → cada linha é uma nota, valor = `VALOR BRUTO`
     da própria linha.
   - `QTD DE PARCELAS` > 1 → agrupar todas as linhas com a mesma
     `DATA DA VENDA` **e** o mesmo `QTD DE PARCELAS`; o valor da nota é a
     soma de `VALOR BRUTO` do grupo. **Risco em aberto**: não há, no
     relatório, um identificador explícito de "venda" que ligue as
     parcelas — a suposição de que parcelas da mesma venda compartilham
     `DATA DA VENDA` idêntica não foi validada contra um exemplo real de
     venda parcelada (o relatório de referência só tem vendas à vista).
     Validar assim que houver uma venda parcelada real para conferir.
4. Deduplicação: a chave é o `STONE ID` da linha (ou da parcela de número 1
   do grupo, quando agrupado). Gravada no campo `Emissao.stone_charge_id`
   — o mesmo campo que a idempotência do webhook já usa, com o mesmo
   índice único por empresa. Se a linha/grupo já corresponde a uma
   `Emissao` existente da mesma empresa, é ignorada (motivo:
   `ja_emitida_anteriormente`), sem gerar nem consumir número novo.
5. Linha com data ou valor em formato inesperado (fora do padrão do
   relatório) é ignorada individualmente (motivo: `linha_invalida`) — não
   derruba o processamento do arquivo inteiro.
6. Cabeçalho do arquivo que não bate com o esperado (coluna obrigatória
   ausente ou renomeada) rejeita o arquivo inteiro antes de processar
   qualquer linha (erro claro, não tenta adivinhar).

## Arquitetura

```
Usuário           [POST /emissoes/csv/preview]         [POST /emissoes/csv/confirmar]
  |  sobe arquivo -------> parser (sem gravar) -------> devolve prévia
  |
  |  confere prévia, clica "confirmar"
  |  reenvia o MESMO arquivo -----> parser (de novo) --> para cada grupo válido e não-duplicado:
  |                                                         reserva número + grava Emissao (origem=csv, pendente)
  v                                                              |
[portal mostra progresso/lista]  <----------------------  worker existente processa (sem nenhuma mudança nele)
```

Sem tabela nova de "rascunho de importação": `preview` não persiste nada;
`confirmar` reprocessa o arquivo recebido nessa chamada (determinístico —
o mesmo arquivo sempre produz o mesmo resultado) e grava diretamente as
`Emissao` válidas, reaproveitando 100% do pipeline já existente
(`reservar_proximo_numero`, `app/worker.py`, `nfse_core`). As próprias
notas criadas (`origem=csv`) já são o rastro de auditoria de o que foi
processado — não há necessidade de um histórico de tentativas de upload
separado.

Reparsear o arquivo duas vezes (uma no preview, outra na confirmação) é
uma decisão deliberada: mais simples que manter estado entre as duas
chamadas, e o custo de reparsear um CSV texto de algumas centenas de
linhas é irrelevante.

## Mudança no modelo de dados

Mínima: `OrigemEmissao` (enum) ganha um terceiro valor, `csv`, ao lado de
`webhook` e `manual`. Nenhuma tabela nova, nenhuma coluna nova em
`Emissao` — o campo `stone_charge_id` já existente é reaproveitado como
chave de deduplicação também para as linhas do CSV.

## Endpoints

- `POST /emissoes/csv/preview` (multipart, autenticado, escopado à
  empresa do usuário) — parseia, filtra, agrupa; devolve contagem total de
  notas, valor total somado, e a contagem de linhas ignoradas por motivo
  (`status_nao_pago`, `categoria_nao_venda`, `ja_emitida_anteriormente`,
  `linha_invalida`). Não grava nada.
- `POST /emissoes/csv/confirmar` (multipart, mesmo formato) — reparseia o
  arquivo enviado nessa chamada; para cada grupo válido e não-duplicado,
  reserva número transacional e grava `Emissao` (`origem=csv`,
  `status=pendente`). Devolve o mesmo formato de resumo do preview, agora
  refletindo o que foi de fato criado.

## Testes

- Parser: linha válida única, linha ignorada por `status_nao_pago`, linha
  ignorada por `categoria_nao_venda`, grupo de parcelamento somado
  corretamente, conversão de valor decimal com vírgula.
- `preview` não grava nenhuma `Emissao` nem avança `proximo_numero` da
  empresa.
- `confirmar` cria as `Emissao` esperadas com número reservado
  corretamente; reenviar o mesmo arquivo não duplica nada (idempotência
  via `stone_charge_id`).
- Upload de uma empresa não afeta/vê dados de outra (mesmo padrão de
  isolamento já testado em `tests/test_tenant_isolation.py`).
- Arquivo com cabeçalho incompatível é rejeitado (400) antes de processar
  qualquer linha, sem gravar nada.

## Fora de escopo (por ora)

- Upload em formato XML (o CSV é o único formato de entrada por agora; XML
  já existe no sistema, mas como formato de **saída** — download da nota
  autorizada, recurso já implementado).
- Histórico/auditoria de tentativas de upload não confirmadas.
- Emissão automática via webhook da Stone (spec anterior, adiada, não
  cancelada).
- Interface para o usuário corrigir/editar uma linha inválida diretamente
  na tela de prévia — linha inválida fica de fora do lote; corrigir exige
  ajustar a planilha e subir de novo.

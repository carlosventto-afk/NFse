# Emissão automática de NFS-e a partir de webhook da Stone

Data: 2026-08-11

## Contexto

Existe hoje um kit Python (`nfse-nacional-kit/`) extraído de um ERP em produção
que resolve a parte fiscal da emissão de NFS-e no padrão Nacional (montagem do
XML da DPS, assinatura com certificado A1, comunicação com a SEFIN,
cancelamento e leitura de resposta). O kit é deliberadamente "burro": não sabe
nada sobre banco de dados, autenticação, webhooks ou o negócio de quem o usa —
ver `nfse-nacional-kit/nfse-nacional-kit/docs/INTEGRACAO.md`.

O objetivo deste projeto é construir o sistema em volta desse núcleo: receber
uma notificação de pagamento da Stone (venda de serviço de lavagem de roupa),
emitir a NFS-e automaticamente, registrar tudo em banco, e oferecer um portal
onde um usuário da empresa consulta as emissões, baixa o XML/PDF, acompanha
valores acumulados e, quando necessário, emite uma nota manualmente (fora do
gatilho automático do webhook).

## Objetivo

Automatizar emissão de NFS-e Nacional disparada por pagamento aprovado na
Stone, com registro auditável e portal de consulta/download — para uma ou mais
empresas (multiempresa desde o modelo de dados, ainda que hoje só uma empresa
utilize). O portal também permite emissão manual, para cobranças fora do fluxo
Stone (ex: venda não passou pela maquininha, reemissão de um caso não
capturado pelo webhook).

## Fora de escopo (por ora)

- UI de administração multiempresa (convite, onboarding self-service). Só o
  suporte de dados (`empresa_id` em toda tabela relevante) entra agora.
- Emissão em lote / processamento de alto volume (Celery, filas dedicadas).
- Cancelamento de nota pelo portal (o `nfse_core` já suporta; a UI fica para
  uma iteração futura).
- Qualquer coisa que dependa do payload real do webhook da Stone além do que
  está documentado publicamente hoje (autenticação da chamada, nome exato dos
  campos) — será ajustado quando o cadastro de parceiro for aprovado e o
  payload real puder ser inspecionado.

## Pré-requisitos externos (bloqueantes, fora do controle deste projeto)

- Cadastro como parceiro Stone (trilha "Plug-in Partner") em
  `partner.stone.com.br/formulario`, para liberar chaves e o webhook de
  `charge.paid` da API Connect. Enquanto isso, o sistema é desenvolvido contra
  um payload de exemplo documentado publicamente.
- Certificado A1 (e-CNPJ) da empresa, inscrição municipal, e confirmação de
  adesão do município ao Sistema Nacional.
- Código de tributação nacional (`c_trib_nac`, LC116) do serviço de lavagem de
  roupa. Evidência do usuário aponta para o item LC116 14.10 (tinturaria e
  lavanderia — CNAE 9601-7/01-00); o dígito de desdobro de 6 posições ainda
  precisa ser confirmado contra a tabela oficial do ANEXO antes de emitir de
  verdade.

## Arquitetura

```
Stone (evento charge.paid)              Portal web (formulário manual)
        |  webhook HTTP                          |  usuário preenche tomador/valor
        v                                         v
[Recebedor do webhook] -- dedup            [Emissão manual]
  por stone_charge_id                     sem stone_charge_id
        |                                         |
        +------------------+----------------------+
                            v
        grava linha "pendente" em emissoes (mesma transação que reserva o número)
                            v
                [tabela emissoes, status=pendente]
                            |  worker consome
                            v
                    [Worker de emissão]
        monta DPS (adaptador) -> assina (nfse_core.signer) -> envia (nfse_core.client)
                            |
                            v
          atualiza emissoes: autorizada (chave_acesso, xml_nfse) | rejeitada (erros)
                            |
                            v
[Portal web] <- usuário faz login, lista emissões, baixa XML/PDF, vê acumulados
```

Componentes:

1. **Recebedor do webhook** (FastAPI): endpoint que recebe o evento da Stone,
   valida que a chamada é legítima, verifica idempotência pelo identificador
   da cobrança Stone, e grava a emissão como `pendente` — sem chamar a SEFIN
   diretamente. Responde rápido; não bloqueia esperando a emissão.
2. **Worker**: processo separado que consome linhas `pendente`, roda o fluxo
   do `nfse_core`, e grava o resultado. Implementado como polling simples na
   tabela (sem fila dedicada) — volume de uma lavanderia não justifica
   Celery/Redis agora; trocar a implementação do worker depois é uma mudança
   isolada.
3. **Núcleo fiscal**: `nfse_core/`, com um ajuste pontual e deliberado em
   `dps.py`: o documento do tomador (CPF/CNPJ) passa a ser opcional — quando
   ausente, o bloco `toma` inteiro é omitido do XML, em vez de levantar
   `ValueError`. Justificado por evidência real (ver "Riscos e decisões em
   aberto"), mas **não verificado contra o validador real da SEFIN** até a
   primeira emissão em homologação — nenhuma outra mudança entra no núcleo
   fiscal nesta fase.
4. **Portal web**: login por empresa, listagem de emissões com filtro por
   período/status, download do XML autorizado (o documento fiscal) e do PDF
   (com fallback próprio se a API do ADN falhar — `ARMADILHAS.md` item 10),
   painel de valor acumulado por período, e um formulário de **emissão
   manual** — usuário informa tomador (CPF/CNPJ, nome), descrição e valor, e a
   emissão segue o mesmo caminho (reserva de número, worker, mesmo
   `nfse_core`) que a automática, só sem `stone_charge_id`.

## Modelo de dados (essencial)

- `empresas`: cnpj, inscrição municipal, município (código IBGE), certificado
  A1 cifrado + data de validade, série e próximo número (numeração
  transacional), ambiente (homologação/produção), código de tributação padrão
  do serviço.
- `usuarios`: vinculado a `empresa_id`, papel (admin/operador).
- `emissoes`: `empresa_id`, `origem` (webhook/manual), `stone_charge_id`
  (nulo quando `origem=manual`; chave de idempotência única por empresa
  quando presente), status (pendente/autorizada/rejeitada/cancelada), numero,
  serie, dps_id, chave_acesso, xml_dps, xml_nfse, erros (json traduzido),
  tomador (cpf/cnpj **opcional**, nome — vem do payload Stone ou do
  formulário manual; nota emitida sem documento do tomador quando ausente),
  valor, criada_por (usuário, quando manual), criada_em.

Numeração é um contador transacional por `empresa_id` + série
(`UPDATE ... RETURNING`), conforme `INTEGRACAO.md` do kit — nunca
`max(numero) + 1` fora de transação.

## Fluxo de emissão

**Automático (webhook):**

1. Webhook chega → valida origem → verifica se `stone_charge_id` já existe
   para a empresa (idempotência: Stone pode reenviar o mesmo evento).
2. Se novo: dentro de uma transação, reserva o próximo número e grava a linha
   `pendente` (`origem=webhook`). Isso acontece **antes** de qualquer chamada
   à SEFIN — se o processo morrer no meio, sobra um registro pendente
   rastreável.

**Manual (portal):**

1. Usuário autenticado preenche o formulário (tomador — documento opcional,
   descrição, valor). Quando informado, o CPF/CNPJ é validado (11 ou 14
   dígitos); valor positivo é sempre obrigatório. Isso acontece na submissão,
   antes de consumir número.
2. Dentro de uma transação, reserva o próximo número e grava a linha
   `pendente` (`origem=manual`, `criada_por=usuário`, sem `stone_charge_id`).

**Comum aos dois (worker):**

3. Worker pega a linha pendente, monta a `DpsData` via adaptador, assina,
   envia à SEFIN — o worker não distingue `origem`, o caminho é o mesmo a
   partir daqui.
4. Resposta interpretada de forma tolerante (`ler_resposta_emissao`); grava
   `autorizada` (com XML e chave de acesso) ou `rejeitada` (com erros
   traduzidos).
5. Usuário acessa o portal, vê a lista, baixa o XML/PDF, consulta valores
   acumulados.

## Riscos e decisões em aberto

- **Identificação do tomador (CPF/CNPJ) — decidido**: o usuário forneceu uma
  NFS-e real, emitida pela prefeitura de Belém/PA para o mesmo CNPJ/serviço
  de lavanderia, com o tomador explicitamente como "NÃO IDENTIFICADO" (campo
  em branco) — a nota foi aceita (depois cancelada por outro motivo, erro de
  preenchimento, não relacionado ao tomador). Essa é evidência real de que a
  identificação do tomador não é sempre obrigatória para este tipo de
  serviço/município. Decisão: `nfse_core/dps.py` é ajustado para tornar
  `toma_cpf_cnpj` opcional — quando ausente, o bloco `toma` inteiro é omitido
  do XML (mesmo formato observado na nota real), em vez de levantar
  `ValueError`. Isto é uma mudança no núcleo fiscal vendorizado, feita fora
  do padrão normal do kit ("não simplifique sem testar em produção
  restrita") porque a evidência que a motiva é de fora do próprio sistema —
  por isso ela é tratada como **não verificada** até a primeira emissão real
  em homologação confirmar que a SEFIN Nacional aceita a mesma coisa que a
  prefeitura de Belém aceitou. Nenhuma emissão em `producao` acontece antes
  dessa confirmação.
- **Payload real do webhook Stone**: o exemplo público do evento
  `charge.paid` (API Connect) traz `order.id`, `amount`, `customer.id`,
  `customer.name`, mas não confirma CPF/CNPJ do cliente nem o mecanismo de
  autenticação da chamada (assinatura/segredo do webhook). Isso só é validado
  com conta de parceiro ativa. O adaptador será ajustado quando o payload real
  estiver disponível.
- **Rota/identificação de empresa no webhook**: com múltiplas empresas
  futuras, cada uma precisa de uma forma de a Stone identificar para qual
  empresa o evento pertence (endpoint por empresa, token, ou campo no
  payload). Definido quando o payload real for conhecido.

## Testes

- `nfse-nacional-kit/exemplos/00_teste_local.py` continua sendo o teste de
  fumaça do núcleo fiscal (sem rede, sem certificado) — não muda.
- Teste do ajuste em `dps.py`: `build_dps_xml` sem `toma_cpf_cnpj` produz um
  XML válido sem o bloco `toma`, e com `toma_cpf_cnpj` continua produzindo o
  bloco como antes — cobre os dois caminhos do `if`.
- Testes do adaptador: payload Stone (exemplo documentado) → `DpsData`
  corretamente montada.
- Testes de idempotência do recebedor de webhook (mesmo `stone_charge_id`
  duas vezes não duplica emissão nem consome dois números).
- Testes do formulário de emissão manual: validação de CPF/CNPJ e valor antes
  de reservar número; resultado grava `origem=manual` e segue o mesmo caminho
  do worker que a emissão automática.
- Emissão real em `homologacao` (produção restrita) antes de qualquer nota em
  `producao` — não pulável, é a única forma de pegar divergência de validador
  (`CLAUDE.md` do kit).

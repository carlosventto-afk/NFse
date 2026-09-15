# Emissão de NFS-e via API da Spedy como alternativa à emissão direta

Data: 2026-09-15

## Contexto

Hoje toda empresa emite NFS-e pelo caminho "direto": `nfse_core` monta o XML
da DPS, assina com o certificado A1 da própria empresa e envia pra SEFIN
Nacional ou pro endpoint próprio do município (caso de Belém/PA, ver
[[project_notafiscal_e0160_belem]]). Esse caminho exige manter, por conta
própria, o conhecimento de cada validador municipal divergente — a saga do
endpoint de Belém (E0039, 404, troca de host, E0160) é um exemplo do custo
disso.

A Spedy (`docs.spedy.com.br`) é uma API multi-tenant de emissão fiscal (NF-e/
NFC-e/NFS-e) que abstrai esse problema: você cadastra a empresa e sobe o
certificado A1 uma vez, e a partir daí ela cuida de montar/assinar/enviar a
nota pro validador certo de cada município, incluindo Belém — confirmado ao
vivo (`GET /v1/service-invoices/cities?code=1501402`, chave sandbox fornecida
pelo usuário) que Belém usa lá o provider `dsFv2`, o mesmo fornecedor (DSF) do
endpoint direto atual.

Avaliamos antes um concorrente (FazNota) e descartamos: o modelo dela exige
pré-cadastro de "cliente" e "produto" no painel dela antes de emitir, quebrando
a transparência de só trocar de provedor. A Spedy aceita os dados do tomador e
do serviço **inline** no próprio payload de emissão, sem esse pré-requisito.

## Objetivo

Cada empresa ganha um campo `provedor_emissao` (`direto` | `spedy`). Trocar
esse campo troca **todas** as operações fiscais daquela empresa (emissão,
cancelamento, consulta, download de PDF) entre o caminho direto atual e a
Spedy — sem mexer no restante do sistema (portal, importação CSV, webhook da
Stone continuam gerando linhas em `emissoes` do jeito que já geram hoje).

## Fora de escopo (por ora)

- Notificação por webhook da Spedy (`invoice.status_changed`). A resolução do
  resultado assíncrono é só por polling do worker, no mesmo padrão que
  `processar_uma_pendente`/`processar_um_cancelamento_pendente` já usam —
  webhook fica como evolução futura, sem mudar o modelo de dados.
- Emissão de NF-e/NFC-e pela Spedy (o app só emite NFS-e).
- Sincronização de clientes/produtos como recursos da Spedy (não é necessário
  — o payload de emissão leva os dados inline).
- Provisionamento automático "silencioso" dentro do worker. O provisionamento
  (criar empresa + subir certificado + configurar na Spedy) é sempre uma ação
  explícita, disparada ao editar a empresa.

## Pré-requisitos externos (bloqueantes parciais)

- Conta Spedy: o usuário já criou uma conta **sandbox** (Plano Desenvolvedor)
  e forneceu uma chave de API funcional, testada ao vivo nesta sessão. Não há
  conta de **produção** contratada ainda.
- No sandbox, a emissão de NFS-e é **simulada** — a Spedy responde como se
  fosse a prefeitura, sem validação fiscal real. Isso é suficiente para
  validar todo o encanamento (provisionamento, payload, transições de
  status), mas **não** confirma se um caso real como o E0160 de Belém seria
  aceito. Essa confirmação só é possível com conta de produção.
- A chave sandbox fornecida pelo usuário foi colada em texto na conversa —
  tratá-la como exposta; não deve ir para `.env.example` nem ser commitada, e
  vale regenerá-la no painel da Spedy antes de qualquer uso além desta
  implementação.

## Arquitetura

```
PUT /empresas/mim (provedor_emissao=spedy)
        |
        v
provisionar_empresa() -- chave MESTRE (por ambiente)
  1. POST /companies                    -> spedy_empresa_id
  2. POST /companies/{id}/certificates  -> usa a X-Api-Key da empresa
  3. PUT configurações (ambiente/série/numeração)
        |
        v
empresa.spedy_empresa_id / spedy_api_key_cifrada gravados (commit atômico:
falha em qualquer passo = nada é salvo, empresa continua em "direto")


                    [tabela emissoes, status=pendente]
                                |  worker consome (a cada 5s)
                                v
                    provedor_emissao da empresa?
                    /                           \
              "direto"                       "spedy"
                 |                               |
     (fluxo atual, inalterado)      monta payload inline (integrationId=
                 |                    str(emissao.id), dedup nativo da Spedy)
                 v                               |
      autorizada | rejeitada          POST /service-invoices
                                                  |
                                    2xx -> status=aguardando_confirmacao
                                    4xx -> rejeitada (mesma hora)
                                                  |
                                                  v
                          [emissoes, status=aguardando_confirmacao]
                                |  worker consome (nova função irmã)
                                v
                    GET /service-invoices/{spedy_nota_id}
                    ainda processando -> não faz nada, tenta de novo depois
                    authorized/rejected -> autorizada | rejeitada
```

Cancelamento e download de PDF seguem o mesmo branch por `provedor_emissao`,
descritos abaixo.

## Modelo de dados

**`Empresa`** (`app/models.py`) — campos novos:

- `provedor_emissao: ProvedorEmissao` (enum `direto` default | `spedy`).
- `spedy_empresa_id: str | None` — UUID devolvido por `POST /companies`.
- `spedy_api_key_cifrada: str | None` — X-Api-Key exclusiva da empresa,
  cifrada com o mesmo esquema Fernet de `certificado_senha_cifrada`
  (`app.crypto.cifrar`/`decifrar`).

**`Emissao`** — campos novos:

- Novo valor em `StatusEmissao`: `aguardando_confirmacao` (só usado pelo
  caminho Spedy; o caminho direto continua síncrono e nunca passa por esse
  status).
- `spedy_nota_id: str | None` — `id` devolvido por `POST /service-invoices`,
  usado para consultar o resultado.

**`Settings`** (`app/config.py`) — campos novos:

- `spedy_api_key_master_homologacao: str = ""`
- `spedy_api_key_master_producao: str = ""`

(a Spedy trata sandbox/homologação e produção como contas totalmente
separadas, cada uma com sua própria chave mestre — não dá para compartilhar).

Nenhuma coluna nova em `Cliente`.

## Componentes

**`app/adapters/spedy_client.py`** (novo módulo, papel equivalente ao
`nfse_core/client.py` do caminho direto, mas para o contrato JSON da Spedy —
sem montagem/assinatura de XML aqui, quem assina é a Spedy usando o
certificado já enviado):

- `SpedyError(RuntimeError)` — espelha `SefinError` (mensagem, status,
  corpo), pra tratamento uniforme no worker.
- `BASE_URLS = {"homologacao": "https://sandbox-api.spedy.com.br/v1", "producao": "https://api.spedy.com.br/v1"}`.
- `provisionar_empresa(empresa, pfx_base64, senha, settings) -> (spedy_empresa_id, spedy_api_key)`
  — os 3 passos do diagrama acima, usando a chave mestre do ambiente da
  empresa.
- `emitir_nfse(empresa, cliente, emissao, api_key) -> dict` — monta o payload
  (mapeamento descrito abaixo) e faz `POST /service-invoices`.
- `consultar_nfse(spedy_nota_id, api_key, ambiente) -> dict` — `GET /service-invoices/{id}`.
- `cancelar_nfse(spedy_nota_id, motivo, api_key, ambiente) -> dict`.
- `baixar_pdf(spedy_nota_id, api_key, ambiente) -> bytes`.

**Mapeamento de payload** (`Empresa`/`Cliente`/`Emissao` → corpo de
`POST /service-invoices`):

| Campo Spedy | Origem |
|---|---|
| `integrationId` | `str(emissao.id)` |
| `description` | `emissao.descricao` |
| `total.invoiceAmount` | `emissao.valor` |
| `effectiveDate` | `emissao.competencia` (ou `dh_emi_original` quando presente, mesma regra do caminho direto) |
| `receiver.federalTaxNumber` / `.name` / `.email` | `emissao.tomador_cpf_cnpj` / `.tomador_nome` / `.tomador_email` |
| `city.code` | `empresa.local_prestacao_ibge` ou `empresa.municipio_ibge` (mesma regra de fallback já usada em `montar_dps_data`) |
| `federalServiceCode` | `empresa.codigo_tributacao` |
| `cityServiceCode` | `empresa.codigo_tributacao_municipal` |
| `location` | `serviceProvisionMunicipality` quando `local_prestacao_ibge` difere de `municipio_ibge`, senão `companyMunicipality` |

`simplesNacionalAnnex`/`taxationType` exatos dependem de como `op_simp_nac`/
`regime_apuracao_sn` mapeiam pro vocabulário da Spedy — isso é confirmado na
implementação com uma emissão real de teste no sandbox (ver "Testes").

**Gatilho do provisionamento**: dentro de `PUT /empresas/mim`
([empresas.py:87](../../../app/routers/empresas.py#L87)), que ganha um campo
`provedor_emissao`. Quando o valor pedido for `spedy` e a empresa ainda não
tiver `spedy_empresa_id` — ou um certificado novo/ambiente novo tenha sido
enviado no mesmo request — o endpoint chama `provisionar_empresa` de forma
síncrona, **antes do commit**. Falha da Spedy = o request inteiro falha com o
erro dela, empresa permanece em `direto`, sem estado parcial salvo.

## Fluxo no worker

**Emissão** (`processar_uma_pendente`, [worker.py:40](../../../app/worker.py#L40)):
branch por `empresa.provedor_emissao` logo após carregar `empresa`. Caminho
`direto` inalterado. Caminho `spedy`:

1. Empresa sem `spedy_empresa_id`/`spedy_api_key_cifrada` → `_marcar_rejeitada`
   com código `SPEDY_NAO_PROVISIONADA` (erro isolado da linha, não derruba o
   worker).
2. Monta o payload, chama `emitir_nfse`.
3. Erro de validação síncrono (HTTP 4xx) → `rejeitada` na mesma hora.
4. Aceite (2xx) → grava `spedy_nota_id`, status vira `aguardando_confirmacao`.
   Não tenta interpretar o resultado final aqui, mesmo que a resposta já
   pareça terminal — isso fica todo na função de confirmação, evitando duas
   lógicas diferentes para a mesma interpretação.

Diferença importante do caminho direto: a Spedy dedupe por `integrationId`
(`str(emissao.id)`), então reenviar a mesma emissão depois de o worker cair no
meio não duplica nada — não precisa replicar a dança de `dps_id`/consulta
prévia que o caminho direto usa para o mesmo problema.

**Nova função `processar_uma_aguardando_confirmacao_spedy`** — irmã de
`processar_uma_pendente`/`processar_um_cancelamento_pendente` (mesmo
`SELECT ... FOR UPDATE SKIP LOCKED`), consulta `GET /service-invoices/{id}`
para linhas em `aguardando_confirmacao`:
- `authorized` → `autorizada` (chave/número/xml conforme a resposta real).
- `rejected`/`denied` → `rejeitada`, com `resposta_bruta` gravada (mesma
  prática já usada para diagnosticar o E0160 de Belém).
- qualquer outro status (ainda processando) → não faz nada e **retorna
  `False`** (não conta como trabalho feito), para o loop respeitar o
  intervalo normal de 5s em vez de martelar a Spedy sem pausa.

Adicionada como uma terceira checagem em `loop_worker`
([worker.py:263](../../../app/worker.py#L263)).

**Cancelamento** (`processar_um_cancelamento_pendente`): mesmo branch,
chamando `cancelar_nfse` com `spedy_nota_id`. Em aberto: não está confirmado
se o cancelamento na Spedy é síncrono ou também assíncrono (precisaria de um
estado extra "aguardando confirmação de cancelamento"). Resolvido na
implementação, testando ao vivo no sandbox.

**Download de PDF** (`app/routers/emissoes.py`, hoje chama
`SefinClient.fetch_danfse_pdf`): mesmo branch, chama `baixar_pdf` com
`spedy_nota_id`.

## Tratamento de erro

- Todo erro do worker no caminho Spedy segue a mesma regra já estabelecida no
  caminho direto: isolado por linha, nunca escapa de
  `processar_uma_pendente`/`processar_um_cancelamento_pendente`/
  `processar_uma_aguardando_confirmacao_spedy` e nunca derruba `loop_worker`
  — um problema de uma empresa (certificado, provisionamento) não pode parar
  a emissão das outras.
- Erro de transporte (timeout, DNS, resposta não-JSON) → `SpedyError` →
  `_marcar_rejeitada(..., "TRANSPORTE", ...)`.
- Empresa não provisionada / chave não decifra (`InvalidToken`, rotação de
  `FERNET_KEY`) → `_marcar_rejeitada(..., "SPEDY_NAO_PROVISIONADA", ...)`.
- Rejeição vinda da própria Spedy → `resposta_bruta` gravado (json bruto),
  igual ao caminho direto.

## Testes

- Suíte mockada (padrão de `tests/test_nfse_core_client_municipio.py`,
  capturando a chamada em vez de bater na rede): branch do worker por
  `provedor_emissao`, mapeamento de payload, interpretação de status
  (authorized/rejected/ainda processando), e os três casos de erro isolado
  acima.
- Teste do provisionamento: os 3 passos de `provisionar_empresa` acontecem na
  ordem certa e nenhum é salvo se um passo falhar no meio.
- Validação pontual ao vivo (uma vez, durante a implementação, com a chave
  sandbox já fornecida): emitir uma nota de teste real contra Belém para
  capturar o formato exato da resposta terminal (`authorized`) e confirmar se
  o cancelamento é síncrono ou assíncrono — os achados viram comentário no
  código (mesmo padrão de `nfse_core/client.py`), não teste automatizado
  permanente com a chave hardcoded.
- Nenhuma emissão real em produção Spedy antes de o usuário contratar e
  confirmar — o mesmo princípio já seguido para o caminho direto
  (homologação antes de produção).

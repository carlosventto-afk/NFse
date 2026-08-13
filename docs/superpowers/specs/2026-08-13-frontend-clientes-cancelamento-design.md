# Frontend, cadastro de clientes e cancelamento de nota

Data: 2026-08-13

## Contexto

O sistema, até aqui, é 100% backend (FastAPI) — todo fluxo (login, convite,
emissão, importação de CSV) é exercitado só via HTTP direto ou testes. O
subprojeto 1 (multiempresa e licenciamento) está pronto e em PR. Este
documento cobre o que havia sido decomposto como "subprojeto 2: tela de
cadastro de empresa", mas o escopo foi ampliado durante o brainstorm: o
usuário quer a introdução de uma camada de frontend completa, cobrindo não só
cadastro de empresa mas também clientes, importação de CSV e gestão de
emissões (incluindo cancelamento) — capacidades que dependiam de subprojetos
futuros (4: cancelamento) ou não existiam de forma alguma (cadastro de
clientes).

## Objetivo

Introduzir um frontend (React + Vite + TypeScript) cobrindo autenticação e
multiempresa, cadastro de empresa (substituindo o CLI), cadastro de clientes
(entidade nova), importação de CSV e gestão de emissões — incluindo
cancelamento de nota (endpoint novo, usando peças do `nfse_core` que já
existem mas nunca foram expostas via API) e download de XML/PDF.

## Fora de escopo (por ora)

- Substituição de nota (subprojeto 5 original — `nfse_core/evento.py` só
  implementa cancelamento puro).
- Múltiplos layouts de CSV além do da Stone (subprojeto 3 original).
- Emissão manual via formulário — confirmado que a emissão continua
  exclusivamente por importação de CSV.
- Suíte de testes automatizados para o frontend (Vitest/Testing Library) —
  validação nesta fase é manual, no navegador, seguindo a prática já usada
  neste projeto para UI.
- Reenvio automático de cancelamento com falha, ou qualquer painel de
  auditoria de eventos além do status da própria emissão.
- Edição de clientes já vinculados a uma emissão emitida (o vínculo é
  gravado no momento da emissão; alterar o cliente depois não re-emite nem
  atualiza a nota já autorizada).

## Telas

1. **Login** — e-mail/senha; se o usuário tem mais de uma empresa vinculada,
   mostra seletor de empresa antes de liberar o resto do sistema.
2. **Aceitar convite** — via link `/aceitar-convite?token=...`; pede senha
   só se o e-mail ainda não tem `Usuario`.
3. **Cadastro de empresa** — formulário com os mesmos campos de
   `scripts/criar_empresa.py` (CNPJ, IM, município, regime, código de
   tributação, descrição padrão, ambiente) + upload do `.pfx` e senha do
   certificado. Chama um endpoint novo que reaproveita `criar_empresa()` de
   `scripts/criar_empresa.py` (extraído para ser chamável tanto pelo CLI
   quanto pela API).
4. **Cadastro de clientes** — listar (com busca por nome/CPF-CNPJ e filtro
   ativo/inativo), criar, editar, inativar.
5. **Importar CSV** — upload → preview (mostra total de notas, valor,
   ignoradas) → confirmar. Reaproveita `/emissoes/csv/preview` e
   `/emissoes/csv/confirmar`, sem mudança de contrato.
6. **Emissões** — lista com filtro por status e período; ações por linha:
   baixar XML, baixar PDF, cancelar (só quando `status=autorizada`).

## Arquitetura do frontend

- **Stack:** React + Vite + TypeScript, em `frontend/` na raiz do repo.
  Roteamento com `react-router`. Sem framework de estado global — Context
  API para sessão (usuário, empresa ativa, lista de empresas) é suficiente
  dado o tamanho do app.
- **Client HTTP:** wrapper fino sobre `fetch` (`frontend/src/api/client.ts`)
  que injeta `Authorization: Bearer <token>` a partir do `localStorage`
  (`nfse.token`) e redireciona para `/login` em qualquer 401. Troca de
  empresa (`POST /auth/trocar-empresa`) atualiza o token salvo e o contexto,
  sem precisar de novo login.
- **Prefixo de API:** hoje os routers do FastAPI não têm prefixo comum
  (`/auth`, `/convites`, `/emissoes`, `/dashboard`,
  `/webhooks/stone/{empresa_id}`). Para servir a SPA e a API do mesmo
  domínio sem colisão de rotas (a SPA precisa de um catch-all em `/` para o
  client-side routing), todos os routers de API passam a ter prefixo
  `/api` (`/api/auth/login`, `/api/emissoes`, etc.) — **exceto**
  `/health`, mantido sem prefixo por convenção de infra (health checks de
  load balancer). Essa mudança toca todo router existente e,
  consequentemente, todo teste que hoje chama esses caminhos diretamente —
  é uma migração de rota ampla, tratada como sua própria tarefa na
  implementação (mesmo padrão do subprojeto 1, que teve uma tarefa dedicada
  só para consertar a suíte depois de uma mudança estrutural).
- **Build/deploy:** em dev, Vite roda em `5173` com proxy para `8000`. Em
  produção, `vite build` gera estático em `frontend/dist/`, servido pelo
  próprio FastAPI via `StaticFiles` montado em `/` (com fallback de
  `index.html` para rotas desconhecidas — necessário para o roteamento
  client-side funcionar em refresh de página), atrás de
  `nfse.gestaotecnologia.com`.

## Modelo de dados novo: `Cliente`

Tabela `clientes`, escopada por `empresa_id` (mesmo padrão de `Emissao`).

| Campo | Tipo | Obrigatório |
|---|---|---|
| `id` | UUID | sim |
| `empresa_id` | UUID (FK) | sim |
| `cpf_cnpj` | String(14) | não |
| `nome` | String(300) | sim |
| `email` | String(80) | não |
| `telefone` | String(20) | não |
| `inscricao_estadual` | String(20) | não |
| `inscricao_municipal` | String(20) | não |
| `logradouro` | String(200) | não |
| `numero` | String(20) | não |
| `complemento` | String(100) | não |
| `bairro` | String(100) | não |
| `municipio_ibge` | String(7) | não |
| `uf` | String(2) | não |
| `cep` | String(8) | não |
| `eh_padrao_csv` | bool, default `false` | sim |
| `ativo` | bool, default `true` | sim |
| `criado_em` / `atualizado_em` | timestamptz | sim |

`cpf_cnpj` é nullable — o CSV da Stone não traz identificação do cliente
(confirmado: o layout real, `CATEGORIA;DATA DA VENDA;STONE ID;QTD DE
PARCELAS;Nº DA PARCELA;VALOR BRUTO;ÚLTIMO STATUS`, não tem coluna de
CPF/CNPJ), então toda emissão importada precisa de um cliente sem
documento. Restrição única em `(empresa_id, cpf_cnpj)` **quando `cpf_cnpj`
não é nulo** (índice único parcial — mesmo padrão já usado em
`Emissao.stone_charge_id`). `eh_padrao_csv` marca o cliente-genérico
reutilizado pela importação (ver abaixo); único por empresa, garantido por
um segundo índice único parcial em `empresa_id WHERE eh_padrao_csv = true`.

`Emissao` ganha `cliente_id: uuid.UUID | None` (FK para `clientes`,
nullable). A confirmação da importação de CSV (`POST
/api/emissoes/csv/confirmar`) busca o `Cliente` com `eh_padrao_csv=true`
da empresa — criando um na primeira vez, com `nome="Cliente não
identificado (importação CSV)"` e todos os demais campos vazios — e grava
esse id em `cliente_id` de toda emissão criada na importação. Não existe
nesta fase nenhum fluxo que vincule um cliente **com dados reais** a uma
emissão específica (ver "Extensão do DPS Builder" abaixo sobre a
consequência disso).

Não há endpoint de exclusão — "inativar" é `ativo=false` via o mesmo
endpoint de atualização (`PUT /api/clientes/{id}`), preservando histórico
de emissões que já referenciam o cliente. O cliente-padrão do CSV nunca
aparece na tela de cadastro de clientes (a listagem filtra
`eh_padrao_csv=false` por padrão).

## Extensão do DPS Builder (`nfse_core/dps.py`)

`DpsData` ganha campos de endereço do tomador (`toma_end_logradouro`,
`toma_end_numero`, `toma_end_complemento`, `toma_end_bairro`,
`toma_end_municipio_ibge`, `toma_end_cep`), todos opcionais — mesmo padrão
dos campos de tomador já existentes (`toma_cpf_cnpj`, `toma_nome`,
`toma_email`), que também são opcionais e testados assim. `UF` não entra
aqui — o bloco nacional `<endNac>` identifica o município só pelo código
IBGE (`cMun`), que já embute a UF nos dois primeiros dígitos; o campo `uf`
do `Cliente` é só cadastral (exibição/filtro na tela), não é enviado à
SEFIN.
`build_dps_xml` monta um bloco `<end>` dentro de `<toma>` quando pelo menos
`toma_end_logradouro` e `toma_end_municipio_ibge` estiverem presentes —
espelhando a estrutura `<end>` já usada pelo padrão ABRASF/NFS-e Nacional
para endereço de tomador. Isso é testado diretamente em `nfse_core`
(função pura, sem dependência de banco/HTTP), do mesmo jeito que o resto
do módulo — **não depende de nenhum caller em `app/`** para ser válido.

**Escopo explicitamente cortado nesta fase:** nada em `app/` (nem
`app/worker.py`, nem `app/adapters/dps_builder.py`) lê `Cliente` para
popular esses campos. Como a única forma de `Emissao.cliente_id` ser
preenchida hoje é o cliente-padrão do CSV (sempre com dados fiscais
vazios), não existe cenário real em que o worker precisaria montar esse
bloco — conectar `Cliente` ao worker fica para quando houver um fluxo real
de vincular um cliente **específico e com dados completos** a uma emissão.
`app/adapters/dps_builder.py` continua montando `DadosEmissao` só a partir
de `Emissao.tomador_cpf_cnpj/nome/email`, como hoje.

**Risco assumido (ver "Riscos" abaixo):** o kit vendorizado nunca
implementou o bloco `<end>` — não há precedente de código para copiar os
nomes exatos de tag/atributo, então a implementação segue o meu
entendimento do leiaute nacional e **precisa ser validada contra a
documentação oficial ou um envio de teste em homologação** antes de
qualquer emissão real vier a usá-la.

## Cancelamento de nota

Segue o mesmo padrão assíncrono já usado para emissão (`app/worker.py`):

1. `StatusEmissao` ganha dois valores novos: `cancelamento_pendente` e
   `erro_cancelamento`. `Emissao` ganha `motivo_cancelamento: str | None` e
   `cancelada_em: datetime | None`.
2. `POST /api/emissoes/{id}/cancelar` — exige `admin` da empresa
   (`exigir_admin_empresa`), corpo `{motivo: str, codigo_motivo: "1"|"2"|"9"}`
   (códigos do leiaute: 1=Erro na Emissão, 2=Serviço não Prestado,
   9=Outros). Só aceita emissões com `status=autorizada`. Grava
   `status=cancelamento_pendente` e os dados do motivo — não chama a SEFIN
   na própria requisição (mesma razão de sempre: chamada externa lenta não
   deve bloquear a resposta HTTP).
3. `app/worker.py` ganha `processar_um_cancelamento_pendente(session,
   settings)`, espelhando `processar_uma_pendente`: busca uma emissão
   `cancelamento_pendente`, monta `EventoCancelamentoData` (já existe em
   `nfse_core/evento.py`), assina (`sign_evento`, já existe), submete via
   `SefinClient.registrar_evento` (já existe), interpreta a resposta
   (`ler_resposta_evento`, já existe) e marca `cancelada` (com
   `cancelada_em`) ou `erro_cancelamento`. `loop_worker` passa a chamar as
   duas funções de processamento em sequência a cada iteração.
4. A tela de emissões só oferece "Cancelar" quando `status=autorizada`, e
   mostra o novo status (`cancelamento_pendente`/`erro_cancelamento`) como
   qualquer outro.

## Endpoints novos

- `POST /api/empresas` — cria empresa (reaproveita a função `criar_empresa`
  hoje em `scripts/criar_empresa.py`, extraída para um módulo importável
  por CLI e API; exige `admin_plataforma` **ou** ser o próprio titular
  criando dentro do seu limite de plano — mesma regra do CLI).
- `POST /api/clientes`, `GET /api/clientes`, `GET /api/clientes/{id}`,
  `PUT /api/clientes/{id}` — qualquer usuário com empresa ativa (não exige
  admin; cadastro de cliente é operacional). `GET /api/clientes` sempre
  exclui o cliente-padrão do CSV (`eh_padrao_csv=true`) da listagem.
- `POST /api/emissoes/{id}/cancelar` — exige admin da empresa.
- Todos os routers existentes passam a responder sob `/api/*` (ver
  "Arquitetura do frontend").

## Migração

Uma migração Alembic cobre: tabela `clientes` (com os dois índices únicos
parciais — `(empresa_id, cpf_cnpj) WHERE cpf_cnpj IS NOT NULL` e
`empresa_id WHERE eh_padrao_csv = true`), coluna `Emissao.cliente_id` (FK
nullable), colunas `Emissao.motivo_cancelamento`/`cancelada_em`, e os dois
valores novos de `StatusEmissao` (coluna `String`, sem `CHECK` constraint
de banco — o enum é só Python, mesma modelagem já usada para os valores
existentes).

## Riscos e decisões em aberto

- **Bloco `<end>` do tomador no DPS é uma extensão sem precedente no kit
  vendorizado** — como registrado acima, precisa de confirmação contra o
  schema oficial ou teste em homologação antes de produção. Fica também
  registrado no checklist de "antes da primeira nota real" do README.
- **Mudança de prefixo `/api` é uma migração de rota ampla** — toca todo
  router e toda suíte de teste existente (mesmo padrão de blast radius já
  visto no subprojeto 1), tratada como tarefa própria na implementação.
- **`POST /api/empresas` reaproveita `criar_empresa()`, mas quem pode
  chamá-lo pela API é mais permissivo que o CLI hoje** (que roda com acesso
  direto ao banco, sem contexto de usuário) — a regra "admin de plataforma
  ou o próprio titular dentro do limite do plano" é nova e precisa ficar
  clara nos testes.
- **Sem suíte automatizada de frontend nesta fase** — validação manual no
  navegador antes de reportar cada tela como pronta, como já é prática
  neste projeto para UI (danfe/PDF, por exemplo, sempre foi validado assim).

## Testes

- `Cliente`: CRUD completo, unicidade de `(empresa_id, cpf_cnpj)` quando
  não nulo, isolamento entre empresas (mesmo padrão de
  `test_tenant_isolation.py`).
- Importação de CSV: primeira confirmação cria o cliente-padrão
  (`eh_padrao_csv=true`) e vincula `cliente_id` em toda emissão criada;
  segunda confirmação (outra remessa) reutiliza o mesmo cliente-padrão em
  vez de criar um novo.
- `POST /api/emissoes/{id}/cancelar`: rejeita quando não `autorizada`,
  rejeita operador (só admin), grava motivo e muda status.
- `processar_um_cancelamento_pendente`: sucesso marca `cancelada` com
  `cancelada_em`; falha de transporte/certificado marca
  `erro_cancelamento` sem derrubar o worker (mesmo padrão de resiliência
  já testado para `processar_uma_pendente`).
- `nfse_core/dps.py` estendido: XML gerado inclui `<end>` quando os campos
  mínimos estão presentes, omite quando ausentes (não quebra o caso sem
  tomador) — testado direto contra `build_dps_xml`, sem depender de nada
  em `app/`.
- `POST /api/empresas`: titular dentro do limite cria; acima do limite
  recusa (mesmas regras já testadas em `test_criar_empresa.py`, agora via
  HTTP).
- Migração de prefixo `/api`: `test_main_rotas_registradas.py` atualizado
  para os caminhos novos.

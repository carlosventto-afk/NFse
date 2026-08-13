# Multiempresa e licenciamento

Data: 2026-08-12

## Contexto

O sistema, até aqui, assume que **1 usuário pertence a exatamente 1 empresa**
(`Usuario.empresa_id`, fixo desde o cadastro, embutido no token JWT). A visão
agora é transformar isso num produto multiempresa hospedado em
`nfse.gestaotecnologia.com`, onde:

- Um usuário pode estar vinculado a **várias empresas**, respeitando um
  limite definido por plano.
- Existe um nível de administração **acima** do que já existe hoje: um ADM
  da plataforma que cadastra usuários titulares e define o plano de cada um.
  O que já existe (`admin`/`operador` dentro de uma empresa) continua, mas
  agora é escopado por vínculo usuário↔empresa, não mais um atributo fixo
  do usuário.

Este é o primeiro de uma série de subprojetos identificados a partir de um
pedido maior (multiempresa, cadastro de empresa pela interface, múltiplos
layouts de importação, cancelamento e substituição de nota). Este documento
cobre **só o subprojeto 1**: o modelo de multiempresa e licenciamento em si
— a fundação da qual os demais dependem. Os outros ficam para specs
separadas, na ordem acordada: cadastro de empresa pela interface,
múltiplos layouts de CSV, cancelamento, substituição (essa última exige
estender o núcleo fiscal vendorizado, que hoje só implementa cancelamento
puro — ver `nfse_core/evento.py`).

## Objetivo

Permitir que um usuário esteja vinculado a múltiplas empresas (cada vínculo
com seu próprio papel), com um limite de empresas por plano, um ADM de
plataforma que cadastra usuários titulares, e ingresso de todo novo usuário
(titular ou operador) por convite via e-mail — nunca com senha definida por
quem convida.

## Fora de escopo (por ora)

- **Tela de cadastro de empresa pela interface** (dados fiscais completos +
  upload de certificado A1) — isso é o subprojeto 2. Aqui, criar uma
  empresa continua sendo feito por `scripts/criar_empresa.py` (CLI), que
  recebe um ajuste mínimo: passa a aceitar o e-mail do titular responsável
  e verificar o limite do plano dele antes de criar.
- Cancelamento e substituição de nota (subprojetos futuros).
- Múltiplos layouts de importação CSV (subprojeto futuro) — o layout Stone
  já existente não muda aqui.
- Cobrança/pagamento por plano — planos aqui só definem um limite numérico
  de empresas, sem nenhuma integração de pagamento.
- Reenvio automático de convite expirado, ou qualquer painel de gestão de
  convites pendentes além de criar e aceitar.
- Auditoria/histórico de quem teve acesso removido de uma empresa (remoção
  de vínculo em si também fica fora — só criação de vínculo via convite,
  por ora).

## Modelo de dados

- **`planos`**: `id`, `nome` (str), `limite_empresas` (int), `criado_em`.
- **`usuarios`**: perde `empresa_id` e `papel` (que eram fixos e globais).
  Ganha `eh_admin_plataforma: bool` (default `false`) e `plano_id`
  (nullable — só usuários titulares têm um plano; um operador convidado
  para uma empresa alheia não precisa de um).
- **`usuario_empresas`** (nova, tabela de associação): `usuario_id` (FK),
  `empresa_id` (FK), `papel` (`admin` | `operador`, o mesmo enum
  `PapelUsuario` que já existe hoje — só muda de lugar), `criado_em`.
  Restrição única em `(usuario_id, empresa_id)` — um usuário tem só um
  papel por empresa.
- **`empresas`**: ganha `titular_id` (FK para `usuarios`, not null) — o
  responsável pela licença dessa empresa. É essa coluna que conta contra
  `plano.limite_empresas` do titular (`SELECT count(*) FROM empresas WHERE
  titular_id = :usuario_id`).
- **`convites`** (nova): `id`, `email`, `empresa_id` (nullable — nulo
  quando é convite de titular feito pelo ADM da plataforma), `papel`
  (nullable, só quando `empresa_id` está presente), `plano_id` (nullable,
  só quando é convite de titular), `token` (string aleatória, única),
  `expira_em` (`criado_em` + 7 dias), `aceito_em` (nullable),
  `criado_por_usuario_id` (FK).

`PapelUsuario` (`admin`/`operador`) é reaproveitado como está, só muda de
coluna (`usuario_empresas.papel` em vez de `usuarios.papel`).
`eh_admin_plataforma` é um booleano à parte, não um terceiro valor desse
enum — um ADM de plataforma não tem vínculo em `usuario_empresas` (opera
fora do contexto de qualquer empresa específica).

## Fluxo de convite e aceite

1. Quem convida (ADM da plataforma → titular; admin de empresa → operador
   para a empresa ativa) cria um convite: `POST /convites`. O sistema
   valida quem pode convidar o quê:
   - `eh_admin_plataforma=true` → pode convidar um titular (`empresa_id`
     ausente, `plano_id` obrigatório).
   - papel `admin` na empresa ativa → pode convidar um operador para
     **essa** empresa (`empresa_id` = empresa ativa, `papel` obrigatório).
   Qualquer outra combinação é rejeitada (403).
2. Se já existe um convite pendente (não aceito, não expirado) para o
   mesmo `email` + `empresa_id` (ou `email` sozinho, no caso de convite de
   titular sem empresa), o novo convite invalida o anterior (marca o
   antigo como expirado imediatamente) em vez de deixar dois links válidos
   ao mesmo tempo para o mesmo destinatário.
3. Sistema grava o convite e envia e-mail (via `app/email.py`, SMTP da
   Hostinger) com o link
   `https://nfse.gestaotecnologia.com/aceitar-convite?token=...`.
4. Destinatário abre o link, `POST /convites/aceitar` com o `token`:
   - Se o e-mail do convite **não** corresponde a nenhum `Usuario`
     existente: o corpo da requisição também traz uma senha nova: cria o
     `Usuario` (com `plano_id`/`eh_admin_plataforma` se for convite de
     titular; sem, se for operador) e, se o convite tinha `empresa_id`,
     cria o vínculo em `usuario_empresas`.
   - Se o e-mail **já** corresponde a um `Usuario` existente: não pede
     senha — só cria o vínculo novo em `usuario_empresas` (a pessoa já
     consegue logar com a senha que já tem).
   - Convite com `token` inválido, já aceito, ou `expira_em` no passado →
     400, com uma mensagem que diferencia "expirado" de "inválido"
     (usuário reenvia pedido de convite se expirou; investiga se acha que
     é golpe, se inválido).
5. Convite consumido (`aceito_em` preenchido) não pode ser reaceito.

## Login, empresa ativa e troca

- `POST /auth/login` continua e-mail+senha. Se o usuário tem vínculo com
  exatamente uma empresa, o token já sai com ela como ativa
  (`empresa_id`/`papel` no payload). Se tem zero ou mais de uma, esses
  campos saem nulos no token.
- **`GET /auth/empresas`** (nova): lista as empresas do usuário logado
  (id, nome, papel) — alimenta a tela de seleção quando há mais de uma, ou
  confirma que não há nenhuma ainda.
- **`POST /auth/trocar-empresa`** (nova): recebe `empresa_id`, valida que
  existe vínculo do usuário logado com essa empresa em `usuario_empresas`,
  devolve um token novo com essa empresa como ativa. Não exige senha de
  novo — é uma troca de contexto, não um novo login.
- Todo endpoint que hoje lê `usuario.empresa_id`/`usuario.papel`
  diretamente (todos os routers de `emissoes`, `dashboard`, o antigo
  `usuarios.py`, o webhook) passa a exigir uma empresa ativa no token —
  uma nova dependency (`get_empresa_ativa`, substituindo o uso direto de
  `usuario.empresa_id`) resolve isso e devolve 409 com uma mensagem clara
  ("selecione uma empresa primeiro") quando o token não tem nenhuma. Um
  ADM de plataforma nunca tem empresa ativa — os endpoints de negócio
  (emissão, dashboard) não fazem sentido pra esse papel de qualquer forma.
- **`POST /usuarios`** (o endpoint atual, que cria operador com e-mail e
  senha definidos na hora pelo admin) é **removido** — substituído por
  `POST /convites` do tipo operador. Ninguém além do próprio usuário
  define sua senha, em nenhum nível da hierarquia.

## E-mail transacional

Módulo novo `app/email.py`: uma função `enviar_convite(destinatario: str,
link: str) -> None`, usando SMTP (Hostinger — `smtp.hostinger.com:465`,
TLS) via `aiosmtplib` (nova dependência). Credenciais
(`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`) só em `.env`,
nunca commitadas — mesmo padrão já usado para `FERNET_KEY`/`JWT_SECRET`.
Falha de envio (SMTP fora do ar) não deve derrubar a criação do convite:
o convite já foi gravado no banco antes do envio; se o e-mail falhar, o
convite continua existindo e pode ser consultado/reenviado depois — mas
reenvio automático fica fora de escopo nesta fase (ver "Fora de escopo").

## Migração dos dados existentes

A migração Alembic desta mudança:

1. Cria `planos`, `usuario_empresas`, `convites`.
2. Adiciona `usuarios.eh_admin_plataforma` (default `false`) e
   `usuarios.plano_id` (nullable).
3. Adiciona `empresas.titular_id` (nullable a princípio).
4. Para cada `Usuario` existente com `empresa_id`/`papel` preenchidos:
   cria a linha correspondente em `usuario_empresas`, e se `papel=admin`,
   preenche `empresas.titular_id` com esse usuário (se a empresa ainda não
   tiver titular). Não há dados reais em produção ainda — esse passo é
   para não quebrar o ambiente de desenvolvimento/testes existente, não
   uma migração de dados de clientes reais.
5. Torna `empresas.titular_id` `NOT NULL` depois do backfill, remove
   `usuarios.empresa_id` e `usuarios.papel`.

## Riscos e decisões em aberto

- **Token de convite em texto puro no link do e-mail**: é o padrão comum
  (mesmo modelo de "esqueci minha senha" da maioria dos sistemas), mas
  depende do link não vazar (por isso a validade de 7 dias e o consumo em
  um único uso). Nenhuma proteção adicional (ex: exigir confirmação por
  outro canal) está prevista nesta fase.
- **TTL do token JWT com empresa ativa**: se um admin de empresa remove o
  vínculo de um operador (ação fora de escopo nesta fase, mas que existirá
  no futuro), o token desse operador continua válido até expirar
  naturalmente (`JWT_TTL_HORAS`, hoje 8h) — não há revogação ativa de
  token. Aceitável por ora, mas registrado como limitação conhecida.
- **`scripts/criar_empresa.py`** precisa do ajuste mínimo (aceitar
  titular + checar limite de plano) descrito em "Fora de escopo" — incluído
  no plano de implementação deste subprojeto, já que sem isso não dá pra
  testar o modelo de licenciamento de ponta a ponta.

## Testes

- Convite de titular pelo ADM da plataforma → aceite cria `Usuario` com
  `plano_id` correto, sem vínculo em `usuario_empresas` (titular ainda não
  tem empresa até cadastrar uma via CLI).
- Convite de operador por admin de empresa → aceite cria vínculo em
  `usuario_empresas` com o papel certo, escopado à empresa correta.
- Convite aceito por e-mail que já é usuário existente → não pede senha,
  só cria o vínculo novo; usuário não ganha um segundo registro.
- Convite expirado ou já aceito → rejeitado, mensagens diferentes para
  cada caso.
- Usuário sem `eh_admin_plataforma` tentando `POST /convites` de titular →
  403. Usuário com papel `operador` tentando convidar alguém pra sua
  empresa → 403 (só `admin` da empresa pode).
- Login com usuário de uma empresa só → token já sai com empresa ativa.
  Login com usuário de várias → token sai sem empresa ativa.
- `POST /auth/trocar-empresa` para uma empresa sem vínculo → 403/404 (não
  revela se a empresa existe, mesmo padrão de segurança já usado no
  webhook da Stone).
- Endpoint de negócio (ex: `GET /emissoes`) chamado com token sem empresa
  ativa → 409 com mensagem clara.
- `scripts/criar_empresa.py` recusa criar empresa além do limite do plano
  do titular indicado.
- Isolamento: titular com duas empresas não vê dados de uma na empresa
  ativa da outra (mesmo padrão de `tests/test_tenant_isolation.py`, agora
  validado também através da troca de empresa ativa, não só de tokens de
  usuários diferentes).

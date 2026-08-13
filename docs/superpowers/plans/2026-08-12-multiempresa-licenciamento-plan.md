# Multiempresa e licenciamento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar o modelo de "1 usuário = 1 empresa fixa" por multiempresa (usuário vinculado a N empresas, papel por vínculo), com um ADM de plataforma que convida usuários titulares (com limite de empresas por plano), e todo ingresso de usuário — titular ou operador — por convite via e-mail.

**Architecture:** O JWT passa a carregar uma "empresa ativa" opcional (em vez de uma fixa). Uma dependency única (`get_contexto_autenticado`) decodifica o token uma vez e devolve usuário + empresa ativa + papel + flag de admin de plataforma; dependencies mais específicas (`get_empresa_ativa`, `exigir_admin_empresa`, `exigir_admin_plataforma`) compõem em cima dela. O vínculo usuário↔empresa vira uma tabela de associação (`usuario_empresas`); toda criação de acesso passa por um fluxo de convite com token de uso único, e-mail enviado via SMTP.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, `python-jose` (JWT), `aiosmtplib` (novo — envio de e-mail assíncrono), PostgreSQL, pytest + pytest-asyncio.

## Global Constraints

- Ver spec completa em `docs/superpowers/specs/2026-08-12-multiempresa-licenciamento-design.md`.
- Todo endpoint de negócio escopa por `empresa_id` da empresa ativa do token — nunca por um valor vindo do cliente.
- Ninguém além do próprio usuário define sua senha — toda criação de acesso (titular ou operador) é por convite aceito pelo próprio destinatário.
- Credenciais de SMTP só em `.env`, nunca commitadas — mesmo padrão já usado para `FERNET_KEY`/`JWT_SECRET`.
- **Decisão de implementação, documentada aqui por divergir da spec:** a spec descreve `empresas.titular_id` como `NOT NULL` após backfill. Este plano mantém a coluna **nullable** no banco — a obrigatoriedade continua real (a única forma de criar uma empresa de verdade, `scripts/criar_empresa.py`, sempre exige um titular, ver Task 6), só não é reforçada por uma constraint de banco. Isso evita adicionar um titular fictício em cada um dos ~5 arquivos de teste que criam uma `Empresa` sem nenhum contexto de usuário (ex: `tests/test_danfe.py`, que nem toca o banco). Se isso for inaceitável, é uma migração pequena e isolada depois — sinalizar antes de seguir se preferir a constraint no banco desde já.
- Nenhuma nota fiscal real depende deste subprojeto — ele é só o modelo de acesso. O núcleo fiscal (`nfse_core/`) não é tocado em nenhuma task aqui.
- `PapelUsuario` (`admin`/`operador`) é reaproveitado como já existe, só muda de coluna (`usuario_empresas.papel`, não mais `usuarios.papel`) — mesma cautela de sempre com colunas enum mapeadas como `String` puro: nunca `.value` num valor recém-carregado do banco sem normalizar via `PapelUsuario(valor)` primeiro.

---

## Estrutura de arquivos

```
app/
  models.py               # MODIFICADO — Plano, UsuarioEmpresa, Convite novos;
                           # Usuario perde empresa_id/papel, ganha
                           # eh_admin_plataforma/plano_id; Empresa ganha titular_id
  security.py              # MODIFICADO — ContextoAutenticado, get_contexto_autenticado,
                            # get_current_user, get_empresa_ativa, exigir_admin_empresa,
                            # exigir_admin_plataforma
  config.py                 # MODIFICADO — smtp_host/port/user/password, app_base_url
  email.py                   # NOVO — enviar_convite()
  schemas.py                  # MODIFICADO — remove UsuarioCriarIn/UsuarioOut, adiciona
                               # EmpresaVinculadaOut, TrocarEmpresaIn, ConviteCriarIn,
                               # ConviteOut, ConviteAceitarIn
  routers/
    auth.py                    # MODIFICADO — login com empresa ativa automatica,
                                # GET /auth/empresas, POST /auth/trocar-empresa
    usuarios.py                 # REMOVIDO (POST /usuarios antigo -> convites)
    convites.py                  # NOVO — POST /convites, POST /convites/aceitar
    emissoes.py                   # MODIFICADO — usuario.empresa_id -> contexto.empresa_id
    dashboard.py                   # MODIFICADO — idem
  main.py                          # MODIFICADO — remove usuarios.router, adiciona convites.router
scripts/
  criar_empresa.py                  # MODIFICADO — aceita titular + checa limite do plano
alembic/versions/
  <nova>_multiempresa_licenciamento.py   # NOVO
tests/
  apoio.py                           # NOVO — helpers compartilhados (criar_empresa_titular,
                                      # criar_empresa_e_token)
  test_security.py                    # NOVO
  test_auth.py                         # MODIFICADO (reescrito)
  test_convites.py                      # NOVO
  test_email.py                          # NOVO
  test_emissoes_manual.py                 # MODIFICADO (helper trocado)
  test_emissoes_download.py                # MODIFICADO (helper + tokens)
  test_emissoes_csv.py                      # MODIFICADO (helper trocado, 2 lugares)
  test_dashboard.py                          # MODIFICADO (reescrito, mais compacto)
  test_tenant_isolation.py                    # MODIFICADO (helper trocado)
  test_worker.py                               # MODIFICADO (titular na fixture)
  test_webhook_stone.py                         # MODIFICADO (titular na fixture)
  test_numeracao.py                              # MODIFICADO (titular na fixture)
  test_criar_empresa.py                           # MODIFICADO (novos parametros)
  test_main_rotas_registradas.py                   # MODIFICADO (rotas novas/removidas)
```

`tests/test_danfe.py` e `tests/test_adapters_dps_builder.py` **não mudam** — constroem `Empresa` só como objeto Python em memória, nunca persistido, então não são afetados por `titular_id` nem pelo modelo de `Usuario`.

---

### Task 1: Modelo de dados (Plano, UsuarioEmpresa, Convite) + migração

**Files:**
- Modify: `app/models.py`
- Create: `alembic/versions/<revisao>_multiempresa_licenciamento.py` (nome exato gerado pelo `alembic revision`)
- Test: `tests/test_models_multiempresa.py`

**Interfaces:**
- Produces: `app.models.Plano` (`id`, `nome: str`, `limite_empresas: int`, `criado_em`), `app.models.UsuarioEmpresa` (`id`, `usuario_id`, `empresa_id`, `papel: PapelUsuario`, `criado_em`; único em `(usuario_id, empresa_id)`), `app.models.Convite` (`id`, `email: str`, `empresa_id: uuid.UUID | None`, `papel: PapelUsuario | None`, `plano_id: uuid.UUID | None`, `token: str` único, `expira_em`, `aceito_em: datetime | None`, `criado_por_usuario_id`, `criado_em`). `Usuario` perde `empresa_id`/`papel`, ganha `eh_admin_plataforma: bool` (default `False`) e `plano_id: uuid.UUID | None`. `Empresa` ganha `titular_id: uuid.UUID | None` (FK `usuarios.id`, nullable — ver Global Constraints).

- [ ] **Step 1: Escrever `tests/test_models_multiempresa.py`**

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.crypto import hash_senha
from app.models import AmbienteEnum, Empresa, PapelUsuario, Plano, Usuario, UsuarioEmpresa


async def _empresa_minima(db_session, titular_id=None) -> Empresa:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular_id,
    )
    db_session.add(empresa)
    await db_session.flush()
    return empresa


@pytest.mark.asyncio
async def test_usuario_nao_tem_mais_empresa_id_nem_papel_fixos(db_session):
    usuario = Usuario(email="titular@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)

    assert not hasattr(usuario, "empresa_id")
    assert not hasattr(usuario, "papel")
    assert usuario.eh_admin_plataforma is False
    assert usuario.plano_id is None


@pytest.mark.asyncio
async def test_plano_limita_empresas_e_e_reaproveitavel(db_session):
    plano = Plano(nome="Basico", limite_empresas=2)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(
        email="titular2@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id,
    )
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)

    assert titular.plano_id == plano.id


@pytest.mark.asyncio
async def test_usuario_empresa_vincula_usuario_a_varias_empresas_com_papel_por_vinculo(db_session):
    titular = Usuario(email="dono@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa_a = await _empresa_minima(db_session, titular_id=titular.id)
    empresa_b = Empresa(
        cnpj="98765432000199", inscricao_municipal="2", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem B",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    db_session.add(empresa_b)
    await db_session.flush()

    db_session.add_all([
        UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_a.id, papel=PapelUsuario.admin),
        UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_b.id, papel=PapelUsuario.operador),
    ])
    await db_session.commit()

    from sqlalchemy import select
    vinculos = (
        await db_session.execute(
            select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == titular.id)
        )
    ).scalars().all()
    assert len(vinculos) == 2
    papeis = {v.empresa_id: v.papel for v in vinculos}
    assert papeis[empresa_a.id] == PapelUsuario.admin
    assert papeis[empresa_b.id] == PapelUsuario.operador


@pytest.mark.asyncio
async def test_usuario_empresa_rejeita_vinculo_duplicado(db_session):
    titular = Usuario(email="dup@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = await _empresa_minima(db_session, titular_id=titular.id)
    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=PapelUsuario.admin))
    await db_session.commit()

    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=PapelUsuario.operador))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_convite_grava_email_papel_plano_e_token(db_session):
    from app.models import Convite

    titular = Usuario(email="quemconvida@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()

    convite = Convite(
        email="novo@teste.com", plano_id=plano.id, token="token-unico-123",
        expira_em=datetime.now(timezone.utc), criado_por_usuario_id=titular.id,
    )
    db_session.add(convite)
    await db_session.commit()
    await db_session.refresh(convite)

    assert convite.aceito_em is None
    assert convite.empresa_id is None
    assert convite.plano_id == plano.id
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_models_multiempresa.py -v`
Expected: FAIL — `Plano`, `UsuarioEmpresa`, `Convite` ainda não existem; `Usuario` ainda tem `empresa_id`/`papel` obrigatórios (o teste que espera a ausência desses atributos falha porque eles ainda existem).

- [ ] **Step 3: Editar `app/models.py`**

Localizar o bloco de enums e acrescentar, logo após `PapelUsuario`:

```python
class Plano(Base):
    __tablename__ = "planos"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    limite_empresas: Mapped[int] = mapped_column(nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)
```

Trocar a classe `Empresa` inteira por (ganha `titular_id`, ganha relationship `usuario_empresas`, perde a relationship antiga `usuarios`):

```python
class Empresa(Base):
    __tablename__ = "empresas"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    inscricao_municipal: Mapped[str] = mapped_column(String(20), nullable=False)
    municipio_ibge: Mapped[str] = mapped_column(String(7), nullable=False)
    op_simp_nac: Mapped[int] = mapped_column(nullable=False)
    codigo_tributacao: Mapped[str] = mapped_column(String(6), nullable=False)
    descricao_servico_padrao: Mapped[str] = mapped_column(String(2000), nullable=False)
    ambiente: Mapped[AmbienteEnum] = mapped_column(
        String(20), default=AmbienteEnum.homologacao, nullable=False
    )
    serie: Mapped[str] = mapped_column(String(5), default="1", nullable=False)
    proximo_numero: Mapped[int] = mapped_column(default=1, nullable=False)
    certificado_pfx_cifrado: Mapped[str] = mapped_column(Text, nullable=False)
    certificado_senha_cifrada: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificado_valido_ate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    webhook_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Responsavel pela licenca desta empresa — conta contra plano.limite_empresas
    # do titular. Nullable no banco por decisao deste plano (ver Global
    # Constraints) — a obrigatoriedade real vem de scripts/criar_empresa.py.
    titular_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    emissoes: Mapped[list["Emissao"]] = relationship(back_populates="empresa")
    usuario_empresas: Mapped[list["UsuarioEmpresa"]] = relationship(back_populates="empresa")
```

Trocar a classe `Usuario` inteira por (perde `empresa_id`/`papel`/relationship `empresa`, ganha `eh_admin_plataforma`/`plano_id`):

```python
class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    eh_admin_plataforma: Mapped[bool] = mapped_column(default=False, nullable=False)
    plano_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("planos.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    usuario_empresas: Mapped[list["UsuarioEmpresa"]] = relationship(back_populates="usuario")
```

Acrescentar, depois da classe `Usuario` (antes de `Emissao`):

```python
class UsuarioEmpresa(Base):
    __tablename__ = "usuario_empresas"
    __table_args__ = (
        UniqueConstraint("usuario_id", "empresa_id", name="uq_usuario_empresa"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    papel: Mapped[PapelUsuario] = mapped_column(String(20), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    usuario: Mapped["Usuario"] = relationship(back_populates="usuario_empresas")
    empresa: Mapped["Empresa"] = relationship(back_populates="usuario_empresas")


class Convite(Base):
    __tablename__ = "convites"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    empresa_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("empresas.id"), nullable=True)
    papel: Mapped[PapelUsuario | None] = mapped_column(String(20), nullable=True)
    plano_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("planos.id"), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    aceito_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_por_usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)
```

Acrescentar `UniqueConstraint` ao import do topo do arquivo:

```python
from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, UniqueConstraint, text,
)
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_models_multiempresa.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Gerar e revisar a migração**

```bash
alembic revision --autogenerate -m "multiempresa e licenciamento"
```

Abra o arquivo gerado em `alembic/versions/`. O autogenerate captura o schema (tabelas/colunas novas, drop de `usuarios.empresa_id`/`papel`) mas **não** o backfill de dados — edite a função `upgrade()` para incluir os passos de backfill, na ordem abaixo (o `downgrade()` gerado automaticamente pode ficar como está, não precisa de backfill reverso nesta fase):

```python
def upgrade() -> None:
    # ... (o autogenerate ja deve ter criado 'planos', 'usuario_empresas',
    # 'convites', e adicionado 'eh_admin_plataforma'/'plano_id' em 'usuarios'
    # e 'titular_id' em 'empresas' — confira que essas operacoes vieram antes
    # deste ponto; se a ordem gerada for diferente, mova o backfill abaixo
    # para depois de 'usuario_empresas' existir e antes de dropar as colunas
    # antigas de 'usuarios')

    import uuid
    from datetime import datetime, timezone

    conexao = op.get_bind()
    linhas = conexao.execute(
        sa.text("SELECT id, empresa_id, papel FROM usuarios WHERE empresa_id IS NOT NULL")
    ).fetchall()
    agora = datetime.now(timezone.utc)
    titulares_definidos: set = set()
    for usuario_id, empresa_id, papel in linhas:
        conexao.execute(
            sa.text(
                "INSERT INTO usuario_empresas (id, usuario_id, empresa_id, papel, criado_em) "
                "VALUES (:id, :usuario_id, :empresa_id, :papel, :criado_em)"
            ),
            {
                "id": uuid.uuid4(), "usuario_id": usuario_id, "empresa_id": empresa_id,
                "papel": papel, "criado_em": agora,
            },
        )
        if papel == "admin" and empresa_id not in titulares_definidos:
            conexao.execute(
                sa.text(
                    "UPDATE empresas SET titular_id = :usuario_id "
                    "WHERE id = :empresa_id AND titular_id IS NULL"
                ),
                {"usuario_id": usuario_id, "empresa_id": empresa_id},
            )
            titulares_definidos.add(empresa_id)

    # so entao remove as colunas antigas de usuarios (confira que o
    # autogenerate colocou op.drop_column("usuarios", "empresa_id") e
    # op.drop_column("usuarios", "papel") DEPOIS do backfill acima — se
    # vieram antes, mova-as para o final da funcao)
```

Se o seu banco de desenvolvimento local já tem alguma `Empresa` sem nenhum `Usuario` com `papel=admin` vinculado, essa empresa fica com `titular_id` nulo depois da migração — aceitável dado que a coluna é nullable (ver Global Constraints); não é um erro de migração.

- [ ] **Step 6: Aplicar a migração**

```bash
alembic upgrade head
```

- [ ] **Step 7: Confirmar que a suíte de migração ainda roda (mesmo que o resto da suíte esteja quebrado nesta altura — ver nota abaixo)**

Run: `pytest tests/test_models_migration.py tests/test_models_multiempresa.py -v`
Expected: PASS (esses dois arquivos, especificamente)

**Nota esperada nesta task:** a suíte completa (`pytest -v`) **não** fica verde ainda — todo arquivo de teste que cria um `Usuario` com `empresa_id=`/`papel=` (o padrão antigo) quebra, porque essas colunas não existem mais. Isso é esperado e corrigido nas Tasks 2-5. Não tente consertar os outros arquivos nesta task.

- [ ] **Step 8: Commit**

```bash
git add app/models.py alembic/versions tests/test_models_multiempresa.py
git commit -m "feat: modelo de dados de multiempresa e licenciamento (planos, usuario_empresas, convites)"
```

---

### Task 2: Contexto de autenticação (empresa ativa) + helper de teste compartilhado

**Files:**
- Modify: `app/security.py` (reescrita)
- Create: `tests/apoio.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: `app.models.Usuario`, `PapelUsuario`, Task 1's `Plano`/`UsuarioEmpresa`.
- Produces: `ContextoAutenticado` (dataclass: `usuario: Usuario`, `empresa_id: uuid.UUID | None`, `papel: PapelUsuario | None`, `eh_admin_plataforma: bool`). `criar_token(usuario: Usuario, *, empresa_id: uuid.UUID | None = None, papel: PapelUsuario | None = None, settings: Settings | None = None) -> str`. `get_contexto_autenticado(...) -> ContextoAutenticado` (dependency). `get_current_user(contexto: ContextoAutenticado = Depends(get_contexto_autenticado)) -> Usuario`. `get_empresa_ativa(contexto: ContextoAutenticado = Depends(get_contexto_autenticado)) -> ContextoAutenticado` (levanta 409 se `contexto.empresa_id is None`). `exigir_admin_empresa(contexto: ContextoAutenticado = Depends(get_empresa_ativa)) -> ContextoAutenticado` (403 se `contexto.papel != PapelUsuario.admin`). `exigir_admin_plataforma(contexto: ContextoAutenticado = Depends(get_contexto_autenticado)) -> ContextoAutenticado` (403 se não `eh_admin_plataforma`).
- `tests/apoio.py` produces: `async def criar_empresa_titular(db_session, *, cnpj="12345678000199", email_titular="titular@teste.com", papel_vinculo=PapelUsuario.admin, **overrides_empresa) -> tuple[Empresa, Usuario]` (cria um `Usuario` titular, uma `Empresa` com `titular_id` apontando pra ele, e um `UsuarioEmpresa` com o papel indicado — commita e dá refresh nos dois). `async def criar_empresa_e_token(db_session, *, papel=PapelUsuario.operador, email="op@teste.com", **overrides_empresa) -> tuple[Empresa, str]` (atalho: chama `criar_empresa_titular` e devolve `(empresa, token_ja_com_empresa_ativa)`).

- [ ] **Step 1: Escrever `tests/apoio.py`**

```python
"""Helpers compartilhados de fixture para os testes de multiempresa.

Centraliza a criacao de "empresa com um titular vinculado" — sem isto, o
mesmo bloco de ~15 linhas se repetiria em quase todo arquivo de teste que
precisa de uma empresa autenticavel.
"""
from datetime import datetime, timezone

from app.crypto import hash_senha
from app.models import AmbienteEnum, Empresa, PapelUsuario, Usuario, UsuarioEmpresa
from app.security import criar_token


async def criar_empresa_titular(
    db_session,
    *,
    cnpj: str = "12345678000199",
    email_titular: str = "titular@teste.com",
    papel_vinculo: PapelUsuario = PapelUsuario.admin,
    **overrides_empresa,
) -> tuple[Empresa, Usuario]:
    titular = Usuario(email=email_titular, senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()

    dados_empresa = dict(
        cnpj=cnpj, inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    dados_empresa.update(overrides_empresa)
    empresa = Empresa(**dados_empresa)
    db_session.add(empresa)
    await db_session.flush()

    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=papel_vinculo))
    await db_session.commit()
    await db_session.refresh(titular)
    await db_session.refresh(empresa)
    return empresa, titular


async def criar_empresa_e_token(
    db_session,
    *,
    papel: PapelUsuario = PapelUsuario.operador,
    email: str = "op@teste.com",
    **overrides_empresa,
) -> tuple[Empresa, str]:
    empresa, usuario = await criar_empresa_titular(
        db_session, email_titular=email, papel_vinculo=papel, **overrides_empresa
    )
    token = criar_token(usuario, empresa_id=empresa.id, papel=papel)
    return empresa, token
```

- [ ] **Step 2: Escrever `tests/test_security.py`**

```python
import uuid

import pytest
from fastapi import HTTPException
from jose import jwt

from app.config import get_settings
from app.crypto import hash_senha
from app.models import PapelUsuario, Usuario
from app.security import (
    criar_token,
    exigir_admin_empresa,
    exigir_admin_plataforma,
    get_contexto_autenticado,
    get_empresa_ativa,
)


async def _usuario(db_session, **overrides) -> Usuario:
    dados = dict(email="u@teste.com", senha_hash=hash_senha("senha-forte-123"))
    dados.update(overrides)
    usuario = Usuario(**dados)
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return usuario


def test_criar_token_sem_empresa_ativa_grava_campos_nulos():
    usuario = Usuario(
        id=uuid.uuid4(), email="x@x.com", senha_hash="hash", eh_admin_plataforma=False,
    )
    token = criar_token(usuario)
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["empresa_id"] is None
    assert payload["papel"] is None
    assert payload["eh_admin_plataforma"] is False


def test_criar_token_com_empresa_ativa_grava_empresa_id_e_papel():
    usuario = Usuario(
        id=uuid.uuid4(), email="x@x.com", senha_hash="hash", eh_admin_plataforma=False,
    )
    empresa_id = uuid.uuid4()
    token = criar_token(usuario, empresa_id=empresa_id, papel=PapelUsuario.admin)
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["empresa_id"] == str(empresa_id)
    assert payload["papel"] == "admin"


@pytest.mark.asyncio
async def test_get_contexto_autenticado_resolve_usuario_e_campos_do_token(db_session):
    usuario = await _usuario(db_session)
    empresa_id = uuid.uuid4()
    token = criar_token(usuario, empresa_id=empresa_id, papel=PapelUsuario.operador)

    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    assert contexto.usuario.id == usuario.id
    assert contexto.empresa_id == empresa_id
    assert contexto.papel == PapelUsuario.operador
    assert contexto.eh_admin_plataforma is False


@pytest.mark.asyncio
async def test_get_empresa_ativa_rejeita_contexto_sem_empresa(db_session):
    usuario = await _usuario(db_session, email="sem-empresa@teste.com")
    token = criar_token(usuario)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    with pytest.raises(HTTPException) as exc:
        await get_empresa_ativa(contexto=contexto)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_exigir_admin_empresa_rejeita_operador(db_session):
    usuario = await _usuario(db_session, email="operador@teste.com")
    empresa_id = uuid.uuid4()
    token = criar_token(usuario, empresa_id=empresa_id, papel=PapelUsuario.operador)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    with pytest.raises(HTTPException) as exc:
        await exigir_admin_empresa(contexto=contexto)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_exigir_admin_plataforma_rejeita_quem_nao_e(db_session):
    usuario = await _usuario(db_session, email="comum@teste.com")
    token = criar_token(usuario)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    with pytest.raises(HTTPException) as exc:
        await exigir_admin_plataforma(contexto=contexto)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_exigir_admin_plataforma_aceita_admin_de_plataforma(db_session):
    usuario = await _usuario(db_session, email="adm@teste.com", eh_admin_plataforma=True)
    token = criar_token(usuario)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    resultado = await exigir_admin_plataforma(contexto=contexto)
    assert resultado.eh_admin_plataforma is True
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `pytest tests/test_security.py -v`
Expected: FAIL — `ContextoAutenticado`, `get_empresa_ativa`, `exigir_admin_empresa`, `exigir_admin_plataforma` ainda não existem; `criar_token`/`get_contexto_autenticado` (que ainda se chama diferente) não aceitam os parâmetros novos.

- [ ] **Step 4: Reescrever `app/security.py`**

```python
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import PapelUsuario, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class ContextoAutenticado:
    usuario: Usuario
    empresa_id: uuid.UUID | None
    papel: PapelUsuario | None
    eh_admin_plataforma: bool


def criar_token(
    usuario: Usuario,
    *,
    empresa_id: uuid.UUID | None = None,
    papel: PapelUsuario | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": str(usuario.id),
        "eh_admin_plataforma": bool(usuario.eh_admin_plataforma),
        "empresa_id": str(empresa_id) if empresa_id else None,
        "papel": PapelUsuario(papel).value if papel else None,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_horas),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_contexto_autenticado(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContextoAutenticado:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        usuario_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token invalido ou expirado")
    usuario = await session.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario nao encontrado")

    empresa_id_str = payload.get("empresa_id")
    papel_str = payload.get("papel")
    return ContextoAutenticado(
        usuario=usuario,
        empresa_id=uuid.UUID(empresa_id_str) if empresa_id_str else None,
        papel=PapelUsuario(papel_str) if papel_str else None,
        eh_admin_plataforma=bool(payload.get("eh_admin_plataforma", False)),
    )


async def get_current_user(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
) -> Usuario:
    return contexto.usuario


async def get_empresa_ativa(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
) -> ContextoAutenticado:
    if contexto.empresa_id is None:
        raise HTTPException(status_code=409, detail="Selecione uma empresa antes de continuar")
    return contexto


async def exigir_admin_empresa(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
) -> ContextoAutenticado:
    if contexto.papel != PapelUsuario.admin:
        raise HTTPException(status_code=403, detail="Somente administradores da empresa")
    return contexto


async def exigir_admin_plataforma(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
) -> ContextoAutenticado:
    if not contexto.eh_admin_plataforma:
        raise HTTPException(status_code=403, detail="Somente administradores da plataforma")
    return contexto
```

- [ ] **Step 5: Rodar e confirmar sucesso**

Run: `pytest tests/test_security.py -v`
Expected: PASS (8 testes)

- [ ] **Step 6: Commit**

```bash
git add app/security.py tests/apoio.py tests/test_security.py
git commit -m "feat: contexto de autenticacao com empresa ativa opcional"
```

---

### Task 3: Login com empresa ativa automática, listar empresas, trocar empresa

**Files:**
- Modify: `app/routers/auth.py`
- Modify: `app/schemas.py` (acrescenta `EmpresaVinculadaOut`, `TrocarEmpresaIn`)
- Test: `tests/test_auth.py` (reescrita completa — ver Task 5 para a remoção dos testes do antigo `POST /usuarios`; aqui o arquivo já nasce sem eles)

**Interfaces:**
- Consumes: Task 2's `ContextoAutenticado`, `criar_token`, `get_contexto_autenticado`; Task 1's `UsuarioEmpresa`.
- Produces: `POST /auth/login` (comportamento novo: se o usuário tem vínculo com exatamente uma empresa, o token sai com ela ativa; senão, sai sem). `GET /auth/empresas` → `list[EmpresaVinculadaOut]` (`empresa_id`, `cnpj`, `papel`). `POST /auth/trocar-empresa` (`TrocarEmpresaIn`: `empresa_id`) → `TokenOut` com a empresa nova ativa, 403 se não há vínculo.

- [ ] **Step 1: Acrescentar a `app/schemas.py`**

```python
class EmpresaVinculadaOut(BaseModel):
    empresa_id: uuid.UUID
    cnpj: str
    papel: str


class TrocarEmpresaIn(BaseModel):
    empresa_id: uuid.UUID
```

- [ ] **Step 2: Escrever `tests/test_auth.py`**

```python
import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import PapelUsuario
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_login_com_uma_empresa_so_ja_sai_com_empresa_ativa(db_session):
    empresa, titular = await criar_empresa_titular(db_session, email_titular="unica@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login", data={"username": "unica@teste.com", "password": "senha-forte-123"}
            )
        assert resposta.status_code == 200
        empresas = await client.get(
            "/auth/empresas",
            headers={"Authorization": f"Bearer {resposta.json()['access_token']}"},
        )
    finally:
        app.dependency_overrides.clear()

    # o token ja sai com empresa ativa: qualquer endpoint de negocio ja funciona
    # sem precisar de POST /auth/trocar-empresa antes
    assert empresas.status_code == 200


@pytest.mark.asyncio
async def test_login_com_senha_errada_devolve_401(db_session):
    await criar_empresa_titular(db_session, email_titular="admin2@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login", data={"username": "admin2@teste.com", "password": "errada"}
            )
        assert resposta.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_senha_absurdamente_longa_devolve_401_e_nao_500(db_session):
    """bcrypt.checkpw levanta ValueError acima de 72 bytes: sem o guarda em
    `verificar_senha`, uma senha gigante no login virava 500."""
    await criar_empresa_titular(db_session, email_titular="admin5@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login", data={"username": "admin5@teste.com", "password": "x" * 500}
            )
        assert resposta.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_duas_empresas_nao_sai_com_empresa_ativa_ate_trocar(db_session):
    empresa_a, titular = await criar_empresa_titular(
        db_session, cnpj="11111111000111", email_titular="multi@teste.com",
    )
    from app.models import Empresa, UsuarioEmpresa

    empresa_b = Empresa(
        cnpj="22222222000122", inscricao_municipal="2", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem B",
        ambiente=empresa_a.ambiente, certificado_pfx_cifrado="x", certificado_senha_cifrada="x",
        certificado_valido_ate=empresa_a.certificado_valido_ate, webhook_token_hash="x",
        titular_id=titular.id,
    )
    db_session.add(empresa_b)
    await db_session.flush()
    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_b.id, papel=PapelUsuario.admin))
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/auth/login", data={"username": "multi@teste.com", "password": "senha-forte-123"}
            )
            token_sem_empresa = login.json()["access_token"]

            listagem = await client.get(
                "/auth/empresas", headers={"Authorization": f"Bearer {token_sem_empresa}"}
            )
            assert {item["empresa_id"] for item in listagem.json()} == {
                str(empresa_a.id), str(empresa_b.id),
            }

            troca = await client.post(
                "/auth/trocar-empresa",
                json={"empresa_id": str(empresa_b.id)},
                headers={"Authorization": f"Bearer {token_sem_empresa}"},
            )
        assert troca.status_code == 200
        token_com_empresa_b = troca.json()["access_token"]
        from jose import jwt

        from app.config import get_settings

        payload = jwt.decode(token_com_empresa_b, get_settings().jwt_secret, algorithms=["HS256"])
        assert payload["empresa_id"] == str(empresa_b.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trocar_empresa_sem_vinculo_devolve_403(db_session):
    _empresa_a, titular = await criar_empresa_titular(db_session, email_titular="isolado@teste.com")
    empresa_alheia, _outro_titular = await criar_empresa_titular(
        db_session, cnpj="33333333000133", email_titular="dono-de-outra@teste.com",
    )
    token = criar_token(titular)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/trocar-empresa",
                json={"empresa_id": str(empresa_alheia.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `GET /auth/empresas` e `POST /auth/trocar-empresa` ainda não existem (404); login ainda não seleciona empresa ativa automaticamente.

- [ ] **Step 4: Reescrever `app/routers/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import verificar_senha
from app.db import get_db
from app.models import Empresa, PapelUsuario, Usuario, UsuarioEmpresa
from app.schemas import EmpresaVinculadaOut, TokenOut, TrocarEmpresaIn
from app.security import ContextoAutenticado, criar_token, get_contexto_autenticado

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
) -> TokenOut:
    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == form.username))
    ).scalar_one_or_none()
    if usuario is None or not verificar_senha(form.password, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Credenciais invalidas")

    vinculos = (
        await session.execute(select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == usuario.id))
    ).scalars().all()

    empresa_id = None
    papel = None
    if len(vinculos) == 1:
        empresa_id = vinculos[0].empresa_id
        papel = PapelUsuario(vinculos[0].papel)

    return TokenOut(access_token=criar_token(usuario, empresa_id=empresa_id, papel=papel))


@router.get("/empresas", response_model=list[EmpresaVinculadaOut])
async def listar_minhas_empresas(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    linhas = (
        await session.execute(
            select(UsuarioEmpresa, Empresa)
            .join(Empresa, Empresa.id == UsuarioEmpresa.empresa_id)
            .where(UsuarioEmpresa.usuario_id == contexto.usuario.id)
        )
    ).all()
    return [
        {"empresa_id": vinculo.empresa_id, "cnpj": empresa.cnpj, "papel": vinculo.papel}
        for vinculo, empresa in linhas
    ]


@router.post("/trocar-empresa", response_model=TokenOut)
async def trocar_empresa(
    dados: TrocarEmpresaIn,
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> TokenOut:
    vinculo = (
        await session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == contexto.usuario.id,
                UsuarioEmpresa.empresa_id == dados.empresa_id,
            )
        )
    ).scalar_one_or_none()
    if vinculo is None:
        raise HTTPException(status_code=403, detail="Sem acesso a essa empresa")
    return TokenOut(
        access_token=criar_token(
            contexto.usuario, empresa_id=vinculo.empresa_id, papel=PapelUsuario(vinculo.papel)
        )
    )
```

- [ ] **Step 5: Rodar e confirmar sucesso**

Run: `pytest tests/test_auth.py tests/test_security.py -v`
Expected: PASS (5 + 8 testes)

- [ ] **Step 6: Commit**

```bash
git add app/routers/auth.py app/schemas.py tests/test_auth.py
git commit -m "feat: login com empresa ativa automatica, listar e trocar empresa"
```

---

### Task 4: Fluxo de convites (e-mail + aceite) e remoção do cadastro antigo

**Files:**
- Create: `app/email.py`, `app/routers/convites.py`
- Modify: `app/config.py` (SMTP + `app_base_url`), `app/schemas.py` (remove `UsuarioCriarIn`/`UsuarioOut`, acrescenta `ConviteCriarIn`/`ConviteOut`/`ConviteAceitarIn`), `app/main.py` (remove `usuarios.router`, adiciona `convites.router`), `requirements.txt` (`aiosmtplib`), `.env.example`
- Delete: `app/routers/usuarios.py`
- Test: `tests/test_email.py`, `tests/test_convites.py`

**Interfaces:**
- Consumes: Task 2's `ContextoAutenticado`/`get_contexto_autenticado`; Task 1's `Convite`/`UsuarioEmpresa`/`Plano`.
- Produces: `app.email.enviar_convite(destinatario: str, link: str) -> None` (assíncrona, via `aiosmtplib`). `POST /convites` (cria convite — titular se `contexto.eh_admin_plataforma`, operador se `contexto.papel == admin` na empresa ativa; 403 caso contrário). `POST /convites/aceitar` (aceita, cria `Usuario` se necessário, cria vínculo se `empresa_id` presente).

- [ ] **Step 1: Acrescentar SMTP a `app/config.py`**

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_test: str = ""
    fernet_key: str
    jwt_secret: str
    jwt_ttl_horas: int = 8
    smtp_host: str = "smtp.hostinger.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    app_base_url: str = "https://nfse.gestaotecnologia.com"
```

- [ ] **Step 2: Acrescentar ao `.env.example`**

```
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=
SMTP_PASSWORD=
APP_BASE_URL=https://nfse.gestaotecnologia.com
```

- [ ] **Step 3: Acrescentar `aiosmtplib` a `requirements.txt`**

```
aiosmtplib>=5.1.0
```

Rodar: `pip install -r requirements-dev.txt`

- [ ] **Step 4: Escrever `tests/test_email.py`**

```python
import pytest

from app import email as modulo_email


@pytest.mark.asyncio
async def test_enviar_convite_chama_aiosmtplib_com_destinatario_e_link(monkeypatch):
    chamadas = []

    async def _send_falso(mensagem, *, hostname, port, username, password, use_tls):
        chamadas.append(
            {
                "to": mensagem["To"], "from": mensagem["From"], "subject": mensagem["Subject"],
                "corpo": mensagem.get_content(), "hostname": hostname, "port": port,
            }
        )

    monkeypatch.setattr(modulo_email.aiosmtplib, "send", _send_falso)

    await modulo_email.enviar_convite("novo@teste.com", "https://nfse.gestaotecnologia.com/aceitar-convite?token=abc")

    assert len(chamadas) == 1
    assert chamadas[0]["to"] == "novo@teste.com"
    assert "https://nfse.gestaotecnologia.com/aceitar-convite?token=abc" in chamadas[0]["corpo"]
```

- [ ] **Step 5: Rodar e confirmar falha**

Run: `pytest tests/test_email.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.email'`

- [ ] **Step 6: Escrever `app/email.py`**

```python
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings


async def enviar_convite(destinatario: str, link: str) -> None:
    settings = get_settings()
    mensagem = EmailMessage()
    mensagem["From"] = settings.smtp_user
    mensagem["To"] = destinatario
    mensagem["Subject"] = "Convite - NFS-e Automatizada"
    mensagem.set_content(
        "Voce foi convidado a acessar o sistema de NFS-e.\n\n"
        f"Clique no link abaixo para aceitar o convite:\n{link}\n\n"
        "Este link expira em 7 dias."
    )
    await aiosmtplib.send(
        mensagem,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=True,
    )
```

- [ ] **Step 7: Rodar e confirmar sucesso**

Run: `pytest tests/test_email.py -v`
Expected: PASS

- [ ] **Step 8: Acrescentar a `app/schemas.py`**

Remover as classes `UsuarioCriarIn` e `UsuarioOut` inteiras (não são mais usadas — o cadastro de usuário agora é só por convite). Acrescentar no lugar:

```python
class ConviteCriarIn(BaseModel):
    email: EmailStr = Field(max_length=TAMANHO_EMAIL_USUARIO)
    papel: str | None = None
    plano_id: uuid.UUID | None = None

    @field_validator("papel")
    @classmethod
    def papel_valido(cls, v: str | None) -> str | None:
        if v is not None and v not in ("admin", "operador"):
            raise ValueError("papel deve ser admin ou operador")
        return v


class ConviteOut(BaseModel):
    id: uuid.UUID
    email: str
    empresa_id: uuid.UUID | None
    papel: str | None
    expira_em: datetime

    model_config = {"from_attributes": True}


class ConviteAceitarIn(BaseModel):
    token: str
    senha: str | None = Field(default=None, max_length=TAMANHO_SENHA_MAX)

    @field_validator("senha")
    @classmethod
    def senha_valida(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("senha precisa ter ao menos 8 caracteres")
        if len(v.encode()) > TAMANHO_SENHA_MAX:
            raise ValueError(f"senha nao pode passar de {TAMANHO_SENHA_MAX} bytes")
        return v
```

`datetime` precisa entrar no import do topo do arquivo: `from datetime import date, datetime`.

- [ ] **Step 9: Escrever `tests/test_convites.py`**

```python
import functools
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha, verificar_senha
from app.db import get_db
from app.main import app
from app.models import Convite, PapelUsuario, Plano, Usuario, UsuarioEmpresa
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_admin_plataforma_convida_titular_e_convite_e_criado(db_session, monkeypatch):
    import app.routers.convites as modulo

    enviados = []

    async def _enviar_falso(destinatario, link):
        enviados.append((destinatario, link))

    monkeypatch.setattr(modulo, "enviar_convite", _enviar_falso)

    adm = Usuario(email="adm@plataforma.com", senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    db_session.add(adm)
    await db_session.flush()
    plano = Plano(nome="Basico", limite_empresas=2)
    db_session.add(plano)
    await db_session.commit()
    await db_session.refresh(adm)
    token = criar_token(adm)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites",
                json={"email": "titular@teste.com", "plano_id": str(plano.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["empresa_id"] is None
    finally:
        app.dependency_overrides.clear()

    assert len(enviados) == 1
    assert enviados[0][0] == "titular@teste.com"


@pytest.mark.asyncio
async def test_aceitar_convite_de_titular_cria_usuario_com_plano_sem_vinculo_de_empresa(db_session, monkeypatch):
    adm = Usuario(email="adm2@plataforma.com", senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    db_session.add(adm)
    await db_session.flush()
    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.commit()
    convite = Convite(
        email="futuro-titular@teste.com", plano_id=plano.id,
        token="token-titular-123", expira_em=datetime.now(timezone.utc) + timedelta(days=7),
        criado_por_usuario_id=adm.id,
    )
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites/aceitar", json={"token": "token-titular-123", "senha": "senha-nova-123"}
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    novo_titular = (
        await db_session.execute(select(Usuario).where(Usuario.email == "futuro-titular@teste.com"))
    ).scalar_one()
    assert novo_titular.plano_id == plano.id
    vinculos = (
        await db_session.execute(select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == novo_titular.id))
    ).scalars().all()
    assert vinculos == []


@pytest.mark.asyncio
async def test_admin_de_empresa_convida_operador_para_a_empresa_ativa(db_session, monkeypatch):
    import app.routers.convites as modulo

    monkeypatch.setattr(modulo, "enviar_convite", lambda *a, **k: _coroutine_vazia())

    async def _coroutine_vazia():
        return None

    empresa, titular = await criar_empresa_titular(db_session, email_titular="dono@teste.com")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites",
                json={"email": "operador@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["empresa_id"] == str(empresa.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_operador_nao_pode_convidar(db_session):
    empresa, _titular = await criar_empresa_titular(
        db_session, email_titular="dono2@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    from tests.apoio import criar_empresa_e_token

    _empresa2, token = await criar_empresa_e_token(
        db_session, papel=PapelUsuario.operador, email="operador2@teste.com", cnpj="55555555000155",
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites",
                json={"email": "x@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_aceitar_convite_de_email_novo_cria_usuario_e_vinculo(db_session, monkeypatch):
    empresa, titular = await criar_empresa_titular(db_session, email_titular="convidante@teste.com")
    convite = Convite(
        email="novato@teste.com", empresa_id=empresa.id, papel=PapelUsuario.operador,
        token="token-de-teste-123", expira_em=datetime.now(timezone.utc) + timedelta(days=7),
        criado_por_usuario_id=titular.id,
    )
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites/aceitar",
                json={"token": "token-de-teste-123", "senha": "senha-nova-123"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    novo = (
        await db_session.execute(select(Usuario).where(Usuario.email == "novato@teste.com"))
    ).scalar_one()
    assert verificar_senha("senha-nova-123", novo.senha_hash)
    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == novo.id, UsuarioEmpresa.empresa_id == empresa.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.operador
    await db_session.refresh(convite)
    assert convite.aceito_em is not None


@pytest.mark.asyncio
async def test_aceitar_convite_de_usuario_existente_nao_pede_senha(db_session):
    empresa_a, titular = await criar_empresa_titular(db_session, email_titular="convidante2@teste.com")
    empresa_b, _outro = await criar_empresa_titular(
        db_session, cnpj="66666666000166", email_titular="dono-b@teste.com",
    )
    convite = Convite(
        email="titular@teste.com", empresa_id=empresa_b.id, papel=PapelUsuario.operador,
        token="token-existente-123", expira_em=datetime.now(timezone.utc) + timedelta(days=7),
        criado_por_usuario_id=titular.id,
    )
    # o convidado, "titular@teste.com", ja existe no sistema como titular de outra empresa
    ja_existente = Usuario(email="titular@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(ja_existente)
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post("/convites/aceitar", json={"token": "token-existente-123"})
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == ja_existente.id, UsuarioEmpresa.empresa_id == empresa_b.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.operador


@pytest.mark.asyncio
async def test_aceitar_convite_expirado_devolve_400(db_session):
    empresa, titular = await criar_empresa_titular(db_session, email_titular="convidante3@teste.com")
    convite = Convite(
        email="tarde@teste.com", empresa_id=empresa.id, papel=PapelUsuario.operador,
        token="token-expirado-123", expira_em=datetime.now(timezone.utc) - timedelta(days=1),
        criado_por_usuario_id=titular.id,
    )
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites/aceitar", json={"token": "token-expirado-123", "senha": "senha-nova-123"}
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_novo_convite_para_o_mesmo_email_invalida_o_anterior(db_session, monkeypatch):
    import app.routers.convites as modulo

    async def _enviar_falso(destinatario, link):
        return None

    monkeypatch.setattr(modulo, "enviar_convite", _enviar_falso)

    empresa, titular = await criar_empresa_titular(db_session, email_titular="repete@teste.com")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeiro = await client.post(
                "/convites", json={"email": "x@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                "/convites", json={"email": "x@teste.com", "papel": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    convite_antigo = await db_session.get(Convite, primeiro.json()["id"])
    assert convite_antigo.expira_em <= datetime.now(timezone.utc)
```

- [ ] **Step 10: Rodar e confirmar falha**

Run: `pytest tests/test_convites.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.routers.convites'`

- [ ] **Step 11: Escrever `app/routers/convites.py`**

```python
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import hash_senha
from app.db import get_db
from app.email import enviar_convite
from app.models import Convite, PapelUsuario, Usuario, UsuarioEmpresa
from app.schemas import ConviteAceitarIn, ConviteCriarIn, ConviteOut
from app.security import ContextoAutenticado, get_contexto_autenticado

router = APIRouter(prefix="/convites", tags=["convites"])


@router.post("", response_model=ConviteOut, status_code=201)
async def criar_convite(
    dados: ConviteCriarIn,
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> Convite:
    from app.config import get_settings

    if contexto.eh_admin_plataforma:
        if dados.plano_id is None:
            raise HTTPException(status_code=422, detail="plano_id e obrigatorio para convite de titular")
        empresa_id = None
        papel = None
    elif contexto.papel == PapelUsuario.admin and contexto.empresa_id is not None:
        if dados.papel is None:
            raise HTTPException(status_code=422, detail="papel e obrigatorio para convite de operador")
        empresa_id = contexto.empresa_id
        papel = PapelUsuario(dados.papel)
    else:
        raise HTTPException(status_code=403, detail="Sem permissao para convidar")

    agora = datetime.now(timezone.utc)
    pendentes = (
        await session.execute(
            select(Convite).where(
                Convite.email == dados.email,
                Convite.empresa_id == empresa_id,
                Convite.aceito_em.is_(None),
                Convite.expira_em > agora,
            )
        )
    ).scalars().all()
    for pendente in pendentes:
        pendente.expira_em = agora

    convite = Convite(
        email=dados.email,
        empresa_id=empresa_id,
        papel=papel,
        plano_id=dados.plano_id,
        token=secrets.token_urlsafe(32),
        expira_em=agora + timedelta(days=7),
        criado_por_usuario_id=contexto.usuario.id,
    )
    session.add(convite)
    await session.commit()
    await session.refresh(convite)

    settings = get_settings()
    link = f"{settings.app_base_url}/aceitar-convite?token={convite.token}"
    await enviar_convite(convite.email, link)

    return convite


@router.post("/aceitar", response_model=ConviteOut)
async def aceitar_convite(
    dados: ConviteAceitarIn,
    session: AsyncSession = Depends(get_db),
) -> Convite:
    convite = (
        await session.execute(select(Convite).where(Convite.token == dados.token))
    ).scalar_one_or_none()
    if convite is None:
        raise HTTPException(status_code=400, detail="Convite invalido")
    if convite.aceito_em is not None:
        raise HTTPException(status_code=400, detail="Convite ja foi aceito")
    if convite.expira_em <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Convite expirado")

    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == convite.email))
    ).scalar_one_or_none()

    if usuario is None:
        if not dados.senha:
            raise HTTPException(status_code=422, detail="senha e obrigatoria para um novo usuario")
        usuario = Usuario(
            email=convite.email, senha_hash=hash_senha(dados.senha), plano_id=convite.plano_id,
        )
        session.add(usuario)
        await session.flush()
    elif convite.plano_id is not None:
        usuario.plano_id = convite.plano_id

    if convite.empresa_id is not None:
        vinculo_existente = (
            await session.execute(
                select(UsuarioEmpresa).where(
                    UsuarioEmpresa.usuario_id == usuario.id,
                    UsuarioEmpresa.empresa_id == convite.empresa_id,
                )
            )
        ).scalar_one_or_none()
        if vinculo_existente is not None:
            raise HTTPException(status_code=409, detail="Usuario ja tem acesso a essa empresa")
        session.add(
            UsuarioEmpresa(usuario_id=usuario.id, empresa_id=convite.empresa_id, papel=convite.papel)
        )

    convite.aceito_em = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(convite)
    return convite
```

- [ ] **Step 12: Remover `app/routers/usuarios.py`**

```bash
git rm app/routers/usuarios.py
```

- [ ] **Step 13: Atualizar `app/main.py`**

```python
from fastapi import FastAPI

from app.routers import auth, convites, dashboard, emissoes, webhook_stone

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router)
app.include_router(convites.router)
app.include_router(emissoes.router)
app.include_router(webhook_stone.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 14: Rodar e confirmar sucesso**

Run: `pytest tests/test_convites.py tests/test_email.py -v`
Expected: PASS (6 + 1 testes)

- [ ] **Step 15: Commit**

```bash
git add app/email.py app/routers/convites.py app/config.py app/schemas.py app/main.py \
        requirements.txt .env.example tests/test_email.py tests/test_convites.py
git commit -m "feat: fluxo de convites por e-mail, remove cadastro direto de usuario"
```

---

### Task 5: Empresa ativa nos endpoints de negócio + reparo da suíte existente

Esta é a task de maior superfície: troca `usuario.empresa_id`/`usuario.id` por `contexto.empresa_id`/`contexto.usuario.id` em `emissoes.py`/`dashboard.py`, e conserta todo teste que ainda usa o padrão antigo (`Usuario(empresa_id=..., papel=...)`). Nenhuma lógica de negócio muda — só a fonte de onde vem `empresa_id`.

**Files:**
- Modify: `app/routers/emissoes.py`, `app/routers/dashboard.py`
- Modify: `tests/test_emissoes_manual.py`, `tests/test_emissoes_download.py`, `tests/test_emissoes_csv.py`, `tests/test_dashboard.py`, `tests/test_tenant_isolation.py`, `tests/test_worker.py`, `tests/test_webhook_stone.py`, `tests/test_numeracao.py`

**Interfaces:**
- Consumes: Task 2's `ContextoAutenticado`, `get_empresa_ativa`; Task 2's `tests/apoio.py` (`criar_empresa_titular`, `criar_empresa_e_token`).
- Produces: nenhuma interface nova — o contrato HTTP de cada endpoint já existente não muda, só a implementação por baixo.

- [ ] **Step 1: Atualizar `app/routers/emissoes.py`**

Trocar o import de `get_current_user` por `get_empresa_ativa`, e `Usuario` continua importado (ainda usado em type hints de outras funções que não mudam de assinatura, se houver — senão remover):

```python
from app.security import get_empresa_ativa
```

Em `emitir_manual`, trocar a assinatura e o corpo:

```python
@router.post("/manual", response_model=EmissaoOut, status_code=201)
async def emitir_manual(
    dados: EmissaoManualIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    serie, numero = await reservar_proximo_numero(session, contexto.empresa_id)
    emissao = Emissao(
        empresa_id=contexto.empresa_id,
        origem=OrigemEmissao.manual,
        status=StatusEmissao.pendente,
        serie=serie,
        numero=numero,
        tomador_cpf_cnpj=dados.cpf_cnpj,
        tomador_nome=dados.nome,
        tomador_email=dados.email,
        descricao=dados.descricao,
        valor=dados.valor,
        competencia=dados.competencia,
        criada_por_usuario_id=contexto.usuario.id,
    )
    session.add(emissao)
    await session.commit()
    await session.refresh(emissao)
    return emissao
```

Em `listar_emissoes`:

```python
@router.get("", response_model=list[EmissaoOut])
async def listar_emissoes(
    status: StatusEmissao | None = Query(default=None),
    inicio: date | None = Query(default=None),
    fim: date | None = Query(default=None),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[Emissao]:
    stmt = select(Emissao).where(Emissao.empresa_id == contexto.empresa_id)
    if status is not None:
        stmt = stmt.where(Emissao.status == status)
    if inicio is not None:
        stmt = stmt.where(Emissao.criada_em >= inicio_do_dia_brt(inicio))
    if fim is not None:
        stmt = stmt.where(Emissao.criada_em < fim_do_dia_brt(fim))
    stmt = stmt.order_by(Emissao.criada_em.desc())
    return list((await session.execute(stmt)).scalars().all())
```

Em `baixar_xml` e `baixar_pdf`, trocar `usuario: Usuario = Depends(get_current_user)` por `contexto: ContextoAutenticado = Depends(get_empresa_ativa)`, e `emissao.empresa_id != usuario.empresa_id` por `emissao.empresa_id != contexto.empresa_id` (as duas ocorrências — uma em cada função). Nenhuma outra linha dessas duas funções muda.

Em `_processar_csv`, trocar a assinatura e as duas referências a `usuario`:

```python
async def _processar_csv(
    conteudo: bytes, contexto: ContextoAutenticado, session: AsyncSession, *, confirmar: bool,
) -> dict:
    try:
        resultado = parsear_relatorio_stone(conteudo)
    except CabecalhoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ignoradas = dict(resultado.ignoradas)
    ignoradas["ja_emitida_anteriormente"] = 0

    stone_ids = [nota.stone_charge_id for nota in resultado.notas]
    existentes: set[str] = set()
    if stone_ids:
        linhas = await session.execute(
            select(Emissao.stone_charge_id).where(
                Emissao.empresa_id == contexto.empresa_id,
                Emissao.stone_charge_id.in_(stone_ids),
            )
        )
        existentes = {linha[0] for linha in linhas}

    notas_validas: list[NotaCandidata] = []
    for nota in resultado.notas:
        if nota.stone_charge_id in existentes:
            ignoradas["ja_emitida_anteriormente"] += 1
            continue
        notas_validas.append(nota)

    if confirmar and notas_validas:
        empresa = await session.get(Empresa, contexto.empresa_id)
        for nota in notas_validas:
            serie, numero = await reservar_proximo_numero(session, contexto.empresa_id)
            emissao = Emissao(
                empresa_id=contexto.empresa_id,
                origem=OrigemEmissao.csv,
                stone_charge_id=nota.stone_charge_id,
                status=StatusEmissao.pendente,
                serie=serie,
                numero=numero,
                descricao=empresa.descricao_servico_padrao,
                valor=nota.valor,
                competencia=nota.data_da_venda.date().replace(day=1),
                criada_por_usuario_id=contexto.usuario.id,
            )
            session.add(emissao)
        await session.commit()

    valor_total = sum((nota.valor for nota in notas_validas), Decimal("0"))
    return {
        "total_notas": len(notas_validas),
        "valor_total": str(valor_total.quantize(Decimal("0.01"))),
        "ignoradas": ignoradas,
    }


@router.post("/csv/preview")
async def preview_csv(
    arquivo: UploadFile = File(...),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    conteudo = await arquivo.read()
    return await _processar_csv(conteudo, contexto, session, confirmar=False)


@router.post("/csv/confirmar")
async def confirmar_csv(
    arquivo: UploadFile = File(...),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    conteudo = await arquivo.read()
    return await _processar_csv(conteudo, contexto, session, confirmar=True)
```

Acrescentar `ContextoAutenticado` ao import de `app.security` no topo do arquivo (junto de `get_empresa_ativa`).

- [ ] **Step 2: Atualizar `app/routers/dashboard.py`**

```python
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Emissao, StatusEmissao
from app.periodo import fim_do_dia_brt, inicio_do_dia_brt
from app.security import ContextoAutenticado, get_empresa_ativa

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    inicio: date = Query(...),
    fim: date = Query(...),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(Emissao.status, func.coalesce(func.sum(Emissao.valor), 0))
        .where(
            Emissao.empresa_id == contexto.empresa_id,
            Emissao.criada_em >= inicio_do_dia_brt(inicio),
            Emissao.criada_em < fim_do_dia_brt(fim),
        )
        .group_by(Emissao.status)
    )
    linhas = (await session.execute(stmt)).all()

    totais: dict[str, Decimal] = {status.value: Decimal("0.00") for status in StatusEmissao}
    for status, soma in linhas:
        totais[status if isinstance(status, str) else status.value] = Decimal(soma).quantize(Decimal("0.01"))

    return {
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "totais_por_status": {chave: str(valor) for chave, valor in totais.items()},
        "total_autorizado": str(totais[StatusEmissao.autorizada.value]),
    }
```

- [ ] **Step 3: Atualizar `tests/test_emissoes_manual.py`**

Trocar a função `_empresa_e_usuario` inteira (o resto do arquivo — os 4 testes — não muda nenhuma linha, já que continuam chamando `empresa, token = await _empresa_e_usuario(db_session)`):

```python
from tests.apoio import criar_empresa_e_token


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    return await criar_empresa_e_token(db_session)
```

Remover o import de `AmbienteEnum, Empresa, PapelUsuario, Usuario` do topo se não forem mais usados diretamente neste arquivo (checar: `Empresa` ainda aparece só na anotação de tipo `-> tuple[Empresa, str]`, então mantenha `from app.models import Empresa`; remova `AmbienteEnum`, `PapelUsuario`, `Usuario` do import se sobrarem sem uso — confira com uma rodada do `pytest` que não há `NameError`, e um lint rápido, se disponível, para imports não usados).

- [ ] **Step 4: Atualizar `tests/test_emissoes_download.py`**

Trocar `_empresa_usuario_emissao_autorizada` para usar o helper (mantém a `Emissao` extra que os outros testes precisam):

```python
from tests.apoio import criar_empresa_titular


async def _empresa_usuario_emissao_autorizada(db_session):
    fernet_key = get_settings().fernet_key
    empresa, usuario = await criar_empresa_titular(
        db_session,
        certificado_pfx_cifrado=cifrar("pfx-fake", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="1" * 50, xml_nfse=b"<NFSe>ok</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(usuario)
    await db_session.refresh(emissao)
    return empresa, usuario, emissao
```

Em cada um dos 5 testes deste arquivo, a linha `token = criar_token(usuario)` passa a `token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)` — a função `criar_empresa_titular` usa `papel_vinculo=PapelUsuario.admin` por padrão, então isso bate com o vínculo real criado. `PapelUsuario` precisa continuar importado de `app.models` (já está).

- [ ] **Step 5: Atualizar `tests/test_emissoes_csv.py`**

Trocar `_empresa_e_usuario` (igual à Task 3 do plano anterior tinha feito):

```python
from tests.apoio import criar_empresa_e_token


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    return await criar_empresa_e_token(
        db_session, municipio_ibge="1501402", codigo_tributacao="141001",
        descricao_servico_padrao="Lavagem de roupa",
    )
```

No teste `test_confirmar_csv_nao_cruza_dedupe_nem_visibilidade_entre_empresas`, trocar o bloco que cria `empresa_b`/`usuario_b`/`token_b` manualmente por:

```python
    from tests.apoio import criar_empresa_e_token

    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="99999999000199", email="op-b@teste.com",
        municipio_ibge="1501402", codigo_tributacao="141001",
        descricao_servico_padrao="Lavagem de roupa B",
    )
```

(remove as ~10 linhas anteriores que construíam `Empresa`/`Usuario` diretamente para `empresa_b`)

- [ ] **Step 5b: Acrescentar teste de 409 sem empresa ativa em `tests/test_emissoes_manual.py`**

O `tests/test_security.py` da Task 2 já cobre `get_empresa_ativa` no nível de unidade; este teste cobre o mesmo caso na integração HTTP real, contra um endpoint de negócio de verdade — é o cenário explicitamente listado na spec ("Endpoint de negócio (ex: `GET /emissoes`) chamado com token sem empresa ativa → 409"). Acrescentar ao fim de `tests/test_emissoes_manual.py`:

```python
@pytest.mark.asyncio
async def test_listar_emissoes_sem_empresa_ativa_devolve_409(db_session):
    from app.crypto import hash_senha
    from app.models import Usuario
    from app.security import criar_token

    usuario_sem_empresa = Usuario(email="sem-empresa-ativa@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(usuario_sem_empresa)
    await db_session.commit()
    await db_session.refresh(usuario_sem_empresa)
    token = criar_token(usuario_sem_empresa)  # sem empresa_id/papel

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get("/emissoes", headers={"Authorization": f"Bearer {token}"})
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 6: Reescrever `tests/test_dashboard.py`**

```python
import functools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, StatusEmissao
from tests.apoio import criar_empresa_e_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_dashboard_soma_valores_por_status(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    db_session.add_all([
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
            serie="1", numero=1, descricao="Lavagem", valor=Decimal("50.00"), competencia=date(2026, 8, 1),
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
            serie="1", numero=2, descricao="Lavagem", valor=Decimal("30.00"), competencia=date(2026, 8, 1),
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
            serie="1", numero=3, descricao="Lavagem", valor=Decimal("20.00"), competencia=date(2026, 8, 1),
        ),
    ])
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/dashboard", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["totais_por_status"]["autorizada"] == "80.00"
        assert corpo["totais_por_status"]["rejeitada"] == "20.00"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_usa_limites_de_dia_em_brt(db_session):
    """`criada_em` e timestamptz e o Postgres converte um `date` cru pelo
    TimeZone da sessao (UTC). A nota das 21:30 BRT do dia 31/08 (00:30 UTC de
    01/09) tem que somar em AGOSTO."""
    empresa, token = await criar_empresa_e_token(db_session, email="op2@teste.com")
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("50.00"),
        competencia=date(2026, 8, 1),
        criada_em=datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc),  # 31/08 21:30 BRT
    )
    db_session.add(emissao)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            agosto = await client.get(
                "/dashboard", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
                headers={"Authorization": f"Bearer {token}"},
            )
            setembro = await client.get(
                "/dashboard", params={"inicio": "2026-09-01", "fim": "2026-09-30"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert agosto.json()["total_autorizado"] == "50.00"
        assert setembro.json()["total_autorizado"] == "0.00"
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 7: Atualizar `tests/test_tenant_isolation.py`**

Trocar `_empresa_com_usuario`:

```python
from tests.apoio import criar_empresa_titular


async def _empresa_com_usuario(db_session, *, cnpj: str, email: str) -> tuple[Empresa, Usuario]:
    return await criar_empresa_titular(db_session, cnpj=cnpj, email_titular=email)
```

Em `_duas_empresas`, a linha `empresa_id=usuario_a.empresa_id` não funciona mais (`Usuario` não tem mais `empresa_id`) — trocar para usar a empresa retornada. A função já descartava `_empresa_a` no unpacking (`_empresa_a, usuario_a = await _empresa_com_usuario(...)`); trocar para manter a referência:

```python
async def _duas_empresas(db_session) -> tuple[Emissao, Usuario, Usuario]:
    empresa_a, usuario_a = await _empresa_com_usuario(
        db_session, cnpj="11111111000111", email="admin@empresa-a.com"
    )
    _empresa_b, usuario_b = await _empresa_com_usuario(
        db_session, cnpj="22222222000122", email="admin@empresa-b.com"
    )
    emissao_de_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.manual,
        status=StatusEmissao.autorizada, serie="1", numero=1,
        chave_acesso="9" * 50, xml_nfse=b"<NFSe>segredo da empresa A</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente da A",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao_de_a)
    await db_session.commit()
    await db_session.refresh(usuario_a)
    await db_session.refresh(usuario_b)
    await db_session.refresh(emissao_de_a)
    return emissao_de_a, usuario_a, usuario_b
```

Cada chamada `criar_token(usuario_a)`/`criar_token(usuario_b)` no resto do arquivo (4 ocorrências) precisa passar a empresa ativa — trocar todas para `criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)` e `criar_token(usuario_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)`. Como `empresa_a`/`empresa_b` não estão no escopo de cada teste (só dentro de `_duas_empresas`), a forma mais simples é `_duas_empresas` devolver também as duas empresas:

```python
async def _duas_empresas(db_session):
    empresa_a, usuario_a = await _empresa_com_usuario(
        db_session, cnpj="11111111000111", email="admin@empresa-a.com"
    )
    empresa_b, usuario_b = await _empresa_com_usuario(
        db_session, cnpj="22222222000122", email="admin@empresa-b.com"
    )
    emissao_de_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.manual,
        status=StatusEmissao.autorizada, serie="1", numero=1,
        chave_acesso="9" * 50, xml_nfse=b"<NFSe>segredo da empresa A</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente da A",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao_de_a)
    await db_session.commit()
    await db_session.refresh(usuario_a)
    await db_session.refresh(usuario_b)
    await db_session.refresh(emissao_de_a)
    return emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b
```

E em cada um dos 4 testes, trocar `emissao_de_a, usuario_a, usuario_b = await _duas_empresas(db_session)` por `emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b = await _duas_empresas(db_session)`, e cada `criar_token(usuario_a)`/`criar_token(usuario_b)` por `criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)`/`criar_token(usuario_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)`. Acrescentar `PapelUsuario` ao import de `app.models` no topo (já deve estar, confira).

Acrescentar um teste novo, cobrindo isolamento através da **troca** de empresa ativa (um único titular com duas empresas, não dois usuários distintos — cenário explicitamente listado na spec, distinto dos 4 testes acima que já existiam):

```python
@pytest.mark.asyncio
async def test_isolamento_atraves_de_troca_de_empresa_ativa(db_session):
    from tests.apoio import criar_empresa_titular

    empresa_a, titular = await criar_empresa_titular(
        db_session, cnpj="77777777000177", email_titular="titular-duas-empresas@teste.com",
    )
    empresa_b = Empresa(
        cnpj="88888888000188", inscricao_municipal="2", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem B",
        ambiente=empresa_a.ambiente, certificado_pfx_cifrado="x", certificado_senha_cifrada="x",
        certificado_valido_ate=empresa_a.certificado_valido_ate, webhook_token_hash="x",
        titular_id=titular.id,
    )
    db_session.add(empresa_b)
    await db_session.flush()
    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_b.id, papel=PapelUsuario.admin))
    emissao_de_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="8" * 50, xml_nfse=b"<NFSe>segredo da empresa A</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente da A",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao_de_a)
    await db_session.commit()
    await db_session.refresh(titular)

    token_ativo_em_b = criar_token(titular, empresa_id=empresa_b.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listagem = await client.get(
                "/emissoes", headers={"Authorization": f"Bearer {token_ativo_em_b}"}
            )
        assert listagem.status_code == 200
        # mesmo titular, mas com B como empresa ativa: nao ve a nota da empresa A
        assert listagem.json() == []
    finally:
        app.dependency_overrides.clear()
```

Acrescentar `UsuarioEmpresa` ao import de `app.models` no topo do arquivo (novo nesta task; `Empresa`, `Emissao`, `OrigemEmissao`, `StatusEmissao` já devem estar importados, sendo usados pelos testes existentes).

- [ ] **Step 8: Atualizar `tests/test_worker.py`**

Em `_empresa_e_emissao_pendente`, antes da construção de `Empresa`, criar um titular descartável e passar `titular_id`:

```python
from app.crypto import hash_senha
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao, Usuario


async def _empresa_e_emissao_pendente(
    db_session,
    tomador_cpf_cnpj: str | None = "98765432100",
    fernet_key: str | None = None,
    dps_id: str | None = None,
) -> Emissao:
    fernet_key = fernet_key or get_settings().fernet_key
    titular = Usuario(email=f"titular-worker-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
        certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, dps_id=dps_id,
        # (resto do corpo da funcao continua identico ao que ja existia)
```

O `cnpj` fixo mais o e-mail do titular gerado com `uuid.uuid4()` evita colisão de `unique=True` em `usuarios.email` entre chamadas repetidas dentro do mesmo teste (esta função é chamada várias vezes ao longo do arquivo, cada vez numa `db_session` nova — mas por clareza, o e-mail único evita qualquer dependência da ordem de limpeza do fixture). Acrescentar `import uuid` e `from app.crypto import cifrar, hash_senha` (confira se `cifrar` já está importado — está, junto com o resto).

- [ ] **Step 9: Atualizar `tests/test_webhook_stone.py`**

Em `_empresa_com_token`, mesmo padrão:

```python
import uuid

from app.crypto import hash_senha
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao, Usuario


async def _empresa_com_token(db_session) -> Empresa:
    titular = Usuario(email=f"titular-webhook-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash=hash_senha("token-secreto"), titular_id=titular.id,
    )
    db_session.add(empresa)
    await db_session.commit()
    return empresa
```

- [ ] **Step 10: Atualizar `tests/test_numeracao.py`**

Em `_criar_empresa`:

```python
import uuid

from app.crypto import hash_senha
from app.models import AmbienteEnum, Empresa, Usuario


async def _criar_empresa(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        titular = Usuario(
            email=f"titular-numeracao-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"),
        )
        session.add(titular)
        await session.flush()
        empresa = Empresa(
            cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
            op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
            ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
            certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
            webhook_token_hash="x", titular_id=titular.id,
        )
        session.add(empresa)
        await session.commit()
        return empresa.id
```

- [ ] **Step 11: Rodar a suíte inteira**

Run: `pytest -v`
Expected: PASS — todos os arquivos, sem exceção. Se algum teste falhar por um `NameError`/`ImportError` de um import não mais usado (ex: `PapelUsuario` sobrando em `test_emissoes_manual.py` depois da Step 3), remova o import sobrando; se faltar um import novo (ex: `uuid` em algum arquivo que passou a usá-lo), acrescente.

- [ ] **Step 12: Commit**

```bash
git add app/routers/emissoes.py app/routers/dashboard.py \
        tests/test_emissoes_manual.py tests/test_emissoes_download.py tests/test_emissoes_csv.py \
        tests/test_dashboard.py tests/test_tenant_isolation.py tests/test_worker.py \
        tests/test_webhook_stone.py tests/test_numeracao.py
git commit -m "feat: endpoints de negocio usam empresa ativa; suite adaptada ao novo modelo"
```

---

### Task 6: Ajuste de `scripts/criar_empresa.py` (titular + limite de plano)

**Files:**
- Modify: `scripts/criar_empresa.py`
- Modify: `tests/test_criar_empresa.py`

**Interfaces:**
- Consumes: Task 1's `Plano`, `UsuarioEmpresa`.
- Produces: `criar_empresa(session, *, ..., titular_email: str, ...) -> Empresa` (assinatura ganha `titular_email`, perde `admin_email`/`admin_senha` — o titular já precisa existir, ter sido criado por convite antes; o script só vincula a empresa nova a ele, checando o limite do plano).

- [ ] **Step 1: Atualizar `tests/test_criar_empresa.py`**

```python
import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.crypto import hash_senha
from app.models import Empresa, PapelUsuario, Plano, Usuario, UsuarioEmpresa
from scripts.criar_empresa import criar_empresa


def _pfx_teste_base64() -> str:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA TESTE LTDA:12345678000199")])
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=b"teste", key=chave, cert=certificado, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"senha123"),
    )
    return base64.b64encode(pfx_bytes).decode()


async def _titular_com_plano(db_session, *, limite_empresas: int, email: str) -> Usuario:
    plano = Plano(nome="Teste", limite_empresas=limite_empresas)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(email=email, senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)
    return titular


@pytest.mark.asyncio
async def test_criar_empresa_grava_empresa_e_vincula_titular_como_admin(db_session):
    titular = await _titular_com_plano(db_session, limite_empresas=2, email="titular@empresa-teste.com")
    pfx_b64 = _pfx_teste_base64()

    empresa = await criar_empresa(
        db_session,
        cnpj="12345678000199",
        inscricao_municipal="123456",
        municipio_ibge="3550308",
        op_simp_nac=3,
        codigo_tributacao="140106",
        descricao_servico_padrao="Servicos de lavagem de roupa",
        ambiente="homologacao",
        pfx_base64=pfx_b64,
        senha_certificado="senha123",
        webhook_token="token-super-secreto",
        titular_email="titular@empresa-teste.com",
    )

    assert empresa.cnpj == "12345678000199"
    assert empresa.titular_id == titular.id
    assert empresa.certificado_pfx_cifrado != pfx_b64  # nunca em claro
    assert empresa.certificado_valido_ate.date() > date.today()

    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == titular.id, UsuarioEmpresa.empresa_id == empresa.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.admin


@pytest.mark.asyncio
async def test_criar_empresa_rejeita_certificado_de_cnpj_diferente(db_session):
    titular = await _titular_com_plano(db_session, limite_empresas=2, email="titular2@empresa-teste.com")
    pfx_b64 = _pfx_teste_base64()  # CNPJ 12345678000199

    with pytest.raises(ValueError, match="CNPJ"):
        await criar_empresa(
            db_session,
            cnpj="99999999000199",
            inscricao_municipal="123456",
            municipio_ibge="3550308",
            op_simp_nac=3,
            codigo_tributacao="140106",
            descricao_servico_padrao="Servicos de lavagem de roupa",
            ambiente="homologacao",
            pfx_base64=pfx_b64,
            senha_certificado="senha123",
            webhook_token="token-super-secreto",
            titular_email="titular2@empresa-teste.com",
        )


@pytest.mark.asyncio
async def test_criar_empresa_recusa_titular_sem_plano(db_session):
    titular = Usuario(email="sem-plano@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.commit()
    pfx_b64 = _pfx_teste_base64()

    with pytest.raises(ValueError, match="plano"):
        await criar_empresa(
            db_session,
            cnpj="12345678000199",
            inscricao_municipal="123456",
            municipio_ibge="3550308",
            op_simp_nac=3,
            codigo_tributacao="140106",
            descricao_servico_padrao="Servicos de lavagem de roupa",
            ambiente="homologacao",
            pfx_base64=pfx_b64,
            senha_certificado="senha123",
            webhook_token="token-super-secreto",
            titular_email="sem-plano@teste.com",
        )


@pytest.mark.asyncio
async def test_criar_empresa_recusa_acima_do_limite_do_plano(db_session):
    titular = await _titular_com_plano(db_session, limite_empresas=1, email="no-limite@teste.com")
    pfx_b64 = _pfx_teste_base64()

    await criar_empresa(
        db_session,
        cnpj="12345678000199",
        inscricao_municipal="123456",
        municipio_ibge="3550308",
        op_simp_nac=3,
        codigo_tributacao="140106",
        descricao_servico_padrao="Servicos de lavagem de roupa",
        ambiente="homologacao",
        pfx_base64=pfx_b64,
        senha_certificado="senha123",
        webhook_token="token-super-secreto-1",
        titular_email="no-limite@teste.com",
    )

    with pytest.raises(ValueError, match="limite"):
        await criar_empresa(
            db_session,
            cnpj="98765432000199",
            inscricao_municipal="654321",
            municipio_ibge="3550308",
            op_simp_nac=3,
            codigo_tributacao="140106",
            descricao_servico_padrao="Segunda empresa",
            ambiente="homologacao",
            pfx_base64=_pfx_teste_base64(),
            senha_certificado="senha123",
            webhook_token="token-super-secreto-2",
            titular_email="no-limite@teste.com",
        )
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_criar_empresa.py -v`
Expected: FAIL — `criar_empresa` ainda não aceita `titular_email`, ainda exige `admin_email`/`admin_senha`.

- [ ] **Step 3: Reescrever `scripts/criar_empresa.py`**

```python
"""Bootstrap de uma empresa (fora da API — roda por quem tem o .pfx em mãos).

O titular precisa já existir no sistema (criado por convite aceito — ver
POST /convites) e ter um plano vinculado com limite de empresas disponível.

Uso:
    python scripts/criar_empresa.py --cnpj 12345678000199 --im 123456 \
        --municipio 3550308 --regime 3 --cod-tributacao 140106 \
        --descricao "Servicos de lavagem de roupa" --ambiente homologacao \
        --pfx caminho/certificado.pfx --senha-certificado "..." \
        --titular-email titular@empresa.com
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import cifrar, hash_senha
from app.db import SessionLocal
from app.models import AmbienteEnum, Empresa, PapelUsuario, Plano, Usuario, UsuarioEmpresa
from nfse_core import CertificateError, conferir_titularidade, inspecionar


async def criar_empresa(
    session: AsyncSession,
    *,
    cnpj: str,
    inscricao_municipal: str,
    municipio_ibge: str,
    op_simp_nac: int,
    codigo_tributacao: str,
    descricao_servico_padrao: str,
    ambiente: str,
    pfx_base64: str,
    senha_certificado: str,
    webhook_token: str,
    titular_email: str,
) -> Empresa:
    titular = (
        await session.execute(select(Usuario).where(Usuario.email == titular_email))
    ).scalar_one_or_none()
    if titular is None:
        raise ValueError(f"Nenhum usuario encontrado com o e-mail {titular_email}")
    if titular.plano_id is None:
        raise ValueError(f"Usuario {titular_email} nao tem plano vinculado")

    plano = await session.get(Plano, titular.plano_id)
    empresas_do_titular = (
        await session.execute(
            select(func.count()).select_from(Empresa).where(Empresa.titular_id == titular.id)
        )
    ).scalar_one()
    if empresas_do_titular >= plano.limite_empresas:
        raise ValueError(
            f"Titular {titular_email} ja atingiu o limite de {plano.limite_empresas} "
            f"empresa(s) do plano {plano.nome}"
        )

    try:
        info = inspecionar(pfx_base64, senha_certificado)
    except CertificateError as exc:
        raise ValueError(f"Certificado invalido: {exc}") from exc

    aviso_titularidade = conferir_titularidade(info, cnpj)
    if aviso_titularidade:
        raise ValueError(aviso_titularidade)
    if info.expirado:
        raise ValueError(f"Certificado ja esta vencido em {info.valido_ate:%d/%m/%Y}")

    fernet_key = _fernet_key_do_ambiente()

    empresa = Empresa(
        cnpj=cnpj,
        inscricao_municipal=inscricao_municipal,
        municipio_ibge=municipio_ibge,
        op_simp_nac=op_simp_nac,
        codigo_tributacao=codigo_tributacao,
        descricao_servico_padrao=descricao_servico_padrao,
        ambiente=AmbienteEnum(ambiente),
        certificado_pfx_cifrado=cifrar(pfx_base64, fernet_key),
        certificado_senha_cifrada=cifrar(senha_certificado, fernet_key),
        certificado_valido_ate=info.valido_ate,
        webhook_token_hash=hash_senha(webhook_token),
        titular_id=titular.id,
    )
    session.add(empresa)
    await session.flush()

    session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=PapelUsuario.admin))
    await session.commit()
    await session.refresh(empresa)
    return empresa


def _fernet_key_do_ambiente() -> str:
    from app.config import get_settings

    return get_settings().fernet_key


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cnpj", required=True)
    parser.add_argument("--im", required=True, dest="inscricao_municipal")
    parser.add_argument("--municipio", required=True, dest="municipio_ibge")
    parser.add_argument("--regime", required=True, type=int, dest="op_simp_nac")
    parser.add_argument("--cod-tributacao", required=True, dest="codigo_tributacao")
    parser.add_argument("--descricao", required=True, dest="descricao_servico_padrao")
    parser.add_argument("--ambiente", required=True, choices=["homologacao", "producao"])
    parser.add_argument("--pfx", required=True, type=Path, dest="pfx_path")
    parser.add_argument("--senha-certificado", required=True)
    parser.add_argument("--titular-email", required=True, dest="titular_email")
    parser.add_argument("--webhook-token", default=None)
    args = parser.parse_args()

    pfx_base64 = base64.b64encode(args.pfx_path.read_bytes()).decode()
    webhook_token = args.webhook_token or secrets.token_urlsafe(32)

    async with SessionLocal() as session:
        empresa = await criar_empresa(
            session,
            cnpj=args.cnpj,
            inscricao_municipal=args.inscricao_municipal,
            municipio_ibge=args.municipio_ibge,
            op_simp_nac=args.op_simp_nac,
            codigo_tributacao=args.codigo_tributacao,
            descricao_servico_padrao=args.descricao_servico_padrao,
            ambiente=args.ambiente,
            pfx_base64=pfx_base64,
            senha_certificado=args.senha_certificado,
            webhook_token=webhook_token,
            titular_email=args.titular_email,
        )

    print(f"Empresa criada: {empresa.id} (CNPJ {empresa.cnpj})")
    if not args.webhook_token:
        print(f"Token do webhook (guarde, so aparece agora): {webhook_token}")
        print(f"URL do webhook na Stone: /webhooks/stone/{empresa.id}")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_criar_empresa.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Commit**

```bash
git add scripts/criar_empresa.py tests/test_criar_empresa.py
git commit -m "feat: criar_empresa vincula a um titular existente e respeita o limite do plano"
```

---

### Task 7: Rotas registradas, README e verificação final

**Files:**
- Modify: `tests/test_main_rotas_registradas.py`, `README.md`

**Interfaces:**
- Nenhuma interface nova — task de fechamento.

- [ ] **Step 1: Atualizar `tests/test_main_rotas_registradas.py`**

```python
from app.main import app


def test_todas_as_rotas_esperadas_estao_registradas():
    caminhos = set()
    for rota in app.routes:
        if hasattr(rota, "path"):
            caminhos.add(rota.path)
        elif type(rota).__name__ == "_IncludedRouter":
            for contexto in rota.effective_route_contexts():
                caminhos.add(contexto.path)

    esperadas = {
        "/health",
        "/auth/login",
        "/auth/empresas",
        "/auth/trocar-empresa",
        "/convites",
        "/convites/aceitar",
        "/webhooks/stone/{empresa_id}",
        "/emissoes/manual",
        "/emissoes",
        "/emissoes/{emissao_id}/xml",
        "/emissoes/{emissao_id}/pdf",
        "/emissoes/csv/preview",
        "/emissoes/csv/confirmar",
        "/dashboard",
    }
    faltando = esperadas - caminhos
    assert not faltando, f"rotas nao registradas: {faltando}"

    inesperadas = caminhos & {"/usuarios"}
    assert not inesperadas, f"rota removida ainda presente: {inesperadas}"
```

- [ ] **Step 2: Rodar e confirmar sucesso**

Run: `pytest tests/test_main_rotas_registradas.py -v`
Expected: PASS

- [ ] **Step 3: Atualizar `README.md`**

Localizar a seção "Checklist antes da primeira nota real" e acrescentar, no topo:

```markdown
- [ ] Cadastrar ao menos um `Plano` (tabela `planos`) e um usuário com
  `eh_admin_plataforma=true` diretamente no banco antes do primeiro uso —
  não há endpoint para isso ainda (é o primeiro operador humano da
  plataforma; convites exigem alguém já com essa permissão).
```

Localizar as instruções de "Rodando localmente" e trocar o passo "Cadastre a primeira empresa" para refletir o novo fluxo:

```markdown
6. Cadastre o primeiro ADM da plataforma e um plano diretamente no banco
   (não há UI para isso ainda), depois convide um titular
   (`POST /convites` com `plano_id`), aceite o convite
   (`POST /convites/aceitar`), e só então cadastre a empresa:
   `python scripts/criar_empresa.py --cnpj ... --pfx caminho/certificado.pfx
   --titular-email titular@empresa.com ...` (veja `--help`)
```

- [ ] **Step 4: Rodar a suíte completa uma última vez**

Run: `pytest -v`
Expected: PASS (todos os testes de todas as tasks)

- [ ] **Step 5: Commit**

```bash
git add tests/test_main_rotas_registradas.py README.md
git commit -m "docs: atualiza checklist e instrucoes de execucao local para multiempresa"
```

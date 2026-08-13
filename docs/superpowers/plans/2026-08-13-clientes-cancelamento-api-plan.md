# Clientes, cancelamento e API sob /api — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preparar o backend para o frontend (plano separado, depois deste): mover toda a API para `/api/*`, adicionar cadastro de clientes, ligar a importação de CSV a um cliente-padrão, permitir cancelamento de nota (ponta a ponta, incluindo submissão à SEFIN) e expor a criação de empresa via HTTP.

**Architecture:** Extensão aditiva do monólito FastAPI já existente — nenhum serviço novo, nenhuma dependência nova. Cancelamento segue o mesmo padrão assíncrono já usado para emissão (`app/worker.py`: grava `status=cancelamento_pendente`, um segundo processador do worker consome e submete à SEFIN). Cliente é uma tabela nova, escopada por empresa como todo o resto. A extensão do gerador de DPS (`nfse_core/dps.py`) é uma capacidade nova e independente, testada isoladamente — nada em `app/` a consome ainda (ver spec, seção "Extensão do DPS Builder").

**Tech Stack:** O mesmo do resto do projeto — FastAPI, SQLAlchemy 2.0 async, Alembic, pytest+pytest-asyncio+httpx.

Este é o primeiro de dois planos derivados da spec
`docs/superpowers/specs/2026-08-13-frontend-clientes-cancelamento-design.md`.
Este plano cobre só o **backend**; o frontend React fica em um plano
separado, escrito depois deste ser implementado (a spec descreve os dois,
mas são subsistemas independentes e testáveis cada um por si — o backend
via pytest, o frontend via verificação manual no navegador contra uma API
já pronta).

## Global Constraints

- Toda rota de API (exceto `/health`) passa a responder sob `/api/*` —
  ver spec, seção "Arquitetura do frontend".
- `Cliente.cpf_cnpj` é opcional — o CSV da Stone nunca traz esse dado.
- Nenhum código em `app/` lê `Cliente` para montar o DPS nesta fase — só
  `nfse_core/dps.py` ganha a capacidade, testada isoladamente.
- Cancelamento segue o padrão assíncrono já estabelecido em
  `app/worker.py` para emissão — nunca chama a SEFIN dentro da requisição
  HTTP.
- Mesma cautela de sempre com colunas enum mapeadas como `String` puro:
  nunca `.value` num valor recém-carregado do banco sem normalizar via
  `EnumType(valor)` primeiro.

---

## Estrutura de arquivos

```
app/
  main.py                    # MODIFICADO — prefixo /api em todos os routers
  security.py                  # MODIFICADO — tokenUrl aponta para /api/auth/login
  models.py                     # MODIFICADO — Cliente, Emissao.cliente_id,
                                 # StatusEmissao novo, Emissao.motivo_cancelamento/cancelada_em
  schemas.py                     # MODIFICADO — ClienteCriarIn/AtualizarIn/Out, CancelarEmissaoIn
  routers/
    clientes.py                   # NOVO — CRUD de clientes
    empresas.py                    # NOVO — POST /empresas
    emissoes.py                     # MODIFICADO — cliente-padrao no CSV, POST /{id}/cancelar
  worker.py                         # MODIFICADO — processar_um_cancelamento_pendente
nfse_core/
  dps.py                              # MODIFICADO — bloco <end> do tomador
alembic/versions/
  <rev1>_clientes_e_vinculo_emissao.py  # NOVO
  <rev2>_cancelamento_de_nota.py         # NOVO
tests/
  test_models_clientes.py                 # NOVO
  test_clientes.py                         # NOVO
  test_nfse_core_dps_end_tomador.py         # NOVO
  test_empresas_endpoint.py                  # NOVO
  test_emissoes_csv.py                        # MODIFICADO — cliente-padrao
  test_emissoes_cancelamento.py                # NOVO
  test_worker.py                                # MODIFICADO — cancelamento
  test_auth.py, test_convites.py, test_emissoes_manual.py,
  test_emissoes_download.py, test_dashboard.py,
  test_tenant_isolation.py, test_webhook_stone.py  # MODIFICADOS — prefixo /api
  test_main_rotas_registradas.py                    # MODIFICADO — rotas novas
```

---

### Task 1: Prefixo `/api` em todos os routers

**Files:**
- Modify: `app/main.py`, `app/security.py`
- Modify (mecânico, via `sed`): `tests/test_auth.py`, `tests/test_convites.py`,
  `tests/test_emissoes_manual.py`, `tests/test_emissoes_download.py`,
  `tests/test_emissoes_csv.py`, `tests/test_dashboard.py`,
  `tests/test_tenant_isolation.py`, `tests/test_webhook_stone.py`
- Rewrite: `tests/test_main_rotas_registradas.py`

**Interfaces:**
- Produces: toda rota de negócio passa a viver sob `/api/*`
  (`/api/auth/login`, `/api/emissoes`, etc.); `/health` continua sem
  prefixo.

- [ ] **Step 1: Editar `app/main.py`**

```python
from fastapi import FastAPI

from app.routers import auth, convites, dashboard, emissoes, webhook_stone

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router, prefix="/api")
app.include_router(convites.router, prefix="/api")
app.include_router(emissoes.router, prefix="/api")
app.include_router(webhook_stone.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

(`include_router(router, prefix="/api")` concatena com o prefixo próprio
de cada router — `auth.router` já tem `prefix="/auth"`, resultado final
`/api/auth`.)

- [ ] **Step 2: Editar `app/security.py`**

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
```

- [ ] **Step 3: Rodar a suíte inteira e confirmar quebra generalizada**

Run: `pytest -q`
Expected: FAIL em massa — todo teste que chama um caminho antigo
(`"/auth/..."`, `"/emissoes..."`, etc.) recebe 404, porque a rota agora só
existe sob `/api/...`.

- [ ] **Step 4: Corrigir os caminhos nos 8 arquivos de teste, de uma vez**

```bash
sed -i \
  -e 's@"/auth@"/api/auth@g' \
  -e 's@"/convites@"/api/convites@g' \
  -e 's@"/emissoes@"/api/emissoes@g' \
  -e 's@"/dashboard@"/api/dashboard@g' \
  -e 's@"/webhooks/stone@"/api/webhooks/stone@g' \
  tests/test_auth.py tests/test_convites.py tests/test_emissoes_manual.py \
  tests/test_emissoes_download.py tests/test_emissoes_csv.py tests/test_dashboard.py \
  tests/test_tenant_isolation.py tests/test_webhook_stone.py
```

Isso cobre tanto strings literais (`"/emissoes"`) quanto f-strings
(`f"/emissoes/{id}/xml"` — o `f` fica antes da aspa, o `sed` casa a partir
da aspa em diante).

- [ ] **Step 5: Confirmar que não sobrou nenhum caminho sem prefixo**

```bash
grep -n '"/auth\|"/convites\|"/emissoes\|"/dashboard\|"/webhooks/stone' \
  tests/test_auth.py tests/test_convites.py tests/test_emissoes_manual.py \
  tests/test_emissoes_download.py tests/test_emissoes_csv.py tests/test_dashboard.py \
  tests/test_tenant_isolation.py tests/test_webhook_stone.py \
  | grep -v '"/api/'
```

Expected: nenhuma linha impressa (grep sem match sai com código 1 — se o
comando "falhar", é sinal de sucesso aqui).

- [ ] **Step 6: Reescrever `tests/test_main_rotas_registradas.py`**

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
        "/api/auth/login",
        "/api/auth/empresas",
        "/api/auth/trocar-empresa",
        "/api/convites",
        "/api/convites/aceitar",
        "/api/webhooks/stone/{empresa_id}",
        "/api/emissoes/manual",
        "/api/emissoes",
        "/api/emissoes/{emissao_id}/xml",
        "/api/emissoes/{emissao_id}/pdf",
        "/api/emissoes/csv/preview",
        "/api/emissoes/csv/confirmar",
        "/api/dashboard",
    }
    faltando = esperadas - caminhos
    assert not faltando, f"rotas nao registradas: {faltando}"

    inesperadas = {c for c in caminhos if c not in esperadas and c != "/health" and not c.startswith("/openapi") and not c.startswith("/docs") and not c.startswith("/redoc")}
    assert not inesperadas, f"rotas sem prefixo /api ou inesperadas: {inesperadas}"
```

(A lista `esperadas` volta a crescer nas Tasks 3, 6 e 8 deste plano, cada
uma acrescentando as rotas que introduz — ver Task 9 para a versão final.)

- [ ] **Step 7: Rodar a suíte inteira e confirmar sucesso**

Run: `pytest -q`
Expected: PASS — mesma contagem de testes de antes (104), agora todos sob
`/api`.

- [ ] **Step 8: Commit**

```bash
git add app/main.py app/security.py tests/test_auth.py tests/test_convites.py \
        tests/test_emissoes_manual.py tests/test_emissoes_download.py \
        tests/test_emissoes_csv.py tests/test_dashboard.py \
        tests/test_tenant_isolation.py tests/test_webhook_stone.py \
        tests/test_main_rotas_registradas.py
git commit -m "feat: move toda a API para o prefixo /api, preparando para servir o frontend"
```

---

### Task 2: Modelo `Cliente` + `Emissao.cliente_id` + migração

**Files:**
- Modify: `app/models.py`
- Create: `alembic/versions/<revisao>_clientes_e_vinculo_emissao.py`
- Test: `tests/test_models_clientes.py`

**Interfaces:**
- Consumes: `app.models.Base`, `_agora`, padrão de `Index(..., unique=True,
  postgresql_where=text(...))` já usado em `Emissao`.
- Produces: `app.models.Cliente` (`id`, `empresa_id`, `cpf_cnpj:
  str | None`, `nome`, `email`, `telefone`, `inscricao_estadual`,
  `inscricao_municipal`, `logradouro`, `numero`, `complemento`, `bairro`,
  `municipio_ibge`, `uf`, `cep`, `eh_padrao_csv: bool`, `ativo: bool`,
  `criado_em`, `atualizado_em`). `Emissao` ganha `cliente_id: uuid.UUID |
  None` (FK `clientes.id`, nullable).

- [ ] **Step 1: Escrever `tests/test_models_clientes.py`**

```python
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AmbienteEnum, Cliente, Emissao, Empresa, OrigemEmissao, StatusEmissao
from tests.apoio import criar_empresa_titular


async def _empresa(db_session) -> Empresa:
    empresa, _titular = await criar_empresa_titular(db_session)
    return empresa


@pytest.mark.asyncio
async def test_cliente_grava_todos_os_campos_fiscais(db_session):
    empresa = await _empresa(db_session)

    cliente = Cliente(
        empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Cliente Teste",
        email="cliente@teste.com", telefone="11999999999",
        inscricao_estadual="ISENTO", inscricao_municipal="123456",
        logradouro="Rua das Flores", numero="100", complemento="Ap 1",
        bairro="Centro", municipio_ibge="3550308", uf="SP", cep="01001000",
    )
    db_session.add(cliente)
    await db_session.commit()
    await db_session.refresh(cliente)

    assert cliente.ativo is True
    assert cliente.eh_padrao_csv is False
    assert cliente.cep == "01001000"


@pytest.mark.asyncio
async def test_cliente_permite_multiplos_com_cpf_cnpj_nulo_na_mesma_empresa(db_session):
    empresa = await _empresa(db_session)

    db_session.add(Cliente(empresa_id=empresa.id, nome="Sem documento 1"))
    db_session.add(Cliente(empresa_id=empresa.id, nome="Sem documento 2"))
    await db_session.commit()  # nao deve levantar


@pytest.mark.asyncio
async def test_cliente_rejeita_cpf_cnpj_duplicado_na_mesma_empresa(db_session):
    empresa = await _empresa(db_session)
    db_session.add(Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Um"))
    await db_session.commit()

    db_session.add(Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Outro"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_cliente_rejeita_segundo_padrao_csv_na_mesma_empresa(db_session):
    empresa = await _empresa(db_session)
    db_session.add(Cliente(empresa_id=empresa.id, nome="Padrao 1", eh_padrao_csv=True))
    await db_session.commit()

    db_session.add(Cliente(empresa_id=empresa.id, nome="Padrao 2", eh_padrao_csv=True))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_emissao_aceita_cliente_id_opcional(db_session):
    empresa = await _empresa(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Vinculado")
    db_session.add(cliente)
    await db_session.flush()

    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem", valor="10.00", competencia=datetime(2026, 8, 1).date(),
        cliente_id=cliente.id,
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)

    assert emissao.cliente_id == cliente.id
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_models_clientes.py -v`
Expected: FAIL — `Cliente` ainda não existe em `app.models`.

- [ ] **Step 3: Editar `app/models.py`**

Adicionar, depois da classe `Convite`:

```python
class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (
        Index(
            "ix_clientes_empresa_cpf_cnpj",
            "empresa_id", "cpf_cnpj",
            unique=True,
            postgresql_where=text("cpf_cnpj IS NOT NULL"),
        ),
        Index(
            "ix_clientes_empresa_padrao_csv",
            "empresa_id",
            unique=True,
            postgresql_where=text("eh_padrao_csv = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    nome: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str | None] = mapped_column(String(80), nullable=True)
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inscricao_estadual: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inscricao_municipal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    logradouro: Mapped[str | None] = mapped_column(String(200), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    complemento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(100), nullable=True)
    municipio_ibge: Mapped[str | None] = mapped_column(String(7), nullable=True)
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    eh_padrao_csv: Mapped[bool] = mapped_column(default=False, nullable=False)
    ativo: Mapped[bool] = mapped_column(default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_agora, onupdate=_agora, nullable=False
    )
```

Em `Emissao`, acrescentar (perto de `empresa_id`):

```python
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clientes.id"), nullable=True)
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_models_clientes.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Gerar e aplicar a migração**

```bash
alembic revision --autogenerate -m "clientes e vinculo com emissao"
alembic upgrade head
```

Abra o arquivo gerado e confirme que os dois índices parciais únicos
vieram como `op.create_index(..., unique=True, postgresql_where=sa.text(...))`
— o autogenerate do Alembic captura `postgresql_where` corretamente a
partir do `Index` do SQLAlchemy, sem edição manual necessária aqui
(diferente da Task 1 do plano anterior, que precisava de backfill de
dados — esta migração é só schema novo).

- [ ] **Step 6: Rodar a suíte inteira**

Run: `pytest -q`
Expected: PASS (mesma contagem de antes + 5 novos = 109)

- [ ] **Step 7: Commit**

```bash
git add app/models.py alembic/versions tests/test_models_clientes.py
git commit -m "feat: modelo de clientes, vinculado opcionalmente a emissoes"
```

---

### Task 3: CRUD de clientes

**Files:**
- Create: `app/routers/clientes.py`
- Modify: `app/schemas.py`, `app/main.py`, `tests/test_main_rotas_registradas.py`
- Test: `tests/test_clientes.py`

**Interfaces:**
- Consumes: Task 2's `Cliente`; `app.security.ContextoAutenticado`,
  `get_empresa_ativa`.
- Produces: `POST /api/clientes`, `GET /api/clientes`, `GET
  /api/clientes/{cliente_id}`, `PUT /api/clientes/{cliente_id}`.

- [ ] **Step 1: Acrescentar a `app/schemas.py`**

```python
class ClienteCriarIn(BaseModel):
    cpf_cnpj: str | None = Field(default=None, max_length=14)
    nome: str = Field(max_length=TAMANHO_NOME)
    email: str | None = Field(default=None, max_length=TAMANHO_EMAIL)
    telefone: str | None = Field(default=None, max_length=20)
    inscricao_estadual: str | None = Field(default=None, max_length=20)
    inscricao_municipal: str | None = Field(default=None, max_length=20)
    logradouro: str | None = Field(default=None, max_length=200)
    numero: str | None = Field(default=None, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str | None = Field(default=None, max_length=100)
    municipio_ibge: str | None = Field(default=None, max_length=7)
    uf: str | None = Field(default=None, max_length=2)
    cep: str | None = Field(default=None, max_length=8)

    @field_validator("cpf_cnpj")
    @classmethod
    def cpf_cnpj_valido(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        digitos = _somente_digitos(v)
        if len(digitos) not in (11, 14):
            raise ValueError("cpf_cnpj, quando informado, deve ter 11 (CPF) ou 14 (CNPJ) digitos")
        return digitos


class ClienteAtualizarIn(ClienteCriarIn):
    ativo: bool = True


class ClienteOut(BaseModel):
    id: uuid.UUID
    cpf_cnpj: str | None
    nome: str
    email: str | None
    telefone: str | None
    inscricao_estadual: str | None
    inscricao_municipal: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    municipio_ibge: str | None
    uf: str | None
    cep: str | None
    ativo: bool

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Escrever `tests/test_clientes.py`**

```python
import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Cliente
from tests.apoio import criar_empresa_e_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_criar_cliente_grava_dados_fiscais_completos(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/clientes",
                json={
                    "cpf_cnpj": "98765432100", "nome": "Cliente Um",
                    "logradouro": "Rua A", "numero": "10", "bairro": "Centro",
                    "municipio_ibge": "3550308", "uf": "SP", "cep": "01001000",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["cpf_cnpj"] == "98765432100"
        assert corpo["cep"] == "01001000"
        assert corpo["ativo"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_cliente_sem_documento_e_aceito(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/clientes", json={"nome": "Sem documento"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["cpf_cnpj"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_cliente_com_cpf_duplicado_devolve_409(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    db_session.add(Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Ja existe"))
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/clientes", json={"cpf_cnpj": "98765432100", "nome": "Duplicado"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_clientes_omite_o_padrao_csv_e_respeita_isolamento(db_session):
    empresa_a, token_a = await criar_empresa_e_token(db_session)
    empresa_b, _token_b = await criar_empresa_e_token(
        db_session, cnpj="99999999000199", email="op-b@teste.com",
    )
    db_session.add_all([
        Cliente(empresa_id=empresa_a.id, nome="Da empresa A"),
        Cliente(empresa_id=empresa_a.id, nome="Padrao CSV da A", eh_padrao_csv=True),
        Cliente(empresa_id=empresa_b.id, nome="Da empresa B"),
    ])
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/clientes", headers={"Authorization": f"Bearer {token_a}"}
            )
        nomes = {item["nome"] for item in resposta.json()}
        assert nomes == {"Da empresa A"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_atualizar_cliente_permite_inativar(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Original")
    db_session.add(cliente)
    await db_session.commit()
    await db_session.refresh(cliente)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                f"/api/clientes/{cliente.id}",
                json={"nome": "Original", "ativo": False},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_obter_cliente_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="88888888000188", email="op-c@teste.com",
    )
    cliente_de_a = Cliente(empresa_id=empresa_a.id, nome="Da A")
    db_session.add(cliente_de_a)
    await db_session.commit()
    await db_session.refresh(cliente_de_a)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/clientes/{cliente_de_a.id}", headers={"Authorization": f"Bearer {token_b}"}
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `pytest tests/test_clientes.py -v`
Expected: FAIL — `app.routers.clientes` não existe, 404 em toda rota.

- [ ] **Step 4: Escrever `app/routers/clientes.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Cliente
from app.schemas import ClienteAtualizarIn, ClienteCriarIn, ClienteOut
from app.security import ContextoAutenticado, get_empresa_ativa

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.post("", response_model=ClienteOut, status_code=201)
async def criar_cliente(
    dados: ClienteCriarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente = Cliente(empresa_id=contexto.empresa_id, **dados.model_dump())
    session.add(cliente)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Ja existe um cliente com esse CPF/CNPJ")
    await session.refresh(cliente)
    return cliente


@router.get("", response_model=list[ClienteOut])
async def listar_clientes(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[Cliente]:
    stmt = (
        select(Cliente)
        .where(Cliente.empresa_id == contexto.empresa_id, Cliente.eh_padrao_csv.is_(False))
        .order_by(Cliente.nome)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{cliente_id}", response_model=ClienteOut)
async def obter_cliente(
    cliente_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None or cliente.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    return cliente


@router.put("/{cliente_id}", response_model=ClienteOut)
async def atualizar_cliente(
    cliente_id: uuid.UUID,
    dados: ClienteAtualizarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None or cliente.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    for campo, valor in dados.model_dump().items():
        setattr(cliente, campo, valor)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Ja existe um cliente com esse CPF/CNPJ")
    await session.refresh(cliente)
    return cliente
```

- [ ] **Step 5: Registrar em `app/main.py`**

```python
from app.routers import auth, clientes, convites, dashboard, emissoes, webhook_stone

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router, prefix="/api")
app.include_router(convites.router, prefix="/api")
app.include_router(clientes.router, prefix="/api")
app.include_router(emissoes.router, prefix="/api")
app.include_router(webhook_stone.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
```

- [ ] **Step 6: Acrescentar as rotas novas a `tests/test_main_rotas_registradas.py`**

No conjunto `esperadas`, adicionar:

```python
        "/api/clientes",
        "/api/clientes/{cliente_id}",
```

- [ ] **Step 7: Rodar e confirmar sucesso**

Run: `pytest tests/test_clientes.py tests/test_main_rotas_registradas.py -v`
Expected: PASS (6 + 1 testes)

- [ ] **Step 8: Commit**

```bash
git add app/routers/clientes.py app/schemas.py app/main.py \
        tests/test_clientes.py tests/test_main_rotas_registradas.py
git commit -m "feat: CRUD de clientes"
```

---

### Task 4: Importação de CSV cria/reutiliza o cliente-padrão

**Files:**
- Modify: `app/routers/emissoes.py`
- Modify: `tests/test_emissoes_csv.py`

**Interfaces:**
- Consumes: Task 2's `Cliente`.
- Produces: `_obter_ou_criar_cliente_padrao_csv(session, empresa_id) ->
  Cliente` (helper interno de `app/routers/emissoes.py`).

- [ ] **Step 1: Acrescentar a `tests/test_emissoes_csv.py`**

```python
@pytest.mark.asyncio
async def test_confirmar_csv_vincula_cliente_padrao_e_reutiliza_entre_importacoes(db_session):
    from app.models import Cliente

    empresa, token = await _empresa_e_usuario(db_session)
    primeira = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago")
    segunda = _csv("Venda;30/07/2026 15:00:00;31163337249999;1;1;15,000000;Pago")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio1.csv", primeira, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio2.csv", segunda, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    clientes_padrao = (
        await db_session.execute(
            select(Cliente).where(Cliente.empresa_id == empresa.id, Cliente.eh_padrao_csv.is_(True))
        )
    ).scalars().all()
    assert len(clientes_padrao) == 1

    emissoes = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert len(emissoes) == 2
    assert {e.cliente_id for e in emissoes} == {clientes_padrao[0].id}
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_emissoes_csv.py::test_confirmar_csv_vincula_cliente_padrao_e_reutiliza_entre_importacoes -v`
Expected: FAIL — `emissao.cliente_id` fica `None`, `clientes_padrao` fica vazio.

- [ ] **Step 3: Editar `app/routers/emissoes.py`**

Acrescentar ao import: `from app.models import ..., Cliente` (juntar à
linha de import de `app.models` já existente).

Acrescentar, antes de `async def _processar_csv`:

```python
async def _obter_ou_criar_cliente_padrao_csv(session: AsyncSession, empresa_id: uuid.UUID) -> Cliente:
    cliente = (
        await session.execute(
            select(Cliente).where(Cliente.empresa_id == empresa_id, Cliente.eh_padrao_csv.is_(True))
        )
    ).scalar_one_or_none()
    if cliente is None:
        cliente = Cliente(
            empresa_id=empresa_id, nome="Cliente nao identificado (importacao CSV)",
            eh_padrao_csv=True,
        )
        session.add(cliente)
        await session.flush()
    return cliente
```

Dentro de `_processar_csv`, no bloco `if confirmar and notas_validas:`,
acrescentar a busca do cliente-padrão antes do `for` e usá-lo na criação
de cada `Emissao`:

```python
    if confirmar and notas_validas:
        empresa = await session.get(Empresa, contexto.empresa_id)
        cliente_padrao = await _obter_ou_criar_cliente_padrao_csv(session, contexto.empresa_id)
        for nota in notas_validas:
            serie, numero = await reservar_proximo_numero(session, contexto.empresa_id)
            emissao = Emissao(
                empresa_id=contexto.empresa_id,
                origem=OrigemEmissao.csv,
                stone_charge_id=nota.stone_charge_id,
                status=StatusEmissao.pendente,
                serie=serie,
                numero=numero,
                cliente_id=cliente_padrao.id,
                descricao=empresa.descricao_servico_padrao,
                valor=nota.valor,
                competencia=nota.data_da_venda.date().replace(day=1),
                criada_por_usuario_id=contexto.usuario.id,
            )
            session.add(emissao)
        await session.commit()
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_emissoes_csv.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add app/routers/emissoes.py tests/test_emissoes_csv.py
git commit -m "feat: importacao de CSV vincula emissoes ao cliente-padrao da empresa"
```

---

### Task 5: Extensão do DPS Builder — endereço do tomador

**Files:**
- Modify: `nfse_core/dps.py`
- Test: `tests/test_nfse_core_dps_end_tomador.py`

**Interfaces:**
- Produces: `DpsData` ganha `toma_end_logradouro`, `toma_end_numero`,
  `toma_end_complemento`, `toma_end_bairro`, `toma_end_municipio_ibge`,
  `toma_end_cep` (todos `str | None`, default `None`). `build_dps_xml`
  passa a montar `<toma><end><endNac>...` quando `toma_end_logradouro` e
  `toma_end_municipio_ibge` estão presentes.

- [ ] **Step 1: Escrever `tests/test_nfse_core_dps_end_tomador.py`**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from lxml import etree

from nfse_core import DpsData, build_dps_xml
from nfse_core.dps import NFSE_NS


def _dados_base(**overrides) -> DpsData:
    base = dict(
        tp_amb=2, dh_emi=datetime.now(timezone.utc), serie="1", numero=1,
        competencia=date(2026, 8, 1), prest_cnpj="12345678000199", prest_im="123456",
        c_loc_emi="1501402", op_simp_nac=3, toma_cpf_cnpj="98765432100",
        toma_nome="Cliente Teste", c_trib_nac="141001", x_desc_serv="Lavagem de roupa",
        v_serv=Decimal("49.90"),
    )
    base.update(overrides)
    return DpsData(**base)


def test_build_dps_xml_com_endereco_completo_monta_bloco_end():
    dados = _dados_base(
        toma_end_logradouro="Rua das Flores", toma_end_numero="100",
        toma_end_complemento="Ap 1", toma_end_bairro="Centro",
        toma_end_municipio_ibge="3550308", toma_end_cep="01001000",
    )

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    toma = root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma")
    end = toma.find(f"{{{NFSE_NS}}}end")
    assert end is not None
    assert end.find(f"{{{NFSE_NS}}}xLgr").text == "Rua das Flores"
    assert end.find(f"{{{NFSE_NS}}}nro").text == "100"
    assert end.find(f"{{{NFSE_NS}}}xCpl").text == "Ap 1"
    assert end.find(f"{{{NFSE_NS}}}xBairro").text == "Centro"
    end_nac = end.find(f"{{{NFSE_NS}}}endNac")
    assert end_nac.find(f"{{{NFSE_NS}}}cMun").text == "3550308"
    assert end_nac.find(f"{{{NFSE_NS}}}CEP").text == "01001000"


def test_build_dps_xml_sem_endereco_omite_bloco_end():
    dados = _dados_base()  # sem nenhum toma_end_*

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    toma = root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma")
    assert toma.find(f"{{{NFSE_NS}}}end") is None


def test_build_dps_xml_com_endereco_parcial_sem_municipio_omite_bloco_end():
    # logradouro sozinho, sem cLocEmi do tomador, nao e suficiente —
    # cMun e obrigatorio dentro de endNac quando o bloco existe.
    dados = _dados_base(toma_end_logradouro="Rua das Flores")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    toma = root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma")
    assert toma.find(f"{{{NFSE_NS}}}end") is None


def test_build_dps_xml_com_endereco_mas_sem_tomador_nao_monta_bloco_toma():
    # Documento do tomador continua opcional (Task 5 do plano anterior) —
    # endereco sem documento nao "inventa" um bloco <toma>.
    dados = _dados_base(toma_cpf_cnpj=None, toma_nome="", toma_end_logradouro="Rua X",
                         toma_end_municipio_ibge="3550308")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    assert root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma") is None
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_nfse_core_dps_end_tomador.py -v`
Expected: FAIL — `DpsData` não aceita `toma_end_logradouro` (`TypeError:
unexpected keyword argument`).

- [ ] **Step 3: Editar `nfse_core/dps.py`**

No dataclass `DpsData`, depois de `toma_email`:

```python
    toma_email: str | None = None
    # Endereco do tomador — nao presente no kit original; adicionado para
    # o cadastro de clientes poder submeter dados fiscais completos.
    # Estrutura <end><endNac> segue o padrao ABRASF/NFS-e Nacional para
    # endereco nacional (nao ha precedente no kit vendorizado para
    # confirmar contra — validar em homologacao antes de producao real).
    toma_end_logradouro: str | None = None
    toma_end_numero: str | None = None
    toma_end_complemento: str | None = None
    toma_end_bairro: str | None = None
    toma_end_municipio_ibge: str | None = None
    toma_end_cep: str | None = None
```

Em `build_dps_xml`, dentro do bloco `if toma_doc:` (logo depois do
`if data.toma_email:`):

```python
    if toma_doc:
        toma = _el(inf, "toma")
        _el(toma, "CPF" if len(toma_doc) == 11 else "CNPJ", toma_doc)
        _el(toma, "xNome", _sanitize_text(data.toma_nome)[:300])
        if data.toma_email:
            _el(toma, "email", data.toma_email.strip()[:80])
        if data.toma_end_logradouro and data.toma_end_municipio_ibge:
            end = _el(toma, "end")
            end_nac = _el(end, "endNac")
            _el(end_nac, "cMun", _digits(data.toma_end_municipio_ibge).zfill(7))
            if data.toma_end_cep:
                _el(end_nac, "CEP", _digits(data.toma_end_cep).zfill(8))
            _el(end, "xLgr", _sanitize_text(data.toma_end_logradouro)[:200])
            if data.toma_end_numero:
                _el(end, "nro", _sanitize_text(data.toma_end_numero)[:60])
            if data.toma_end_complemento:
                _el(end, "xCpl", _sanitize_text(data.toma_end_complemento)[:60])
            if data.toma_end_bairro:
                _el(end, "xBairro", _sanitize_text(data.toma_end_bairro)[:60])
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_nfse_core_dps_end_tomador.py tests/test_nfse_core_dps_tomador_opcional.py -v`
Expected: PASS (4 + 5 testes) — o arquivo existente de tomador opcional
continua passando, prova que a extensão não quebrou o comportamento atual.

- [ ] **Step 5: Commit**

```bash
git add nfse_core/dps.py tests/test_nfse_core_dps_end_tomador.py
git commit -m "feat: nfse_core/dps.py aceita endereco opcional do tomador"
```

---

### Task 6: Cancelamento — migração e endpoint

**Files:**
- Modify: `app/models.py`, `app/schemas.py`, `app/routers/emissoes.py`
- Create: `alembic/versions/<revisao>_cancelamento_de_nota.py`
- Create: `tests/test_emissoes_cancelamento.py`
- Modify: `tests/test_main_rotas_registradas.py`

**Interfaces:**
- Produces: `StatusEmissao.cancelamento_pendente`,
  `StatusEmissao.erro_cancelamento`. `Emissao.motivo_cancelamento: str |
  None`, `Emissao.cancelada_em: datetime | None`.
  `POST /api/emissoes/{emissao_id}/cancelar` (schema `CancelarEmissaoIn`:
  `motivo: str`, `codigo_motivo: Literal["1","2","9"]`).

- [ ] **Step 1: Escrever `tests/test_emissoes_cancelamento.py`**

```python
import functools
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, PapelUsuario, StatusEmissao
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


async def _empresa_titular_e_emissao_autorizada(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="1" * 50,
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return empresa, titular, emissao


@pytest.mark.asyncio
async def test_admin_cancela_emissao_autorizada(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao_autorizada(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/cancelar",
                json={"motivo": "Servico nao foi prestado", "codigo_motivo": "2"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "cancelamento_pendente"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_pendente
    assert emissao.motivo_cancelamento == "Servico nao foi prestado"


@pytest.mark.asyncio
async def test_operador_nao_pode_cancelar(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-cancelamento@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="2" * 50,
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/cancelar",
                json={"motivo": "Servico nao foi prestado", "codigo_motivo": "2"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cancelar_emissao_nao_autorizada_devolve_409(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/cancelar",
                json={"motivo": "Erro na emissao", "codigo_motivo": "1"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_emissoes_cancelamento.py -v`
Expected: FAIL — `StatusEmissao.cancelamento_pendente` não existe
(`AttributeError`) e a rota `/cancelar` não existe (404).

- [ ] **Step 3: Editar `app/models.py`**

Em `StatusEmissao`:

```python
class StatusEmissao(str, enum.Enum):
    pendente = "pendente"
    autorizada = "autorizada"
    rejeitada = "rejeitada"
    cancelada = "cancelada"
    cancelamento_pendente = "cancelamento_pendente"
    erro_cancelamento = "erro_cancelamento"
```

Em `Emissao`, depois de `atualizada_em`:

```python
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cancelada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Acrescentar a `app/schemas.py`**

```python
class CancelarEmissaoIn(BaseModel):
    motivo: str = Field(max_length=2000)
    codigo_motivo: str = "9"

    @field_validator("codigo_motivo")
    @classmethod
    def codigo_motivo_valido(cls, v: str) -> str:
        if v not in ("1", "2", "9"):
            raise ValueError("codigo_motivo deve ser 1 (erro na emissao), 2 (servico nao prestado) ou 9 (outros)")
        return v
```

- [ ] **Step 5: Editar `app/routers/emissoes.py`**

Acrescentar ao import de `app.schemas`: `CancelarEmissaoIn`.

Acrescentar, ao fim do arquivo:

```python
@router.post("/{emissao_id}/cancelar", response_model=EmissaoOut)
async def cancelar_emissao(
    emissao_id: uuid.UUID,
    dados: CancelarEmissaoIn,
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(
            status_code=409, detail=f"So e possivel cancelar uma emissao autorizada (status atual: {emissao.status})"
        )
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.motivo_cancelamento = dados.motivo
    await session.commit()
    await session.refresh(emissao)
    return emissao
```

Trocar o import de `app.security` (hoje só `ContextoAutenticado,
get_empresa_ativa`) para incluir `exigir_admin_empresa`:

```python
from app.security import ContextoAutenticado, exigir_admin_empresa, get_empresa_ativa
```

- [ ] **Step 6: Gerar e aplicar a migração**

```bash
alembic revision --autogenerate -m "cancelamento de nota"
alembic upgrade head
```

- [ ] **Step 7: Acrescentar a rota nova a `tests/test_main_rotas_registradas.py`**

No conjunto `esperadas`:

```python
        "/api/emissoes/{emissao_id}/cancelar",
```

- [ ] **Step 8: Rodar e confirmar sucesso**

Run: `pytest tests/test_emissoes_cancelamento.py tests/test_main_rotas_registradas.py -v`
Expected: PASS (3 + 1 testes)

- [ ] **Step 9: Commit**

```bash
git add app/models.py app/schemas.py app/routers/emissoes.py alembic/versions \
        tests/test_emissoes_cancelamento.py tests/test_main_rotas_registradas.py
git commit -m "feat: endpoint de cancelamento de nota (assincrono, via worker)"
```

---

### Task 7: Cancelamento — processamento assíncrono no worker

**Files:**
- Modify: `app/worker.py`
- Modify: `tests/test_worker.py`

**Interfaces:**
- Consumes: Task 6's `StatusEmissao.cancelamento_pendente/erro_cancelamento`,
  `Emissao.motivo_cancelamento/cancelada_em`; `nfse_core.EventoCancelamentoData`,
  `build_evento_cancelamento_xml`, `sign_evento`, `ler_resposta_evento`
  (todos já existem, nunca usados em `app/` até aqui).
- Produces: `processar_um_cancelamento_pendente(session, settings=None) ->
  bool` (mesma assinatura de `processar_uma_pendente`).

- [ ] **Step 1: Acrescentar a `tests/test_worker.py`**

```python
@pytest.mark.asyncio
async def test_processar_um_cancelamento_pendente_marca_cancelada_em_sucesso(db_session, monkeypatch):
    from datetime import date
    from decimal import Decimal

    from app.models import Emissao, OrigemEmissao, StatusEmissao
    import app.worker as worker_module

    emissao = await _empresa_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.chave_acesso = "1" * 50
    emissao.motivo_cancelamento = "Servico nao prestado"
    await db_session.commit()

    async def _registrar_evento_falso(self, chave_acesso, evento_xml_assinado):
        return {"_http_status": 200}

    monkeypatch.setattr(worker_module.SefinClient, "registrar_evento", _registrar_evento_falso)
    monkeypatch.setattr(
        worker_module, "ler_resposta_evento",
        lambda bruta: worker_module.RespostaEvento(registrado=True, http_status=200),
    )

    processou = await worker_module.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelada
    assert emissao.cancelada_em is not None


@pytest.mark.asyncio
async def test_processar_um_cancelamento_pendente_marca_erro_em_falha_de_transporte(db_session, monkeypatch):
    from app.models import StatusEmissao
    import app.worker as worker_module
    from nfse_core import SefinError

    emissao = await _empresa_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.chave_acesso = "1" * 50
    emissao.motivo_cancelamento = "Servico nao prestado"
    await db_session.commit()

    async def _registrar_evento_explodindo(self, chave_acesso, evento_xml_assinado):
        raise SefinError("falha de rede")

    monkeypatch.setattr(worker_module.SefinClient, "registrar_evento", _registrar_evento_explodindo)

    processou = await worker_module.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento


@pytest.mark.asyncio
async def test_processar_um_cancelamento_pendente_devolve_falso_quando_fila_vazia(db_session):
    import app.worker as worker_module

    processou = await worker_module.processar_um_cancelamento_pendente(db_session)

    assert processou is False
```

Note que `_empresa_e_emissao_pendente` (helper já existente neste
arquivo) cria a emissão como `status=StatusEmissao.pendente` — os dois
primeiros testes acima sobrescrevem para `cancelamento_pendente` logo
depois, reaproveitando a criação de empresa/certificado cifrado que o
helper já monta.

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_worker.py -v -k cancelamento`
Expected: FAIL — `app.worker` não tem `processar_um_cancelamento_pendente`
nem `SefinClient`/`ler_resposta_evento`/`RespostaEvento` importados no
módulo.

- [ ] **Step 3: Editar `app/worker.py`**

Trocar o import de `nfse_core` para incluir as peças de evento:

```python
from nfse_core import (
    CertificateError,
    EventoCancelamentoData,
    RespostaEvento,
    SefinClient,
    SefinError,
    build_dps_xml,
    build_evento_cancelamento_xml,
    ler_resposta_emissao,
    ler_resposta_evento,
    sign_dps,
    sign_evento,
)
```

Acrescentar, depois de `processar_uma_pendente`:

```python
async def _marcar_erro_cancelamento(session: AsyncSession, emissao: Emissao, codigo: str, titulo: str) -> None:
    emissao.status = StatusEmissao.erro_cancelamento
    emissao.erros = json.dumps([{"codigo": codigo, "titulo": titulo}], ensure_ascii=False)
    await session.commit()


async def processar_um_cancelamento_pendente(session: AsyncSession, settings: Settings | None = None) -> bool:
    """Processa uma emissao 'cancelamento_pendente' (se houver). Retorna True se processou.

    Espelha processar_uma_pendente: SELECT ... FOR UPDATE SKIP LOCKED,
    exceptions isoladas por linha (nunca derruba o loop inteiro).
    """
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.cancelamento_pendente)
        .order_by(Emissao.criada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)

    try:
        pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
        senha = (
            decifrar(empresa.certificado_senha_cifrada, settings.fernet_key)
            if empresa.certificado_senha_cifrada
            else None
        )

        evento_data = EventoCancelamentoData(
            chave_nfse=emissao.chave_acesso,
            tp_amb=1 if AmbienteEnum(empresa.ambiente) == AmbienteEnum.producao else 2,
            dh_evento=datetime.now(timezone.utc),
            autor_cpf_cnpj=empresa.cnpj,
            x_motivo=emissao.motivo_cancelamento or "",
        )
        xml_evento = build_evento_cancelamento_xml(evento_data)
        assinado = sign_evento(xml_evento, pfx_base64, senha)

        cliente = SefinClient(AmbienteEnum(empresa.ambiente).value, pfx_base64, senha)
        try:
            bruta = await cliente.registrar_evento(emissao.chave_acesso, assinado)
        finally:
            await cliente.close()
    except SefinError as exc:
        await _marcar_erro_cancelamento(session, emissao, "TRANSPORTE", str(exc))
        return True
    except (CertificateError, InvalidToken, ValueError) as exc:
        detalhe = str(exc) or (
            "certificado cifrado desta empresa nao pode ser decifrado com a "
            "FERNET_KEY atual (recadastre o certificado)"
        )
        await _marcar_erro_cancelamento(session, emissao, "CERTIFICADO_OU_DADOS", detalhe)
        return True

    resultado = ler_resposta_evento(bruta)
    if resultado.registrado:
        emissao.status = StatusEmissao.cancelada
        emissao.cancelada_em = datetime.now(timezone.utc)
    else:
        emissao.status = StatusEmissao.erro_cancelamento
        emissao.erros = json.dumps(resultado.erros, ensure_ascii=False)

    await session.commit()
    return True
```

Precisa também acrescentar `from datetime import datetime, timezone` ao
topo do arquivo (hoje `app/worker.py` não importa `datetime`).

Atualizar `loop_worker` para processar as duas filas a cada iteração:

```python
async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        try:
            async with session_factory() as session:
                processou_emissao = await processar_uma_pendente(session)
            async with session_factory() as session:
                processou_cancelamento = await processar_um_cancelamento_pendente(session)
        except Exception:
            logger.exception("falha inesperada ao processar fila pendente; o loop continua")
            processou_emissao = False
            processou_cancelamento = False
        if not processou_emissao and not processou_cancelamento:
            await asyncio.sleep(intervalo_segundos)
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (12 testes existentes + 3 novos = 15)

- [ ] **Step 5: Commit**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: worker processa cancelamentos pendentes, submetendo o evento a SEFIN"
```

---

### Task 8: `POST /api/empresas` — criação de empresa via API

**Files:**
- Create: `app/routers/empresas.py`
- Modify: `app/main.py`, `tests/test_main_rotas_registradas.py`
- Test: `tests/test_empresas_endpoint.py`

**Interfaces:**
- Consumes: `scripts.criar_empresa.criar_empresa` (já existe e já é
  importável — assinatura inalterada); `app.security.ContextoAutenticado`,
  `get_contexto_autenticado`.
- Produces: `POST /api/empresas` (multipart/form-data).

- [ ] **Step 1: Escrever `tests/test_empresas_endpoint.py`**

```python
import base64
import functools
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import Plano, Usuario


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


async def _yield_session(session):
    yield session


def _form_padrao(titular_email: str) -> dict:
    return {
        "cnpj": "12345678000199", "inscricao_municipal": "123456", "municipio_ibge": "3550308",
        "op_simp_nac": "3", "codigo_tributacao": "140106",
        "descricao_servico_padrao": "Servicos de lavagem de roupa", "ambiente": "homologacao",
        "senha_certificado": "senha123", "titular_email": titular_email,
    }


@pytest.mark.asyncio
async def test_titular_cria_a_propria_empresa_dentro_do_limite(db_session):
    from app.security import criar_token

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(email="titular@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)
    token = criar_token(titular)

    pfx_b64 = _pfx_teste_base64()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("titular@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["cnpj"] == "12345678000199"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usuario_comum_nao_pode_criar_empresa_para_outro_titular(db_session):
    from app.security import criar_token

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    usuario = Usuario(email="comum@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    outro_titular = Usuario(email="outro@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add_all([usuario, outro_titular])
    await db_session.commit()
    await db_session.refresh(usuario)
    token = criar_token(usuario)

    pfx_b64 = _pfx_teste_base64()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("outro@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_plataforma_cria_empresa_para_qualquer_titular(db_session):
    from app.security import criar_token

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    adm = Usuario(email="adm@plataforma.com", senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    titular = Usuario(email="titular2@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add_all([adm, titular])
    await db_session.commit()
    await db_session.refresh(adm)
    token = criar_token(adm)

    pfx_b64 = _pfx_teste_base64()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("titular2@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_titular_acima_do_limite_do_plano_devolve_422(db_session):
    from app.security import criar_token
    from scripts.criar_empresa import criar_empresa

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(email="no-limite@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)

    await criar_empresa(
        db_session, cnpj="99999999000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Primeira",
        ambiente="homologacao", pfx_base64=_pfx_teste_base64(), senha_certificado="senha123",
        webhook_token="token-1", titular_email="no-limite@teste.com",
    )
    token = criar_token(titular)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("no-limite@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(_pfx_teste_base64()), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_empresas_endpoint.py -v`
Expected: FAIL — `app.routers.empresas` não existe, 404 em toda rota.

- [ ] **Step 3: Escrever `app/routers/empresas.py`**

```python
import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.security import ContextoAutenticado, get_contexto_autenticado
from scripts.criar_empresa import criar_empresa

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.post("", status_code=201)
async def criar_empresa_via_api(
    cnpj: str = Form(...),
    inscricao_municipal: str = Form(...),
    municipio_ibge: str = Form(...),
    op_simp_nac: int = Form(...),
    codigo_tributacao: str = Form(...),
    descricao_servico_padrao: str = Form(...),
    ambiente: str = Form(...),
    senha_certificado: str = Form(...),
    titular_email: str = Form(...),
    pfx: UploadFile = File(...),
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> dict:
    if not contexto.eh_admin_plataforma and titular_email != contexto.usuario.email:
        raise HTTPException(status_code=403, detail="So e possivel criar empresa para si mesmo")

    pfx_bytes = await pfx.read()
    pfx_base64 = base64.b64encode(pfx_bytes).decode()

    try:
        empresa = await criar_empresa(
            session,
            cnpj=cnpj,
            inscricao_municipal=inscricao_municipal,
            municipio_ibge=municipio_ibge,
            op_simp_nac=op_simp_nac,
            codigo_tributacao=codigo_tributacao,
            descricao_servico_padrao=descricao_servico_padrao,
            ambiente=ambiente,
            pfx_base64=pfx_base64,
            senha_certificado=senha_certificado,
            webhook_token=base64.urlsafe_b64encode(cnpj.encode()).decode(),
            titular_email=titular_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "id": str(empresa.id), "cnpj": empresa.cnpj,
        "ambiente": empresa.ambiente if isinstance(empresa.ambiente, str) else empresa.ambiente.value,
    }
```

`webhook_token` é gerado a partir do CNPJ aqui só como valor não-vazio
determinístico para os testes — o webhook da Stone está fora de uso neste
momento (ver histórico do projeto); quando isso mudar, trocar por
`secrets.token_urlsafe(32)` como o CLI já faz.

- [ ] **Step 4: Registrar em `app/main.py`**

```python
from app.routers import auth, clientes, convites, dashboard, emissoes, empresas, webhook_stone

app.include_router(empresas.router, prefix="/api")
```

(acrescentar essa linha junto das outras `include_router`, em qualquer
posição — a ordem não importa para o roteamento)

- [ ] **Step 5: Acrescentar a rota nova a `tests/test_main_rotas_registradas.py`**

No conjunto `esperadas`:

```python
        "/api/empresas",
```

- [ ] **Step 6: Rodar e confirmar sucesso**

Run: `pytest tests/test_empresas_endpoint.py tests/test_main_rotas_registradas.py -v`
Expected: PASS (4 + 1 testes)

- [ ] **Step 7: Commit**

```bash
git add app/routers/empresas.py app/main.py \
        tests/test_empresas_endpoint.py tests/test_main_rotas_registradas.py
git commit -m "feat: criacao de empresa via API, reaproveitando scripts/criar_empresa.py"
```

---

### Task 9: Verificação final e README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Nenhuma interface nova — task de fechamento.

- [ ] **Step 1: Atualizar `README.md`**

Na seção "Rodando localmente", trocar a referência a caminhos de API sem
prefixo (`http://localhost:8000`) para deixar claro que agora é
`http://localhost:8000/api/...`:

```markdown
7. `uvicorn app.main:app --reload` — API em `http://localhost:8000/api`
   (rotas de negócio) e `http://localhost:8000/health` (health check, sem
   prefixo). O frontend (plano separado) espera exatamente esse prefixo.
```

No "Checklist antes da primeira nota real", acrescentar:

```markdown
- [ ] **Bloco `<end>` de endereço do tomador (`nfse_core/dps.py`) é uma
  extensão sem precedente no kit vendorizado** — precisa ser confirmado
  contra a documentação oficial ou um envio de teste em homologação antes
  de qualquer emissão real vir a usá-lo (hoje nada em `app/` o aciona
  ainda).
```

- [ ] **Step 2: Rodar a suíte completa uma última vez**

Run: `pytest -q`
Expected: PASS — todos os testes (104 do plano anterior + os novos deste
plano: 5 + 6 + 1 + 4 + 3 + 3 + 4 = 26 → total 130).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: atualiza README para o prefixo /api e o novo checklist de risco do endereco do tomador"
```

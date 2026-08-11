# Emissão automática de NFS-e via webhook Stone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o backend (API + worker + portal) que recebe pagamentos aprovados da Stone, emite a NFS-e Nacional automaticamente usando o `nfse_core` já existente, registra tudo em banco, e permite consulta, download e emissão manual pelo portal.

**Architecture:** FastAPI (API síncrona de recebimento + portal) + worker assíncrono de polling (processa emissões `pendente` chamando `nfse_core`) + PostgreSQL (fonte da verdade e do contador transacional de numeração). Multiempresa desde o modelo de dados. Ver spec completa em `docs/superpowers/specs/2026-08-11-nfse-stone-webhook-design.md`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async, driver `asyncpg`), Alembic, Pydantic v2 / pydantic-settings, `python-jose` (JWT), `bcrypt` (senha), `reportlab` (PDF fallback), PostgreSQL 16 (via Docker Compose), pytest + pytest-asyncio.

## Global Constraints

- `nfse_core/` (vendorizado neste repo a partir do kit) recebe **um único ajuste deliberado**, na Task 7: tornar o documento do tomador (`toma_cpf_cnpj`) opcional em `dps.py`, omitindo o bloco `toma` inteiro quando ausente em vez de levantar `ValueError`. Justificado por uma NFS-e real (Belém/PA, mesmo CNPJ/serviço) emitida com tomador "NÃO IDENTIFICADO" — ver spec, seção "Riscos e decisões em aberto". Fora desse ajuste pontual, nenhuma outra linha de `nfse_core/` muda nesta fase — qualquer outra alteração é tarefa separada, testada em homologação, seguindo a regra do próprio kit ("não simplifique sem reproduzir contra produção restrita" — `nfse-nacional-kit/nfse-nacional-kit/CLAUDE.md`).
- Ambiente da SEFIN é sempre `homologacao` até decisão explícita de trocar para `producao` (nunca hardcode `producao`) — o ajuste de tomador opcional acima **não foi validado contra a SEFIN real**, então essa regra vale com força redobrada até a primeira emissão limpa em homologação.
- PFX e senha do certificado nunca aparecem em log, mensagem de erro ou resposta HTTP. `.env` fica fora do git (`.gitignore` já existe no kit; o `.gitignore` da raiz do projeto precisa cobrir o mesmo).
- Toda emissão (webhook ou manual) grava um registro em `emissoes` **antes** de qualquer chamada à SEFIN.
- Numeração é sempre obtida via `UPDATE ... RETURNING` transacional (`reservar_proximo_numero`) — nunca `max(numero) + 1`.
- Todo endpoint autenticado escopa dados pelo `empresa_id` do usuário logado (nunca por um `empresa_id` recebido do cliente) — evita um usuário de uma empresa ver dados de outra.
- Documento do tomador (CPF/CNPJ) é **opcional** em toda a cadeia — modelo, adaptador, emissão manual e webhook. Nome do tomador é gravado quando disponível, mas não bloqueia a emissão sozinho.

---

## Estrutura de arquivos

```
NotaFiscal/
  nfse_core/                       # copia de nfse-nacional-kit/nfse-nacional-kit/nfse_core,
                                    # com um ajuste pontual em dps.py (Task 7 — tomador opcional)
  app/
    __init__.py
    config.py                      # Settings (pydantic-settings)
    db.py                          # engine/session async + get_db()
    models.py                      # Base, enums, Empresa, Usuario, Emissao
    schemas.py                     # Pydantic: EmissaoOut, EmissaoManualIn, TokenOut
    crypto.py                      # cifrar/decifrar (Fernet), hash_senha/verificar_senha (bcrypt)
    security.py                    # criar_token, get_current_user, get_current_admin
    numeracao.py                   # reservar_proximo_numero
    adapters/
      __init__.py
      dps_builder.py                # DadosEmissao, montar_dps_data
      stone.py                      # StoneChargePaidEvent, parse_stone_charge_paid
    routers/
      __init__.py
      auth.py                       # POST /auth/login
      usuarios.py                   # POST /usuarios (admin cria operador na própria empresa)
      webhook_stone.py              # POST /webhooks/stone/{empresa_id}
      emissoes.py                   # POST /emissoes/manual,
                                     # GET /emissoes, GET /emissoes/{id}/xml, GET /emissoes/{id}/pdf
      dashboard.py                  # GET /dashboard
    worker.py                       # processar_uma_pendente, loop_worker
    danfe.py                        # gerar_danfse_fallback
    main.py                         # monta o FastAPI app com os routers
  scripts/
    criar_empresa.py                # bootstrap: cadastra 1ª empresa + admin (fora da API)
  alembic/
    env.py
    versions/
  alembic.ini
  tests/
    conftest.py
    test_health.py
    test_models_migration.py
    test_crypto.py
    test_criar_empresa.py
    test_auth.py
    test_numeracao.py
    test_nfse_core_dps_tomador_opcional.py
    test_adapters_dps_builder.py
    test_adapters_stone.py
    test_emissoes_manual.py
    test_webhook_stone.py
    test_worker.py
    test_danfe.py
    test_emissoes_download.py
    test_dashboard.py
    test_main_rotas_registradas.py
  docker-compose.yml
  requirements.txt
  requirements-dev.txt
  .env.example
  .gitignore
  README.md
```

---

### Task 1: Scaffolding do projeto (config, banco, health-check)

**Files:**
- Create: `docker-compose.yml`, `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.gitignore`
- Create: `app/__init__.py`, `app/config.py`, `app/db.py`, `app/main.py`
- Create: `nfse_core/` (cópia de `nfse-nacional-kit/nfse-nacional-kit/nfse_core/`)
- Test: `tests/conftest.py`, `tests/test_health.py`

**Interfaces:**
- Produces: `app.config.get_settings() -> Settings` (campos: `database_url: str`, `database_url_test: str`, `fernet_key: str`, `jwt_secret: str`, `jwt_ttl_horas: int`). `app.db.get_db()` (async generator de `AsyncSession`). `app.db.engine`, `app.db.SessionLocal`. `app.main.app` (instância FastAPI).

- [ ] **Step 1: Copiar o núcleo fiscal para dentro do projeto**

```bash
cp -r "nfse-nacional-kit/nfse-nacional-kit/nfse_core" "nfse_core"
```

Confirme que `nfse_core/__init__.py` existe na raiz do projeto depois de copiar. Este diretório não é editado por nenhuma task deste plano.

- [ ] **Step 2: Criar `requirements.txt`**

```
fastapi>=0.139.0
uvicorn[standard]>=0.47.0
sqlalchemy>=2.0.51
asyncpg>=0.31.0
alembic>=1.18.5
pydantic>=2.13.4
pydantic-settings>=2.14.2
python-jose[cryptography]>=3.5.0
bcrypt>=5.0.0
python-multipart>=0.0.29
reportlab>=4.2.0
lxml>=5.2.0
cryptography>=42.0
httpx>=0.27.0
```

- [ ] **Step 3: Criar `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.4.2
pytest-asyncio>=1.4.0
pypdf>=5.0.0
```

- [ ] **Step 4: Instalar dependências**

```bash
pip install -r requirements-dev.txt
```

- [ ] **Step 5: Criar `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: nfse
      POSTGRES_PASSWORD: nfse
      POSTGRES_DB: nfse
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```

- [ ] **Step 6: Subir o Postgres e criar o banco de teste**

```bash
docker compose up -d db
docker compose exec db psql -U nfse -d nfse -c "CREATE DATABASE nfse_test;"
```

- [ ] **Step 7: Criar `.env.example`**

```
DATABASE_URL=postgresql+asyncpg://nfse:nfse@localhost:5432/nfse
DATABASE_URL_TEST=postgresql+asyncpg://nfse:nfse@localhost:5432/nfse_test
FERNET_KEY=
JWT_SECRET=
JWT_TTL_HORAS=8
```

Gere `FERNET_KEY` com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` e `JWT_SECRET` com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Copie para `.env` (não commitado) preenchido.

- [ ] **Step 8: Criar `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
*.pfx
*.pem
*.b64.txt
```

- [ ] **Step 9: Criar `app/__init__.py`** (vazio)

- [ ] **Step 10: Criar `app/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_test: str = ""
    fernet_key: str
    jwt_secret: str
    jwt_ttl_horas: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 11: Criar `app/db.py`**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 12: Criar `app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="NFS-e Automatizada")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 13: Criar `tests/conftest.py`** (fixtures reaproveitadas pelas próximas tasks)

```python
import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nfse:nfse@localhost:5432/nfse")
os.environ.setdefault("DATABASE_URL_TEST", "postgresql+asyncpg://nfse:nfse@localhost:5432/nfse_test")
os.environ.setdefault("FERNET_KEY", "zH9m1yv3xVvV8v0T6t3s9m2m9m2m9m2m9m2m9m2m9m0=")
os.environ.setdefault("JWT_SECRET", "test-secret-nao-use-em-producao")

from app.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url_test)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory():
    settings = get_settings()
    engine = create_async_engine(settings.database_url_test)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()
```

A fixture `FERNET_KEY` de teste acima é uma chave Fernet válida fixa (32 bytes urlsafe-base64) só para os testes — nunca a mesma do `.env` real. `db_session` recria o schema do zero a cada teste que a usa (`drop_all`/`create_all`), então testes não vazam estado um para o outro. `db_session_factory` existe para testes que precisam abrir várias sessões concorrentes (numeração, worker).

Este `conftest.py` importa `app.models.Base`, que só existe a partir da Task 2 — normal que `test_health.py` (Step 14) seja o único teste executável até lá.

- [ ] **Step 14: Criar `tests/test_health.py`**

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_retorna_ok():
    client = TestClient(app)
    resposta = client.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
```

- [ ] **Step 15: Rodar o teste de health (não depende de banco)**

Run: `pytest tests/test_health.py -v`
Expected: PASS (o `conftest.py` só é totalmente exercitado a partir da Task 2, mas o import de `app.models` nele já precisa existir — crie um `app/models.py` vazio com `from sqlalchemy.orm import DeclarativeBase` e `class Base(DeclarativeBase): pass` só para este teste passar; a Task 2 substitui esse arquivo pelo conteúdo completo).

- [ ] **Step 16: Commit**

```bash
git add nfse_core app requirements.txt requirements-dev.txt docker-compose.yml .env.example .gitignore tests/conftest.py tests/test_health.py
git commit -m "feat: scaffolding do projeto (fastapi, config, docker compose, nfse_core vendorizado)"
```

---

### Task 2: Modelos de dados e migração (Empresa, Usuario, Emissao)

**Files:**
- Modify: `app/models.py` (conteúdo completo, substitui o placeholder da Task 1)
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`
- Test: `tests/test_models_migration.py`

**Interfaces:**
- Consumes: nada de tasks anteriores além de `app.db`.
- Produces: `app.models.Base`, `app.models.AmbienteEnum`, `app.models.StatusEmissao`, `app.models.OrigemEmissao`, `app.models.PapelUsuario`, `app.models.Empresa`, `app.models.Usuario`, `app.models.Emissao` — campos usados por todas as tasks seguintes:
  - `Empresa`: `id (uuid.UUID)`, `cnpj (str)`, `inscricao_municipal (str)`, `municipio_ibge (str)`, `op_simp_nac (int)`, `codigo_tributacao (str)`, `descricao_servico_padrao (str)`, `ambiente (AmbienteEnum)`, `serie (str)`, `proximo_numero (int)`, `certificado_pfx_cifrado (str)`, `certificado_senha_cifrada (str | None)`, `certificado_valido_ate (datetime)`, `webhook_token_hash (str)`, `criada_em (datetime)`.
  - `Usuario`: `id (uuid.UUID)`, `empresa_id (uuid.UUID)`, `email (str)`, `senha_hash (str)`, `papel (PapelUsuario)`, `criado_em (datetime)`.
  - `Emissao`: `id (uuid.UUID)`, `empresa_id (uuid.UUID)`, `origem (OrigemEmissao)`, `stone_charge_id (str | None)`, `status (StatusEmissao)`, `serie (str | None)`, `numero (int | None)`, `dps_id (str | None)`, `chave_acesso (str | None)`, `xml_dps (bytes | None)`, `xml_nfse (bytes | None)`, `erros (str | None)`, `tomador_cpf_cnpj (str | None)`, `tomador_nome (str | None)`, `tomador_email (str | None)`, `descricao (str)`, `valor (Decimal)`, `competencia (date)`, `criada_por_usuario_id (uuid.UUID | None)`, `criada_em (datetime)`, `atualizada_em (datetime)`.

- [ ] **Step 1: Escrever `app/models.py`**

```python
import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class AmbienteEnum(str, enum.Enum):
    homologacao = "homologacao"
    producao = "producao"


class StatusEmissao(str, enum.Enum):
    pendente = "pendente"
    autorizada = "autorizada"
    rejeitada = "rejeitada"
    cancelada = "cancelada"


class OrigemEmissao(str, enum.Enum):
    webhook = "webhook"
    manual = "manual"


class PapelUsuario(str, enum.Enum):
    admin = "admin"
    operador = "operador"


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
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="empresa")
    emissoes: Mapped[list["Emissao"]] = relationship(back_populates="empresa")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    papel: Mapped[PapelUsuario] = mapped_column(String(20), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    empresa: Mapped["Empresa"] = relationship(back_populates="usuarios")


class Emissao(Base):
    __tablename__ = "emissoes"
    __table_args__ = (
        Index(
            "ix_emissoes_empresa_stone_charge_id",
            "empresa_id", "stone_charge_id",
            unique=True,
            postgresql_where=text("stone_charge_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    origem: Mapped[OrigemEmissao] = mapped_column(String(20), nullable=False)
    stone_charge_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[StatusEmissao] = mapped_column(String(30), nullable=False)
    serie: Mapped[str | None] = mapped_column(String(5), nullable=True)
    numero: Mapped[int | None] = mapped_column(nullable=True)
    dps_id: Mapped[str | None] = mapped_column(String(45), nullable=True)
    chave_acesso: Mapped[str | None] = mapped_column(String(50), nullable=True)
    xml_dps: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    xml_nfse: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    erros: Mapped[str | None] = mapped_column(Text, nullable=True)
    tomador_cpf_cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    tomador_nome: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tomador_email: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descricao: Mapped[str] = mapped_column(String(2000), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    competencia: Mapped[date] = mapped_column(Date, nullable=False)
    criada_por_usuario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_agora, onupdate=_agora, nullable=False
    )

    empresa: Mapped["Empresa"] = relationship(back_populates="emissoes")
```

- [ ] **Step 2: Inicializar Alembic**

```bash
alembic init alembic
```

- [ ] **Step 3: Editar `alembic.ini`**

Trocar a linha `sqlalchemy.url = driver://user:pass@localhost/dbname` para vazio (`sqlalchemy.url =`) — a URL real vem de `app.config` dentro de `alembic/env.py`, não do ini.

- [ ] **Step 4: Editar `alembic/env.py`**

No topo do arquivo, após os imports existentes do Alembic, adicionar:

```python
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)
```

Substituir a função `run_migrations_online` gerada pelo template por:

```python
from sqlalchemy.ext.asyncio import create_async_engine


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())
```

- [ ] **Step 5: Gerar e aplicar a migração**

```bash
alembic revision --autogenerate -m "cria empresas, usuarios, emissoes"
alembic upgrade head
```

- [ ] **Step 6: Escrever `tests/test_models_migration.py`**

```python
import subprocess

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


def test_alembic_upgrade_cria_todas_as_tabelas():
    settings = get_settings()
    subprocess.run(
        ["alembic", "-x", f"db_url={settings.database_url_test}", "upgrade", "head"],
        check=True,
        env={"DATABASE_URL": settings.database_url_test, **__import__("os").environ},
    )
    engine = create_async_engine(settings.database_url_test)

    async def _tabelas():
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    import asyncio

    nomes = asyncio.get_event_loop().run_until_complete(_tabelas())
    assert {"empresas", "usuarios", "emissoes"}.issubset(set(nomes))
```

Este teste roda `alembic upgrade head` apontando para `DATABASE_URL_TEST` (via variável de ambiente, que `app/config.py` já lê) e confirma que as três tabelas existem — é o único teste deste plano que valida a migração de verdade; as demais tasks usam `db_session`/`db_session_factory` do `conftest.py`, que criam o schema direto do `Base.metadata` (mais rápido, não depende do Alembic estar em dia).

- [ ] **Step 7: Rodar o teste**

Run: `pytest tests/test_models_migration.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/models.py alembic alembic.ini tests/test_models_migration.py
git commit -m "feat: modelos de dados (empresas, usuarios, emissoes) e migração inicial"
```

---

### Task 3: Criptografia (certificado e senha)

**Files:**
- Create: `app/crypto.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Consumes: `app.config.Settings.fernet_key`.
- Produces: `cifrar(valor: str, chave: str) -> str`, `decifrar(token: str, chave: str) -> str`, `hash_senha(senha: str) -> str`, `verificar_senha(senha: str, hash_: str) -> bool`.

- [ ] **Step 1: Escrever o teste**

```python
import pytest
from cryptography.fernet import Fernet

from app.crypto import cifrar, decifrar, hash_senha, verificar_senha


def test_cifrar_decifrar_recupera_valor_original():
    chave = Fernet.generate_key().decode()
    token = cifrar("conteudo-secreto", chave)
    assert token != "conteudo-secreto"
    assert decifrar(token, chave) == "conteudo-secreto"


def test_hash_senha_verifica_correta_e_rejeita_errada():
    hash_ = hash_senha("minha-senha-forte")
    assert verificar_senha("minha-senha-forte", hash_)
    assert not verificar_senha("senha-errada", hash_)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_crypto.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.crypto'`

- [ ] **Step 3: Implementar `app/crypto.py`**

```python
import bcrypt
from cryptography.fernet import Fernet


def cifrar(valor: str, chave: str) -> str:
    return Fernet(chave.encode()).encrypt(valor.encode()).decode()


def decifrar(token: str, chave: str) -> str:
    return Fernet(chave.encode()).decrypt(token.encode()).decode()


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def verificar_senha(senha: str, hash_: str) -> bool:
    return bcrypt.checkpw(senha.encode(), hash_.encode())
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_crypto.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/crypto.py tests/test_crypto.py
git commit -m "feat: criptografia de certificado (Fernet) e senha (bcrypt)"
```

---

### Task 4: Cadastro de empresa (script de bootstrap)

**Files:**
- Create: `scripts/__init__.py`, `scripts/criar_empresa.py`
- Test: `tests/test_criar_empresa.py`

**Interfaces:**
- Consumes: `nfse_core.inspecionar`, `nfse_core.conferir_titularidade`, `nfse_core.CertificateError`, `app.crypto.cifrar`, `app.crypto.hash_senha`, `app.models.Empresa`, `app.models.Usuario`, `app.models.PapelUsuario`.
- Produces: `scripts.criar_empresa.criar_empresa(session, *, cnpj, inscricao_municipal, municipio_ibge, op_simp_nac, codigo_tributacao, descricao_servico_padrao, ambiente, pfx_base64, senha_certificado, webhook_token, admin_email, admin_senha) -> Empresa`. Usado pelo script CLI e reutilizável em testes/futuras rotas administrativas.

Este script é a forma de cadastrar uma empresa (e seu primeiro usuário admin) **fora** da API — não existe endpoint público de auto-cadastro (fora de escopo da spec). Quem roda é o operador do sistema, com o `.pfx` em mãos.

- [ ] **Step 1: Escrever o teste**

```python
import base64
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.models import Empresa, PapelUsuario, Usuario
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


@pytest.mark.asyncio
async def test_criar_empresa_grava_empresa_e_admin_cifrando_certificado(db_session):
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
        admin_email="admin@empresa-teste.com",
        admin_senha="senha-forte-123",
    )

    assert empresa.cnpj == "12345678000199"
    assert empresa.certificado_pfx_cifrado != pfx_b64  # nunca em claro
    assert empresa.certificado_valido_ate.date() > date.today()

    admin = (
        await db_session.execute(select(Usuario).where(Usuario.empresa_id == empresa.id))
    ).scalar_one()
    assert admin.email == "admin@empresa-teste.com"
    assert admin.papel == PapelUsuario.admin
    assert admin.senha_hash != "senha-forte-123"


@pytest.mark.asyncio
async def test_criar_empresa_rejeita_certificado_de_cnpj_diferente(db_session, capsys):
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
            admin_email="admin@empresa-teste.com",
            admin_senha="senha-forte-123",
        )
```

Adicionar `pytest-asyncio` em modo automático: criar/editar `pytest.ini` na raiz com:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_criar_empresa.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'scripts.criar_empresa'`

- [ ] **Step 3: Implementar `scripts/__init__.py`** (vazio)

- [ ] **Step 4: Implementar `scripts/criar_empresa.py`**

```python
"""Bootstrap de uma empresa (fora da API — roda por quem tem o .pfx em mãos).

Uso:
    python scripts/criar_empresa.py --cnpj 12345678000199 --im 123456 \
        --municipio 3550308 --regime 3 --cod-tributacao 140106 \
        --descricao "Servicos de lavagem de roupa" --ambiente homologacao \
        --pfx caminho/certificado.pfx --senha-certificado "..." \
        --admin-email admin@empresa.com --admin-senha "..."
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import cifrar, hash_senha
from app.db import SessionLocal
from app.models import AmbienteEnum, Empresa, PapelUsuario, Usuario
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
    admin_email: str,
    admin_senha: str,
) -> Empresa:
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
    )
    session.add(empresa)
    await session.flush()

    admin = Usuario(
        empresa_id=empresa.id,
        email=admin_email,
        senha_hash=hash_senha(admin_senha),
        papel=PapelUsuario.admin,
    )
    session.add(admin)
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
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-senha", required=True)
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
            admin_email=args.admin_email,
            admin_senha=args.admin_senha,
        )

    print(f"Empresa criada: {empresa.id} (CNPJ {empresa.cnpj})")
    if not args.webhook_token:
        print(f"Token do webhook (guarde, so aparece agora): {webhook_token}")
        print(f"URL do webhook na Stone: /webhooks/stone/{empresa.id}")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 5: Rodar e confirmar sucesso**

Run: `pytest tests/test_criar_empresa.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts pytest.ini tests/test_criar_empresa.py
git commit -m "feat: script de bootstrap de empresa com validacao de certificado A1"
```

---

### Task 5: Autenticação (login, JWT, criação de usuário operador)

**Files:**
- Create: `app/security.py`, `app/schemas.py` (parte de auth), `app/routers/__init__.py`, `app/routers/auth.py`, `app/routers/usuarios.py`
- Modify: `app/main.py` (registra os routers)
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `app.crypto.verificar_senha`, `app.crypto.hash_senha`, `app.models.Usuario`, `app.models.PapelUsuario`, `app.db.get_db`.
- Produces: `app.security.criar_token(usuario: Usuario) -> str`, `app.security.get_current_user` (dependency, retorna `Usuario`), `app.security.exigir_admin` (dependency, retorna `Usuario` ou 403). Router `auth.router` (`POST /auth/login`), router `usuarios.router` (`POST /usuarios`).

- [ ] **Step 1: Escrever `app/schemas.py`** (início do arquivo — outras tasks acrescentam schemas aqui)

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, field_validator


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioCriarIn(BaseModel):
    email: EmailStr
    senha: str
    papel: str = "operador"

    @field_validator("senha")
    @classmethod
    def senha_minima(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("senha precisa ter ao menos 8 caracteres")
        return v

    @field_validator("papel")
    @classmethod
    def papel_valido(cls, v: str) -> str:
        if v not in ("admin", "operador"):
            raise ValueError("papel deve ser admin ou operador")
        return v


class UsuarioOut(BaseModel):
    id: uuid.UUID
    email: str
    papel: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Escrever `app/security.py`**

```python
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import PapelUsuario, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def criar_token(usuario: Usuario, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": str(usuario.id),
        "empresa_id": str(usuario.empresa_id),
        "papel": usuario.papel.value,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_horas),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Usuario:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        usuario_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token invalido ou expirado")
    usuario = await session.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario nao encontrado")
    return usuario


async def exigir_admin(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    if usuario.papel != PapelUsuario.admin:
        raise HTTPException(status_code=403, detail="Somente administradores")
    return usuario
```

- [ ] **Step 3: Escrever `app/routers/__init__.py`** (vazio)

- [ ] **Step 4: Escrever `app/routers/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import verificar_senha
from app.db import get_db
from app.models import Usuario
from app.schemas import TokenOut
from app.security import criar_token

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
    return TokenOut(access_token=criar_token(usuario))
```

- [ ] **Step 5: Escrever `app/routers/usuarios.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import hash_senha
from app.db import get_db
from app.models import PapelUsuario, Usuario
from app.schemas import UsuarioCriarIn, UsuarioOut
from app.security import exigir_admin

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.post("", response_model=UsuarioOut, status_code=201)
async def criar_usuario(
    dados: UsuarioCriarIn,
    admin: Usuario = Depends(exigir_admin),
    session: AsyncSession = Depends(get_db),
) -> Usuario:
    usuario = Usuario(
        empresa_id=admin.empresa_id,
        email=dados.email,
        senha_hash=hash_senha(dados.senha),
        papel=PapelUsuario(dados.papel),
    )
    session.add(usuario)
    await session.commit()
    await session.refresh(usuario)
    return usuario
```

- [ ] **Step 6: Registrar os routers em `app/main.py`**

```python
from fastapi import FastAPI

from app.routers import auth, usuarios

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router)
app.include_router(usuarios.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 7: Escrever `tests/test_auth.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import Empresa, PapelUsuario, Usuario
from app.security import criar_token
from datetime import datetime, timezone


async def _empresa_minima(db_session) -> Empresa:
    from app.models import AmbienteEnum

    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    return empresa


@pytest.mark.asyncio
async def test_login_com_credenciais_corretas_devolve_token(db_session):
    empresa = await _empresa_minima(db_session)
    usuario = Usuario(
        empresa_id=empresa.id, email="admin@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(usuario)
    await db_session.commit()

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login", data={"username": "admin@teste.com", "password": "senha-forte-123"}
            )
        assert resposta.status_code == 200
        assert "access_token" in resposta.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_senha_errada_devolve_401(db_session):
    empresa = await _empresa_minima(db_session)
    usuario = Usuario(
        empresa_id=empresa.id, email="admin2@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(usuario)
    await db_session.commit()

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
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
async def test_admin_cria_operador_na_propria_empresa(db_session):
    empresa = await _empresa_minima(db_session)
    admin = Usuario(
        empresa_id=empresa.id, email="admin3@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/usuarios",
                json={"email": "operador@teste.com", "senha": "outra-senha-123", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["papel"] == "operador"
    finally:
        app.dependency_overrides.clear()


async def _yield_session(session):
    yield session
```

- [ ] **Step 8: Rodar e confirmar falha**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL (módulos `app.security`/`app.routers.auth` ainda não existem quando o teste é escrito antes deles — se seguindo TDD estrito, escreva o teste primeiro; a ordem acima já entrega a implementação junto por clareza de leitura do plano, então rode o teste logo após o Step 6 para validar)

- [ ] **Step 9: Rodar e confirmar sucesso**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (3 testes)

- [ ] **Step 10: Commit**

```bash
git add app/security.py app/schemas.py app/routers app/main.py tests/test_auth.py
git commit -m "feat: autenticacao JWT e criacao de usuario operador por admin"
```

---

### Task 6: Numeração transacional

**Files:**
- Create: `app/numeracao.py`
- Test: `tests/test_numeracao.py`

**Interfaces:**
- Consumes: `app.models.Empresa`.
- Produces: `async def reservar_proximo_numero(session: AsyncSession, empresa_id: uuid.UUID) -> tuple[str, int]` (retorna `(serie, numero)`).

- [ ] **Step 1: Escrever o teste**

```python
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import AmbienteEnum, Empresa
from app.numeracao import reservar_proximo_numero


async def _criar_empresa(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        empresa = Empresa(
            cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
            op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
            ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
            certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
            webhook_token_hash="x",
        )
        session.add(empresa)
        await session.commit()
        return empresa.id


@pytest.mark.asyncio
async def test_reservar_proximo_numero_avanca_sequencialmente(db_session_factory):
    empresa_id = await _criar_empresa(db_session_factory)
    async with db_session_factory() as session:
        serie1, numero1 = await reservar_proximo_numero(session, empresa_id)
        await session.commit()
        serie2, numero2 = await reservar_proximo_numero(session, empresa_id)
        await session.commit()

    assert serie1 == serie2 == "1"
    assert numero2 == numero1 + 1


@pytest.mark.asyncio
async def test_reservar_proximo_numero_e_seguro_sob_concorrencia(db_session_factory):
    empresa_id = await _criar_empresa(db_session_factory)

    async def _reservar_em_sessao_propria() -> int:
        async with db_session_factory() as session:
            _serie, numero = await reservar_proximo_numero(session, empresa_id)
            await session.commit()
            return numero

    resultados = await asyncio.gather(*[_reservar_em_sessao_propria() for _ in range(20)])

    assert len(set(resultados)) == 20  # nenhum numero duplicado
    assert sorted(resultados) == list(range(1, 21))  # sem buracos, sequencial
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_numeracao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.numeracao'`

- [ ] **Step 3: Implementar `app/numeracao.py`**

```python
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Empresa


async def reservar_proximo_numero(session: AsyncSession, empresa_id: uuid.UUID) -> tuple[str, int]:
    """Reserva o proximo numero de forma transacional (UPDATE ... RETURNING).

    O caller deve commitar a transacao logo em seguida. Duas chamadas
    concorrentes na mesma empresa serializam pela trava de linha que o
    UPDATE adquire — nunca leem o mesmo proximo_numero.
    """
    stmt = (
        update(Empresa)
        .where(Empresa.id == empresa_id)
        .values(proximo_numero=Empresa.proximo_numero + 1)
        .returning(Empresa.serie, Empresa.proximo_numero)
    )
    resultado = await session.execute(stmt)
    serie, proximo_numero_apos = resultado.one()
    return serie, proximo_numero_apos - 1
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_numeracao.py -v`
Expected: PASS (2 testes — o de concorrência é o que prova a garantia mais importante da spec)

- [ ] **Step 5: Commit**

```bash
git add app/numeracao.py tests/test_numeracao.py
git commit -m "feat: numeracao transacional de emissoes (UPDATE...RETURNING)"
```

---

### Task 7: Tomador opcional no núcleo fiscal + adaptador comum de DPS

Esta task tem duas partes: primeiro um ajuste cirúrgico em `nfse_core/dps.py`
(o único ponto do núcleo fiscal vendorizado que este plano modifica — ver
Global Constraints), depois o adaptador que usa esse núcleo. O ajuste é
necessário porque o adaptador precisa poder montar uma `DpsData` sem
documento do tomador (webhook da Stone não traz CPF/CNPJ do cliente, e há
evidência real de que a SEFIN aceita isso para este serviço/município — ver
spec).

**Files:**
- Modify: `nfse_core/dps.py`
- Create: `app/adapters/__init__.py`, `app/adapters/dps_builder.py`
- Test: `tests/test_nfse_core_dps_tomador_opcional.py`, `tests/test_adapters_dps_builder.py`

**Interfaces:**
- Consumes: `nfse_core.DpsData`, `nfse_core.build_dps_xml`, `app.models.Empresa`, `app.models.AmbienteEnum`.
- Produces: `DadosEmissao` (dataclass: `tomador_cpf_cnpj: str | None`, `tomador_nome: str | None`, `tomador_email: str | None`, `descricao: str`, `valor: Decimal`, `competencia: date`), `montar_dps_data(empresa: Empresa, serie: str, numero: int, dados: DadosEmissao) -> DpsData`. `nfse_core.build_dps_xml` passa a aceitar `DpsData.toma_cpf_cnpj` vazio/`None` sem levantar `ValueError`.

- [ ] **Step 1: Escrever `tests/test_nfse_core_dps_tomador_opcional.py`**

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


def test_build_dps_xml_sem_tomador_omite_bloco_toma_inteiro():
    dados = _dados_base(toma_cpf_cnpj=None, toma_nome="")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    assert inf.find(f"{{{NFSE_NS}}}toma") is None


def test_build_dps_xml_com_tomador_mantem_bloco_toma_como_antes():
    dados = _dados_base()

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    toma = inf.find(f"{{{NFSE_NS}}}toma")
    assert toma is not None
    assert toma.find(f"{{{NFSE_NS}}}CPF").text == "98765432100"
    assert toma.find(f"{{{NFSE_NS}}}xNome").text == "Cliente Teste"


def test_build_dps_xml_com_documento_invalido_ainda_levanta_erro():
    dados = _dados_base(toma_cpf_cnpj="123")  # nem 11 nem 14 digitos

    try:
        build_dps_xml(dados)
        assert False, "deveria ter levantado ValueError"
    except ValueError as exc:
        assert "tomador" in str(exc).lower()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_nfse_core_dps_tomador_opcional.py -v`
Expected: FAIL — o primeiro teste falha porque `build_dps_xml` hoje levanta `ValueError("CPF/CNPJ do tomador ausente ou inválido")` quando `toma_cpf_cnpj` está vazio.

- [ ] **Step 3: Ajustar `nfse_core/dps.py`**

Localize este trecho em `build_dps_xml` (dentro do bloco de validações no início da função):

```python
    toma_doc = _digits(data.toma_cpf_cnpj)
    if len(toma_doc) not in (11, 14):
        raise ValueError("CPF/CNPJ do tomador ausente ou inválido")
```

Troque por:

```python
    # Documento do tomador e OPCIONAL — ajuste de 11/08/2026, nao presente no
    # kit original. Evidencia: NFS-e real (Belem/PA, mesmo CNPJ/servico de
    # lavanderia) emitida com tomador "NAO IDENTIFICADO" e aceita. Quando o
    # documento esta ausente, o bloco <toma> inteiro e omitido (replica o
    # formato da nota real) em vez de bloquear a emissao. NAO VERIFICADO
    # contra o validador real da SEFIN Nacional ainda — so contra o
    # município/portal de Belem. Confirmar em homologacao antes de producao.
    toma_doc = _digits(data.toma_cpf_cnpj)
    if toma_doc and len(toma_doc) not in (11, 14):
        raise ValueError("CPF/CNPJ do tomador, quando informado, deve ter 11 ou 14 digitos")
```

Depois, localize o bloco que monta o elemento `toma`:

```python
    toma = _el(inf, "toma")
    _el(toma, "CPF" if len(toma_doc) == 11 else "CNPJ", toma_doc)
    _el(toma, "xNome", _sanitize_text(data.toma_nome)[:300])
    if data.toma_email:
        _el(toma, "email", data.toma_email.strip()[:80])
```

Troque por:

```python
    if toma_doc:
        toma = _el(inf, "toma")
        _el(toma, "CPF" if len(toma_doc) == 11 else "CNPJ", toma_doc)
        _el(toma, "xNome", _sanitize_text(data.toma_nome)[:300])
        if data.toma_email:
            _el(toma, "email", data.toma_email.strip()[:80])
```

Nenhuma outra linha de `dps.py` muda — em particular, a validação de
`prest_cnpj`, `c_loc_emi` e `v_serv` continua exatamente como estava.

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_nfse_core_dps_tomador_opcional.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Rodar o smoke test original do kit para garantir que nada quebrou**

Run: `python nfse-nacional-kit/nfse-nacional-kit/exemplos/00_teste_local.py`
Expected: `[OK] Tudo certo` — este script usa `DpsData` com tomador preenchido, então exercita exatamente o caminho que não deveria ter mudado.

- [ ] **Step 6: Commit**

```bash
git add nfse_core/dps.py tests/test_nfse_core_dps_tomador_opcional.py
git commit -m "fix(nfse_core): documento do tomador passa a ser opcional na DPS

Evidencia real (NFS-e de Belem/PA, mesmo CNPJ/servico) mostra tomador
NAO IDENTIFICADO aceito. Bloco <toma> agora e omitido quando o
documento esta ausente, em vez de bloquear a emissao. Nao verificado
contra a SEFIN Nacional real ainda -- confirmar em homologacao."
```

- [ ] **Step 7: Escrever o teste do adaptador**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.models import AmbienteEnum, Empresa


def _empresa() -> Empresa:
    return Empresa(
        cnpj="12345678000199", inscricao_municipal="123456", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )


def test_montar_dps_data_mapeia_empresa_e_dados_corretamente():
    dados = DadosEmissao(
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste",
        tomador_email="cliente@teste.com", descricao="Lavagem de 5kg de roupa",
        valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(_empresa(), serie="1", numero=42, dados=dados)

    assert dps_data.tp_amb == 2  # homologacao
    assert dps_data.serie == "1"
    assert dps_data.numero == 42
    assert dps_data.prest_cnpj == "12345678000199"
    assert dps_data.prest_im == "123456"
    assert dps_data.c_loc_emi == "1501402"
    assert dps_data.op_simp_nac == 3
    assert dps_data.toma_cpf_cnpj == "98765432100"
    assert dps_data.toma_nome == "Cliente Teste"
    assert dps_data.c_trib_nac == "141001"
    assert dps_data.x_desc_serv == "Lavagem de 5kg de roupa"
    assert dps_data.v_serv == Decimal("49.90")


def test_montar_dps_data_producao_usa_tp_amb_1():
    empresa = _empresa()
    empresa.ambiente = AmbienteEnum.producao
    dados = DadosEmissao(
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste", tomador_email=None,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(empresa, serie="1", numero=1, dados=dados)

    assert dps_data.tp_amb == 1


def test_montar_dps_data_sem_documento_do_tomador_passa_none_adiante():
    dados = DadosEmissao(
        tomador_cpf_cnpj=None, tomador_nome="Cliente Sem Documento", tomador_email=None,
        descricao="Lavagem", valor=Decimal("15.00"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(_empresa(), serie="1", numero=2, dados=dados)

    assert dps_data.toma_cpf_cnpj is None
    assert dps_data.toma_nome == "Cliente Sem Documento"
```

- [ ] **Step 8: Rodar e confirmar falha**

Run: `pytest tests/test_adapters_dps_builder.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.adapters'`

- [ ] **Step 9: Implementar `app/adapters/__init__.py`** (vazio)

- [ ] **Step 10: Implementar `app/adapters/dps_builder.py`**

```python
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import AmbienteEnum, Empresa
from nfse_core import DpsData


@dataclass
class DadosEmissao:
    tomador_cpf_cnpj: str | None
    tomador_nome: str | None
    tomador_email: str | None
    descricao: str
    valor: Decimal
    competencia: date


def montar_dps_data(empresa: Empresa, serie: str, numero: int, dados: DadosEmissao) -> DpsData:
    return DpsData(
        tp_amb=1 if empresa.ambiente == AmbienteEnum.producao else 2,
        dh_emi=datetime.now(timezone.utc),
        serie=serie,
        numero=numero,
        competencia=dados.competencia,
        prest_cnpj=empresa.cnpj,
        prest_im=empresa.inscricao_municipal,
        c_loc_emi=empresa.municipio_ibge,
        op_simp_nac=empresa.op_simp_nac,
        toma_cpf_cnpj=dados.tomador_cpf_cnpj,
        toma_nome=dados.tomador_nome,
        toma_email=dados.tomador_email,
        c_trib_nac=empresa.codigo_tributacao,
        x_desc_serv=dados.descricao,
        v_serv=dados.valor,
    )
```

- [ ] **Step 11: Rodar e confirmar sucesso**

Run: `pytest tests/test_adapters_dps_builder.py -v`
Expected: PASS (3 testes)

- [ ] **Step 12: Commit**

```bash
git add app/adapters/__init__.py app/adapters/dps_builder.py tests/test_adapters_dps_builder.py
git commit -m "feat: adaptador comum empresa+dados -> DpsData, tomador opcional"
```

---

### Task 8: Emissão manual

**Files:**
- Modify: `app/schemas.py` (acrescenta `EmissaoManualIn`, `EmissaoOut`)
- Create: `app/routers/emissoes.py`
- Modify: `app/main.py` (registra o router)
- Test: `tests/test_emissoes_manual.py`

**Interfaces:**
- Consumes: `app.numeracao.reservar_proximo_numero`, `app.security.get_current_user`, `app.models.Emissao`, `app.models.OrigemEmissao`, `app.models.StatusEmissao`.
- Produces: `EmissaoManualIn` (Pydantic, `cpf_cnpj` **opcional** — quando informado, precisa ter 11 ou 14 dígitos; `valor` sempre `> 0`), `EmissaoOut`. Router `emissoes.router` com `POST /emissoes/manual` (mais rotas nas Tasks 9 e 11).

- [ ] **Step 1: Acrescentar a `app/schemas.py`**

```python
import re


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


class EmissaoManualIn(BaseModel):
    cpf_cnpj: str | None = None
    nome: str
    email: str | None = None
    descricao: str
    valor: Decimal
    competencia: date

    @field_validator("cpf_cnpj")
    @classmethod
    def cpf_cnpj_valido(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        digitos = _somente_digitos(v)
        if len(digitos) not in (11, 14):
            raise ValueError("cpf_cnpj, quando informado, deve ter 11 (CPF) ou 14 (CNPJ) digitos")
        return digitos

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("valor deve ser positivo")
        return v


class EmissaoOut(BaseModel):
    id: uuid.UUID
    origem: str
    status: str
    serie: str | None
    numero: int | None
    chave_acesso: str | None
    tomador_cpf_cnpj: str | None
    tomador_nome: str | None
    descricao: str
    valor: Decimal
    competencia: date
    erros: str | None

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Escrever `tests/test_emissoes_manual.py`**

```python
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Empresa, PapelUsuario, Usuario
from app.security import criar_token


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    usuario = Usuario(
        empresa_id=empresa.id, email="op@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return empresa, criar_token(usuario)


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_emissao_manual_reserva_numero_e_cria_pendente(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/manual",
                json={
                    "cpf_cnpj": "98765432100", "nome": "Cliente Manual",
                    "descricao": "Lavagem de edredom", "valor": "35.00",
                    "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["origem"] == "manual"
        assert corpo["status"] == "pendente"
        assert corpo["numero"] == 1
        assert corpo["tomador_cpf_cnpj"] == "98765432100"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emissao_manual_com_cpf_invalido_nao_reserva_numero(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/manual",
                json={
                    "cpf_cnpj": "123", "nome": "Cliente Invalido",
                    "descricao": "Lavagem", "valor": "10.00", "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422

        await db_session.refresh(empresa)
        assert empresa.proximo_numero == 1  # nao avancou
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emissao_manual_sem_documento_do_tomador_e_aceita(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/manual",
                json={
                    "nome": "Cliente Sem Documento",
                    "descricao": "Lavagem", "valor": "10.00", "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["numero"] == 1
        assert corpo["tomador_cpf_cnpj"] is None
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `pytest tests/test_emissoes_manual.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.routers.emissoes'`

- [ ] **Step 4: Implementar `app/routers/emissoes.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Emissao, OrigemEmissao, StatusEmissao, Usuario
from app.numeracao import reservar_proximo_numero
from app.schemas import EmissaoManualIn, EmissaoOut
from app.security import get_current_user

router = APIRouter(prefix="/emissoes", tags=["emissoes"])


@router.post("/manual", response_model=EmissaoOut, status_code=201)
async def emitir_manual(
    dados: EmissaoManualIn,
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    serie, numero = await reservar_proximo_numero(session, usuario.empresa_id)
    emissao = Emissao(
        empresa_id=usuario.empresa_id,
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
        criada_por_usuario_id=usuario.id,
    )
    session.add(emissao)
    await session.commit()
    await session.refresh(emissao)
    return emissao
```

- [ ] **Step 5: Registrar o router em `app/main.py`**

```python
from app.routers import auth, emissoes, usuarios

app.include_router(emissoes.router)
```

(acrescentar ao bloco de `include_router` já existente)

- [ ] **Step 6: Rodar e confirmar sucesso**

Run: `pytest tests/test_emissoes_manual.py -v`
Expected: PASS (3 testes)

- [ ] **Step 7: Commit**

```bash
git add app/schemas.py app/routers/emissoes.py app/main.py tests/test_emissoes_manual.py
git commit -m "feat: emissao manual de nota pelo portal"
```

---

### Task 9: Webhook Stone (idempotência)

Como o documento do tomador agora é opcional em toda a cadeia (Task 7), o
webhook não precisa mais de um estado intermediário à espera de dados — ele
reserva o número e grava `pendente` diretamente, com `tomador_cpf_cnpj=None`
quando o payload não traz o documento (o caso de hoje).

**Files:**
- Create: `app/adapters/stone.py`, `app/routers/webhook_stone.py`
- Modify: `app/main.py` (registra o router do webhook)
- Test: `tests/test_adapters_stone.py`, `tests/test_webhook_stone.py`

**Interfaces:**
- Produces: `StoneChargePaidEvent` (dataclass: `charge_id: str`, `customer_id: str`, `customer_name: str`, `valor: Decimal`), `parse_stone_charge_paid(payload: dict) -> StoneChargePaidEvent` (levanta `ValueError` se campo essencial faltar). Router `webhook_stone.router` com `POST /webhooks/stone/{empresa_id}`.

- [ ] **Step 1: Escrever `tests/test_adapters_stone.py`**

```python
from decimal import Decimal

import pytest

from app.adapters.stone import parse_stone_charge_paid


def test_parse_stone_charge_paid_extrai_campos_documentados():
    payload = {
        "id": "ch_123abc",
        "amount": 4990,
        "customer": {"id": "cus_456", "name": "Fulano de Tal"},
    }

    evento = parse_stone_charge_paid(payload)

    assert evento.charge_id == "ch_123abc"
    assert evento.customer_id == "cus_456"
    assert evento.customer_name == "Fulano de Tal"
    assert evento.valor == Decimal("49.90")


def test_parse_stone_charge_paid_rejeita_payload_incompleto():
    with pytest.raises(ValueError, match="payload"):
        parse_stone_charge_paid({"id": "ch_123abc"})
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_adapters_stone.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.adapters.stone'`

- [ ] **Step 3: Implementar `app/adapters/stone.py`**

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StoneChargePaidEvent:
    charge_id: str
    customer_id: str
    customer_name: str
    valor: Decimal


def parse_stone_charge_paid(payload: dict) -> StoneChargePaidEvent:
    """Extrai os campos documentados publicamente do evento charge.paid.

    Nao inclui CPF/CNPJ do cliente porque o payload de exemplo publico da
    Stone Connect nao o traz. Isso e aceitavel porque o documento do tomador
    e opcional na emissao (ver Task 7 e a spec) — a nota sai sem ele. Este
    parser sera revisado quando o payload real (conta de parceiro ativa)
    confirmar os nomes de campo; se o documento passar a vir no payload,
    o router pode passa-lo direto para `tomador_cpf_cnpj` como um bonus,
    sem exigir nenhuma mudanca estrutural.
    """
    try:
        charge_id = str(payload["id"])
        customer = payload["customer"]
        customer_id = str(customer["id"])
        customer_name = str(customer["name"])
        amount_centavos = int(payload["amount"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"payload da Stone incompleto: falta {exc}") from exc

    return StoneChargePaidEvent(
        charge_id=charge_id,
        customer_id=customer_id,
        customer_name=customer_name,
        valor=Decimal(amount_centavos) / Decimal(100),
    )
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_adapters_stone.py -v`
Expected: PASS

- [ ] **Step 5: Escrever `tests/test_webhook_stone.py`**

```python
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Emissao, Empresa, StatusEmissao


async def _empresa_com_token(db_session) -> Empresa:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash=hash_senha("token-secreto"),
    )
    db_session.add(empresa)
    await db_session.commit()
    return empresa


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_webhook_stone_cria_emissao_pendente_sem_documento_do_tomador(db_session):
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={
                    "type": "charge.paid",
                    "id": "ch_abc123",
                    "amount": 4990,
                    "customer": {"id": "cus_1", "name": "Cliente Stone"},
                },
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["criado"] is True
    finally:
        app.dependency_overrides.clear()

    emissao = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalar_one()
    assert emissao.status == StatusEmissao.pendente
    assert emissao.stone_charge_id == "ch_abc123"
    assert emissao.numero == 1  # reservado na hora, sem esperar documento
    assert emissao.tomador_cpf_cnpj is None
    assert emissao.tomador_nome == "Cliente Stone"


@pytest.mark.asyncio
async def test_webhook_stone_e_idempotente(db_session):
    empresa = await _empresa_com_token(db_session)
    payload = {
        "type": "charge.paid", "id": "ch_repetido", "amount": 1000,
        "customer": {"id": "cus_2", "name": "Cliente Repetido"},
    }

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                f"/webhooks/stone/{empresa.id}", json=payload,
                headers={"X-Webhook-Token": "token-secreto"},
            )
            segunda = await client.post(
                f"/webhooks/stone/{empresa.id}", json=payload,
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert primeira.status_code == 200
        assert segunda.status_code == 200
        assert segunda.json().get("duplicado") is True
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == "ch_repetido"
            )
        )
    ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_webhook_stone_rejeita_token_errado(db_session):
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={"type": "charge.paid", "id": "x", "amount": 100, "customer": {"id": "1", "name": "A"}},
                headers={"X-Webhook-Token": "token-errado"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


```

- [ ] **Step 6: Rodar e confirmar falha**

Run: `pytest tests/test_webhook_stone.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.routers.webhook_stone'`

- [ ] **Step 7: Implementar `app/routers/webhook_stone.py`**

```python
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.stone import parse_stone_charge_paid
from app.crypto import verificar_senha
from app.db import get_db
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao
from app.numeracao import reservar_proximo_numero

router = APIRouter(prefix="/webhooks/stone", tags=["webhook-stone"])


@router.post("/{empresa_id}")
async def receber_webhook_stone(
    empresa_id: str,
    request: Request,
    x_webhook_token: str = Header(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    empresa = await session.get(Empresa, empresa_id)
    if empresa is None or not verificar_senha(x_webhook_token, empresa.webhook_token_hash):
        raise HTTPException(status_code=404)

    payload = await request.json()
    if payload.get("type") != "charge.paid":
        return {"ignorado": True}

    evento = parse_stone_charge_paid(payload)

    existente = (
        await session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == evento.charge_id
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        return {"duplicado": True, "emissao_id": str(existente.id)}

    serie, numero = await reservar_proximo_numero(session, empresa.id)
    emissao = Emissao(
        empresa_id=empresa.id,
        origem=OrigemEmissao.webhook,
        stone_charge_id=evento.charge_id,
        status=StatusEmissao.pendente,
        serie=serie,
        numero=numero,
        tomador_nome=evento.customer_name,
        descricao=empresa.descricao_servico_padrao,
        valor=evento.valor,
        competencia=date.today().replace(day=1),
    )
    session.add(emissao)
    await session.commit()
    await session.refresh(emissao)
    return {"criado": True, "emissao_id": str(emissao.id)}
```

- [ ] **Step 8: Registrar o router em `app/main.py`**

```python
from app.routers import auth, emissoes, usuarios, webhook_stone

app.include_router(webhook_stone.router)
```

- [ ] **Step 9: Rodar e confirmar sucesso**

Run: `pytest tests/test_webhook_stone.py -v`
Expected: PASS (3 testes)

- [ ] **Step 10: Commit**

```bash
git add app/adapters/stone.py app/routers/webhook_stone.py app/main.py tests/test_adapters_stone.py tests/test_webhook_stone.py
git commit -m "feat: webhook Stone idempotente, emite sem exigir documento do tomador"
```

---

### Task 10: Worker de emissão

**Files:**
- Create: `app/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `app.adapters.dps_builder.DadosEmissao`, `montar_dps_data`, `app.crypto.decifrar`, `nfse_core.build_dps_xml`, `nfse_core.sign_dps`, `nfse_core.SefinClient`, `nfse_core.SefinError`, `nfse_core.ler_resposta_emissao`.
- Produces: `async def processar_uma_pendente(session: AsyncSession, settings: Settings | None = None) -> bool` (retorna `True` se processou algo). `async def loop_worker(session_factory, intervalo_segundos: float = 5.0) -> None` (loop infinito — não é chamado pelos testes, só pelo processo real).

- [ ] **Step 1: Escrever o teste**

```python
import base64
import gzip
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.crypto import cifrar
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao
import app.worker as worker


async def _empresa_e_emissao_pendente(db_session, tomador_cpf_cnpj: str | None = "98765432100") -> Emissao:
    fernet_key = get_settings().fernet_key
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
        certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, tomador_cpf_cnpj=tomador_cpf_cnpj, tomador_nome="Cliente",
        descricao="Lavagem de roupa", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


def _cliente_falso_autorizado():
    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            return {
                "_http_status": 201,
                "chaveAcesso": "1" * 50,
                "nfseXmlGZipB64": base64.b64encode(
                    gzip.compress(b"<NFSe>autorizada</NFSe>")
                ).decode(),
            }

        async def close(self) -> None:
            pass

    return ClienteFalso


@pytest.mark.asyncio
async def test_processar_uma_pendente_marca_autorizada_em_sucesso(db_session, monkeypatch):
    emissao = await _empresa_e_emissao_pendente(db_session)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    monkeypatch.setattr(worker, "SefinClient", _cliente_falso_autorizado())

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "1" * 50
    assert emissao.xml_nfse == b"<NFSe>autorizada</NFSe>"


@pytest.mark.asyncio
async def test_processar_uma_pendente_autoriza_mesmo_sem_documento_do_tomador(db_session, monkeypatch):
    """Cobre o caso do webhook Stone: emissao sem CPF/CNPJ do tomador (Task 7
    tornou isso opcional em build_dps_xml) precisa passar pelo worker sem
    levantar excecao."""
    emissao = await _empresa_e_emissao_pendente(db_session, tomador_cpf_cnpj=None)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    monkeypatch.setattr(worker, "SefinClient", _cliente_falso_autorizado())

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada


@pytest.mark.asyncio
async def test_processar_uma_pendente_marca_rejeitada_com_erros(db_session, monkeypatch):
    emissao = await _empresa_e_emissao_pendente(db_session)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            return {"_http_status": 422, "erros": [{"codigo": "E0714", "mensagem": "Erro na assinatura"}]}

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.erros is not None
    assert "E0714" in emissao.erros


@pytest.mark.asyncio
async def test_processar_uma_pendente_devolve_falso_quando_fila_vazia(db_session):
    processou = await worker.processar_uma_pendente(db_session)
    assert processou is False
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.worker'`

- [ ] **Step 3: Implementar `app/worker.py`**

```python
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.models import Emissao, Empresa, StatusEmissao
from nfse_core import SefinClient, SefinError, build_dps_xml, ler_resposta_emissao, sign_dps


async def processar_uma_pendente(session: AsyncSession, settings: Settings | None = None) -> bool:
    """Processa uma emissao 'pendente' (se houver). Retorna True se processou.

    Usa SELECT ... FOR UPDATE SKIP LOCKED: seguro mesmo com mais de um
    worker rodando ao mesmo tempo, cada um pega uma linha diferente.
    """
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.pendente)
        .order_by(Emissao.criada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)
    pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
    senha = decifrar(empresa.certificado_senha_cifrada, settings.fernet_key) if empresa.certificado_senha_cifrada else None

    dados = DadosEmissao(
        tomador_cpf_cnpj=emissao.tomador_cpf_cnpj,
        tomador_nome=emissao.tomador_nome,
        tomador_email=emissao.tomador_email,
        descricao=emissao.descricao,
        valor=emissao.valor,
        competencia=emissao.competencia,
    )
    dps_data = montar_dps_data(empresa, emissao.serie, emissao.numero, dados)

    try:
        xml = build_dps_xml(dps_data)
        assinado = sign_dps(xml, pfx_base64, senha)
        emissao.xml_dps = assinado

        cliente = SefinClient(empresa.ambiente.value, pfx_base64, senha)
        try:
            bruta = await cliente.emitir_dps(assinado)
        finally:
            await cliente.close()
    except SefinError as exc:
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = f'[{{"codigo": "TRANSPORTE", "titulo": "{exc}"}}]'
        await session.commit()
        return True

    resultado = ler_resposta_emissao(bruta)
    if resultado.autorizada:
        emissao.status = StatusEmissao.autorizada
        emissao.chave_acesso = resultado.chave_acesso
        emissao.xml_nfse = resultado.xml_nfse
        emissao.dps_id = dps_data.dps_id
    else:
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = resultado.erros_json()

    await session.commit()
    return True


async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        async with session_factory() as session:
            processou = await processar_uma_pendente(session)
        if not processou:
            await asyncio.sleep(intervalo_segundos)
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Commit**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: worker de emissao (integra nfse_core, testado com SEFIN mockada)"
```

---

### Task 11: Listagem, download XML/PDF, fallback de PDF e dashboard

**Files:**
- Create: `app/danfe.py`
- Modify: `app/routers/emissoes.py` (acrescenta `GET /emissoes`, `GET /emissoes/{id}/xml`, `GET /emissoes/{id}/pdf`)
- Create: `app/routers/dashboard.py`
- Modify: `app/main.py` (registra `dashboard.router`)
- Test: `tests/test_danfe.py`, `tests/test_emissoes_download.py`, `tests/test_dashboard.py`

**Interfaces:**
- Produces: `gerar_danfse_fallback(emissao: Emissao, empresa: Empresa) -> bytes` (PDF). Rotas `GET /emissoes` (filtros `status`, `inicio`, `fim` — query params), `GET /emissoes/{id}/xml`, `GET /emissoes/{id}/pdf`, `GET /dashboard?inicio=&fim=`.

- [ ] **Step 1: Escrever `tests/test_danfe.py`**

```python
from datetime import date
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.danfe import gerar_danfse_fallback
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao


def test_gerar_danfse_fallback_produz_pdf_com_dados_da_nota():
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="123456", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=None, webhook_token_hash="x",
    )
    emissao = Emissao(
        empresa_id=None, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=42, chave_acesso="12345678901234567890123456789012345678901234567890",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste",
        descricao="Lavagem de 5kg de roupa", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )

    pdf_bytes = gerar_danfse_fallback(emissao, empresa)

    assert pdf_bytes.startswith(b"%PDF")
    texto = "".join(pagina.extract_text() for pagina in PdfReader(BytesIO(pdf_bytes)).pages)
    assert "Cliente Teste" in texto
    assert "49.90" in texto
    assert emissao.chave_acesso in texto
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_danfe.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.danfe'`

- [ ] **Step 3: Implementar `app/danfe.py`**

```python
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.models import Emissao, Empresa


def gerar_danfse_fallback(emissao: Emissao, empresa: Empresa) -> bytes:
    """Representacao propria da nota quando a API do ADN nao responde.

    Nao e o documento fiscal (o XML e) — e so uma representacao legivel.
    """
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    y = altura - 50
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "NFS-e Nacional — Representacao (DANFSe indisponivel)")
    y -= 30

    pdf.setFont("Helvetica", 10)
    linhas = [
        f"Prestador: CNPJ {empresa.cnpj}",
        f"Serie/Numero: {emissao.serie}/{emissao.numero}",
        f"Chave de acesso: {emissao.chave_acesso or '-'}",
        f"Tomador: {emissao.tomador_nome or '-'} ({emissao.tomador_cpf_cnpj or 'nao informado'})",
        f"Descricao do servico: {emissao.descricao}",
        f"Valor: R$ {emissao.valor:.2f}",
        f"Competencia: {emissao.competencia:%m/%Y}",
    ]
    for linha in linhas:
        pdf.drawString(50, y, linha)
        y -= 20

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_danfe.py -v`
Expected: PASS

- [ ] **Step 5: Escrever `tests/test_emissoes_download.py`**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import cifrar, hash_senha
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, PapelUsuario, StatusEmissao, Usuario
from app.security import criar_token


async def _empresa_usuario_emissao_autorizada(db_session):
    fernet_key = get_settings().fernet_key
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado=cifrar("pfx-fake", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
        certificado_valido_ate=datetime.now(timezone.utc), webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    usuario = Usuario(
        empresa_id=empresa.id, email="op@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario)
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


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_listar_emissoes_filtra_por_status(db_session):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/emissoes", params={"status": "autorizada"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert len(corpo) == 1
        assert corpo[0]["id"] == str(emissao.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xml_devolve_documento_autorizado(db_session):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/emissoes/{emissao.id}/xml", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content == b"<NFSe>ok</NFSe>"
        assert resposta.headers["content-type"].startswith("application/xml")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_pdf_usa_fallback_quando_adn_nao_responde(db_session, monkeypatch):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario)

    import app.routers.emissoes as emissoes_router

    async def _fetch_danfse_pdf_falso(*args, **kwargs):
        return None

    monkeypatch.setattr(
        emissoes_router.SefinClient, "fetch_danfse_pdf", staticmethod(_fetch_danfse_pdf_falso)
    )

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/emissoes/{emissao.id}/pdf", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content.startswith(b"%PDF")
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 6: Rodar e confirmar falha**

Run: `pytest tests/test_emissoes_download.py -v`
Expected: FAIL (rotas `GET /emissoes`, `.../xml`, `.../pdf` ainda não existem)

- [ ] **Step 7: Acrescentar as rotas a `app/routers/emissoes.py`**

```python
from datetime import date, timedelta

from fastapi import Query, Response

from app.config import Settings, get_settings
from app.crypto import decifrar
from app.danfe import gerar_danfse_fallback
from app.models import Empresa, StatusEmissao
from nfse_core import SefinClient
from sqlalchemy import select


@router.get("", response_model=list[EmissaoOut])
async def listar_emissoes(
    status: StatusEmissao | None = Query(default=None),
    inicio: date | None = Query(default=None),
    fim: date | None = Query(default=None),
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[Emissao]:
    stmt = select(Emissao).where(Emissao.empresa_id == usuario.empresa_id)
    if status is not None:
        stmt = stmt.where(Emissao.status == status)
    if inicio is not None:
        stmt = stmt.where(Emissao.criada_em >= inicio)
    if fim is not None:
        stmt = stmt.where(Emissao.criada_em < fim + timedelta(days=1))
    stmt = stmt.order_by(Emissao.criada_em.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{emissao_id}/xml")
async def baixar_xml(
    emissao_id: uuid.UUID,
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != usuario.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada or not emissao.xml_nfse:
        raise HTTPException(status_code=404, detail="XML autorizado nao disponivel")
    return Response(
        content=emissao.xml_nfse, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{emissao.chave_acesso}.xml"'},
    )


@router.get("/{emissao_id}/pdf")
async def baixar_pdf(
    emissao_id: uuid.UUID,
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != usuario.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(status_code=404, detail="Nota nao autorizada")

    empresa = await session.get(Empresa, emissao.empresa_id)
    pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
    senha = decifrar(empresa.certificado_senha_cifrada, settings.fernet_key) if empresa.certificado_senha_cifrada else None

    pdf = await SefinClient.fetch_danfse_pdf(empresa.ambiente.value, pfx_base64, senha, emissao.chave_acesso)
    if pdf is None:
        pdf = gerar_danfse_fallback(emissao, empresa)
    return Response(content=pdf, media_type="application/pdf")
```

(`import uuid` já está no topo do arquivo desde a Task 9; os demais imports acima entram junto dos existentes)

- [ ] **Step 8: Rodar e confirmar sucesso**

Run: `pytest tests/test_emissoes_download.py -v`
Expected: PASS (3 testes)

- [ ] **Step 9: Escrever `tests/test_dashboard.py`**

```python
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, PapelUsuario, StatusEmissao, Usuario
from app.security import criar_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_dashboard_soma_valores_por_status(db_session):
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    usuario = Usuario(
        empresa_id=empresa.id, email="op@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario)
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
    await db_session.refresh(usuario)
    token = criar_token(usuario)

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
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
```

- [ ] **Step 10: Rodar e confirmar falha**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.routers.dashboard'`

- [ ] **Step 11: Implementar `app/routers/dashboard.py`**

```python
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Emissao, StatusEmissao, Usuario
from app.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    inicio: date = Query(...),
    fim: date = Query(...),
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(Emissao.status, func.coalesce(func.sum(Emissao.valor), 0))
        .where(
            Emissao.empresa_id == usuario.empresa_id,
            Emissao.criada_em >= inicio,
            Emissao.criada_em < fim + timedelta(days=1),
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

- [ ] **Step 12: Registrar o router em `app/main.py`**

```python
from app.routers import auth, dashboard, emissoes, usuarios, webhook_stone

app.include_router(dashboard.router)
```

- [ ] **Step 13: Rodar e confirmar sucesso**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS

- [ ] **Step 14: Rodar a suíte inteira**

Run: `pytest -v`
Expected: PASS (todos os testes de todas as tasks)

- [ ] **Step 15: Commit**

```bash
git add app/danfe.py app/routers/emissoes.py app/routers/dashboard.py app/main.py tests/test_danfe.py tests/test_emissoes_download.py tests/test_dashboard.py
git commit -m "feat: listagem, download de XML/PDF com fallback e dashboard de valores acumulados"
```

---

### Task 12: Montagem final do app, execução local e checklist de homologação

**Files:**
- Verify: `app/main.py` (todos os routers registrados)
- Create: `README.md`
- Test: `tests/test_main_rotas_registradas.py`

**Interfaces:**
- Nenhuma interface nova — esta task fecha o app e documenta como rodar.

- [ ] **Step 1: Escrever `tests/test_main_rotas_registradas.py`**

```python
from app.main import app


def test_todas_as_rotas_esperadas_estao_registradas():
    caminhos = {rota.path for rota in app.routes}
    esperadas = {
        "/health",
        "/auth/login",
        "/usuarios",
        "/webhooks/stone/{empresa_id}",
        "/emissoes/manual",
        "/emissoes",
        "/emissoes/{emissao_id}/xml",
        "/emissoes/{emissao_id}/pdf",
        "/dashboard",
    }
    faltando = esperadas - caminhos
    assert not faltando, f"rotas nao registradas: {faltando}"
```

- [ ] **Step 2: Rodar e corrigir o que faltar**

Run: `pytest tests/test_main_rotas_registradas.py -v`
Expected: PASS — se alguma rota estiver faltando, é sinal de que um `include_router` ficou pra trás em alguma task anterior; adicione o `include_router` que falta em `app/main.py` e rode de novo.

- [ ] **Step 3: Escrever `README.md`**

```markdown
# NFS-e Automatizada — Stone webhook

Emite NFS-e Nacional automaticamente a partir de pagamentos aprovados na
Stone, com portal para consulta, download e emissão manual. Ver desenho
completo em `docs/superpowers/specs/2026-08-11-nfse-stone-webhook-design.md`.

## Rodando localmente

1. `docker compose up -d db`
2. `docker compose exec db psql -U nfse -d nfse -c "CREATE DATABASE nfse_test;"`
3. Copie `.env.example` para `.env` e preencha `FERNET_KEY`/`JWT_SECRET` (comandos no próprio `.env.example`).
4. `pip install -r requirements-dev.txt`
5. `alembic upgrade head`
6. Cadastre a primeira empresa: `python scripts/criar_empresa.py --cnpj ... --pfx caminho/certificado.pfx ...` (veja `--help`)
7. `uvicorn app.main:app --reload` — API em `http://localhost:8000`
8. Em outro terminal, rode o worker: `python -c "import asyncio; from app.db import SessionLocal; from app.worker import loop_worker; asyncio.run(loop_worker(SessionLocal))"`

## Rodando os testes

```bash
pytest -v
```

Exige o Postgres do `docker compose` no ar (banco `nfse_test`).

## Checklist antes da primeira nota real (fora do automatizável por teste)

- [ ] `python nfse-nacional-kit/nfse-nacional-kit/exemplos/00_teste_local.py` — smoke test do núcleo fiscal, sem rede.
- [ ] **Confirmar contra a SEFIN Nacional real (homologação) que a emissão sem documento do tomador é aceita** — o ajuste da Task 7 replica o que a prefeitura de Belém/PA aceitou, mas isso nunca foi testado contra o validador do Sistema Nacional. Se for rejeitado, o fallback é coletar o documento antes de emitir (ex: reativar um formulário de complemento no portal) — mas só decida isso depois do teste real, não antes.
- [ ] Confirmar o código de tributação nacional (6 dígitos) exato para "14.10 — Tinturaria e lavanderia" contra a tabela oficial de desdobros do ANEXO — `141001` usado nos testes deste plano é um palpite baseado no padrão observado, não uma fonte oficial.
- [ ] Cadastro de parceiro Stone aprovado (`partner.stone.com.br/formulario`) e webhook real recebido pelo menos uma vez em ambiente de teste — confirmar nomes de campo exatos do payload real; se o CPF/CNPJ do tomador vier disponível, é uma melhoria simples ajustar `app/adapters/stone.py` para preenchê-lo (não é obrigatório, já que a emissão funciona sem ele).
- [ ] Confirmar em <https://www.gov.br/nfse> que o município aderiu ao Sistema Nacional.
- [ ] Emissão limpa em `homologacao` (produção restrita) com o certificado A1 real da empresa.
- [ ] Só depois de uma emissão limpa em homologação, trocar `Empresa.ambiente` para `producao`.
```

- [ ] **Step 4: Rodar a suíte completa uma última vez**

Run: `pytest -v`
Expected: PASS (todos os testes)

- [ ] **Step 5: Commit**

```bash
git add tests/test_main_rotas_registradas.py README.md
git commit -m "docs: readme de execucao local e checklist de homologacao"
```

# Integração com a Spedy como provedor alternativo de emissão — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada empresa ganha um campo `provedor_emissao` (`direto` | `spedy`) que troca emissão, confirmação, cancelamento e download de PDF entre o caminho direto atual (SEFIN/município próprio) e a API da Spedy.

**Architecture:** Um novo módulo `app/adapters/spedy_client.py` (cliente HTTP por X-Api-Key, sem XML/assinatura — quem assina é a Spedy) e `app/adapters/spedy_payload.py`/`spedy_resposta.py` (mapeamento de payload e leitura tolerante de resposta). O worker (`app/worker.py`) ganha branches por `provedor_emissao` nas suas três funções de polling existentes, mais duas novas funções irmãs para resolver os dois fluxos assíncronos da Spedy (confirmação de emissão, confirmação de cancelamento). O provisionamento (criar empresa + subir certificado + configurar) é síncrono e explícito, disparado de `PUT /empresas/mim`.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, httpx, pytest + pytest-asyncio, Postgres.

**Spec:** `docs/superpowers/specs/2026-09-15-spedy-integration-design.md`

## Global Constraints

- Nunca commitar a chave de API da Spedy (mestre ou de empresa) em texto puro — sempre cifrada com `app.crypto.cifrar`/`decifrar` (mesma `FERNET_KEY`), nunca em `.env.example`.
- Todo erro no caminho Spedy do worker é isolado por linha (nunca escapa de uma função `processar_*` nem derruba `loop_worker`) — mesma regra já aplicada ao caminho direto.
- O caminho `direto` existente não pode mudar de comportamento — toda mudança é aditiva (branch por `provedor_emissao`).
- Nenhuma emissão real em produção Spedy nesta implementação — só sandbox (a chave já fornecida pelo usuário é de sandbox).

---

### Task 1: Modelo de dados e configuração

**Files:**
- Modify: `app/models.py`
- Modify: `app/config.py`
- Create: `alembic/versions/a5d9f13c6e82_provedor_emissao_e_integracao_spedy.py`
- Test: `tests/test_models_migration.py` (já existe — só precisa continuar passando)

**Interfaces:**
- Produces: `ProvedorEmissao` (enum: `direto`, `spedy`), `StatusEmissao.aguardando_confirmacao`, `StatusEmissao.cancelamento_aguardando_confirmacao`, `Empresa.provedor_emissao/spedy_empresa_id/spedy_api_key_cifrada/razao_social/logradouro/numero/complemento/bairro/cep`, `Emissao.spedy_nota_id`, `Settings.spedy_api_key_master_homologacao/spedy_api_key_master_producao` — usados por todas as tasks seguintes.

- [ ] **Step 1: Adicionar o enum `ProvedorEmissao` e os novos valores de `StatusEmissao`**

Em `app/models.py`, logo depois de `class AmbienteEnum(str, enum.Enum): ...`:

```python
class ProvedorEmissao(str, enum.Enum):
    direto = "direto"
    spedy = "spedy"
```

E em `class StatusEmissao(str, enum.Enum)`, acrescentar duas linhas ao final do corpo existente:

```python
    aguardando_confirmacao = "aguardando_confirmacao"
    cancelamento_aguardando_confirmacao = "cancelamento_aguardando_confirmacao"
```

- [ ] **Step 2: Alargar a coluna `Emissao.status` e adicionar os campos novos em `Empresa`/`Emissao`**

`cancelamento_aguardando_confirmacao` tem 35 caracteres — a coluna atual é `String(30)`. Trocar para `String(40)`:

```python
status: Mapped[StatusEmissao] = mapped_column(String(40), nullable=False)
```

Em `class Empresa`, adicionar (antes de `titular_id`):

```python
    razao_social: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logradouro: Mapped[str | None] = mapped_column(String(200), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    complemento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Provedor usado para TODAS as operacoes fiscais desta empresa (emissao,
    # cancelamento, consulta, PDF) -- "spedy" exige spedy_empresa_id e
    # spedy_api_key_cifrada preenchidos (provisionamento em PUT /empresas/mim).
    provedor_emissao: Mapped[ProvedorEmissao] = mapped_column(
        String(20), default=ProvedorEmissao.direto, nullable=False
    )
    spedy_empresa_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    spedy_api_key_cifrada: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Em `class Emissao`, adicionar (perto de `chave_acesso`):

```python
    spedy_nota_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
```

- [ ] **Step 3: Adicionar as chaves mestre da Spedy em `Settings`**

Em `app/config.py`, dentro de `class Settings(BaseSettings)`:

```python
    spedy_api_key_master_homologacao: str = ""
    spedy_api_key_master_producao: str = ""
```

- [ ] **Step 4: Criar a migration Alembic**

Criar `alembic/versions/a5d9f13c6e82_provedor_emissao_e_integracao_spedy.py`:

```python
"""provedor de emissao e integracao com a Spedy

Revision ID: a5d9f13c6e82
Revises: 4b7e1a9c3d2f
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5d9f13c6e82'
down_revision: Union[str, Sequence[str], None] = '4b7e1a9c3d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('razao_social', sa.String(length=200), nullable=True))
    op.add_column('empresas', sa.Column('logradouro', sa.String(length=200), nullable=True))
    op.add_column('empresas', sa.Column('numero', sa.String(length=20), nullable=True))
    op.add_column('empresas', sa.Column('complemento', sa.String(length=100), nullable=True))
    op.add_column('empresas', sa.Column('bairro', sa.String(length=100), nullable=True))
    op.add_column('empresas', sa.Column('cep', sa.String(length=8), nullable=True))
    op.add_column(
        'empresas',
        sa.Column('provedor_emissao', sa.String(length=20), nullable=False, server_default='direto'),
    )
    op.add_column('empresas', sa.Column('spedy_empresa_id', sa.String(length=36), nullable=True))
    op.add_column('empresas', sa.Column('spedy_api_key_cifrada', sa.Text(), nullable=True))
    op.add_column('emissoes', sa.Column('spedy_nota_id', sa.String(length=36), nullable=True))
    op.alter_column('emissoes', 'status', existing_type=sa.String(length=30), type_=sa.String(length=40))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('emissoes', 'status', existing_type=sa.String(length=40), type_=sa.String(length=30))
    op.drop_column('emissoes', 'spedy_nota_id')
    op.drop_column('empresas', 'spedy_api_key_cifrada')
    op.drop_column('empresas', 'spedy_empresa_id')
    op.drop_column('empresas', 'provedor_emissao')
    op.drop_column('empresas', 'cep')
    op.drop_column('empresas', 'bairro')
    op.drop_column('empresas', 'complemento')
    op.drop_column('empresas', 'numero')
    op.drop_column('empresas', 'logradouro')
    op.drop_column('empresas', 'razao_social')
```

- [ ] **Step 5: Rodar a suíte de migração e a suíte completa para garantir que nada quebrou**

Run: `pytest tests/test_models_migration.py -v && pytest tests/ -x -q`
Expected: todos os testes existentes continuam passando (nenhum teste novo ainda nesta task — é só schema).

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/config.py alembic/versions/a5d9f13c6e82_provedor_emissao_e_integracao_spedy.py
git commit -m "feat: adiciona modelo de dados para provedor de emissao alternativo (Spedy)"
```

---

### Task 2: Cliente HTTP da Spedy

**Files:**
- Create: `app/adapters/spedy_client.py`
- Test: `tests/test_spedy_client.py`

**Interfaces:**
- Consumes: nada de tasks anteriores (módulo isolado, só `httpx`).
- Produces: `SpedyError(RuntimeError)`, `SpedyClient(ambiente: str, api_key: str)` com `criar_empresa(dados: dict) -> dict`, `adicionar_certificado(spedy_empresa_id: str, pfx_bytes: bytes, senha: str) -> dict`, `configurar_nfse(spedy_empresa_id: str, dados: dict) -> dict`, `emitir_nfse(payload: dict) -> dict`, `consultar_nfse(spedy_nota_id: str) -> dict`, `cancelar_nfse(spedy_nota_id: str, motivo: str) -> dict`, `baixar_pdf(spedy_nota_id: str) -> bytes`, `close() -> None`. Usado pelas Tasks 3, 4, 5, 6, 7.

- [ ] **Step 1: Escrever o teste de emissão (payload e path corretos) — vai falhar (módulo não existe)**

Criar `tests/test_spedy_client.py`:

```python
import pytest

from app.adapters.spedy_client import SpedyClient, SpedyError


class _RespostaFalsa:
    def __init__(self, status_code: int, corpo):
        self.status_code = status_code
        self._corpo = corpo
        self.text = str(corpo)
        self.content = corpo if isinstance(corpo, bytes) else str(corpo).encode()

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo JSON")
        return self._corpo


@pytest.mark.asyncio
async def test_emitir_nfse_chama_o_path_e_metodo_corretos():
    cliente = SpedyClient("homologacao", "chave-teste")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"id": "nota-1", "status": "enqueued"})

    cliente._request = _request_falso
    resultado = await cliente.emitir_nfse({"description": "Lavagem"})

    assert chamadas == [("POST", "/service-invoices", {"json": {"description": "Lavagem"}})]
    assert resultado == {"id": "nota-1", "status": "enqueued", "_http_status": 200}


@pytest.mark.asyncio
async def test_emitir_nfse_nao_levanta_em_rejeicao_4xx():
    """Rejeicao de negocio (validacao) precisa voltar como dict pro worker
    interpretar -- so falha de transporte/5xx levanta SpedyError."""
    cliente = SpedyClient("homologacao", "chave-teste")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(400, {"processingDetail": {"message": "CNPJ invalido"}})

    cliente._request = _request_falso
    resultado = await cliente.emitir_nfse({})

    assert resultado["_http_status"] == 400
    assert resultado["processingDetail"]["message"] == "CNPJ invalido"


@pytest.mark.asyncio
async def test_emitir_nfse_levanta_spedyerror_em_5xx():
    cliente = SpedyClient("homologacao", "chave-teste")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(503, {"message": "indisponivel"})

    cliente._request = _request_falso
    with pytest.raises(SpedyError):
        await cliente.emitir_nfse({})


@pytest.mark.asyncio
async def test_criar_empresa_desembrulha_o_campo_result():
    cliente = SpedyClient("homologacao", "chave-mestre")

    async def _request_falso(method, path, **kwargs):
        assert (method, path) == ("POST", "/companies")
        return _RespostaFalsa(
            201,
            {"result": {"id": "empresa-1", "apiCredentials": {"apiKey": "chave-nova"}}},
        )

    cliente._request = _request_falso
    resultado = await cliente.criar_empresa({"federalTaxNumber": "12345678000199"})

    assert resultado == {"id": "empresa-1", "apiCredentials": {"apiKey": "chave-nova"}}


@pytest.mark.asyncio
async def test_criar_empresa_levanta_em_erro_de_validacao():
    """Provisionamento e uma acao explicita do admin -- QUALQUER erro (nao so
    5xx) deve virar excecao pro endpoint devolver na hora, sem estado parcial."""
    cliente = SpedyClient("homologacao", "chave-mestre")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(422, {"message": "federalTaxNumber invalido"})

    cliente._request = _request_falso
    with pytest.raises(SpedyError, match="federalTaxNumber invalido"):
        await cliente.criar_empresa({})


@pytest.mark.asyncio
async def test_adicionar_certificado_envia_multipart_com_os_campos_certos():
    cliente = SpedyClient("homologacao", "chave-empresa")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"id": "cert-1", "isActive": True})

    cliente._request = _request_falso
    await cliente.adicionar_certificado("empresa-1", b"conteudo-pfx", "senha123")

    metodo, caminho, kwargs = chamadas[0]
    assert (metodo, caminho) == ("POST", "/companies/empresa-1/certificates")
    assert kwargs["files"]["certificateFile"] == ("certificado.pfx", b"conteudo-pfx", "application/x-pkcs12")
    assert kwargs["data"] == {"password": "senha123"}


@pytest.mark.asyncio
async def test_configurar_nfse_envelopa_em_serviceinvoice():
    cliente = SpedyClient("homologacao", "chave-empresa")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"serviceInvoice": {"series": "1"}})

    cliente._request = _request_falso
    await cliente.configurar_nfse("empresa-1", {"series": "1", "environmentType": "simulation"})

    metodo, caminho, kwargs = chamadas[0]
    assert (metodo, caminho) == ("PUT", "/companies/empresa-1/settings")
    assert kwargs["json"] == {"serviceInvoice": {"series": "1", "environmentType": "simulation"}}


@pytest.mark.asyncio
async def test_cancelar_nfse_envia_delete_com_motivo():
    cliente = SpedyClient("homologacao", "chave-empresa")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"id": "nota-1", "status": "canceled"})

    cliente._request = _request_falso
    resultado = await cliente.cancelar_nfse("nota-1", "Servico nao prestado")

    assert chamadas == [("DELETE", "/service-invoices/nota-1", {"json": {"reason": "Servico nao prestado"}})]
    assert resultado["status"] == "canceled"


@pytest.mark.asyncio
async def test_baixar_pdf_devolve_bytes_em_sucesso():
    cliente = SpedyClient("homologacao", "chave-empresa")

    async def _request_falso(method, path, **kwargs):
        assert (method, path) == ("GET", "/service-invoices/nota-1/pdf")
        return _RespostaFalsa(200, b"%PDF-conteudo")

    cliente._request = _request_falso
    pdf = await cliente.baixar_pdf("nota-1")

    assert pdf == b"%PDF-conteudo"


@pytest.mark.asyncio
async def test_baixar_pdf_levanta_spedyerror_em_falha():
    cliente = SpedyClient("homologacao", "chave-empresa")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(404, b"nao encontrado")

    cliente._request = _request_falso
    with pytest.raises(SpedyError):
        await cliente.baixar_pdf("nota-1")
```

- [ ] **Step 2: Rodar os testes para confirmar que falham (módulo não existe)**

Run: `pytest tests/test_spedy_client.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.adapters.spedy_client'`

- [ ] **Step 3: Implementar `app/adapters/spedy_client.py`**

```python
"""Cliente REST da Spedy (docs.spedy.com.br) -- provedor alternativo de
emissao de NFS-e. Ao contrario de nfse_core/client.py, aqui NAO ha
montagem/assinatura de XML: a Spedy recebe dados estruturados e assina do
lado dela, usando o certificado A1 enviado uma vez no provisionamento
(ver provisionar_empresa)."""
from __future__ import annotations

import httpx

BASE_URLS = {
    "homologacao": "https://sandbox-api.spedy.com.br/v1",
    "producao": "https://api.spedy.com.br/v1",
}


class SpedyError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SpedyClient:
    def __init__(self, ambiente: str, api_key: str):
        if ambiente not in BASE_URLS:
            raise ValueError(f"Ambiente Spedy invalido: {ambiente}")
        self._client = httpx.AsyncClient(
            base_url=BASE_URLS[ambiente],
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SpedyError(f"falha de rede com a Spedy ({type(exc).__name__}): {exc}")

    # -- provisionamento (chamadas com a chave MESTRE ou a da empresa recem-criada) --

    async def criar_empresa(self, dados: dict) -> dict:
        resp = await self._request("POST", "/companies", json=dados)
        return self._handle_estrito(resp)["result"]

    async def adicionar_certificado(self, spedy_empresa_id: str, pfx_bytes: bytes, senha: str) -> dict:
        resp = await self._request(
            "POST", f"/companies/{spedy_empresa_id}/certificates",
            files={"certificateFile": ("certificado.pfx", pfx_bytes, "application/x-pkcs12")},
            data={"password": senha},
        )
        return self._handle_estrito(resp)

    async def configurar_nfse(self, spedy_empresa_id: str, dados: dict) -> dict:
        resp = await self._request(
            "PUT", f"/companies/{spedy_empresa_id}/settings", json={"serviceInvoice": dados},
        )
        return self._handle_estrito(resp)

    # -- emissao/consulta/cancelamento (chamadas com a X-Api-Key da empresa) --

    async def emitir_nfse(self, payload: dict) -> dict:
        resp = await self._request("POST", "/service-invoices", json=payload)
        return self._handle(resp)

    async def consultar_nfse(self, spedy_nota_id: str) -> dict:
        resp = await self._request("GET", f"/service-invoices/{spedy_nota_id}")
        return self._handle(resp)

    async def cancelar_nfse(self, spedy_nota_id: str, motivo: str) -> dict:
        resp = await self._request(
            "DELETE", f"/service-invoices/{spedy_nota_id}", json={"reason": motivo},
        )
        return self._handle(resp)

    async def baixar_pdf(self, spedy_nota_id: str) -> bytes:
        resp = await self._request("GET", f"/service-invoices/{spedy_nota_id}/pdf")
        if resp.status_code >= 400:
            raise SpedyError(
                f"Spedy recusou o PDF (HTTP {resp.status_code})", resp.status_code, str(resp.text)[:2000],
            )
        return resp.content

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        """Tolerante: so levanta em 5xx/resposta nao-JSON. Rejeicao de negocio
        (4xx) volta como dict com `_http_status`, pro worker interpretar --
        mesmo padrao de nfse_core/client.py."""
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if resp.status_code >= 500 or payload is None:
            raise SpedyError(
                f"Spedy indisponivel ou resposta invalida (HTTP {resp.status_code})",
                resp.status_code, str(resp.text)[:2000],
            )
        payload["_http_status"] = resp.status_code
        return payload

    @staticmethod
    def _handle_estrito(resp: httpx.Response) -> dict:
        """Usado so no provisionamento: e uma acao explicita do admin, entao
        QUALQUER erro (nao so 5xx) deve virar excecao na hora."""
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if resp.status_code >= 400 or payload is None:
            detalhe = (payload or {}).get("message") if isinstance(payload, dict) else None
            raise SpedyError(
                detalhe or f"Spedy recusou a requisicao (HTTP {resp.status_code})",
                resp.status_code, str(resp.text)[:2000],
            )
        return payload
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_spedy_client.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add app/adapters/spedy_client.py tests/test_spedy_client.py
git commit -m "feat: adiciona cliente HTTP da Spedy"
```

---

### Task 3: Provisionamento de empresa na Spedy

**Files:**
- Create: `app/adapters/spedy_provisionamento.py`
- Modify: `app/routers/empresas.py`
- Modify: `app/schemas.py`
- Test: `tests/test_spedy_provisionamento.py`
- Test: `tests/test_empresas_editar.py` (estender)

**Interfaces:**
- Consumes: `SpedyClient`, `SpedyError` (Task 2); `Empresa`, `ProvedorEmissao` (Task 1); `Settings` (Task 1).
- Produces: `provisionar_empresa(empresa: Empresa, pfx_base64: str, senha: str | None, settings: Settings) -> tuple[str, str]` (devolve `spedy_empresa_id`, `spedy_api_key`) — usado só pelo endpoint desta task, nenhuma task depende dele depois.

- [ ] **Step 1: Escrever o teste de `provisionar_empresa` — vai falhar (módulo não existe)**

Criar `tests/test_spedy_provisionamento.py`:

```python
import base64
from datetime import datetime, timezone

import pytest

from app.adapters.spedy_client import SpedyError
import app.adapters.spedy_provisionamento as provisionamento
from app.config import Settings
from app.models import AmbienteEnum, Empresa


def _settings_teste(**overrides) -> Settings:
    """Instancia nova (nao o singleton cacheado de get_settings()) -- evita
    contaminar outros testes com a chave mestre setada aqui."""
    dados = {"spedy_api_key_master_homologacao": "", "spedy_api_key_master_producao": ""}
    dados.update(overrides)
    return Settings(**dados)


def _empresa_para_provisionar(**overrides) -> Empresa:
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, razao_social="EMPRESA TESTE LTDA",
        serie="1", proximo_numero=1,
        certificado_pfx_cifrado="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    dados.update(overrides)
    return Empresa(**dados)


@pytest.mark.asyncio
async def test_provisionar_empresa_chama_os_tres_passos_na_ordem(monkeypatch):
    settings = _settings_teste(spedy_api_key_master_homologacao="chave-mestre")
    empresa = _empresa_para_provisionar()
    chamadas = []

    class _ClienteFalso:
        def __init__(self, ambiente, api_key):
            chamadas.append(("init", ambiente, api_key))

        async def criar_empresa(self, dados):
            chamadas.append(("criar_empresa", dados))
            return {"id": "empresa-1", "apiCredentials": {"apiKey": "chave-empresa"}}

        async def adicionar_certificado(self, spedy_empresa_id, pfx_bytes, senha):
            chamadas.append(("adicionar_certificado", spedy_empresa_id, pfx_bytes, senha))
            return {"id": "cert-1"}

        async def configurar_nfse(self, spedy_empresa_id, dados):
            chamadas.append(("configurar_nfse", spedy_empresa_id, dados))
            return {}

        async def close(self):
            pass

    monkeypatch.setattr(provisionamento, "SpedyClient", _ClienteFalso)

    spedy_empresa_id, api_key = await provisionamento.provisionar_empresa(
        empresa, base64.b64encode(b"conteudo-pfx").decode(), "senha123", settings,
    )

    assert spedy_empresa_id == "empresa-1"
    assert api_key == "chave-empresa"
    nomes_das_chamadas = [c[0] for c in chamadas if c[0] != "init"]
    assert nomes_das_chamadas == ["criar_empresa", "adicionar_certificado", "configurar_nfse"]
    # 1o cliente usa a chave MESTRE, os dois seguintes usam a chave da empresa recem-criada
    assert chamadas[0] == ("init", "homologacao", "chave-mestre")
    assert chamadas[2] == ("init", "homologacao", "chave-empresa")
    assert chamadas[3][2] == b"conteudo-pfx"  # pfx decodificado de base64
    assert chamadas[3][3] == "senha123"


@pytest.mark.asyncio
async def test_provisionar_empresa_sem_chave_mestre_configurada_levanta_erro_claro(monkeypatch):
    settings = _settings_teste()
    empresa = _empresa_para_provisionar()

    with pytest.raises(SpedyError, match="chave mestre"):
        await provisionamento.provisionar_empresa(empresa, base64.b64encode(b"x").decode(), None, settings)


@pytest.mark.asyncio
async def test_provisionar_empresa_sem_razao_social_levanta_erro_claro(monkeypatch):
    settings = _settings_teste(spedy_api_key_master_homologacao="chave-mestre")
    empresa = _empresa_para_provisionar(razao_social=None)

    with pytest.raises(SpedyError, match="razao_social"):
        await provisionamento.provisionar_empresa(empresa, base64.b64encode(b"x").decode(), "senha123", settings)
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `pytest tests/test_spedy_provisionamento.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/adapters/spedy_provisionamento.py`**

```python
"""Provisionamento de uma empresa na Spedy: criar o cadastro la, subir o
certificado A1 ja usado no caminho direto, e configurar a serie/numeracao.
Chamado uma unica vez, de forma sincrona e explicita, quando o admin liga
`provedor_emissao=spedy` em PUT /empresas/mim -- nunca de dentro do worker."""
from __future__ import annotations

import base64

from app.adapters.spedy_client import SpedyClient, SpedyError
from app.config import Settings
from app.models import AmbienteEnum, Empresa


def _chave_mestre(ambiente: str, settings: Settings) -> str:
    chave = (
        settings.spedy_api_key_master_producao if ambiente == "producao"
        else settings.spedy_api_key_master_homologacao
    )
    if not chave:
        raise SpedyError(f"chave mestre da Spedy nao configurada para o ambiente {ambiente}")
    return chave


async def provisionar_empresa(
    empresa: Empresa, pfx_base64: str, senha: str | None, settings: Settings,
) -> tuple[str, str]:
    if not empresa.razao_social:
        raise SpedyError("razao_social e obrigatoria para provisionar a empresa na Spedy")

    ambiente = AmbienteEnum(empresa.ambiente).value
    chave_mestre = _chave_mestre(ambiente, settings)

    cliente_mestre = SpedyClient(ambiente, chave_mestre)
    try:
        criada = await cliente_mestre.criar_empresa({
            "name": empresa.razao_social,
            "legalName": empresa.razao_social,
            "federalTaxNumber": empresa.cnpj,
            "cityTaxNumber": empresa.inscricao_municipal,
            "address": {
                "street": empresa.logradouro or "",
                "district": empresa.bairro or "",
                "postalCode": empresa.cep or "",
                "number": empresa.numero or "S/N",
                "city": {"code": empresa.municipio_ibge},
            },
        })
    finally:
        await cliente_mestre.close()

    spedy_empresa_id = criada["id"]
    api_key = criada["apiCredentials"]["apiKey"]

    cliente_empresa = SpedyClient(ambiente, api_key)
    try:
        await cliente_empresa.adicionar_certificado(
            spedy_empresa_id, base64.b64decode(pfx_base64), senha or "",
        )
        await cliente_empresa.configurar_nfse(spedy_empresa_id, {
            "series": empresa.serie,
            "environmentType": "production" if ambiente == "producao" else "simulation",
            "nextNumber": empresa.proximo_numero,
        })
    finally:
        await cliente_empresa.close()

    return spedy_empresa_id, api_key
```

- [ ] **Step 4: Rodar para confirmar que passam**

Run: `pytest tests/test_spedy_provisionamento.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Estender `EmpresaDetalheOut` em `app/schemas.py`**

Adicionar campos ao final da classe (antes de `model_config`):

```python
    razao_social: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    cep: str | None
    provedor_emissao: str
    spedy_empresa_id: str | None
```

(nunca expor `spedy_api_key_cifrada` — é segredo.)

- [ ] **Step 6: Escrever os testes do endpoint — vão falhar (campo não existe no form)**

Adicionar a `tests/test_empresas_editar.py` (mesmo arquivo, mesmo padrão de `_form_edicao`):

```python
@pytest.mark.asyncio
async def test_admin_liga_spedy_e_provisiona_a_empresa(db_session, monkeypatch):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="99988877000155")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.empresas as empresas_router

    async def _provisionar_falso(empresa_, pfx_base64, senha, settings):
        return "spedy-empresa-1", "spedy-chave-1"

    monkeypatch.setattr(empresas_router, "provisionar_empresa", _provisionar_falso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data={
                    **_form_edicao(cnpj="99988877000155"),
                    "provedor_emissao": "spedy", "razao_social": "EMPRESA TESTE LTDA",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["provedor_emissao"] == "spedy"
        assert corpo["spedy_empresa_id"] == "spedy-empresa-1"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    settings = get_settings()
    assert decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key) == "spedy-chave-1"


@pytest.mark.asyncio
async def test_ligar_spedy_com_erro_da_spedy_nao_salva_nada(db_session, monkeypatch):
    from app.adapters.spedy_client import SpedyError

    empresa, titular = await criar_empresa_titular(db_session, cnpj="99988877000155")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.empresas as empresas_router

    async def _provisionar_explodindo(empresa_, pfx_base64, senha, settings):
        raise SpedyError("federalTaxNumber invalido")

    monkeypatch.setattr(empresas_router, "provisionar_empresa", _provisionar_explodindo)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data={
                    **_form_edicao(cnpj="99988877000155"),
                    "provedor_emissao": "spedy", "razao_social": "EMPRESA TESTE LTDA",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 502
        assert "federalTaxNumber invalido" in resposta.json()["detail"]
    finally:
        app.dependency_overrides.clear()

    # A rota real usa `async with SessionLocal() as session` (app/db.py): ao
    # sair por excecao sem commit, a conexao volta pro pool e o Postgres
    # desfaz a transacao sozinho. O `_yield_session` de teste reusa a MESMA
    # sessao sem esse ciclo de vida, entao o rollback precisa ser explicito
    # aqui pra reproduzir o mesmo efeito antes de conferir o banco.
    await db_session.rollback()
    await db_session.refresh(empresa)
    assert empresa.provedor_emissao == "direto"
    assert empresa.spedy_empresa_id is None


@pytest.mark.asyncio
async def test_provedor_emissao_invalido_devolve_422(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data={**_form_edicao(), "provedor_emissao": "outro"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 7: Rodar para confirmar que falham**

Run: `pytest tests/test_empresas_editar.py -k spedy -v`
Expected: FAIL (endpoint ainda não aceita `provedor_emissao`/`razao_social`)

- [ ] **Step 8: Implementar no endpoint**

Em `app/routers/empresas.py`, ajustar imports:

```python
from app.crypto import cifrar, decifrar
from app.adapters.spedy_provisionamento import provisionar_empresa
from app.adapters.spedy_client import SpedyError
```

Em `editar_minha_empresa`, adicionar parâmetros de `Form` (junto aos existentes):

```python
    razao_social: str | None = Form(None),
    logradouro: str | None = Form(None),
    numero: str | None = Form(None),
    complemento: str | None = Form(None),
    bairro: str | None = Form(None),
    cep: str | None = Form(None),
    provedor_emissao: str = Form("direto"),
```

Logo depois da validação de `ambiente` existente:

```python
    if provedor_emissao not in ("direto", "spedy"):
        raise HTTPException(status_code=422, detail="provedor_emissao deve ser direto ou spedy")
```

Depois de atribuir os campos simples (`empresa.ambiente = ambiente`), adicionar:

```python
    empresa.razao_social = (razao_social or "").strip() or None
    empresa.logradouro = (logradouro or "").strip() or None
    empresa.numero = (numero or "").strip() or None
    empresa.complemento = (complemento or "").strip() or None
    empresa.bairro = (bairro or "").strip() or None
    empresa.cep = (cep or "").strip() or None

    precisa_provisionar = provedor_emissao == "spedy" and empresa.spedy_empresa_id is None
    empresa.provedor_emissao = provedor_emissao

    if precisa_provisionar:
        fernet_key = get_settings().fernet_key
        pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, fernet_key)
        senha_cert = (
            decifrar(empresa.certificado_senha_cifrada, fernet_key)
            if empresa.certificado_senha_cifrada else None
        )
        try:
            spedy_empresa_id, spedy_api_key = await provisionar_empresa(
                empresa, pfx_base64, senha_cert, get_settings(),
            )
        except SpedyError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        empresa.spedy_empresa_id = spedy_empresa_id
        empresa.spedy_api_key_cifrada = cifrar(spedy_api_key, fernet_key)
```

Isso precisa ficar **antes** do `try: await session.commit()` já existente, e nada é adicionado a `session` (o objeto `empresa` já está na sessão) — se `provisionar_empresa` levantar, a `HTTPException` interrompe a função antes do commit, então nenhuma mudança (nem `provedor_emissao`) é persistida.

- [ ] **Step 9: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_empresas_editar.py -v && pytest tests/test_spedy_provisionamento.py -v`
Expected: PASS (todos, incluindo os já existentes nesse arquivo — nenhuma regressão)

- [ ] **Step 10: Commit**

```bash
git add app/adapters/spedy_provisionamento.py app/routers/empresas.py app/schemas.py tests/test_spedy_provisionamento.py tests/test_empresas_editar.py
git commit -m "feat: provisiona empresa na Spedy ao ligar o provedor de emissao"
```

---

### Task 4: Emissão via Spedy no worker

**Files:**
- Create: `app/adapters/spedy_payload.py`
- Modify: `app/worker.py`
- Test: `tests/test_spedy_payload.py`
- Create: `tests/test_worker_spedy.py`

**Interfaces:**
- Consumes: `SpedyClient`, `SpedyError` (Task 2); `ProvedorEmissao`, `Empresa`, `Emissao`, `StatusEmissao` (Task 1).
- Produces: `montar_payload_spedy(empresa: Empresa, emissao: Emissao) -> dict` (usado só aqui); branch dentro de `processar_uma_pendente` que a Task 5 e o loop consomem via o novo status `aguardando_confirmacao`.

- [ ] **Step 1: Escrever o teste do mapeador de payload — vai falhar (módulo não existe)**

Criar `tests/test_spedy_payload.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from app.adapters.spedy_payload import montar_payload_spedy
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao


def _empresa(**overrides) -> Empresa:
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", codigo_tributacao_municipal=None,
        descricao_servico_padrao="Lavagem", local_prestacao_ibge=None,
    )
    dados.update(overrides)
    return Empresa(**dados)


def _emissao(**overrides) -> Emissao:
    dados = dict(
        id=uuid.uuid4(), origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem de roupa", valor=Decimal("49.90"),
        competencia=date(2026, 9, 1), tomador_cpf_cnpj=None, tomador_nome=None, tomador_email=None,
    )
    dados.update(overrides)
    return Emissao(**dados)


def test_monta_campos_basicos():
    payload = montar_payload_spedy(_empresa(), _emissao())

    assert payload["description"] == "Lavagem de roupa"
    assert payload["total"]["invoiceAmount"] == 49.90
    assert payload["city"]["code"] == "1501402"
    assert payload["location"] == "companyMunicipality"
    assert payload["federalServiceCode"] == "140106"
    assert payload["issue"] is True
    assert "receiver" not in payload
    assert "cityServiceCode" not in payload


def test_integration_id_e_o_id_da_emissao():
    emissao = _emissao()
    payload = montar_payload_spedy(_empresa(), emissao)
    assert payload["integrationId"] == str(emissao.id)


def test_usa_local_de_prestacao_quando_diferente_do_municipio_emissor():
    payload = montar_payload_spedy(_empresa(local_prestacao_ibge="3550308"), _emissao())
    assert payload["city"]["code"] == "3550308"
    assert payload["location"] == "serviceProvisionMunicipality"


def test_inclui_receiver_quando_ha_documento_do_tomador():
    emissao = _emissao(tomador_cpf_cnpj="98765432100", tomador_nome="Cliente", tomador_email="c@x.com")
    payload = montar_payload_spedy(_empresa(), emissao)
    assert payload["receiver"] == {
        "federalTaxNumber": "98765432100", "name": "Cliente", "email": "c@x.com",
    }


def test_inclui_codigo_tributacao_municipal_quando_presente():
    payload = montar_payload_spedy(_empresa(codigo_tributacao_municipal="007"), _emissao())
    assert payload["cityServiceCode"] == "007"
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `pytest tests/test_spedy_payload.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/adapters/spedy_payload.py`**

```python
"""Mapeia Empresa/Emissao para o payload de POST /service-invoices da Spedy.
Ao contrario do caminho direto (nfse_core/dps.py monta XML), aqui os dados
vao inline no JSON -- a Spedy nao exige cliente/produto pre-cadastrados."""
from __future__ import annotations

from datetime import datetime, time, timezone

from app.models import Emissao, Empresa


def montar_payload_spedy(empresa: Empresa, emissao: Emissao) -> dict:
    cidade = empresa.local_prestacao_ibge or empresa.municipio_ibge
    payload: dict = {
        "integrationId": str(emissao.id),
        "description": emissao.descricao,
        "effectiveDate": datetime.combine(emissao.competencia, time.min, tzinfo=timezone.utc).isoformat(),
        "total": {"invoiceAmount": float(emissao.valor)},
        "city": {"code": cidade},
        "location": "serviceProvisionMunicipality" if empresa.local_prestacao_ibge else "companyMunicipality",
        "taxationType": "taxationInMunicipality",
        "federalServiceCode": empresa.codigo_tributacao,
        "issue": True,
    }
    if empresa.codigo_tributacao_municipal:
        payload["cityServiceCode"] = empresa.codigo_tributacao_municipal
    if emissao.tomador_cpf_cnpj:
        payload["receiver"] = {
            "federalTaxNumber": emissao.tomador_cpf_cnpj,
            "name": emissao.tomador_nome,
            "email": emissao.tomador_email,
        }
    return payload
```

- [ ] **Step 4: Rodar para confirmar que passam**

Run: `pytest tests/test_spedy_payload.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Escrever os testes do branch no worker — vão falhar (branch não existe)**

Criar `tests/test_worker_spedy.py`:

```python
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.crypto import cifrar, hash_senha
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, ProvedorEmissao, StatusEmissao, Usuario
from app.adapters.spedy_client import SpedyError
import app.worker as worker


async def _empresa_spedy_e_emissao_pendente(db_session, **overrides_empresa) -> Emissao:
    fernet_key = get_settings().fernet_key
    titular = Usuario(email=f"titular-spedy-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, provedor_emissao=ProvedorEmissao.spedy,
        spedy_empresa_id="spedy-empresa-1",
        spedy_api_key_cifrada=cifrar("spedy-chave-1", fernet_key),
        certificado_pfx_cifrado="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    dados.update(overrides_empresa)
    empresa = Empresa(**dados)
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, tomador_cpf_cnpj="98765432100", tomador_nome="Cliente",
        descricao="Lavagem de roupa", valor=Decimal("49.90"), competencia=date(2026, 9, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_aceita_e_fica_aguardando_confirmacao(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            assert payload["integrationId"] == str(emissao.id)
            return {"_http_status": 200, "id": "nota-spedy-1", "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao
    assert emissao.spedy_nota_id == "nota-spedy-1"


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_rejeicao_sincrona(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            return {
                "_http_status": 400,
                "processingDetail": {"message": "CNPJ do tomador invalido"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert "CNPJ do tomador invalido" in erros[0]["titulo"]
    assert emissao.resposta_bruta is not None


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_falha_de_transporte(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            raise SpedyError("falha de rede com a Spedy (ConnectTimeout)")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "TRANSPORTE"


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_sem_provisionamento_marca_rejeitada(db_session):
    emissao = await _empresa_spedy_e_emissao_pendente(
        db_session, spedy_empresa_id=None, spedy_api_key_cifrada=None,
    )

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "SPEDY_NAO_PROVISIONADA"
```

- [ ] **Step 6: Rodar para confirmar que falham**

Run: `pytest tests/test_worker_spedy.py -v`
Expected: FAIL (worker ainda não importa `SpedyClient` nem faz o branch — `AttributeError: module 'app.worker' has no attribute 'SpedyClient'`)

- [ ] **Step 7: Implementar o branch em `app/worker.py`**

Ajustar os imports do topo do arquivo:

```python
from app.adapters.spedy_client import SpedyClient, SpedyError
from app.adapters.spedy_payload import montar_payload_spedy
from app.models import AmbienteEnum, Emissao, Empresa, ProvedorEmissao, StatusEmissao
```

Em `processar_uma_pendente`, logo após `empresa = await session.get(Empresa, emissao.empresa_id)`, adicionar:

```python
    if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
        return await _processar_pendente_spedy(session, emissao, empresa, settings)
```

E adicionar a função nova (antes de `processar_uma_pendente` ou logo depois — junto de `_marcar_rejeitada`):

```python
async def _processar_pendente_spedy(
    session: AsyncSession, emissao: Emissao, empresa: Empresa, settings: Settings,
) -> bool:
    if not empresa.spedy_empresa_id or not empresa.spedy_api_key_cifrada:
        await _marcar_rejeitada(
            session, emissao, "SPEDY_NAO_PROVISIONADA",
            "empresa nao esta provisionada na Spedy (edite a empresa para reconfigurar o provedor)",
        )
        return True

    try:
        api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
    except InvalidToken:
        await _marcar_rejeitada(
            session, emissao, "SPEDY_NAO_PROVISIONADA",
            "chave da Spedy cifrada com outra FERNET_KEY (reconfigure o provedor)",
        )
        return True

    payload = montar_payload_spedy(empresa, emissao)
    cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    try:
        bruta = await cliente.emitir_nfse(payload)
    except SpedyError as exc:
        await cliente.close()
        await _marcar_rejeitada(session, emissao, "TRANSPORTE", str(exc))
        return True
    await cliente.close()

    http_status = int(bruta.get("_http_status") or 0)
    if http_status >= 400:
        detalhe = (bruta.get("processingDetail") or {}).get("message") or "Spedy recusou a emissao"
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = json.dumps([{"codigo": "SPEDY", "titulo": detalhe}], ensure_ascii=False)
        emissao.resposta_bruta = json.dumps(bruta, ensure_ascii=False)
    else:
        emissao.spedy_nota_id = bruta.get("id")
        emissao.status = StatusEmissao.aguardando_confirmacao
    await session.commit()
    return True
```

`decifrar`, `InvalidToken`, `json` e `AsyncSession`/`Settings` já estão importados no arquivo (usados pelo fluxo direto existente).

- [ ] **Step 8: Rodar os testes e confirmar que passam, e que nada quebrou no resto do worker**

Run: `pytest tests/test_worker_spedy.py -v && pytest tests/test_worker.py -v`
Expected: PASS (todos)

- [ ] **Step 9: Commit**

```bash
git add app/adapters/spedy_payload.py app/worker.py tests/test_spedy_payload.py tests/test_worker_spedy.py
git commit -m "feat: emite NFS-e via Spedy no worker quando o provedor esta configurado"
```

---

### Task 5: Confirmação assíncrona de emissão via Spedy

**Files:**
- Create: `app/adapters/spedy_resposta.py`
- Modify: `app/worker.py`
- Test: `tests/test_spedy_resposta.py`
- Modify: `tests/test_worker_spedy.py` (estender)

**Interfaces:**
- Consumes: `SpedyClient`, `SpedyError` (Task 2); tudo de Task 4.
- Produces: `interpretar_status_emissao(bruta: dict) -> str` (`"authorized"`, `"rejected"` ou `"pending"`), `chave_acesso_de(bruta: dict) -> str | None`; `processar_uma_aguardando_confirmacao_spedy(session, settings=None) -> bool`, adicionada ao `loop_worker`.

- [ ] **Step 1: Escrever o teste do parser de status — vai falhar (módulo não existe)**

Criar `tests/test_spedy_resposta.py`:

```python
from app.adapters.spedy_resposta import chave_acesso_de, interpretar_status_emissao


def test_interpreta_autorizada():
    assert interpretar_status_emissao({"status": "authorized"}) == "authorized"


def test_interpreta_rejeitada():
    assert interpretar_status_emissao({"status": "rejected"}) == "rejected"
    assert interpretar_status_emissao({"status": "denied"}) == "rejected"


def test_interpreta_ainda_processando():
    assert interpretar_status_emissao({"status": "enqueued"}) == "pending"
    assert interpretar_status_emissao({"status": "processing"}) == "pending"
    assert interpretar_status_emissao({}) == "pending"


def test_chave_acesso_tenta_varios_campos():
    assert chave_acesso_de({"accessKey": "abc"}) == "abc"
    assert chave_acesso_de({"chaveAcesso": "def"}) == "def"
    assert chave_acesso_de({}) is None
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `pytest tests/test_spedy_resposta.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/adapters/spedy_resposta.py`**

```python
"""Leitura tolerante das respostas da Spedy -- mesmo espirito de
nfse_core/resposta.py. Os nomes de campo do estado FINAL (autorizada) nao
estao 100% confirmados pela documentacao publica; ajustar as chaves
candidatas abaixo apos a validacao ao vivo com o sandbox (Task 5, ultimo
passo deste arquivo do plano)."""
from __future__ import annotations


def interpretar_status_emissao(bruta: dict) -> str:
    """Devolve "authorized", "rejected" ou "pending" (qualquer outro status
    da Spedy, incluindo "enqueued"/"processing"/campo ausente)."""
    status = bruta.get("status")
    if status == "authorized":
        return "authorized"
    if status in ("rejected", "denied"):
        return "rejected"
    return "pending"


def chave_acesso_de(bruta: dict) -> str | None:
    for chave in ("accessKey", "chaveAcesso", "nfseAccessKey", "number"):
        valor = bruta.get(chave)
        if valor:
            return str(valor)
    return None
```

- [ ] **Step 4: Rodar para confirmar que passam**

Run: `pytest tests/test_spedy_resposta.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Escrever os testes de `processar_uma_aguardando_confirmacao_spedy` — vão falhar (função não existe)**

Adicionar a `tests/test_worker_spedy.py`:

```python
async def _emissao_aguardando_confirmacao(db_session) -> Emissao:
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.aguardando_confirmacao
    emissao.spedy_nota_id = "nota-spedy-1"
    await db_session.commit()
    return emissao


@pytest.mark.asyncio
async def test_confirmacao_spedy_marca_autorizada(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            assert spedy_nota_id == "nota-spedy-1"
            return {"_http_status": 200, "status": "authorized", "accessKey": "chave-final-1"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "chave-final-1"


@pytest.mark.asyncio
async def test_confirmacao_spedy_marca_rejeitada(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {
                "_http_status": 200, "status": "rejected",
                "processingDetail": {"code": "SPD123", "message": "servico invalido"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "SPD123"


@pytest.mark.asyncio
async def test_confirmacao_spedy_ainda_processando_nao_conta_como_trabalho(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao


@pytest.mark.asyncio
async def test_processar_uma_aguardando_confirmacao_spedy_devolve_falso_quando_fila_vazia(db_session):
    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)
    assert processou is False
```

- [ ] **Step 6: Rodar para confirmar que falham**

Run: `pytest tests/test_worker_spedy.py -k confirmacao_spedy -v`
Expected: FAIL com `AttributeError: module 'app.worker' has no attribute 'processar_uma_aguardando_confirmacao_spedy'`

- [ ] **Step 7: Implementar `processar_uma_aguardando_confirmacao_spedy` e ligar no loop**

Ajustar o import em `app/worker.py`:

```python
from app.adapters.spedy_resposta import chave_acesso_de, interpretar_status_emissao
```

Adicionar a função (perto de `processar_uma_pendente`):

```python
async def processar_uma_aguardando_confirmacao_spedy(
    session: AsyncSession, settings: Settings | None = None,
) -> bool:
    """Consulta o resultado final de uma emissao Spedy ainda pendente de
    confirmacao. So conta como "trabalho feito" (True) quando o status vira
    terminal -- assim o loop respeita o intervalo normal entre tentativas em
    vez de martelar a Spedy sem pausa enquanto a nota ainda processa."""
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.aguardando_confirmacao)
        .order_by(Emissao.criada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)
    try:
        api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
    except InvalidToken:
        await _marcar_rejeitada(
            session, emissao, "SPEDY_NAO_PROVISIONADA",
            "chave da Spedy cifrada com outra FERNET_KEY (reconfigure o provedor)",
        )
        return True

    cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    try:
        bruta = await cliente.consultar_nfse(emissao.spedy_nota_id)
    except SpedyError as exc:
        await cliente.close()
        logger.warning("falha ao consultar emissao %s na Spedy: %s", emissao.id, exc)
        return False
    await cliente.close()

    status = interpretar_status_emissao(bruta)
    if status == "authorized":
        emissao.status = StatusEmissao.autorizada
        emissao.chave_acesso = chave_acesso_de(bruta)
        await session.commit()
        return True
    if status == "rejected":
        detalhe = bruta.get("processingDetail") or {}
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = json.dumps(
            [{"codigo": detalhe.get("code") or "SPEDY", "titulo": detalhe.get("message") or "Emissao rejeitada pela Spedy"}],
            ensure_ascii=False,
        )
        emissao.resposta_bruta = json.dumps(bruta, ensure_ascii=False)
        await session.commit()
        return True
    return False
```

Em `loop_worker`, adicionar a terceira checagem:

```python
async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        try:
            async with session_factory() as session:
                processou_emissao = await processar_uma_pendente(session)
            async with session_factory() as session:
                processou_cancelamento = await processar_um_cancelamento_pendente(session)
            async with session_factory() as session:
                processou_confirmacao_spedy = await processar_uma_aguardando_confirmacao_spedy(session)
        except Exception:
            logger.exception("falha inesperada ao processar fila pendente; o loop continua")
            processou_emissao = False
            processou_cancelamento = False
            processou_confirmacao_spedy = False
        if not processou_emissao and not processou_cancelamento and not processou_confirmacao_spedy:
            await asyncio.sleep(intervalo_segundos)
```

- [ ] **Step 8: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_worker_spedy.py -v && pytest tests/test_worker.py -v`
Expected: PASS (todos)

- [ ] **Step 9: Validação ao vivo contra o sandbox (usa a chave já fornecida pelo usuário)**

Definir a chave localmente (nunca commitar): `export SPEDY_API_KEY_EMPRESA="c54514d7-9eb4-4aee-b34c-73ae1e2b1931"` (é a chave da empresa padrão do sandbox, `73856754-2f7f-48d3-bf86-b4c600dc9d00`, já em Belém).

Rodar (fora da suíte de testes, um script pontual, não commitado):

```bash
python -c "
import asyncio
import os
from app.adapters.spedy_client import SpedyClient

async def main():
    cliente = SpedyClient('homologacao', os.environ['SPEDY_API_KEY_EMPRESA'])
    resultado = await cliente.emitir_nfse({
        'integrationId': 'teste-plano-spedy-1',
        'description': 'Teste de integracao',
        'effectiveDate': '2026-09-15T00:00:00Z',
        'total': {'invoiceAmount': 10.0},
        'city': {'code': '1501402'},
        'location': 'companyMunicipality',
        'federalServiceCode': '140106',
        'issue': True,
    })
    print('emissao:', resultado)
    nota_id = resultado['id']
    for _ in range(5):
        await asyncio.sleep(3)
        status = await cliente.consultar_nfse(nota_id)
        print('status:', status)
        if status.get('status') in ('authorized', 'rejected', 'denied'):
            break
    await cliente.close()

asyncio.run(main())
"
```

Comparar os nomes de campo reais da resposta final contra `interpretar_status_emissao`/`chave_acesso_de`. Se algum nome divergir (ex.: a chave de acesso vier num campo diferente dos já cobertos), ajustar a lista de `chave_acesso_de` em `app/adapters/spedy_resposta.py` e adicionar um comentário citando o achado real (mesmo padrão de `nfse_core/client.py`), depois rodar `pytest tests/test_spedy_resposta.py -v` de novo.

- [ ] **Step 10: Commit**

```bash
git add app/adapters/spedy_resposta.py app/worker.py tests/test_spedy_resposta.py tests/test_worker_spedy.py
git commit -m "feat: resolve a confirmacao assincrona de emissao via Spedy no worker"
```

---

### Task 6: Cancelamento via Spedy

**Files:**
- Modify: `app/models.py` (já coberto na Task 1 — `cancelamento_aguardando_confirmacao`)
- Modify: `app/worker.py`
- Modify: `tests/test_worker_spedy.py`

**Interfaces:**
- Consumes: tudo das Tasks 2, 4, 5.
- Produces: branch em `processar_um_cancelamento_pendente`; `processar_um_cancelamento_aguardando_confirmacao_spedy(session, settings=None) -> bool`, adicionada ao `loop_worker`.

- [ ] **Step 1: Escrever os testes — vão falhar (branch/função não existem)**

Adicionar a `tests/test_worker_spedy.py`:

```python
async def _emissao_cancelamento_pendente_spedy(db_session) -> Emissao:
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.chave_acesso = "chave-final-1"
    emissao.spedy_nota_id = "nota-spedy-1"
    emissao.motivo_cancelamento = "Servico nao prestado"
    await db_session.commit()
    return emissao


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_fica_aguardando_confirmacao(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            assert spedy_nota_id == "nota-spedy-1"
            assert motivo == "Servico nao prestado"
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_falha_de_transporte(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            raise SpedyError("falha de rede")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_marca_cancelada(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceled"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelada
    assert emissao.cancelada_em is not None


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_ainda_processando_nao_conta_como_trabalho(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao
```

- [ ] **Step 2: Rodar para confirmar que falham**

Run: `pytest tests/test_worker_spedy.py -k cancelamento -v`
Expected: FAIL (branch/`processar_um_cancelamento_aguardando_confirmacao_spedy` não existem)

- [ ] **Step 3: Implementar no worker**

Em `processar_um_cancelamento_pendente`, logo após `empresa = await session.get(Empresa, emissao.empresa_id)`, adicionar:

```python
    if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
        return await _processar_cancelamento_pendente_spedy(session, emissao, empresa, settings)
```

Adicionar as duas funções novas (perto de `_marcar_erro_cancelamento`):

```python
async def _processar_cancelamento_pendente_spedy(
    session: AsyncSession, emissao: Emissao, empresa: Empresa, settings: Settings,
) -> bool:
    try:
        api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
    except InvalidToken:
        await _marcar_erro_cancelamento(
            session, emissao, "SPEDY_NAO_PROVISIONADA",
            "chave da Spedy cifrada com outra FERNET_KEY (reconfigure o provedor)",
        )
        return True

    cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    try:
        await cliente.cancelar_nfse(emissao.spedy_nota_id, emissao.motivo_cancelamento or "")
    except SpedyError as exc:
        await cliente.close()
        await _marcar_erro_cancelamento(session, emissao, "TRANSPORTE", str(exc))
        return True
    await cliente.close()

    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await session.commit()
    return True


async def processar_um_cancelamento_aguardando_confirmacao_spedy(
    session: AsyncSession, settings: Settings | None = None,
) -> bool:
    """Espelha processar_uma_aguardando_confirmacao_spedy: o cancelamento na
    Spedy tambem e assincrono (confirmado na doc oficial -- DELETE
    /service-invoices/{id} processa ate o status "canceled")."""
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao)
        .order_by(Emissao.criada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)
    try:
        api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
    except InvalidToken:
        await _marcar_erro_cancelamento(
            session, emissao, "SPEDY_NAO_PROVISIONADA",
            "chave da Spedy cifrada com outra FERNET_KEY (reconfigure o provedor)",
        )
        return True

    cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    try:
        bruta = await cliente.consultar_nfse(emissao.spedy_nota_id)
    except SpedyError as exc:
        await cliente.close()
        logger.warning("falha ao consultar cancelamento %s na Spedy: %s", emissao.id, exc)
        return False
    await cliente.close()

    if bruta.get("status") == "canceled":
        emissao.status = StatusEmissao.cancelada
        emissao.cancelada_em = datetime.now(timezone.utc)
        await session.commit()
        return True
    return False
```

Em `loop_worker`, adicionar a quarta checagem:

```python
async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        try:
            async with session_factory() as session:
                processou_emissao = await processar_uma_pendente(session)
            async with session_factory() as session:
                processou_cancelamento = await processar_um_cancelamento_pendente(session)
            async with session_factory() as session:
                processou_confirmacao_spedy = await processar_uma_aguardando_confirmacao_spedy(session)
            async with session_factory() as session:
                processou_confirmacao_cancel_spedy = await processar_um_cancelamento_aguardando_confirmacao_spedy(session)
        except Exception:
            logger.exception("falha inesperada ao processar fila pendente; o loop continua")
            processou_emissao = False
            processou_cancelamento = False
            processou_confirmacao_spedy = False
            processou_confirmacao_cancel_spedy = False
        if not any([
            processou_emissao, processou_cancelamento,
            processou_confirmacao_spedy, processou_confirmacao_cancel_spedy,
        ]):
            await asyncio.sleep(intervalo_segundos)
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest tests/test_worker_spedy.py -v && pytest tests/test_worker.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Validação ao vivo do cancelamento contra o sandbox**

Usando a `nota_id` de uma emissão autorizada no sandbox (Task 5, Step 9), rodar um script equivalente chamando `cliente.cancelar_nfse(nota_id, "teste do plano")` e depois `consultar_nfse` em loop até `status == "canceled"`, confirmando que o campo realmente usado é `status` (não outro nome). Ajustar `processar_um_cancelamento_aguardando_confirmacao_spedy` se divergir, com um comentário citando o achado.

- [ ] **Step 6: Commit**

```bash
git add app/worker.py tests/test_worker_spedy.py
git commit -m "feat: cancela NFS-e via Spedy no worker, incluindo confirmacao assincrona"
```

---

### Task 7: Download de PDF via Spedy

**Files:**
- Modify: `app/routers/emissoes.py`
- Modify: `tests/test_emissoes_download.py`

**Interfaces:**
- Consumes: `SpedyClient`, `SpedyError` (Task 2).
- Produces: branch em `GET /emissoes/{id}/pdf` — nenhuma task depende disso depois (é o fim da cadeia).

- [ ] **Step 1: Escrever o teste — vai falhar (branch não existe)**

Adicionar a `tests/test_emissoes_download.py`:

```python
@pytest.mark.asyncio
async def test_baixar_pdf_usa_spedy_quando_esse_e_o_provedor(db_session, monkeypatch):
    from app.models import ProvedorEmissao

    fernet_key = get_settings().fernet_key
    empresa, usuario = await criar_empresa_titular(
        db_session,
        provedor_emissao=ProvedorEmissao.spedy,
        spedy_api_key_cifrada=cifrar("spedy-chave-1", fernet_key),
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-final-1", spedy_nota_id="nota-spedy-1",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.emissoes as emissoes_router

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def baixar_pdf(self, spedy_nota_id):
            assert spedy_nota_id == "nota-spedy-1"
            return b"%PDF-da-spedy"

        async def close(self):
            pass

    monkeypatch.setattr(emissoes_router, "SpedyClient", ClienteFalso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/pdf", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content == b"%PDF-da-spedy"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_pdf_via_spedy_cai_no_fallback_quando_spedy_falha(db_session, monkeypatch):
    from app.models import ProvedorEmissao

    fernet_key = get_settings().fernet_key
    empresa, usuario = await criar_empresa_titular(
        db_session,
        provedor_emissao=ProvedorEmissao.spedy,
        spedy_api_key_cifrada=cifrar("spedy-chave-1", fernet_key),
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-final-1", spedy_nota_id="nota-spedy-1",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.emissoes as emissoes_router

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def baixar_pdf(self, spedy_nota_id):
            raise RuntimeError("Spedy indisponivel")

        async def close(self):
            pass

    monkeypatch.setattr(emissoes_router, "SpedyClient", ClienteFalso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/pdf", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content.startswith(b"%PDF")
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Rodar para confirmar que falham**

Run: `pytest tests/test_emissoes_download.py -k spedy -v`
Expected: FAIL (endpoint ainda não conhece `SpedyClient`)

- [ ] **Step 3: Implementar no endpoint**

Em `app/routers/emissoes.py`, ajustar imports (`decifrar` já está importado — só falta `SpedyClient` e `ProvedorEmissao`):

```python
from app.adapters.spedy_client import SpedyClient
from app.models import AmbienteEnum, Cliente, Emissao, Empresa, OrigemEmissao, ProvedorEmissao, StatusEmissao
```

Substituir o bloco `try/except` de busca do PDF dentro de `baixar_pdf` (a partir de `try:` na linha 148 do arquivo atual) por:

```python
    try:
        if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
            api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
            cliente_spedy = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
            try:
                pdf = await cliente_spedy.baixar_pdf(emissao.spedy_nota_id)
            finally:
                await cliente_spedy.close()
        else:
            pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
            senha = (
                decifrar(empresa.certificado_senha_cifrada, settings.fernet_key)
                if empresa.certificado_senha_cifrada
                else None
            )
            pdf = await SefinClient.fetch_danfse_pdf(
                AmbienteEnum(empresa.ambiente).value, pfx_base64, senha, emissao.chave_acesso
            )
    except Exception:
        logger.warning(
            "falha ao buscar o DANFSe oficial da emissao %s; usando o fallback local",
            emissao.id, exc_info=True,
        )
        pdf = None
```

(o restante da função — `if pdf is None: pdf = gerar_danfse_fallback(...)` — continua igual.)

- [ ] **Step 4: Rodar os testes e confirmar que passam, sem regressão no resto do arquivo**

Run: `pytest tests/test_emissoes_download.py -v`
Expected: PASS (todos, incluindo os testes do fluxo direto já existentes)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `pytest tests/ -q`
Expected: PASS (nenhuma regressão em nenhum arquivo)

- [ ] **Step 6: Commit**

```bash
git add app/routers/emissoes.py tests/test_emissoes_download.py
git commit -m "feat: baixa PDF via Spedy quando esse e o provedor configurado"
```

---

## Pendências pós-implementação (fora deste plano)

- Configurar `spedy_api_key_master_homologacao`/`spedy_api_key_master_producao` no `.env` de cada ambiente (nunca em `.env.example`).
- Regenerar a chave sandbox usada nas validações ao vivo (Tasks 5 e 6), já que foi compartilhada em texto na conversa.
- Nenhuma emissão real em Spedy produção antes do usuário contratar e confirmar — mesmo princípio já seguido no caminho direto.

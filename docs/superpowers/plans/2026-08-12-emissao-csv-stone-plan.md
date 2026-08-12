# Emissão de NFS-e a partir do CSV de recebimentos da Stone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o usuário suba o relatório CSV de recebimentos da Stone e, após conferir uma prévia (contagem de notas e valor total), confirme a criação das emissões correspondentes — reaproveitando o pipeline de numeração e o worker já existentes.

**Architecture:** Um parser puro (sem I/O, sem banco) lê o CSV e devolve as "notas candidatas" já filtradas e agrupadas; dois endpoints HTTP (`preview` e `confirmar`) usam esse parser e decidem, respectivamente, apenas relatar ou também persistir. Nenhuma tabela nova — reaproveita `Emissao` (um novo valor de `origem`) e o campo `stone_charge_id` já existente para deduplicação.

**Tech Stack:** Python 3.12, FastAPI (`UploadFile`/multipart), csv (stdlib), Decimal, o mesmo stack já usado no resto do projeto (SQLAlchemy async, PostgreSQL, pytest + pytest-asyncio, httpx `ASGITransport`).

## Global Constraints

- Ver spec completa em `docs/superpowers/specs/2026-08-12-emissao-csv-stone-design.md` e a spec anterior (webhook, adiada) em `docs/superpowers/specs/2026-08-11-nfse-stone-webhook-design.md`.
- Valor da nota = `VALOR BRUTO` da planilha, **nunca** `VALOR LÍQUIDO`.
- Só linhas com `ÚLTIMO STATUS` = `Pago` e `CATEGORIA` = `Venda` geram nota; as demais são contadas e reportadas, nunca silenciosamente descartadas.
- `QTD DE PARCELAS` > 1: agrupar por `DATA DA VENDA` + `QTD DE PARCELAS`, somar `VALOR BRUTO` do grupo, uma nota por grupo. **Não verificado contra um exemplo real de venda parcelada** — todo teste deste plano que exercita esse caminho usa dados sintéticos, não um exemplo real do relatório da Stone.
- Deduplicação usa o `STONE ID` da linha (ou da parcela nº 1 do grupo) gravado em `Emissao.stone_charge_id` — o mesmo campo, o mesmo índice único por empresa, que a idempotência do webhook (spec anterior) já usa.
- `preview` nunca grava nada no banco — nem `Emissao`, nem avanço de `proximo_numero`.
- Numeração é sempre obtida via `reservar_proximo_numero` (`UPDATE ... RETURNING` transacional) — nunca outro padrão.
- Todo endpoint autenticado escopa dados pelo `empresa_id` do usuário logado (`Depends(get_current_user)`), nunca por um valor vindo do cliente.
- Cabeçalho do arquivo que não contém as colunas obrigatórias rejeita o arquivo inteiro (400) **antes** de processar qualquer linha — não tenta adivinhar nomes de coluna parecidos.
- Arquivo em codificação diferente de UTF-8 (com ou sem BOM) é rejeitado (400) — o relatório oficial da Stone usado como referência é UTF-8 com BOM.

---

## Estrutura de arquivos

```
app/
  adapters/
    stone_csv.py          # NOVO — parser puro: NotaCandidata, ResultadoParse,
                           # CabecalhoInvalidoError, parsear_relatorio_stone()
  models.py                # MODIFICADO — OrigemEmissao ganha o valor "csv"
  routers/
    emissoes.py             # MODIFICADO — acrescenta POST /emissoes/csv/preview
                             # e POST /emissoes/csv/confirmar (já registrado em
                             # app/main.py desde a Task 8 do plano anterior —
                             # nenhuma mudança em main.py é necessária)
tests/
  test_adapters_stone_csv.py   # NOVO — testes do parser, sem banco
  test_emissoes_csv.py          # NOVO — testes HTTP dos dois endpoints, banco real
```

---

### Task 1: Parser do relatório CSV da Stone

**Files:**
- Create: `app/adapters/stone_csv.py`
- Test: `tests/test_adapters_stone_csv.py`

**Interfaces:**
- Produces:
  - `NotaCandidata` (dataclass): `stone_charge_id: str`, `data_da_venda: datetime`, `valor: Decimal`.
  - `ResultadoParse` (dataclass): `notas: list[NotaCandidata]`, `ignoradas: dict[str, int]` — chaves sempre presentes: `"status_nao_pago"`, `"categoria_nao_venda"`, `"linha_invalida"` (a quarta chave, `"ja_emitida_anteriormente"`, é adicionada depois pelo router na Task 2 — o parser não sabe o que já foi emitido, não tem acesso a banco).
  - `CabecalhoInvalidoError(ValueError)`.
  - `parsear_relatorio_stone(conteudo: bytes) -> ResultadoParse` — função pura, sem I/O, sem banco. Levanta `CabecalhoInvalidoError` se o arquivo não for UTF-8 válido, ou se faltar alguma das colunas obrigatórias no cabeçalho.

- [ ] **Step 1: Escrever o teste**

```python
from datetime import datetime
from decimal import Decimal

import pytest

from app.adapters.stone_csv import CabecalhoInvalidoError, parsear_relatorio_stone

CABECALHO = "CATEGORIA;DATA DA VENDA;STONE ID;QTD DE PARCELAS;Nº DA PARCELA;VALOR BRUTO;ÚLTIMO STATUS"


def _csv(*linhas: str) -> bytes:
    conteudo = "﻿" + "\n".join([CABECALHO, *linhas]) + "\n"
    return conteudo.encode("utf-8")


def test_parsear_linha_valida_unica_gera_uma_nota():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 1
    nota = resultado.notas[0]
    assert nota.stone_charge_id == "31163337249888"
    assert nota.data_da_venda == datetime(2026, 7, 30, 14, 30, 4)
    assert nota.valor == Decimal("27.980000")
    assert resultado.ignoradas == {
        "status_nao_pago": 0, "categoria_nao_venda": 0, "linha_invalida": 0,
    }


def test_parsear_ignora_linha_com_status_diferente_de_pago():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Estornado"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["status_nao_pago"] == 1


def test_parsear_ignora_linha_com_categoria_diferente_de_venda():
    conteudo = _csv(
        "Ajuste Financeiro;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["categoria_nao_venda"] == 1


def test_parsear_agrupa_parcelas_da_mesma_venda_somando_o_valor():
    conteudo = _csv(
        "Venda;22/07/2026 18:17:45;31063343476401;3;1;41,970000;Pago",
        "Venda;22/07/2026 18:17:45;31063343476402;3;2;41,970000;Pago",
        "Venda;22/07/2026 18:17:45;31063343476403;3;3;41,960000;Pago",
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 1
    nota = resultado.notas[0]
    # chave de dedupe vem da parcela numero 1 do grupo, nao da ultima linha lida
    assert nota.stone_charge_id == "31063343476401"
    assert nota.valor == Decimal("125.900000")


def test_parsear_nao_agrupa_vendas_distintas_com_mesma_data_e_qtd_parcelas_diferente():
    conteudo = _csv(
        "Venda;22/07/2026 18:17:45;31063343476401;1;1;10,000000;Pago",
        "Venda;22/07/2026 18:17:45;31063343476402;1;1;20,000000;Pago",
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 2


def test_parsear_ignora_linha_com_valor_invalido():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;nao-e-um-numero;Pago"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["linha_invalida"] == 1


def test_parsear_ignora_linha_com_data_invalida():
    conteudo = _csv(
        "Venda;30-07-2026;31163337249888;1;1;27,980000;Pago"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["linha_invalida"] == 1


def test_parsear_arquivo_sem_coluna_obrigatoria_levanta_erro():
    conteudo = "﻿CATEGORIA;DATA DA VENDA\nVenda;30/07/2026 14:30:04\n".encode("utf-8")

    with pytest.raises(CabecalhoInvalidoError):
        parsear_relatorio_stone(conteudo)


def test_parsear_arquivo_fora_de_utf8_levanta_erro():
    conteudo = "CATEGORIA;DATA DA VENDA".encode("utf-16")

    with pytest.raises(CabecalhoInvalidoError):
        parsear_relatorio_stone(conteudo)


def test_parsear_arquivo_vazio_nao_gera_notas_nem_erro():
    conteudo = _csv()

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas == {
        "status_nao_pago": 0, "categoria_nao_venda": 0, "linha_invalida": 0,
    }
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_adapters_stone_csv.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.adapters.stone_csv'`

- [ ] **Step 3: Implementar `app/adapters/stone_csv.py`**

```python
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

COLUNAS_OBRIGATORIAS = (
    "CATEGORIA",
    "DATA DA VENDA",
    "STONE ID",
    "QTD DE PARCELAS",
    "Nº DA PARCELA",
    "VALOR BRUTO",
    "ÚLTIMO STATUS",
)


class CabecalhoInvalidoError(ValueError):
    """Arquivo nao esta em UTF-8, ou falta coluna obrigatoria no cabecalho."""


@dataclass
class NotaCandidata:
    stone_charge_id: str
    data_da_venda: datetime
    valor: Decimal


@dataclass
class ResultadoParse:
    notas: list[NotaCandidata]
    ignoradas: dict[str, int] = field(
        default_factory=lambda: {
            "status_nao_pago": 0, "categoria_nao_venda": 0, "linha_invalida": 0,
        }
    )


def parsear_relatorio_stone(conteudo: bytes) -> ResultadoParse:
    """Le o relatorio de recebimentos da Stone (CSV, ';', UTF-8 com BOM).

    Nao acessa banco: nao sabe se uma nota ja foi emitida antes (isso e
    responsabilidade de quem chama, que tem acesso ao banco). Nao levanta
    excecao por causa de uma linha invalida — so por cabecalho incompativel
    ou encoding errado, que invalidam o arquivo inteiro.
    """
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CabecalhoInvalidoError(f"arquivo nao esta em UTF-8: {exc}") from exc

    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    colunas_presentes = set(leitor.fieldnames or [])
    faltando = set(COLUNAS_OBRIGATORIAS) - colunas_presentes
    if faltando:
        raise CabecalhoInvalidoError(
            f"colunas obrigatorias ausentes no cabecalho: {sorted(faltando)}"
        )

    resultado = ResultadoParse(notas=[])
    grupos: dict[tuple, list[tuple[int, str, Decimal, datetime]]] = {}
    ordem_grupos: list[tuple] = []

    for linha in leitor:
        try:
            status = linha["ÚLTIMO STATUS"].strip()
            categoria = linha["CATEGORIA"].strip()
            if status != "Pago":
                resultado.ignoradas["status_nao_pago"] += 1
                continue
            if categoria != "Venda":
                resultado.ignoradas["categoria_nao_venda"] += 1
                continue
            data_da_venda = datetime.strptime(
                linha["DATA DA VENDA"].strip(), "%d/%m/%Y %H:%M:%S"
            )
            valor = Decimal(linha["VALOR BRUTO"].strip().replace(",", "."))
            qtd_parcelas = int(linha["QTD DE PARCELAS"].strip())
            numero_parcela = int(linha["Nº DA PARCELA"].strip())
            stone_id = linha["STONE ID"].strip()
            if not stone_id:
                raise ValueError("STONE ID vazio")
        except (KeyError, ValueError, InvalidOperation):
            resultado.ignoradas["linha_invalida"] += 1
            continue

        if qtd_parcelas <= 1:
            chave = ("unico", stone_id)
        else:
            chave = ("grupo", data_da_venda.isoformat(), qtd_parcelas)

        if chave not in grupos:
            grupos[chave] = []
            ordem_grupos.append(chave)
        grupos[chave].append((numero_parcela, stone_id, valor, data_da_venda))

    for chave in ordem_grupos:
        itens = sorted(grupos[chave], key=lambda item: item[0])
        _numero_parcela, stone_charge_id, _valor, data_da_venda = itens[0]
        valor_total = sum((item[2] for item in itens), Decimal("0"))
        resultado.notas.append(
            NotaCandidata(
                stone_charge_id=stone_charge_id,
                data_da_venda=data_da_venda,
                valor=valor_total,
            )
        )

    return resultado
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `pytest tests/test_adapters_stone_csv.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add app/adapters/stone_csv.py tests/test_adapters_stone_csv.py
git commit -m "feat: parser do relatorio de recebimentos CSV da Stone"
```

---

### Task 2: Endpoints de preview e confirmação de importação CSV

**Files:**
- Modify: `app/models.py:33-35` (acrescenta `csv = "csv"` a `OrigemEmissao`)
- Modify: `app/routers/emissoes.py` (acrescenta `POST /emissoes/csv/preview` e `POST /emissoes/csv/confirmar`)
- Test: `tests/test_emissoes_csv.py`

**Interfaces:**
- Consumes: `app.adapters.stone_csv.parsear_relatorio_stone`, `NotaCandidata`, `ResultadoParse`, `CabecalhoInvalidoError` (Task 1); `app.numeracao.reservar_proximo_numero`; `app.security.get_current_user`; `app.models.Emissao`, `Empresa`, `OrigemEmissao`, `StatusEmissao`, `Usuario`.
- Produces: `POST /emissoes/csv/preview` e `POST /emissoes/csv/confirmar`, ambos multipart (`arquivo: UploadFile`), ambos devolvendo `{"total_notas": int, "valor_total": str, "ignoradas": {"status_nao_pago": int, "categoria_nao_venda": int, "linha_invalida": int, "ja_emitida_anteriormente": int}}`. Nenhuma migração Alembic necessária — `Emissao.origem` é uma coluna `String` pura (sem `CHECK` de banco), então um novo valor de enum no lado Python não muda o schema.

- [ ] **Step 1: Escrever o teste**

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import (
    AmbienteEnum, Emissao, Empresa, OrigemEmissao, PapelUsuario, StatusEmissao, Usuario,
)
from app.security import criar_token

CABECALHO = "CATEGORIA;DATA DA VENDA;STONE ID;QTD DE PARCELAS;Nº DA PARCELA;VALOR BRUTO;ÚLTIMO STATUS"


def _csv(*linhas: str) -> bytes:
    conteudo = "﻿" + "\n".join([CABECALHO, *linhas]) + "\n"
    return conteudo.encode("utf-8")


async def _yield_session(session):
    yield session


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem de roupa",
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


@pytest.mark.asyncio
async def test_preview_csv_nao_grava_nada_e_devolve_resumo_correto(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago",
        "Venda;30/07/2026 17:00:47;31163341016913;1;1;13,990000;Pago",
        "Ajuste Financeiro;30/07/2026 10:00:00;31163300000000;1;1;5,000000;Pago",
        "Venda;30/07/2026 10:00:00;31163300000001;1;1;5,000000;Estornado",
    )

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/csv/preview",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total_notas"] == 2
        assert corpo["valor_total"] == "41.97"
        assert corpo["ignoradas"] == {
            "status_nao_pago": 1, "categoria_nao_venda": 1,
            "linha_invalida": 0, "ja_emitida_anteriormente": 0,
        }
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert total == []
    await db_session.refresh(empresa)
    assert empresa.proximo_numero == 1


@pytest.mark.asyncio
async def test_confirmar_csv_cria_emissoes_pendentes_com_numero_reservado(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago",
        "Venda;30/07/2026 17:00:47;31163341016913;1;1;13,990000;Pago",
    )

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total_notas"] == 2
        assert corpo["valor_total"] == "41.97"
    finally:
        app.dependency_overrides.clear()

    emissoes = (
        await db_session.execute(
            select(Emissao)
            .where(Emissao.empresa_id == empresa.id)
            .order_by(Emissao.numero)
        )
    ).scalars().all()
    assert len(emissoes) == 2
    assert [e.numero for e in emissoes] == [1, 2]
    assert [e.serie for e in emissoes] == ["1", "1"]
    assert {e.origem for e in emissoes} == {OrigemEmissao.csv}
    assert {e.status for e in emissoes} == {StatusEmissao.pendente}
    assert {e.stone_charge_id for e in emissoes} == {"31163337249888", "31163341016913"}
    assert {e.descricao for e in emissoes} == {"Lavagem de roupa"}
    assert {e.valor for e in emissoes} == {Decimal("27.98"), Decimal("13.99")}
    assert {e.competencia.isoformat() for e in emissoes} == {"2026-07-01"}


@pytest.mark.asyncio
async def test_confirmar_csv_duas_vezes_nao_duplica_nem_reserva_numero_de_novo(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago")

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
            segunda = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert primeira.json()["total_notas"] == 1
        assert segunda.json()["total_notas"] == 0
        assert segunda.json()["ignoradas"]["ja_emitida_anteriormente"] == 1
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == "31163337249888"
            )
        )
    ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_confirmar_csv_nao_cruza_dedupe_nem_visibilidade_entre_empresas(db_session):
    empresa_a, token_a = await _empresa_e_usuario(db_session)
    empresa_b = Empresa(
        cnpj="99999999000199", inscricao_municipal="2", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem de roupa B",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa_b)
    await db_session.flush()
    usuario_b = Usuario(
        empresa_id=empresa_b.id, email="op-b@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario_b)
    await db_session.commit()
    await db_session.refresh(usuario_b)
    token_b = criar_token(usuario_b)

    # mesmo STONE ID em ambas as empresas — nao deveria haver colisao de dedupe
    conteudo = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago")

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta_a = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token_a}"},
            )
            resposta_b = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert resposta_a.json()["total_notas"] == 1
        # empresa B nao e afetada pelo STONE ID ja usado pela empresa A
        assert resposta_b.json()["total_notas"] == 1
        assert resposta_b.json()["ignoradas"]["ja_emitida_anteriormente"] == 0
    finally:
        app.dependency_overrides.clear()

    emissoes_b = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa_b.id))
    ).scalars().all()
    assert len(emissoes_b) == 1
    assert emissoes_b[0].descricao == "Lavagem de roupa B"


@pytest.mark.asyncio
async def test_csv_com_cabecalho_invalido_devolve_400_sem_gravar_nada(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = "﻿COLUNA_ERRADA;OUTRA\nx;y\n".encode("utf-8")

    app.dependency_overrides[get_db] = lambda: _yield_session(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert total == []
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `pytest tests/test_emissoes_csv.py -v`
Expected: FAIL com `404 Not Found` nas chamadas (rotas ainda não existem) ou erro de asserção nos JSONs — as rotas `/emissoes/csv/preview` e `/emissoes/csv/confirmar` ainda não estão registradas.

- [ ] **Step 3: Acrescentar `csv` a `OrigemEmissao` em `app/models.py`**

Localizar:

```python
class OrigemEmissao(str, enum.Enum):
    webhook = "webhook"
    manual = "manual"
```

Trocar por:

```python
class OrigemEmissao(str, enum.Enum):
    webhook = "webhook"
    manual = "manual"
    csv = "csv"
```

- [ ] **Step 4: Acrescentar os dois endpoints a `app/routers/emissoes.py`**

No topo do arquivo, acrescentar aos imports já existentes:

```python
from decimal import Decimal

from fastapi import File, UploadFile

from app.adapters.stone_csv import CabecalhoInvalidoError, NotaCandidata, parsear_relatorio_stone
```

No final do arquivo, acrescentar:

```python
async def _processar_csv(
    conteudo: bytes, usuario: Usuario, session: AsyncSession, *, confirmar: bool,
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
                Emissao.empresa_id == usuario.empresa_id,
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
        empresa = await session.get(Empresa, usuario.empresa_id)
        for nota in notas_validas:
            serie, numero = await reservar_proximo_numero(session, usuario.empresa_id)
            emissao = Emissao(
                empresa_id=usuario.empresa_id,
                origem=OrigemEmissao.csv,
                stone_charge_id=nota.stone_charge_id,
                status=StatusEmissao.pendente,
                serie=serie,
                numero=numero,
                descricao=empresa.descricao_servico_padrao,
                valor=nota.valor,
                competencia=nota.data_da_venda.date().replace(day=1),
                criada_por_usuario_id=usuario.id,
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
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    conteudo = await arquivo.read()
    return await _processar_csv(conteudo, usuario, session, confirmar=False)


@router.post("/csv/confirmar")
async def confirmar_csv(
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    conteudo = await arquivo.read()
    return await _processar_csv(conteudo, usuario, session, confirmar=True)
```

`main.py` não precisa de nenhuma mudança: `emissoes.router` já está registrado desde a Task 8 do plano anterior, e essas duas rotas novas herdam o mesmo prefixo `/emissoes`.

- [ ] **Step 5: Rodar e confirmar sucesso**

Run: `pytest tests/test_emissoes_csv.py -v`
Expected: PASS (5 testes)

- [ ] **Step 6: Rodar a suíte inteira**

Run: `pytest -v`
Expected: PASS (todos os testes, incluindo os das Tasks anteriores — nada deveria ter regredido)

- [ ] **Step 7: Commit**

```bash
git add app/models.py app/routers/emissoes.py tests/test_emissoes_csv.py
git commit -m "feat: endpoints de preview e confirmacao de importacao CSV da Stone"
```

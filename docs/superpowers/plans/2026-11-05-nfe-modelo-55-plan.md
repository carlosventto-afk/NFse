# Emissão de NF-e modelo 55 (backend) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empresa cadastrada consegue emitir NF-e modelo 55 (produto, venda interna ou interestadual) pra um `Cliente` já existente, com autorização pela SEFAZ da UF do emitente, cálculo de ICMS (incl. DIFAL/FCP quando interestadual), download de XML/DANFE e cancelamento — tudo via API, sem frontend ainda.

**Architecture:** Novo módulo `nfe_core/` espelha `nfse_core/` (dataclass de dados fiscais, builder de XML, signer reaproveitado, client de transporte, catálogo de erro, evento de cancelamento). `app/worker.py` ganha um segundo método de processamento que roda no mesmo loop/processo, despachando por tabela (`emissoes_nfe` em vez de `emissoes`). XML autorizado fica como `bytes` no Postgres e o PDF (DANFE) é gerado on-demand — mesmo padrão já usado hoje pra NFS-e, sem storage novo.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, `lxml` (já usado em `nfse_core/dps.py`), `zeep` (novo — client SOAP SEFAZ), `reportlab` (já usado em `app/danfe.py`), PostgreSQL, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-11-05-nfe-modelo-55-design.md`

## Global Constraints

- Venda interestadual está no MVP: quando `Cliente.uf` difere da UF do emitente, o item carrega DIFAL + FCP + partilha ICMS (EC 87/2015). ICMS-ST fica fora de escopo (bloquear/avisar, não calcular).
- `emissoes_nfe` é tabela separada de `emissoes` (não reaproveita a tabela de NFS-e).
- Cliente SOAP: `zeep`.
- UF piloto do lado emitente: Pará — mas a tabela `UF_ENDPOINTS` nasce com as 27 UFs (só Pará fica validado ao vivo neste plano).
- **Pré-requisito real, fora de qualquer task de código:** a Fase 1 do design doc (spike de homologação SEFAZ-PA) precisa ter confirmado, antes da Task 3 abaixo, a URL do WSDL de autorização em homologação e a versão exata do schema NF-e em vigor — os nomes de tag/namespace exatos do XML dependem disso e podem exigir ajuste fino depois de escritos.
- Idempotência: chave de acesso é determinística e gravada ANTES de chamar a SEFAZ (mesmo padrão do `dps_id` em `app/worker.py`); reenvio após rejeição reaproveita a mesma série/número (rejeição não "queima" numeração).
- Nenhuma mudança em `nfse_core/` ou nas tabelas `emissoes`/`empresas.certificado_pfx_cifrado` — certificado é reaproveitado como já existe.
- Frontend (cadastro de produto, tela de emissão, listagem) fica para um plano separado, depois deste — mesma convenção já usada no projeto (`2026-08-12-multiempresa-licenciamento-plan.md` é backend, `2026-08-13-frontend-plan.md` é o frontend correspondente).

## Review Focus

- Produto com CRT=3 (Regime Normal) manda CST de ICMS; produto de empresa com CRT=1/2 (Simples Nacional) manda CSOSN — usar o campo errado rejeita na SEFAZ. Precisa de teste que cobre os dois regimes.
- Venda interestadual pra UF sem alíquota interna cadastrada ainda deve falhar de forma clara (erro de validação, não exceção não tratada) — mesma filosofia do `ValueError` explícito já usada em `nfse_core/dps.py` pro NBS.
- Produto marcado com ICMS-ST deve ser rejeitado na criação da emissão (ou no cadastro do produto) com mensagem clara, não silenciosamente calculado errado.
- Worker caindo entre "gravar chave de acesso" e "receber resposta da SEFAZ" não deve duplicar o envio na próxima passada (mesmo risco que o `ja_submetida` resolve hoje pra NFS-e).
- Quantidade/valor de item zerado ou negativo deve ser rejeitado na validação do schema (Pydantic), não chegar ao builder de XML.

---

## Estrutura de arquivos

```
app/models.py                    MODIFICADO — Empresa (+inscricao_estadual, +crt, +uf);
                                  Produto, EmissaoNfe, ItemEmissaoNfe novos
alembic/versions/<rev1>_*.py      NOVO — Task 1
alembic/versions/<rev2>_*.py      NOVO — Task 2
nfe_core/
  __init__.py                      NOVO — exports públicos (espelha nfse_core/__init__.py)
  nfe.py                           NOVO — NfeData, NfeItemData, build_nfe_xml(), chave_de_acesso()
  client.py                        NOVO — UF_ENDPOINTS, SefazClient
  error_catalog.py                  NOVO — catálogo de cStat conhecidos
  evento.py                         NOVO — EventoCancelamentoNfeData, build_evento_cancelamento_nfe_xml()
app/adapters/
  icms.py                           NOVO — calcular_icms_item()
  nfe_builder.py                    NOVO — montar_nfe_data() (espelha dps_builder.py)
app/danfe_nfe.py                    NOVO — gerar_danfe_fallback()
app/worker.py                       MODIFICADO — processar_uma_pendente_nfe()
app/routers/
  produtos.py                       NOVO — CRUD produto
  emissoes_nfe.py                   NOVO — criar/listar/baixar xml+pdf/cancelar
app/schemas.py                      MODIFICADO — ProdutoIn/Out, EmissaoNfeIn/Out
app/main.py                         MODIFICADO — registra os 2 routers novos
tests/
  test_models_nfe.py                 NOVO — Task 1 e 2
  test_icms.py                       NOVO — Task 4
  test_nfe_core_nfe.py                NOVO — Task 3
  test_nfe_builder.py                  NOVO — Task 5
  test_nfe_core_client.py               NOVO — Task 6 (mocka `zeep`, sem rede real)
  test_nfe_core_error_catalog.py          NOVO — Task 7
  test_worker_nfe.py                     NOVO — Task 8
  test_nfe_core_evento.py                 NOVO — Task 9
  test_danfe_nfe.py                        NOVO — Task 10
  test_produtos_endpoint.py                 NOVO — Task 11
  test_emissoes_nfe_endpoint.py              NOVO — Task 12
```

---

### Task 1: Dados — Empresa (IE/CRT/UF) e Produto

**Files:**
- Modify: `app/models.py`
- Create: `alembic/versions/<revisao>_empresa_ie_crt_uf_e_produto.py`
- Test: `tests/test_models_nfe.py`

**Interfaces:**
- Produces: `app.models.Empresa.inscricao_estadual: str | None`, `.crt: int | None`, `.uf: str | None` (2 chars). `app.models.Produto` (`id`, `empresa_id` FK, `codigo_interno: str`, `descricao: str`, `ncm: str` (8 dígitos), `cfop_padrao: str` (4 dígitos), `unidade: str`, `cst_icms: str | None`, `csosn_icms: str | None`, `valor_unitario_padrao: Decimal | None`, `eh_substituicao_tributaria: bool` default `False`, `ativo: bool` default `True`, `criado_em`).

- [ ] **Step 1: Escrever `tests/test_models_nfe.py::test_empresa_aceita_ie_crt_uf`**

```python
async def test_empresa_aceita_ie_crt_uf(db_session):
    empresa = Empresa(..., inscricao_estadual="123456789", crt=3, uf="PA")
    db_session.add(empresa)
    await db_session.flush()
    assert empresa.crt == 3
```

- [ ] **Step 2: Escrever `tests/test_models_nfe.py::test_produto_normal_usa_cst_sn_usa_csosn`**

```python
async def test_produto_normal_usa_cst_sn_usa_csosn(db_session):
    empresa, _usuario = await criar_empresa_titular(db_session)  # tests/apoio.py, ja existente
    produto = Produto(
        empresa_id=empresa.id, codigo_interno="P1", descricao="Camiseta",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
        cst_icms=None, csosn_icms="101", valor_unitario_padrao=Decimal("49.90"),
    )
    db_session.add(produto)
    await db_session.flush()
    assert produto.csosn_icms == "101"
    assert produto.cst_icms is None
```

- [ ] **Step 3: Rodar os dois testes, confirmar falha** (`Produto`/campos novos não existem ainda)

Run: `pytest tests/test_models_nfe.py -v`
Expected: FAIL com `ImportError` ou `AttributeError`

- [ ] **Step 4: Adicionar os campos em `Empresa` e a classe `Produto` em `app/models.py`, gerar e revisar a migração Alembic**

Run: `alembic revision --autogenerate -m "empresa_ie_crt_uf_e_produto"` e revisar o arquivo gerado antes de aplicar.

- [ ] **Step 5: Rodar os testes, confirmar passam**

Run: `pytest tests/test_models_nfe.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models.py alembic/versions/ tests/test_models_nfe.py
git commit -m "feat: adiciona IE/CRT/UF na empresa e cadastro de produto"
```

---

### Task 2: Dados — EmissaoNfe e ItemEmissaoNfe

**Files:**
- Modify: `app/models.py`
- Create: `alembic/versions/<revisao>_emissoes_nfe.py`
- Test: `tests/test_models_nfe.py` (acrescenta)

**Interfaces:**
- Consumes: `app.models.Produto`, `app.models.Cliente` (de Task 1 e já existente).
- Produces: `app.models.EmissaoNfe` (`id`, `empresa_id` FK, `cliente_id` FK, `serie: str`, `numero: int`, `chave_acesso: str | None`, `status: StatusEmissao`, `xml_nfe: bytes | None`, `protocolo_autorizacao: str | None`, `erros: str | None`, `resposta_bruta: str | None`, `requisicao_bruta: str | None`, `criado_em`). `app.models.ItemEmissaoNfe` (`id`, `emissao_nfe_id` FK, `produto_id` FK, `quantidade: Decimal`, `valor_unitario: Decimal`, `valor_total: Decimal`, `cfop: str`, `base_icms: Decimal | None`, `valor_icms: Decimal | None`, `valor_icms_uf_remetente: Decimal | None`, `valor_icms_uf_destino: Decimal | None`, `valor_fcp: Decimal | None`).

- [ ] **Step 1: Escrever `tests/test_models_nfe.py::test_emissao_nfe_com_itens`**

```python
async def test_emissao_nfe_com_itens(db_session):
    empresa, _usuario = await criar_empresa_titular(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Comprador", cpf_cnpj="12345678901")
    produto = Produto(empresa_id=empresa.id, codigo_interno="P1", descricao="X",
                       ncm="61091000", cfop_padrao="5102", unidade="UN")
    db_session.add_all([cliente, produto])
    await db_session.flush()

    emissao = EmissaoNfe(empresa_id=empresa.id, cliente_id=cliente.id,
                          serie="1", numero=1, status=StatusEmissao.aguardando_emissao)
    db_session.add(emissao)
    await db_session.flush()
    item = ItemEmissaoNfe(emissao_nfe_id=emissao.id, produto_id=produto.id,
                           quantidade=Decimal("2"), valor_unitario=Decimal("49.90"),
                           valor_total=Decimal("99.80"), cfop="5102")
    db_session.add(item)
    await db_session.flush()
    assert item.valor_total == Decimal("99.80")
```

- [ ] **Step 2: Rodar, confirmar falha**

Run: `pytest tests/test_models_nfe.py::test_emissao_nfe_com_itens -v`
Expected: FAIL

- [ ] **Step 3: Adicionar `EmissaoNfe` e `ItemEmissaoNfe` em `app/models.py`, gerar/revisar migração**

Run: `alembic revision --autogenerate -m "emissoes_nfe"`

- [ ] **Step 4: Rodar, confirmar passa**

Run: `pytest tests/test_models_nfe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models.py alembic/versions/ tests/test_models_nfe.py
git commit -m "feat: adiciona tabelas emissoes_nfe e itens_emissao_nfe"
```

---

### Task 3: `nfe_core.nfe` — NfeData, chave de acesso e build_nfe_xml

**Files:**
- Create: `nfe_core/nfe.py`
- Test: `tests/test_nfe_core_nfe.py`

**Interfaces:**
- Produces: `nfe_core.nfe.NfeItemData` (dataclass: `n_item: int`, `c_prod: str`, `descricao: str`, `ncm: str`, `cfop: str`, `unidade: str`, `quantidade: Decimal`, `valor_unitario: Decimal`, `valor_total: Decimal`, `cst_icms: str | None`, `csosn_icms: str | None`, `base_icms: Decimal | None`, `valor_icms: Decimal | None`, `valor_icms_uf_remetente: Decimal | None`, `valor_icms_uf_destino: Decimal | None`, `valor_fcp: Decimal | None`). `nfe_core.nfe.NfeData` (dataclass: `tp_amb: int`, `c_uf_emit: str`, `dh_emi: datetime`, `serie: str`, `numero: int`, `emit_cnpj: str`, `emit_ie: str`, `emit_crt: int`, `emit_uf: str`, `dest_cpf_cnpj: str`, `dest_nome: str`, `dest_uf: str`, `dest_ie: str | None`, `itens: list[NfeItemData]`). `nfe_core.nfe.chave_de_acesso(data: NfeData, c_nf: str) -> str` (algoritmo padrão de 44 dígitos: UF+AAMM+CNPJ+modelo "55"+série+número+tpEmis+cNF+DV mod-11 — documentado publicamente nas notas técnicas da NF-e). `nfe_core.nfe.build_nfe_xml(data: NfeData) -> bytes`.

- [ ] **Step 1: Escrever `tests/test_nfe_core_nfe.py::test_chave_de_acesso_tem_44_digitos_e_dv_valido`**

```python
def test_chave_de_acesso_tem_44_digitos_e_dv_valido():
    data = _nfe_data_minima()  # helper local do teste
    chave = chave_de_acesso(data, c_nf="12345678")
    assert len(chave) == 44
    assert chave.isdigit()
```

- [ ] **Step 2: Escrever `tests/test_nfe_core_nfe.py::test_build_nfe_xml_rejeita_item_sem_cst_nem_csosn`**

```python
def test_build_nfe_xml_rejeita_item_sem_cst_nem_csosn():
    data = _nfe_data_minima(cst_icms=None, csosn_icms=None)
    with pytest.raises(ValueError, match="CST ou CSOSN"):
        build_nfe_xml(data)
```

- [ ] **Step 3: Escrever `tests/test_nfe_core_nfe.py::test_build_nfe_xml_inclui_icms_uf_destino_quando_interestadual`**

```python
def test_build_nfe_xml_inclui_icms_uf_destino_quando_interestadual():
    data = _nfe_data_minima(emit_uf="PA", dest_uf="SP",
                             valor_icms_uf_destino=Decimal("10.00"), valor_fcp=Decimal("2.00"))
    xml = build_nfe_xml(data)
    assert b"vICMSUFDest" in xml
    assert b"vFCP" in xml
```

- [ ] **Step 4: Rodar os três testes, confirmar falha**

Run: `pytest tests/test_nfe_core_nfe.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 5: Implementar `nfe_core/nfe.py`**

Seguir o mesmo estilo de `nfse_core/dps.py` (construção de elemento via `lxml`, validação explícita com `ValueError` em vez de default silencioso — mesma lição aplicada ao `cNBS`). Tags exatas de partilha ICMS (`ICMSUFDest`) e demais nomes de elemento conforme a versão de schema confirmada na Fase 1 (spike); se o nome real de alguma tag divergir do nome assumido aqui, ajustar — não é uma decisão deste plano, é o schema oficial.

- [ ] **Step 6: Rodar os testes, confirmar passam**

Run: `pytest tests/test_nfe_core_nfe.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add nfe_core/nfe.py tests/test_nfe_core_nfe.py
git commit -m "feat: adiciona builder de XML da NF-e com chave de acesso"
```

---

### Task 4: Cálculo de ICMS (interno + DIFAL/FCP)

**Files:**
- Create: `app/adapters/icms.py`
- Test: `tests/test_icms.py`

**Interfaces:**
- Consumes: nada de tasks anteriores (função pura).
- Produces: `app.adapters.icms.AliquotaInterestadualInvalida(ValueError)`. `app.adapters.icms.calcular_icms_item(valor_total: Decimal, uf_emitente: str, uf_destino: str, aliquota_interna_destino: Decimal | None, cst_ou_csosn: str) -> ItemIcmsCalculado` onde `ItemIcmsCalculado` é um dataclass com `base_icms`, `valor_icms`, `valor_icms_uf_remetente`, `valor_icms_uf_destino`, `valor_fcp` (os 3 últimos `None` quando `uf_emitente == uf_destino`).

- [ ] **Step 1: Escrever `tests/test_icms.py::test_venda_interna_nao_calcula_difal`**

```python
def test_venda_interna_nao_calcula_difal():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "PA", None, "102")
    assert resultado.valor_icms_uf_destino is None
    assert resultado.valor_fcp is None
```

- [ ] **Step 2: Escrever `tests/test_icms.py::test_venda_interestadual_sem_aliquota_interna_levanta_erro_claro`**

```python
def test_venda_interestadual_sem_aliquota_interna_levanta_erro_claro():
    with pytest.raises(AliquotaInterestadualInvalida, match="aliquota interna"):
        calcular_icms_item(Decimal("100.00"), "PA", "SP", None, "102")
```

- [ ] **Step 3: Escrever `tests/test_icms.py::test_venda_interestadual_calcula_partilha_e_fcp`**

```python
def test_venda_interestadual_calcula_partilha_e_fcp():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "SP", Decimal("18.00"), "102")
    assert resultado.valor_icms_uf_destino > 0
    assert resultado.valor_icms_uf_remetente >= 0
```

- [ ] **Step 4: Rodar, confirmar falha**

Run: `pytest tests/test_icms.py -v`
Expected: FAIL

- [ ] **Step 5: Implementar `app/adapters/icms.py`**

Alíquota interestadual (4%/7%/12% conforme origem/destino, regra pública EC 87/2015) nasce como constante no módulo (tabela fixa por par de UF ou regra simplificada 4% quando o produto é importado, 7%/12% conforme região — confirmar a regra exata na Fase 1 junto do spike fiscal, não é uma escolha livre do implementador). Partilha ICMS: diferença entre alíquota interna do destino e a interestadual, dividida pelo cronograma vigente da EC 87/2015.

- [ ] **Step 6: Rodar, confirmar passam**

Run: `pytest tests/test_icms.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/adapters/icms.py tests/test_icms.py
git commit -m "feat: adiciona calculo de ICMS interno e DIFAL/FCP interestadual"
```

---

### Task 5: `app/adapters/nfe_builder.py` — monta NfeData a partir do banco

**Files:**
- Create: `app/adapters/nfe_builder.py`
- Test: `tests/test_nfe_builder.py`

**Interfaces:**
- Consumes: `app.models.Empresa`, `app.models.Cliente`, `app.models.Produto`, `app.adapters.icms.calcular_icms_item` (Task 4), `nfe_core.nfe.NfeData`/`NfeItemData` (Task 3).
- Produces: `app.adapters.nfe_builder.ItemPedido` (dataclass simples: `produto_id`, `quantidade`, `valor_unitario_override: Decimal | None`). `app.adapters.nfe_builder.montar_nfe_data(empresa: Empresa, cliente: Cliente, serie: str, numero: int, produtos_por_id: dict, itens: list[ItemPedido]) -> NfeData`.

- [ ] **Step 1: Escrever `tests/test_nfe_builder.py::test_monta_nfe_data_produto_com_substituicao_tributaria_levanta_erro`**

```python
def test_monta_nfe_data_produto_com_substituicao_tributaria_levanta_erro():
    produto = _produto(eh_substituicao_tributaria=True)
    with pytest.raises(ValueError, match="Substituicao Tributaria"):
        montar_nfe_data(empresa, cliente, "1", 1, {produto.id: produto},
                         [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)])
```

- [ ] **Step 2: Escrever `tests/test_nfe_builder.py::test_monta_nfe_data_usa_crt_da_empresa_pra_escolher_cst_ou_csosn`**

```python
@pytest.mark.parametrize("crt,cst_icms,csosn_icms", [(1, None, "101"), (3, "020", None)])
def test_monta_nfe_data_usa_crt_da_empresa_pra_escolher_cst_ou_csosn(crt, cst_icms, csosn_icms):
    empresa = _empresa(crt=crt)
    produto = _produto(csosn_icms=csosn_icms, cst_icms=cst_icms)
    data = montar_nfe_data(empresa, cliente, "1", 1, {produto.id: produto},
                            [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)])
    assert data.itens[0].csosn_icms == csosn_icms
    assert data.itens[0].cst_icms == cst_icms
```

- [ ] **Step 3: Rodar, confirmar falha**

Run: `pytest tests/test_nfe_builder.py -v`
Expected: FAIL

- [ ] **Step 4: Implementar `app/adapters/nfe_builder.py`**

Espelha a estrutura de `app/adapters/dps_builder.py`: função pura que le os campos do `Empresa`/`Cliente`/`Produto`, chama `calcular_icms_item` por item e devolve `NfeData` pronta pro `build_nfe_xml`.

- [ ] **Step 5: Rodar, confirmar passam**

Run: `pytest tests/test_nfe_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/adapters/nfe_builder.py tests/test_nfe_builder.py
git commit -m "feat: adiciona builder que monta NfeData a partir do cadastro"
```

---

### Task 6: `nfe_core.client` — UF_ENDPOINTS e SefazClient

**Files:**
- Create: `nfe_core/client.py`
- Test: `tests/test_nfe_core_client.py`

**Interfaces:**
- Consumes: `zeep` (novo, adicionar em `requirements.txt`).
- Produces: `nfe_core.client.UF_ENDPOINTS: dict[str, dict[str, str]]` (chave UF, valores `autorizacao_homologacao`/`autorizacao_producao`/`consulta_protocolo_homologacao`/`consulta_protocolo_producao`, preenchido pra todas as 27 UFs). `nfe_core.client.SefazClient` com `async def autorizar(self, xml_assinado: bytes, uf: str, ambiente: AmbienteEnum) -> RespostaAutorizacao` e `async def consultar_protocolo(self, chave_acesso: str, uf: str, ambiente: AmbienteEnum) -> RespostaConsulta`.

- [ ] **Step 1: Escrever `tests/test_nfe_core_client.py::test_uf_endpoints_cobre_todas_as_27_ufs`**

```python
def test_uf_endpoints_cobre_todas_as_27_ufs():
    assert len(UF_ENDPOINTS) == 27
    assert "PA" in UF_ENDPOINTS
```

- [ ] **Step 2: Escrever `tests/test_nfe_core_client.py::test_autorizar_usa_endpoint_de_homologacao_quando_ambiente_homologacao`** (mockar `zeep.Client` via `unittest.mock.patch`)

```python
@patch("nfe_core.client.zeep.Client")
async def test_autorizar_usa_endpoint_de_homologacao_quando_ambiente_homologacao(mock_zeep_client):
    client = SefazClient()
    await client.autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.homologacao)
    chamada_url = mock_zeep_client.call_args[0][0]
    assert chamada_url == UF_ENDPOINTS["PA"]["autorizacao_homologacao"]
```

- [ ] **Step 3: Rodar, confirmar falha**

Run: `pytest tests/test_nfe_core_client.py -v`
Expected: FAIL

- [ ] **Step 4: Implementar `nfe_core/client.py`**

URLs reais de WSDL por UF vêm do Manual de Integração do Contribuinte (confirmar as de homologação/produção na Fase 1/spike antes de travar os valores — tabela pública, não decisão deste plano).

- [ ] **Step 5: Rodar, confirmar passam**

Run: `pytest tests/test_nfe_core_client.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nfe_core/client.py tests/test_nfe_core_client.py requirements.txt
git commit -m "feat: adiciona client SOAP da SEFAZ (zeep) com endpoints por UF"
```

---

### Task 7: `nfe_core.error_catalog` — catálogo de rejeição (cStat)

**Files:**
- Create: `nfe_core/error_catalog.py`
- Test: `tests/test_nfe_core_error_catalog.py`

**Interfaces:**
- Produces: `nfe_core.error_catalog.CATALOGO_CSTAT: dict[str, str]` (mapeia código `cStat` pra descrição legível, pelo menos `100` autorizado, `110`/`301`/`302` denegado, demais rejeições comuns). `nfe_core.error_catalog.eh_autorizado(c_stat: str) -> bool`.

- [ ] **Step 1: Escrever `tests/test_nfe_core_error_catalog.py::test_eh_autorizado_so_para_cstat_100`**

```python
def test_eh_autorizado_so_para_cstat_100():
    assert eh_autorizado("100") is True
    assert eh_autorizado("110") is False
    assert eh_autorizado("999") is False
```

- [ ] **Step 2: Rodar, confirmar falha**

Run: `pytest tests/test_nfe_core_error_catalog.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `nfe_core/error_catalog.py`** (tabela estática, sem ambiguidade de design — espelha `nfse_core/error_catalog.py` em formato)

- [ ] **Step 4: Rodar, confirmar passa**

Run: `pytest tests/test_nfe_core_error_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nfe_core/error_catalog.py tests/test_nfe_core_error_catalog.py
git commit -m "feat: adiciona catalogo de codigos de status (cStat) da SEFAZ"
```

---

### Task 8: Worker — processar_uma_pendente_nfe

**Files:**
- Modify: `app/worker.py`
- Test: `tests/test_worker_nfe.py`

**Interfaces:**
- Consumes: `app.models.EmissaoNfe`, `app.adapters.nfe_builder.montar_nfe_data` (Task 5), `nfe_core.nfe.build_nfe_xml`/`chave_de_acesso` (Task 3), `nfe_core.client.SefazClient` (Task 6), `nfe_core.error_catalog.eh_autorizado` (Task 7), `nfse_core.sign_dps`-equivalente (reaproveitar `nfse_core.signer` diretamente — assinatura XML-DSig é genérica, não specifica de NFS-e).
- Produces: `app.worker.processar_uma_pendente_nfe(session: AsyncSession, settings: Settings) -> bool` (mesma convenção de retorno de `processar_uma_pendente` já existente — `True` se processou algo).

- [ ] **Step 1: Escrever `tests/test_worker_nfe.py::test_grava_chave_de_acesso_antes_de_chamar_sefaz`**

```python
@patch("app.worker.SefazClient")
async def test_grava_chave_de_acesso_antes_de_chamar_sefaz(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock(side_effect=Exception("rede caiu"))
    emissao = await _criar_emissao_nfe_pendente(db_session)
    with pytest.raises(Exception):
        await processar_uma_pendente_nfe(db_session, get_settings())
    await db_session.refresh(emissao)
    assert emissao.chave_acesso is not None
```

- [ ] **Step 2: Escrever `tests/test_worker_nfe.py::test_nao_reenvia_quando_ja_tem_protocolo_de_autorizacao`**

```python
async def test_nao_reenvia_quando_ja_tem_protocolo_de_autorizacao(db_session):
    emissao = await _criar_emissao_nfe_pendente(db_session, protocolo_autorizacao="123", status=StatusEmissao.autorizada)
    processou = await processar_uma_pendente_nfe(db_session, get_settings())
    assert processou is False
```

- [ ] **Step 3: Escrever `tests/test_worker_nfe.py::test_rejeicao_mantem_mesma_serie_numero_pra_reenvio`**

```python
@patch("app.worker.SefazClient")
async def test_rejeicao_mantem_mesma_serie_numero_pra_reenvio(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock(return_value=_resposta_rejeitada("110"))
    emissao = await _criar_emissao_nfe_pendente(db_session, serie="1", numero=42)
    await processar_uma_pendente_nfe(db_session, get_settings())
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.serie == "1" and emissao.numero == 42
```

- [ ] **Step 4: Rodar os três, confirmar falha**

Run: `pytest tests/test_worker_nfe.py -v`
Expected: FAIL

- [ ] **Step 5: Implementar `processar_uma_pendente_nfe` em `app/worker.py`**

Mesmo esqueleto de `processar_uma_pendente` (NFS-e): `SELECT ... FOR UPDATE SKIP LOCKED` em `emissoes_nfe`, gravar `chave_acesso` antes do `autorizar`, interpretar `cStat` via `error_catalog.eh_autorizado`, aplicar o mesmo backoff (`_BACKOFF_REEMISSAO_AUTOMATICA`) em rejeição. Chamar essa função a cada iteração do `loop_worker` existente, ao lado de `processar_uma_pendente`.

- [ ] **Step 6: Rodar, confirmar passam**

Run: `pytest tests/test_worker_nfe.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/worker.py tests/test_worker_nfe.py
git commit -m "feat: worker passa a processar emissoes de NF-e"
```

---

### Task 9: `nfe_core.evento` — cancelamento

**Files:**
- Create: `nfe_core/evento.py`
- Test: `tests/test_nfe_core_evento.py`

**Interfaces:**
- Consumes: `nfse_core.signer` (reaproveitado — assinatura genérica).
- Produces: `nfe_core.evento.EventoCancelamentoNfeData` (dataclass: `chave_acesso: str`, `protocolo_autorizacao: str`, `justificativa: str` mín. 15 caracteres), `nfe_core.evento.build_evento_cancelamento_nfe_xml(data: EventoCancelamentoNfeData) -> bytes`.

- [ ] **Step 1: Escrever `tests/test_nfe_core_evento.py::test_justificativa_curta_levanta_erro`**

```python
def test_justificativa_curta_levanta_erro():
    with pytest.raises(ValueError, match="15 caracteres"):
        build_evento_cancelamento_nfe_xml(EventoCancelamentoNfeData(
            chave_acesso="4" * 44, protocolo_autorizacao="123", justificativa="curta"))
```

- [ ] **Step 2: Rodar, confirmar falha**

Run: `pytest tests/test_nfe_core_evento.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `nfe_core/evento.py`** (espelha `nfse_core/evento.py`)

- [ ] **Step 4: Rodar, confirmar passa**

Run: `pytest tests/test_nfe_core_evento.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nfe_core/evento.py tests/test_nfe_core_evento.py
git commit -m "feat: adiciona evento de cancelamento da NF-e"
```

---

### Task 10: `app/danfe_nfe.py` — DANFE on-demand

**Files:**
- Create: `app/danfe_nfe.py`
- Test: `tests/test_danfe_nfe.py`

**Interfaces:**
- Consumes: `app.models.EmissaoNfe`, `app.models.Empresa`.
- Produces: `app.danfe_nfe.gerar_danfe_fallback(emissao: EmissaoNfe, empresa: Empresa) -> bytes`.

- [ ] **Step 1: Escrever `tests/test_danfe_nfe.py::test_gerar_danfe_fallback_inclui_chave_de_acesso`**

```python
def test_gerar_danfe_fallback_inclui_chave_de_acesso():
    pdf = gerar_danfe_fallback(_emissao_nfe_autorizada(), _empresa())
    assert pdf.startswith(b"%PDF")
```

- [ ] **Step 2: Rodar, confirmar falha**

Run: `pytest tests/test_danfe_nfe.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/danfe_nfe.py`** (copiar o esqueleto de `app/danfe.py`, troca os campos exibidos pra chave de acesso/itens/CFOP)

- [ ] **Step 4: Rodar, confirmar passa**

Run: `pytest tests/test_danfe_nfe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/danfe_nfe.py tests/test_danfe_nfe.py
git commit -m "feat: adiciona geracao de DANFE on-demand"
```

---

### Task 11: `app/routers/produtos.py` — CRUD de produto

**Files:**
- Create: `app/routers/produtos.py`
- Modify: `app/schemas.py` (adiciona `ProdutoIn`, `ProdutoOut`), `app/main.py` (registra router)
- Test: `tests/test_produtos_endpoint.py`

**Interfaces:**
- Consumes: `app.security.ContextoAutenticado` (padrão já usado em todos os routers), `app.models.Produto`.
- Produces: router com prefixo `/produtos` (montado sob `/api` em `app/main.py`, igual aos demais — caminho final `/api/produtos`): `POST`, `GET` (lista), `GET /{id}`, `PUT /{id}`, `DELETE /{id}` (soft-delete via `ativo=False`, mesmo padrão de `Cliente`).

**Padrão de teste a seguir** (não inventar fixture nova): igual a `tests/test_clientes.py` — `empresa, token = await criar_empresa_e_token(db_session)` (de `tests/apoio.py`, já existente), `app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)`, requisição via `ASGITransport(app=app)` + `AsyncClient`, header `Authorization: Bearer {token}`, path com prefixo `/api/produtos`.

- [ ] **Step 1: Escrever `tests/test_produtos_endpoint.py::test_criar_produto_com_substituicao_tributaria_e_aceito_mas_marcado`**

```python
async def test_criar_produto_com_substituicao_tributaria_e_aceito_mas_marcado(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/produtos",
                json={"codigo_interno": "P1", "descricao": "Camiseta", "ncm": "61091000",
                      "cfop_padrao": "5102", "unidade": "UN", "eh_substituicao_tributaria": True},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["eh_substituicao_tributaria"] is True
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Escrever `tests/test_produtos_endpoint.py::test_listar_produtos_so_da_propria_empresa`** (mesmo padrão de isolamento de `tests/test_tenant_isolation.py`)

- [ ] **Step 3: Rodar, confirmar falha**

Run: `pytest tests/test_produtos_endpoint.py -v`
Expected: FAIL

- [ ] **Step 4: Implementar `app/routers/produtos.py`** (espelha o CRUD de `Cliente` já existente)

- [ ] **Step 5: Rodar, confirmar passam**

Run: `pytest tests/test_produtos_endpoint.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/produtos.py app/schemas.py app/main.py tests/test_produtos_endpoint.py
git commit -m "feat: adiciona CRUD de produtos"
```

---

### Task 12: `app/routers/emissoes_nfe.py` — criar/listar/baixar/cancelar

**Files:**
- Create: `app/routers/emissoes_nfe.py`
- Modify: `app/schemas.py` (adiciona `EmissaoNfeIn`, `EmissaoNfeOut`, `ItemEmissaoNfeIn`), `app/main.py` (registra router)
- Test: `tests/test_emissoes_nfe_endpoint.py`

**Interfaces:**
- Consumes: `app.adapters.nfe_builder` (Task 5), `app.danfe_nfe.gerar_danfe_fallback` (Task 10), `nfe_core.evento.build_evento_cancelamento_nfe_xml` (Task 9), `app.models.EmissaoNfe`/`ItemEmissaoNfe`.
- Produces: router com prefixo `/emissoes-nfe` (montado sob `/api`, caminho final `/api/emissoes-nfe`): `POST` (cria em `status=aguardando_emissao`, pro worker pegar), `GET` (lista), `GET /{id}/xml`, `GET /{id}/pdf`, `POST /{id}/cancelar`.

**Mesmo padrão de teste de endpoint do Task 11** (`criar_empresa_e_token`, `ASGITransport`/`AsyncClient`, `app.dependency_overrides[get_db]`, prefixo `/api/emissoes-nfe`) — não repetido em cada step abaixo por brevidade, mas obrigatório em todos.

- [ ] **Step 1: Escrever `tests/test_emissoes_nfe_endpoint.py::test_criar_emissao_com_produto_de_outra_empresa_e_rejeitado`**

```python
async def test_criar_emissao_com_produto_de_outra_empresa_e_rejeitado(db_session):
    _empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, _token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    produto_de_outra_empresa = Produto(empresa_id=empresa_b.id, codigo_interno="PB", descricao="X",
                                        ncm="61091000", cfop_padrao="5102", unidade="UN")
    db_session.add(produto_de_outra_empresa)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes-nfe",
                json={"itens": [{"produto_id": str(produto_de_outra_empresa.id), "quantidade": "1"}]},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert resposta.status_code in (400, 404)
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Escrever `tests/test_emissoes_nfe_endpoint.py::test_criar_emissao_fica_aguardando_emissao_pro_worker`**

- [ ] **Step 3: Escrever `tests/test_emissoes_nfe_endpoint.py::test_criar_emissao_com_quantidade_zero_e_rejeitado_pelo_schema`**

```python
async def test_criar_emissao_com_quantidade_zero_e_rejeitado_pelo_schema(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    produto = Produto(empresa_id=empresa.id, codigo_interno="P1", descricao="X",
                       ncm="61091000", cfop_padrao="5102", unidade="UN")
    db_session.add(produto)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes-nfe",
                json={"itens": [{"produto_id": str(produto.id), "quantidade": "0"}]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 4: Escrever `tests/test_emissoes_nfe_endpoint.py::test_cancelar_emissao_nao_autorizada_e_rejeitado`**

```python
async def test_cancelar_emissao_nao_autorizada_e_rejeitado(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    emissao_pendente = EmissaoNfe(empresa_id=empresa.id, serie="1", numero=1,
                                   status=StatusEmissao.aguardando_emissao)
    db_session.add(emissao_pendente)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes-nfe/{emissao_pendente.id}/cancelar",
                json={"justificativa": "Erro no pedido do cliente"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 5: Rodar, confirmar falha**

Run: `pytest tests/test_emissoes_nfe_endpoint.py -v`
Expected: FAIL

- [ ] **Step 6: Implementar `app/routers/emissoes_nfe.py`** (espelha `app/routers/emissoes.py`: valida itens/produtos pertencem à empresa ativa do token, calcula `valor_total` por item, grava e deixa pro worker; `/xml` e `/pdf` seguem o padrão de `baixar_pdf`/`baixar_xml` já existentes)

- [ ] **Step 7: Rodar, confirmar passam**

Run: `pytest tests/test_emissoes_nfe_endpoint.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/routers/emissoes_nfe.py app/schemas.py app/main.py tests/test_emissoes_nfe_endpoint.py
git commit -m "feat: adiciona endpoints de criacao/consulta/cancelamento de NF-e"
```

---

## Depois deste plano

- Rodar a suíte completa (`pytest`) e confirmar que nenhum teste de NFS-e quebrou (nenhuma task aqui toca `nfse_core/` ou `emissoes`).
- Plano separado de frontend (cadastro de produto, tela de emissão, listagem/download) — só depois do backend estável, mesma ordem já usada em multiempresa/licenciamento.
- Homologação ponta a ponta com certificado de teste antes de qualquer piloto em produção.

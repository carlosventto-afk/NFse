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

from app.crypto import cifrar, decifrar
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import PapelUsuario
from app.security import criar_token
from tests.apoio import criar_empresa_titular


def _pfx_teste_base64(cnpj: str = "99988877000155") -> str:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{cnpj}")])
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


def _form_edicao(**overrides) -> dict:
    base = {
        "cnpj": "12345678000199", "inscricao_municipal": "1", "municipio_ibge": "3550308",
        "op_simp_nac": "3", "codigo_tributacao": "140106",
        "descricao_servico_padrao": "Lavagem de roupa", "ambiente": "homologacao",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_admin_le_dados_atuais_da_empresa(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/empresas/mim", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["cnpj"] == "12345678000199"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_edita_campos_simples_sem_trocar_certificado(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    certificado_original = empresa.certificado_pfx_cifrado

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(
                    descricao_servico_padrao="Lavagem e passagem de roupa", ambiente="producao",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["descricao_servico_padrao"] == "Lavagem e passagem de roupa"
        assert corpo["ambiente"] == "producao"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.certificado_pfx_cifrado == certificado_original


@pytest.mark.asyncio
async def test_admin_define_regime_apuracao_sn(db_session):
    # SEFIN/Belem confirmado ao vivo (E0160) -- op_simp_nac=3 sem esse campo
    # e rejeitado mesmo com o cadastro Simples Nacional correto.
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(regime_apuracao_sn="1"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["regime_apuracao_sn"] == 1
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.regime_apuracao_sn == 1


@pytest.mark.asyncio
async def test_admin_define_local_da_prestacao_diferente_do_municipio_emissor(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(local_prestacao_ibge="1501402"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["local_prestacao_ibge"] == "1501402"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.local_prestacao_ibge == "1501402"


@pytest.mark.asyncio
async def test_admin_limpa_inscricao_municipal(db_session):
    # Alguns municipios rejeitam a DPS se a IM vier preenchida (SEFIN
    # E0120) -- precisa ser possivel deixar em branco.
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(inscricao_municipal=""),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["inscricao_municipal"] is None
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.inscricao_municipal is None


@pytest.mark.asyncio
async def test_admin_define_codigo_tributacao_municipal(db_session):
    # Belem exige esse campo (SEFIN L0017: "codigo de tributacao municipal
    # nao foi informado") -- precisa ser possivel cadastrar.
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(codigo_tributacao_municipal="007"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["codigo_tributacao_municipal"] == "007"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.codigo_tributacao_municipal == "007"


@pytest.mark.asyncio
async def test_admin_troca_cnpj(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99.988.877/0001-55"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["cnpj"] == "99988877000155"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_editar_com_cnpj_ja_usado_por_outra_empresa_devolve_422(db_session):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="12345678000199")
    await criar_empresa_titular(
        db_session, cnpj="99988877000155", email_titular="outro-titular@teste.com",
    )
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99988877000155"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_troca_o_certificado(db_session):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="99988877000155")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    pfx_b64 = _pfx_teste_base64(cnpj="99988877000155")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data={**_form_edicao(cnpj="99988877000155"), "senha_certificado": "senha123"},
                files={"pfx": ("novo.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    settings = get_settings()
    assert decifrar(empresa.certificado_senha_cifrada, settings.fernet_key) == "senha123"


@pytest.mark.asyncio
async def test_trocar_certificado_sem_senha_devolve_422(db_session):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="99988877000155")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    pfx_b64 = _pfx_teste_base64(cnpj="99988877000155")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99988877000155"),
                files={"pfx": ("novo.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_liga_spedy_e_provisiona_a_empresa(db_session, monkeypatch):
    # certificado_pfx_cifrado/certificado_senha_cifrada precisam ser tokens
    # Fernet validos aqui: o endpoint decifra os dois antes de chamar
    # provisionar_empresa (mesmo com provisionar_empresa mockado abaixo) --
    # o placeholder "x" default de criar_empresa_titular nao decifra.
    fernet_key = get_settings().fernet_key
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99988877000155",
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
    )
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

    # Mesmo motivo do teste acima: certificado precisa decifrar antes de
    # chegar em provisionar_empresa (aqui mockado para explodir).
    fernet_key = get_settings().fernet_key
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99988877000155",
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
    )
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
async def test_segunda_edicao_sem_provedor_emissao_mantem_spedy(db_session, monkeypatch):
    # Fix 1: o frontend atual (EditarEmpresaPage.tsx) nao conhece o campo
    # provedor_emissao e nunca o envia. `_form_edicao()` reproduz exatamente
    # isso -- nao inclui provedor_emissao nem os campos de endereco. Uma
    # segunda edicao "normal" (so mexendo em outro campo) nao pode reverter
    # o provedor pra "direto" nem provisionar de novo.
    fernet_key = get_settings().fernet_key
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99988877000155",
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
    )
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.empresas as empresas_router

    chamadas = []

    async def _provisionar_falso(empresa_, pfx_base64, senha, settings):
        chamadas.append(1)
        return "spedy-empresa-1", "spedy-chave-1"

    monkeypatch.setattr(empresas_router, "provisionar_empresa", _provisionar_falso)

    class _ClienteSpedyFalso:
        def __init__(self, ambiente, api_key):
            pass

        async def alterar_empresa(self, spedy_empresa_id, dados):
            return {}

        async def close(self):
            pass

    monkeypatch.setattr(empresas_router, "SpedyClient", _ClienteSpedyFalso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.put(
                "/api/empresas/mim",
                data={
                    **_form_edicao(cnpj="99988877000155"),
                    "provedor_emissao": "spedy", "razao_social": "EMPRESA TESTE LTDA",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert primeira.status_code == 200
            assert len(chamadas) == 1

            # Segunda edicao "normal": _form_edicao() NAO manda
            # provedor_emissao nem razao_social/logradouro/etc.
            segunda = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(
                    cnpj="99988877000155", descricao_servico_padrao="Lavagem e passagem de roupa",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert segunda.status_code == 200
        corpo = segunda.json()
        assert corpo["provedor_emissao"] == "spedy"
        assert corpo["spedy_empresa_id"] == "spedy-empresa-1"
        # nao provisionou de novo
        assert len(chamadas) == 1
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.provedor_emissao == "spedy"
    assert empresa.spedy_empresa_id == "spedy-empresa-1"


@pytest.mark.asyncio
async def test_segunda_edicao_de_empresa_ja_na_spedy_sincroniza_regime_tributario(db_session, monkeypatch):
    # Regressao do erro E188 em Belem: taxRegime/specialTaxRegime sao
    # campos do CADASTRO da empresa na Spedy (nao da nota) -- uma empresa
    # provisionada antes desses campos existirem no nosso payload fica com
    # o cadastro desatualizado na Spedy pra sempre, a nao ser que toda
    # edicao normal (que nao reprovisiona) tambem sincronize isso.
    fernet_key = get_settings().fernet_key
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99988877000155",
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
    )
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.empresas as empresas_router

    async def _provisionar_falso(empresa_, pfx_base64, senha, settings):
        return "spedy-empresa-1", "spedy-chave-1"

    monkeypatch.setattr(empresas_router, "provisionar_empresa", _provisionar_falso)

    chamadas = []

    class _ClienteSpedyFalso:
        def __init__(self, ambiente, api_key):
            pass

        async def alterar_empresa(self, spedy_empresa_id, dados):
            chamadas.append((spedy_empresa_id, dados))
            return {}

        async def close(self):
            pass

    monkeypatch.setattr(empresas_router, "SpedyClient", _ClienteSpedyFalso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.put(
                "/api/empresas/mim",
                data={
                    **_form_edicao(cnpj="99988877000155"),
                    "provedor_emissao": "spedy", "razao_social": "EMPRESA TESTE LTDA",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert primeira.status_code == 200
            # o provisionamento inicial ja manda o regime junto (ver
            # test_spedy_provisionamento.py) -- a sincronizacao aqui e so
            # pra edicoes SEGUINTES, que nao reprovisionam.
            assert chamadas == []

            segunda = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99988877000155", op_simp_nac="2"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert segunda.status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert len(chamadas) == 1
    spedy_empresa_id, dados = chamadas[0]
    assert spedy_empresa_id == "spedy-empresa-1"
    assert dados == {"taxRegime": "simplesNacionalMEI", "specialTaxRegime": "individualMicroenterprise"}


@pytest.mark.asyncio
async def test_segunda_edicao_sem_endereco_mantem_valor_anterior(db_session):
    # Fix 1: razao_social/logradouro/numero/complemento/bairro/cep tambem
    # nao podem ser silenciosamente apagados quando um request posterior nao
    # os envia (cliente antigo que desconhece esses campos).
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.put(
                "/api/empresas/mim",
                data={**_form_edicao(), "razao_social": "EMPRESA TESTE LTDA", "logradouro": "Rua Um"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert primeira.status_code == 200
            assert primeira.json()["razao_social"] == "EMPRESA TESTE LTDA"

            # segunda edicao via _form_edicao() puro -- nao manda razao_social
            # nem logradouro.
            segunda = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(descricao_servico_padrao="Lavagem e passagem de roupa"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert segunda.status_code == 200
        corpo = segunda.json()
        assert corpo["razao_social"] == "EMPRESA TESTE LTDA"
        assert corpo["logradouro"] == "Rua Um"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.razao_social == "EMPRESA TESTE LTDA"
    assert empresa.logradouro == "Rua Um"


@pytest.mark.asyncio
async def test_trocar_certificado_de_empresa_ja_na_spedy_devolve_422(db_session, monkeypatch):
    # Fix 6: uma empresa ja provisionada na Spedy nao pode ter o certificado
    # trocado silenciosamente sem re-provisionar (rotacao anual de A1) --
    # precisa recusar com erro claro em vez de deixar o cert local
    # dessincronizado do que a Spedy conhece.
    fernet_key = get_settings().fernet_key
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99988877000155",
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
    )
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    certificado_original = empresa.certificado_pfx_cifrado

    import app.routers.empresas as empresas_router

    async def _provisionar_falso(empresa_, pfx_base64, senha, settings):
        return "spedy-empresa-1", "spedy-chave-1"

    monkeypatch.setattr(empresas_router, "provisionar_empresa", _provisionar_falso)

    pfx_b64 = _pfx_teste_base64(cnpj="99988877000155")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.put(
                "/api/empresas/mim",
                data={
                    **_form_edicao(cnpj="99988877000155"),
                    "provedor_emissao": "spedy", "razao_social": "EMPRESA TESTE LTDA",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert primeira.status_code == 200

            segunda = await client.put(
                "/api/empresas/mim",
                data={**_form_edicao(cnpj="99988877000155"), "senha_certificado": "senha123"},
                files={"pfx": ("novo.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert segunda.status_code == 422
        assert "ja esta provisionada na Spedy" in segunda.json()["detail"]
    finally:
        app.dependency_overrides.clear()

    await db_session.rollback()
    await db_session.refresh(empresa)
    assert empresa.certificado_pfx_cifrado == certificado_original


@pytest.mark.asyncio
async def test_trocar_ambiente_de_empresa_ja_na_spedy_reprovisiona(db_session, monkeypatch):
    # Homologacao e producao sao contas/chaves mestras separadas na Spedy --
    # so trocar o campo local deixaria o cliente apontando pra conta errada.
    # Por isso a troca de ambiente reprovisiona do zero no ambiente novo,
    # sobrescrevendo spedy_empresa_id/spedy_api_key_cifrada.
    fernet_key = get_settings().fernet_key
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99988877000155",
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
    )
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.empresas as empresas_router

    chamadas = []

    async def _provisionar_falso(empresa_, pfx_base64, senha, settings):
        chamadas.append(empresa_.ambiente)
        if empresa_.ambiente == "producao":
            return "spedy-empresa-producao", "spedy-chave-producao"
        return "spedy-empresa-homologacao", "spedy-chave-homologacao"

    monkeypatch.setattr(empresas_router, "provisionar_empresa", _provisionar_falso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.put(
                "/api/empresas/mim",
                data={
                    **_form_edicao(cnpj="99988877000155"),
                    "provedor_emissao": "spedy", "razao_social": "EMPRESA TESTE LTDA",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert primeira.status_code == 200

            segunda = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99988877000155", ambiente="producao"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert segunda.status_code == 200
        corpo = segunda.json()
        assert corpo["ambiente"] == "producao"
        assert corpo["spedy_empresa_id"] == "spedy-empresa-producao"
        assert chamadas == ["homologacao", "producao"]
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    settings = get_settings()
    assert empresa.ambiente == "producao"
    assert empresa.spedy_empresa_id == "spedy-empresa-producao"
    assert decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key) == "spedy-chave-producao"


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


@pytest.mark.asyncio
async def test_operador_nao_pode_editar_empresa(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-editar@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()

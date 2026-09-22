import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao, Usuario
from app.crypto import hash_senha
from scripts.reverter_erro_cancelamento import reverter_erro_cancelamento


async def _empresa_e_emissao(db_session, status: StatusEmissao) -> Emissao:
    titular = Usuario(email=f"titular-reverter-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = Empresa(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="141001", descricao_servico_padrao="Lavagem",
        ambiente="homologacao", certificado_pfx_cifrado="x",
        certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=status,
        serie="1", numero=3, chave_acesso="chave-final-1",
        erros=json.dumps([{"codigo": "L999", "titulo": "O prazo para cancelamento expirou."}]),
        motivo_cancelamento="Servico nao prestado",
        descricao="Lavagem de roupa", valor=Decimal("27.98"), competencia=date(2026, 7, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


@pytest.mark.asyncio
async def test_reverte_erro_cancelamento_para_autorizada(db_session):
    emissao = await _empresa_e_emissao(db_session, StatusEmissao.erro_cancelamento)

    revertida = await reverter_erro_cancelamento(db_session, emissao.id)

    assert revertida.status == StatusEmissao.autorizada
    assert revertida.erros is None
    assert revertida.motivo_cancelamento is None
    # a chave de acesso da autorizacao original nao pode ser mexida --
    # a nota continua sendo a mesma NFS-e valida de antes.
    assert revertida.chave_acesso == "chave-final-1"


@pytest.mark.asyncio
async def test_reverter_recusa_quando_status_nao_e_erro_cancelamento(db_session):
    emissao = await _empresa_e_emissao(db_session, StatusEmissao.autorizada)

    with pytest.raises(ValueError, match="erro_cancelamento"):
        await reverter_erro_cancelamento(db_session, emissao.id)


@pytest.mark.asyncio
async def test_reverter_recusa_emissao_inexistente(db_session):
    with pytest.raises(ValueError, match="nao encontrada"):
        await reverter_erro_cancelamento(db_session, uuid.uuid4())

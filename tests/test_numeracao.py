import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.crypto import hash_senha
from app.models import AmbienteEnum, Empresa, Usuario
from app.numeracao import reservar_proximo_numero, reservar_proximo_numero_nfe


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


@pytest.mark.asyncio
async def test_reservar_proximo_numero_avanca_sequencialmente(db_session_factory):
    empresa_id = await _criar_empresa(db_session_factory)
    async with db_session_factory() as session:
        serie1, numero1 = await reservar_proximo_numero(session, empresa_id)
        await session.commit()
        serie2, numero2 = await reservar_proximo_numero(session, empresa_id)
        await session.commit()

    assert serie1 == serie2 == "10001"
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


@pytest.mark.asyncio
async def test_reservar_proximo_numero_nfe_tem_sequencia_propria_independente_da_nfse(db_session_factory):
    # NF-e (modelo 55) e NFS-e sao documentos fiscais distintos: cada um tem
    # serie/numeracao propria, uma nao pode consumir numero da outra.
    empresa_id = await _criar_empresa(db_session_factory)
    async with db_session_factory() as session:
        serie_nfe1, numero_nfe1 = await reservar_proximo_numero_nfe(session, empresa_id)
        await session.commit()
        serie_nfe2, numero_nfe2 = await reservar_proximo_numero_nfe(session, empresa_id)
        await session.commit()
        _serie_nfse, numero_nfse = await reservar_proximo_numero(session, empresa_id)
        await session.commit()

    assert serie_nfe1 == serie_nfe2 == "1"
    assert (numero_nfe1, numero_nfe2) == (1, 2)
    # A NFS-e nao foi afetada pelas duas reservas de NF-e acima.
    assert numero_nfse == 1

    async with db_session_factory() as session:
        empresa = (await session.execute(select(Empresa).where(Empresa.id == empresa_id))).scalar_one()
    assert empresa.proximo_numero_nfe == 3
    assert empresa.proximo_numero == 2


@pytest.mark.asyncio
async def test_reservar_proximo_numero_nfe_e_seguro_sob_concorrencia(db_session_factory):
    empresa_id = await _criar_empresa(db_session_factory)

    async def _reservar_em_sessao_propria() -> int:
        async with db_session_factory() as session:
            _serie, numero = await reservar_proximo_numero_nfe(session, empresa_id)
            await session.commit()
            return numero

    resultados = await asyncio.gather(*[_reservar_em_sessao_propria() for _ in range(20)])

    assert sorted(resultados) == list(range(1, 21))

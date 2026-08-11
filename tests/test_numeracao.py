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

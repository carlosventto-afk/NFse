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

    # Confirmado ao vivo em producao (16/09): ao contrario do que a doc
    # publica sugere (usar a X-Api-Key da empresa recem-criada), tanto
    # adicionar_certificado quanto configurar_nfse devolvem 403 "Acesso nao
    # autorizado" com a chave da empresa -- so funcionam com a chave MESTRE.
    # A chave da empresa (api_key acima) so e usada depois, nas operacoes de
    # emissao/consulta/cancelamento (ver app/worker.py).
    cliente_mestre = SpedyClient(ambiente, chave_mestre)
    try:
        await cliente_mestre.adicionar_certificado(
            spedy_empresa_id, base64.b64decode(pfx_base64), senha or "",
        )
        await cliente_mestre.configurar_nfse(spedy_empresa_id, {
            "series": empresa.serie,
            "environmentType": "production" if ambiente == "producao" else "simulation",
            "nextNumber": empresa.proximo_numero,
        })
    finally:
        await cliente_mestre.close()

    return spedy_empresa_id, api_key

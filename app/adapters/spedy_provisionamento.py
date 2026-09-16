"""Provisionamento de uma empresa na Spedy: criar o cadastro la, subir o
certificado A1 ja usado no caminho direto, e configurar a serie/numeracao.
Chamado uma unica vez, de forma sincrona e explicita, quando o admin liga
`provedor_emissao=spedy` em PUT /empresas/mim -- nunca de dentro do worker."""
from __future__ import annotations

import base64
import logging

from app.adapters.spedy_client import SpedyClient, SpedyError
from app.config import Settings
from app.models import AmbienteEnum, Empresa

logger = logging.getLogger(__name__)


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
    dados_empresa = {
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
    }

    cliente_mestre = SpedyClient(ambiente, chave_mestre)
    try:
        try:
            criada = await cliente_mestre.criar_empresa(dados_empresa)
        except SpedyError as exc:
            if "já possui uma conta" not in str(exc):
                raise
            # Orfa de uma tentativa anterior que criou a empresa na Spedy mas
            # falhou antes de terminar o resto do provisionamento (ex.:
            # certificado invalido). A chave daquela tentativa nunca foi
            # capturada -- a Spedy so devolve a chave da empresa uma vez, na
            # criacao, sem endpoint pra recupera-la depois -- a unica saida e
            # apagar a orfa e recriar do zero. Confirmado ao vivo (16/09):
            # aconteceu de verdade em producao, mais de uma vez na mesma
            # sessao de testes.
            orfas = await cliente_mestre.listar_empresas_por_cnpj(empresa.cnpj)
            for orfa in orfas:
                await cliente_mestre.excluir_empresa(orfa["id"])
            criada = await cliente_mestre.criar_empresa(dados_empresa)

        spedy_empresa_id = criada["id"]
        api_key = criada["apiCredentials"]["apiKey"]

        # Confirmado ao vivo em producao (16/09): ao contrario do que a doc
        # publica sugere (usar a X-Api-Key da empresa recem-criada), tanto
        # adicionar_certificado quanto configurar_nfse devolvem 403 "Acesso
        # nao autorizado" com a chave da empresa -- so funcionam com a chave
        # MESTRE. A chave da empresa (api_key acima) so e usada depois, nas
        # operacoes de emissao/consulta/cancelamento (ver app/worker.py).
        pfx_bytes = base64.b64decode(pfx_base64)
        # Diagnostico temporario (16/09): a Spedy respondeu "Password/
        # CertificateFile field is required" mesmo com certificado novo
        # selecionado -- logando so os tamanhos (nunca o conteudo/senha) pra
        # confirmar se pfx_base64/senha chegam vazios ate aqui.
        logger.warning(
            "diagnostico provisionamento empresa %s: pfx_base64 len=%d, pfx_bytes len=%d, senha vazia=%s",
            empresa.id, len(pfx_base64 or ""), len(pfx_bytes), not senha,
        )
        await cliente_mestre.adicionar_certificado(
            spedy_empresa_id, pfx_bytes, senha or "",
        )
        await cliente_mestre.configurar_nfse(spedy_empresa_id, {
            "series": empresa.serie,
            "environmentType": "production" if ambiente == "producao" else "simulation",
            "nextNumber": empresa.proximo_numero,
        })
    finally:
        await cliente_mestre.close()

    return spedy_empresa_id, api_key

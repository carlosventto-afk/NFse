"""Núcleo de emissão de NF-e modelo 55 (venda de mercadoria).

Espelha a organização de `nfse_core/` (ver docstring daquele pacote). Este
módulo nasce com a montagem do XML; tarefas seguintes do plano de NF-e
modelo 55 adicionam seus próprios arquivos aqui (assinatura, comunicação
com a SEFAZ, leitura de respostas, cancelamento) e acrescentam seus
próprios exports a este mesmo `__init__.py`.

    nfe.py    monta o XML da NF-e e calcula a chave de acesso
    client.py conversa com a SEFAZ (SOAP/zeep): autorização e consulta de protocolo
    signer.py assina o infNFe (reaproveita nfse_core.signer.sign_root_element)
"""

from nfe_core.client import (
    AmbienteEnum, RespostaAutorizacao, RespostaConsulta, SefazClient, UF_ENDPOINTS,
)
from nfe_core.error_catalog import CATALOGO_CSTAT, eh_autorizado
from nfe_core.nfe import NFE_NS, NfeData, NfeItemData, build_nfe_xml, chave_de_acesso
from nfe_core.signer import CertificateError, sign_nfe

__all__ = [
    # montagem
    "NfeData", "NfeItemData", "build_nfe_xml", "chave_de_acesso", "NFE_NS",
    # comunicação
    "AmbienteEnum", "SefazClient", "RespostaAutorizacao", "RespostaConsulta", "UF_ENDPOINTS",
    # catálogo de cStat
    "CATALOGO_CSTAT", "eh_autorizado",
    # assinatura
    "sign_nfe", "CertificateError",
]

"""Núcleo de emissão de NFS-e no padrão NACIONAL (SEFIN / gov.br).

Sete módulos, nenhuma dependência de banco, ORM ou framework web:

    dps.py            monta o XML da DPS (Declaração de Prestação de Serviços)
    signer.py         assina com certificado A1 (ICP-Brasil), padrão DF-e
    client.py         conversa com a SEFIN (mTLS + GZip + Base64)
    evento.py         monta o XML de cancelamento
    resposta.py       lê as respostas da SEFIN de forma tolerante a mudança de nome
    certificado.py    valida o A1: titular, CNPJ, validade, alerta de vencimento
    error_catalog.py  traduz os códigos de erro para português claro

O fluxo de uma emissão:

    xml       = build_dps_xml(DpsData(...))
    assinado  = sign_dps(xml, pfx_base64, senha)
    bruta     = await SefinClient(ambiente, pfx_base64, senha).emitir_dps(assinado)
    resultado = ler_resposta_emissao(bruta)

    if resultado.autorizada:
        guardar(resultado.chave_acesso, resultado.xml_nfse)   # o XML é o documento
    else:
        mostrar(resultado.erros)                              # já traduzidos

O cancelamento é simétrico (`build_evento_cancelamento_xml` → `sign_evento` →
`registrar_evento` → `ler_resposta_evento`).

Tudo o que é específico do SEU sistema (de onde vêm o valor e o tomador, como a
numeração é controlada, onde a emissão é gravada) fica FORA daqui, de propósito
— veja `docs/INTEGRACAO.md`.
"""

from nfse_core.certificado import InfoCertificado, conferir_titularidade, inspecionar
from nfse_core.client import SefinClient, SefinError
from nfse_core.dps import DpsData, build_dps_xml, NFSE_NS
from nfse_core.error_catalog import summarize_for_exception, translate, translate_erros
from nfse_core.evento import EventoCancelamentoData, build_evento_cancelamento_xml
from nfse_core.resposta import (
    RespostaEmissao, RespostaEvento, erros_de_falha,
    ler_resposta_emissao, ler_resposta_evento,
)
from nfse_core.signer import CertificateError, load_pfx, sign_dps, sign_evento

__all__ = [
    # montagem
    "DpsData", "build_dps_xml", "NFSE_NS",
    "EventoCancelamentoData", "build_evento_cancelamento_xml",
    # assinatura
    "sign_dps", "sign_evento", "load_pfx", "CertificateError",
    # comunicação
    "SefinClient", "SefinError",
    # leitura das respostas
    "RespostaEmissao", "RespostaEvento",
    "ler_resposta_emissao", "ler_resposta_evento", "erros_de_falha",
    # certificado
    "InfoCertificado", "inspecionar", "conferir_titularidade",
    # erros
    "translate", "translate_erros", "summarize_for_exception",
]

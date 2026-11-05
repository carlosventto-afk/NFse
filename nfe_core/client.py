"""Cliente SOAP da SEFAZ para autorização e consulta de NF-e (modelo 55).

Cada UF opera (ou delega a um ambiente compartilhado, como o SVRS) seu
próprio webservice `NFeAutorizacao4` (autorização de lote) e
`NFeConsultaProtocolo4` (consulta por chave de acesso), descritos por um
WSDL próprio. Este módulo usa `zeep` como cliente SOAP.

  PLACEHOLDER -- LEIA ANTES DE QUALQUER HOMOLOGACAO/PRODUCAO REAL
  ================================================================
  As URLs em `UF_ENDPOINTS` seguem um padrão PLACEHOLDER
  (`https://nfe.sefaz.<uf>.gov.br/ws/...`), inventado apenas para ter uma
  entrada por UF e permitir este módulo ser testado (mock de `zeep.Client`,
  sem rede real). NENHUMA dessas URLs foi confirmada contra o Manual de
  Integração do Contribuinte de cada UF ou contra a tabela de webservices
  compartilhados (SVRS/SVAN) -- várias UFs não rodam seu próprio ambiente e
  delegam para um desses ambientes compartilhados, o que este módulo ainda
  não reflete. Confirmar/corrigir todas as 27 entradas é tarefa do spike de
  homologação da Fase 1 do plano, não deste módulo.

  Da mesma forma, os nomes de operação SOAP usados aqui (`nfeAutorizacaoLote`,
  `nfeConsultaNF`) e os nomes dos campos lidos da resposta
  (`protNFe.infProt.cStat/xMotivo/nProt`, com fallback pro `cStat`/`xMotivo`
  do topo) seguem o leiaute publicamente
  documentado da NF-e 4.00, mas -- assim como os nomes de tag não
  confirmados em `nfe_core/nfe.py` -- precisam ser reconfirmados contra o
  WSDL real de homologação antes de qualquer emissão real.

  Este módulo também NÃO implementa o transporte mTLS (certificado A1 do
  emitente) que a SEFAZ exige na conexão SOAP real -- `zeep.Client` é
  chamado aqui sem `Transport` customizado. Isso é suficiente pros testes
  (que mockeiam `zeep.Client` inteiramente) mas precisa ser adicionado antes
  de qualquer chamada real.
"""
from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass

import zeep


class AmbienteEnum(str, enum.Enum):
    homologacao = "homologacao"
    producao = "producao"


def _gerar_uf_endpoints() -> dict[str, dict[str, str]]:
    """Gera as 4 URLs (autorização/consulta x homologação/produção) de cada
    UF a partir de um padrão fixo -- ver aviso de PLACEHOLDER no topo do
    módulo. Nenhuma dessas URLs deve ser considerada real."""
    ufs = (
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
        "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
        "SP", "SE", "TO",
    )
    endpoints: dict[str, dict[str, str]] = {}
    for uf in ufs:
        dominio = f"nfe.sefaz.{uf.lower()}.gov.br"
        endpoints[uf] = {
            "autorizacao_homologacao": (
                f"https://{dominio}/ws/homologacao/NFeAutorizacao4/NFeAutorizacao4.asmx?wsdl"
            ),
            "autorizacao_producao": (
                f"https://{dominio}/ws/producao/NFeAutorizacao4/NFeAutorizacao4.asmx?wsdl"
            ),
            "consulta_protocolo_homologacao": (
                f"https://{dominio}/ws/homologacao/NFeConsultaProtocolo4/NFeConsultaProtocolo4.asmx?wsdl"
            ),
            "consulta_protocolo_producao": (
                f"https://{dominio}/ws/producao/NFeConsultaProtocolo4/NFeConsultaProtocolo4.asmx?wsdl"
            ),
        }
    return endpoints


UF_ENDPOINTS: dict[str, dict[str, str]] = _gerar_uf_endpoints()


@dataclass
class RespostaAutorizacao:
    """Resultado de uma autorização, já interpretado.

    `autorizada` é a única coisa que o chamador precisa checar pra decidir o
    caminho feliz (cStat 100). `bruta` guarda o objeto devolvido pelo zeep,
    pra quem precisar inspecionar campos não cobertos aqui."""
    autorizada: bool
    c_stat: str | None = None
    x_motivo: str | None = None
    protocolo: str | None = None
    bruta: object = None


@dataclass
class RespostaConsulta:
    """Resultado de uma consulta de protocolo, já interpretado (mesma forma
    de `RespostaAutorizacao` -- ver docstring dela)."""
    autorizada: bool
    c_stat: str | None = None
    x_motivo: str | None = None
    protocolo: str | None = None
    bruta: object = None


def _texto(valor) -> str | None:
    """Converte pra str sem quebrar quando o campo não existir na resposta
    (leitura tolerante -- mesma ideia de `nfse_core/resposta.py`, adaptada
    pra objetos do zeep em vez de dict)."""
    if valor is None:
        return None
    texto = str(valor)
    return texto or None


def _protocolo_de(resposta) -> str | None:
    try:
        return _texto(resposta.protNFe.infProt.nProt)
    except AttributeError:
        return None


def _campo_efetivo(resposta, campo: str) -> str | None:
    """Lê `campo` (cStat/xMotivo) da NF-e em si, não do envelope.

    No retorno síncrono de `nfeAutorizacaoLote`, o cStat/xMotivo do TOPO são
    do LOTE (ex.: 104 "Lote processado") -- o status da NF-e (100
    "Autorizado o uso", ou a rejeição dela) fica em `protNFe.infProt`. Ler
    só o topo faria toda autorização real virar "rejeitada" (104 != 100).
    Sem `protNFe` (lote assíncrono 103/105, erro de lote, NF-e inexistente
    na consulta -- 217) cai no topo, que aí é o único status que existe.
    Mesmo padrão de `_protocolo_de`: zeep devolve elemento opcional ausente
    como None, então `None.infProt` cai no AttributeError."""
    try:
        valor = _texto(getattr(resposta.protNFe.infProt, campo))
    except AttributeError:
        valor = None
    if valor is not None:
        return valor
    return _texto(getattr(resposta, campo, None))


def _ler_resposta_autorizacao(resposta) -> RespostaAutorizacao:
    c_stat = _campo_efetivo(resposta, "cStat")
    return RespostaAutorizacao(
        autorizada=c_stat == "100",
        c_stat=c_stat,
        x_motivo=_campo_efetivo(resposta, "xMotivo"),
        protocolo=_protocolo_de(resposta),
        bruta=resposta,
    )


def _ler_resposta_consulta(resposta) -> RespostaConsulta:
    # Na consulta (retConsSitNFe) de uma NF-e CANCELADA, o topo vem 101 e
    # protNFe.infProt continua com o 100 da autorizacao original -- aqui isso
    # le como autorizada, o que e o correto pro uso do worker (a nota EXISTE
    # na SEFAZ com aquela chave; reenviar so daria duplicidade).
    c_stat = _campo_efetivo(resposta, "cStat")
    return RespostaConsulta(
        autorizada=c_stat == "100",
        c_stat=c_stat,
        x_motivo=_campo_efetivo(resposta, "xMotivo"),
        protocolo=_protocolo_de(resposta),
        bruta=resposta,
    )


class SefazClient:
    """Cliente SOAP da SEFAZ. Sem estado entre chamadas -- cada operação
    cria seu próprio `zeep.Client` a partir da URL da UF/ambiente, pois cada
    operação usa um WSDL (serviço) diferente."""

    async def autorizar(self, xml_assinado: bytes, uf: str, ambiente: AmbienteEnum) -> RespostaAutorizacao:
        url = UF_ENDPOINTS[uf.upper()][f"autorizacao_{AmbienteEnum(ambiente).value}"]
        return await asyncio.to_thread(self._autorizar_sync, url, xml_assinado)

    def _autorizar_sync(self, url: str, xml_assinado: bytes) -> RespostaAutorizacao:
        cliente = zeep.Client(url)
        resposta = cliente.service.nfeAutorizacaoLote(nfeDadosMsg=xml_assinado.decode("utf-8"))
        return _ler_resposta_autorizacao(resposta)

    async def consultar_protocolo(self, chave_acesso: str, uf: str, ambiente: AmbienteEnum) -> RespostaConsulta:
        url = UF_ENDPOINTS[uf.upper()][f"consulta_protocolo_{AmbienteEnum(ambiente).value}"]
        return await asyncio.to_thread(self._consultar_protocolo_sync, url, chave_acesso)

    def _consultar_protocolo_sync(self, url: str, chave_acesso: str) -> RespostaConsulta:
        cliente = zeep.Client(url)
        resposta = cliente.service.nfeConsultaNF(nfeDadosMsg=chave_acesso)
        return _ler_resposta_consulta(resposta)

"""Construtor do XML do evento de cancelamento da NF-e modelo 55.

Leiaute: Evento de Cancelamento de NF-e (NT da NF-e), tpEvento="110111",
namespace oficial http://www.portalfiscal.inf.br/nfe. Espelha
`nfse_core/evento.py` (mesma estrutura: dataclass + `id_...` + `_el()` +
só monta o XML, sem assinar nem submeter -- a submissão fica para quando
houver um `SefazClient` de eventos).

NÃO é a implementação exaustiva do schema XSD completo do `envEvento`: o
CNPJ/CPF do autor do evento e o ambiente (tpAmb) ficam fora de
`EventoCancelamentoNfeData` neste MVP (o brief da tarefa restringe o
dataclass aos três campos abaixo) -- `tpAmb` sai fixo em homologação e a
tag `CNPJ` do autor é omitida. Quando a submissão real do evento for
implementada, esses dados precisam ser adicionados aqui. Os nomes exatos
de tag usados seguem o leiaute publicamente documentado nas notas
técnicas da NF-e, mas devem ser reconfirmados contra o schema/WSDL de
homologação da SEFAZ-PA (spike da Fase 1) antes de qualquer emissão real
-- mesma ressalva de `nfe_core/nfe.py` e `nfe_core/client.py`.

Regra do Id (leiaute): infEvento.Id = "ID" + tpEvento(6) + chave(44) +
nSeqEvento(2, zero-padded).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from lxml import etree

from nfe_core.nfe import NFE_NS, _digits

TP_AMB_HOMOLOGACAO = 2  # fixo neste MVP -- ver ressalva no docstring do módulo
TP_EVENTO_CANCELAMENTO = "110111"
N_SEQ_EVENTO = "1"  # primeiro e único evento deste tipo por NF-e, neste MVP
VER_EVENTO = "1.00"
DESC_EVENTO_CANCELAMENTO = "Cancelamento"


@dataclass
class EventoCancelamentoNfeData:
    chave_acesso: str
    protocolo_autorizacao: str
    justificativa: str

    @property
    def id_evento(self) -> str:
        chave = _digits(self.chave_acesso).zfill(44)
        return f"ID{TP_EVENTO_CANCELAMENTO}{chave}{N_SEQ_EVENTO.zfill(2)}"


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    node = etree.SubElement(parent, f"{{{NFE_NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def build_evento_cancelamento_nfe_xml(data: EventoCancelamentoNfeData) -> bytes:
    """Monta o XML do evento de cancelamento da NF-e (sem assinatura).

    Retorna bytes UTF-8.
    """
    chave = _digits(data.chave_acesso)
    if len(chave) != 44:
        raise ValueError(
            f"chave de acesso inválida: '{data.chave_acesso}' tem {len(chave)} "
            "dígitos, precisa ter exatamente 44"
        )
    protocolo = data.protocolo_autorizacao.strip()
    if not protocolo:
        raise ValueError("protocolo de autorização (nProt) é obrigatório")
    justificativa = data.justificativa.strip()
    if len(justificativa) < 15:
        raise ValueError(
            f"justificativa do cancelamento precisa ter ao menos 15 caracteres "
            f"(tem {len(justificativa)})"
        )

    c_orgao = chave[:2]
    dh_evento = datetime.now(timezone.utc)

    root = etree.Element(f"{{{NFE_NS}}}envEvento", versao=VER_EVENTO, nsmap={None: NFE_NS})
    _el(root, "idLote", "1")

    evento = _el(root, "evento")
    evento.set("versao", VER_EVENTO)
    inf = _el(evento, "infEvento")
    inf.set("Id", data.id_evento)

    _el(inf, "cOrgao", c_orgao)
    _el(inf, "tpAmb", str(TP_AMB_HOMOLOGACAO))
    _el(inf, "chNFe", chave)
    _el(inf, "dhEvento", dh_evento.isoformat(timespec="seconds"))
    _el(inf, "tpEvento", TP_EVENTO_CANCELAMENTO)
    _el(inf, "nSeqEvento", N_SEQ_EVENTO)
    _el(inf, "verEvento", VER_EVENTO)

    det = _el(inf, "detEvento")
    det.set("versao", VER_EVENTO)
    _el(det, "descEvento", DESC_EVENTO_CANCELAMENTO)
    _el(det, "nProt", protocolo)
    _el(det, "xJust", justificativa[:255])

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

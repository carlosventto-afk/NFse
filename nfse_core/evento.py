"""Construtor do XML do Pedido de Registro de Evento de NFS-e (padrão nacional).

Leiaute: NFS-e Nacional ANEXO II (Pedido de Registro de Eventos) v1.00.
Só implementa o evento e101101 (Cancelamento de NFS-e) — os demais
(cancelamento por substituição, análise fiscal, rejeição/confirmação do
tomador etc.) ficam para quando houver necessidade real.

IMPORTANTE (E1235 — descoberto na prática, não documentado em manual/swagger
oficial): a API espera como raiz do XML submetido o `pedRegEvento` (o PEDIDO
em si), não o `evento` completo. O `evento`/`infEvento` (com nSeqEvento,
ambGer, nDFSe, dhProc) é o artefato final que o Sistema Nacional CONSTRÓI ao
redor do nosso pedido e devolve/armazena — simétrico ao par DPS→NFS-e (nós
submetemos a DPS, o sistema gera e guarda a NFS-e completa).

Regra do Id (leiaute): infPedReg.Id = "PRE" + chave(50) + tipoEvento(6)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from lxml import etree

from nfse_core.dps import NFSE_NS, _digits, _sanitize_text

PED_REG_EVENTO_VERSAO = "1.00"
TIPO_EVENTO_CANCELAMENTO = "101101"  # e101101


@dataclass
class EventoCancelamentoData:
    chave_nfse: str
    tp_amb: int                    # 1=produção, 2=homologação
    dh_evento: datetime            # com timezone
    autor_cpf_cnpj: str             # CNPJ ou CPF do autor do evento (normalmente o prestador)
    c_motivo: str = "1"             # 1=Erro na Emissão, 2=Serviço não Prestado, 9=Outros
    x_motivo: str = ""
    ver_aplic: str = "NFSeKit/1.0"

    @property
    def id_ped_reg(self) -> str:
        chave = _digits(self.chave_nfse).zfill(50)
        return f"PRE{chave}{TIPO_EVENTO_CANCELAMENTO}"


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    node = etree.SubElement(parent, f"{{{NFSE_NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def build_evento_cancelamento_xml(data: EventoCancelamentoData) -> bytes:
    """Monta o XML do Pedido de Registro de Evento de cancelamento (sem
    assinatura). Retorna bytes UTF-8."""
    chave = _digits(data.chave_nfse)
    if len(chave) != 50:
        raise ValueError("Chave de acesso da NFS-e inválida (esperado 50 dígitos)")
    autor_doc = _digits(data.autor_cpf_cnpj)
    if len(autor_doc) not in (11, 14):
        raise ValueError("CPF/CNPJ do autor do evento ausente ou inválido")
    x_motivo = _sanitize_text(data.x_motivo)[:255]
    if len(x_motivo) < 15:
        x_motivo = x_motivo.ljust(15, ".")

    root = etree.Element(f"{{{NFSE_NS}}}pedRegEvento", versao=PED_REG_EVENTO_VERSAO, nsmap={None: NFSE_NS})
    inf = etree.SubElement(root, f"{{{NFSE_NS}}}infPedReg")
    inf.set("Id", data.id_ped_reg)

    _el(inf, "tpAmb", str(data.tp_amb))
    _el(inf, "verAplic", data.ver_aplic[:20])
    _el(inf, "dhEvento", data.dh_evento.isoformat(timespec="seconds"))
    _el(inf, "CPFAutor" if len(autor_doc) == 11 else "CNPJAutor",
        autor_doc if len(autor_doc) == 11 else autor_doc.zfill(14))
    _el(inf, "chNFSe", chave)

    e101101 = _el(inf, "e101101")
    _el(e101101, "xDesc", "Cancelamento de NFS-e")
    _el(e101101, "cMotivo", data.c_motivo)
    _el(e101101, "xMotivo", x_motivo)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

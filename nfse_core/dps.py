"""Construtor do XML da DPS — Declaração de Prestação de Serviços (padrão nacional).

Leiaute: NFS-e Nacional ANEXO I (SEFIN ADN-DPS/NFSe) v1.01 de 09/02/2026;
schemas oficiais: NFSe-ESQUEMAS_XSD-v1.01 em
https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual
Estrutura mínima do prestador de serviço educacional (ISSQN tributado no
município do prestador, sem retenção). Campos da reforma (IBS/CBS) entram na
fase 2 do módulo, quando obrigatórios para o regime da escola.

Regra do Id da DPS (45 chars): "DPS" + cLocEmi(7) + tpInscricao(1: 1=CPF 2=CNPJ)
+ inscrição federal com zeros à esquerda(14) + série(5) + número(15).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from lxml import etree

NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
# 1.00 = versão dos integradores homologados hoje; 1.01 (IBS/CBS) entra quando
# a produção restrita estabilizar o validador do leiaute novo
DPS_VERSAO = "1.00"


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


# Pontuação tipográfica → ASCII. E0714 na SEFIN é disparado por "caracteres
# inválidos" em campos texto (caso real: travessão na discriminação do serviço).
_TYPOGRAPHIC = str.maketrans({
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', " ": " ", "…": "...",
})


def _sanitize_text(value: str) -> str:
    """Texto seguro para a SEFIN: transliterado para ASCII.

    O validador rejeita com E0714 ("erro na assinatura") quando campos texto
    têm caracteres não-ASCII — o digest é recalculado lá com decodificação
    divergente. Prática consolidada no ecossistema DF-e: emitir sem acento.
    """
    value = (value or "").translate(_TYPOGRAPHIC)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^\S ]+", " ", value).strip()


@dataclass
class DpsData:
    # Ambiente/controle
    tp_amb: int                    # 1=produção, 2=homologação (produção restrita)
    dh_emi: datetime               # com timezone
    serie: str
    numero: int
    competencia: date              # dCompet — competência do serviço
    ver_aplic: str = "NFSeKit/1.0"

    # Prestador (a unidade emissora)
    prest_cnpj: str = ""
    prest_im: str | None = None
    c_loc_emi: str = ""            # código IBGE (7) do município emissor
    op_simp_nac: int = 2           # 1=não optante, 2=optante MEI, 3=optante ME/EPP — conferir tabela
    reg_ap_trib_sn: int | None = None  # regime de apuração SN — obrigatório quando opSimpNac=3
    reg_esp_trib: int = 0          # 0=nenhum; 3=imune... conferir tabela do leiaute

    # Tomador (o responsável financeiro)
    toma_cpf_cnpj: str = ""
    toma_nome: str = ""
    toma_email: str | None = None

    # Serviço
    c_trib_nac: str = "080101"     # código de tributação nacional (LC116 item+desdobro)
    x_desc_serv: str = ""
    c_loc_prestacao: str = ""      # IBGE do local da prestação (padrão: mesmo do emissor)

    # Valores
    v_serv: Decimal = Decimal("0")
    p_aliq: Decimal | None = None  # alíquota ISS % (omitir quando o município fixa)

    @property
    def tp_inscricao(self) -> str:
        return "1" if len(_digits(self.toma_cpf_cnpj)) == 11 else "2"

    @property
    def dps_id(self) -> str:
        doc = _digits(self.prest_cnpj)
        tp = "1" if len(doc) == 11 else "2"
        return (
            "DPS"
            + _digits(self.c_loc_emi).zfill(7)
            + tp
            + doc.zfill(14)
            + _digits(self.serie).zfill(5)
            + str(self.numero).zfill(15)
        )


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    node = etree.SubElement(parent, f"{{{NFSE_NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def build_dps_xml(data: DpsData) -> bytes:
    """Monta o XML da DPS (sem assinatura). Retorna bytes UTF-8."""
    if not _digits(data.prest_cnpj):
        raise ValueError("CNPJ do prestador (unidade) não configurado")
    if len(_digits(data.c_loc_emi)) != 7:
        raise ValueError("Código IBGE do município emissor inválido (esperado 7 dígitos)")
    toma_doc = _digits(data.toma_cpf_cnpj)
    if len(toma_doc) not in (11, 14):
        raise ValueError("CPF/CNPJ do tomador ausente ou inválido")
    if data.v_serv <= 0:
        raise ValueError("Valor do serviço deve ser positivo")

    root = etree.Element(f"{{{NFSE_NS}}}DPS", versao=DPS_VERSAO, nsmap={None: NFSE_NS})
    inf = etree.SubElement(root, f"{{{NFSE_NS}}}infDPS")
    inf.set("Id", data.dps_id)

    _el(inf, "tpAmb", str(data.tp_amb))
    _el(inf, "dhEmi", data.dh_emi.isoformat(timespec="seconds"))
    _el(inf, "verAplic", data.ver_aplic[:20])
    # Manual §6.1.1.d: sem zeros não significativos (o zfill fica só no Id)
    _el(inf, "serie", str(int(_digits(data.serie) or "1")))
    _el(inf, "nDPS", str(data.numero))
    _el(inf, "dCompet", data.competencia.isoformat())
    _el(inf, "tpEmit", "1")                                    # 1 = emitida pelo prestador
    _el(inf, "cLocEmi", _digits(data.c_loc_emi))

    prest = _el(inf, "prest")
    prest_doc = _digits(data.prest_cnpj)
    # Prestador pode ser PJ (escola) ou PF (ex.: professor autônomo); a tag
    # e o Id da DPS seguem o tamanho da inscrição federal
    _el(prest, "CPF" if len(prest_doc) == 11 else "CNPJ",
        prest_doc if len(prest_doc) == 11 else prest_doc.zfill(14))
    if data.prest_im:
        _el(prest, "IM", _digits(data.prest_im))
    reg = _el(prest, "regTrib")
    _el(reg, "opSimpNac", str(data.op_simp_nac))
    if data.reg_ap_trib_sn is not None:
        _el(reg, "regApTribSN", str(data.reg_ap_trib_sn))
    _el(reg, "regEspTrib", str(data.reg_esp_trib))

    toma = _el(inf, "toma")
    _el(toma, "CPF" if len(toma_doc) == 11 else "CNPJ", toma_doc)
    _el(toma, "xNome", _sanitize_text(data.toma_nome)[:300])
    if data.toma_email:
        _el(toma, "email", data.toma_email.strip()[:80])

    serv = _el(inf, "serv")
    loc = _el(serv, "locPrest")
    _el(loc, "cLocPrestacao", _digits(data.c_loc_prestacao or data.c_loc_emi))
    cserv = _el(serv, "cServ")
    _el(cserv, "cTribNac", _digits(data.c_trib_nac).zfill(6))
    _el(cserv, "xDescServ", _sanitize_text(data.x_desc_serv)[:2000] or "Servicos educacionais")

    valores = _el(inf, "valores")
    vsp = _el(valores, "vServPrest")
    _el(vsp, "vServ", f"{data.v_serv:.2f}")
    trib = _el(valores, "trib")
    trib_mun = _el(trib, "tribMun")
    _el(trib_mun, "tribISSQN", "1")                            # 1 = operação tributável
    if data.p_aliq is not None:
        _el(trib_mun, "pAliq", f"{data.p_aliq:.2f}")
    _el(trib_mun, "tpRetISSQN", "1")                           # 1 = não retido
    trib_fed = _el(trib, "tribFed")
    pis_cofins = _el(trib_fed, "piscofins")
    _el(pis_cofins, "CST", "00")                               # 00 = nenhum
    tot = _el(trib, "totTrib")
    if data.op_simp_nac == 3:
        # E0712: ME/EPP não pode usar indTotTrib — exige o detalhamento em
        # percentual (zerado, na ausência de cálculo de carga tributária).
        p_tot = _el(tot, "pTotTrib")
        _el(p_tot, "pTotTribFed", "0.00")
        _el(p_tot, "pTotTribEst", "0.00")
        _el(p_tot, "pTotTribMun", "0.00")
    else:
        _el(tot, "indTotTrib", "0")                            # 0 = não informa total de tributos

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

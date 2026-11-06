"""Construtor do XML da NF-e modelo 55 (venda de mercadoria).

Leiaute: NF-e 4.00 (NT da NF-e), namespace oficial
http://www.portalfiscal.inf.br/nfe. Estrutura mínima: identificação (ide),
emitente (emit), destinatário (dest) e itens (det/prod/imposto/ICMS), com
partilha de ICMS interestadual (ICMSUFDest, EC 87/2015) só quando a UF do
destinatário difere da UF do emitente E o destinatário não tem IE (não
contribuinte / consumidor final) -- venda interestadual B2B não tem DIFAL.

NAO é a implementação exaustiva do schema XSD completo (sem enderEmit,
enderDest, totais <total>, transporte <transp> ou grupos de PIS/COFINS/IPI
por item) -- esses grupos exigem dados que NfeData ainda não carrega
(endereço completo, totalizadores calculados) e ficam para quando essas
informações existirem no restante do plano. Os nomes exatos de tag usados
aqui seguem o leiaute publicamente documentado nas notas técnicas da NF-e,
mas devem ser reconfirmados contra o schema/WSDL de homologação da SEFAZ-PA
(spike da Fase 1) antes de qualquer emissão real.

Regra da chave de acesso (44 dígitos): cUF(2) + AAMM(4) + CNPJ(14) +
mod(2)="55" + série(3) + número(9) + tpEmis(1) + cNF(8) + DV(1, mod-11).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from lxml import etree

NFE_NS = "http://www.portalfiscal.inf.br/nfe"

# So estes CST tem vBC/vICMS no leiaute real (00 tributada integralmente,
# 10 com ST, 20 com reducao de base, 51 diferimento, 70 reducao+ST, 90
# outros). Qualquer CST fora desta lista (ex.: 30 isenta/nao-tributada
# com ST, 40/41/50 isenta/nao-tributada/suspensao, 60 ST ja retido) nao
# tem esses campos -- omitir em vez de arriscar emitir errado.
_CST_COM_VBC_VICMS = frozenset({"00", "10", "20", "51", "70", "90"})

# Simples Nacional: SO o CSOSN 900 ("Outros") tem vBC/vICMS no leiaute
# real. Os demais (101, 102, 103, 201, 202, 203, 300, 400, 500) nao tem
# esses campos -- alguns (ex.: 101) tem campos PROPRIOS (pCredSN,
# vCredICMSSN) que este modulo ainda nao modela (NfeItemData nao carrega
# essa informacao). Omitir vBC/vICMS para qualquer CSOSN fora desta lista
# e o minimo seguro (nao emite campo errado); nao e a implementacao
# completa do CSOSN 101 em si, que precisa de pCredSN/vCredICMSSN -- fica
# para quando esses dados existirem no cadastro (ver Fase 1 do plano).
_CSOSN_COM_VBC_VICMS = frozenset({"900"})

# Nome do grupo XML (independente de ter vBC/vICMS): o leiaute agrupa
# CST 40/41/50 em ICMS40 e CSOSN 102/103/300/400 em ICMSSN102; os demais
# códigos usam o grupo de mesmo número (ICMS{cst} / ICMSSN{csosn}).
_CST_GRUPO_ICMS40 = frozenset({"40", "41", "50"})
_CSOSN_GRUPO_ICMSSN102 = frozenset({"102", "103", "300", "400"})


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _dv_mod11(chave_sem_dv: str) -> str:
    """Dígito verificador mod-11 da chave de acesso (pesos 2..9 cíclicos, da direita p/ a esquerda)."""
    pesos = (2, 3, 4, 5, 6, 7, 8, 9)
    soma = sum(int(digito) * pesos[i % len(pesos)] for i, digito in enumerate(reversed(chave_sem_dv)))
    resto = soma % 11
    return "0" if resto in (0, 1) else str(11 - resto)


@dataclass
class NfeItemData:
    n_item: int
    c_prod: str
    descricao: str
    ncm: str
    cfop: str
    unidade: str
    quantidade: Decimal
    valor_unitario: Decimal
    valor_total: Decimal
    # ICMS: exatamente um dos dois é esperado -- CST para Regime Normal
    # (CRT=3), CSOSN para Simples Nacional (CRT=1/2). Usar o campo errado
    # pro regime da empresa é rejeitado na SEFAZ (ver Review Focus do plano).
    cst_icms: str | None
    csosn_icms: str | None
    base_icms: Decimal | None
    valor_icms: Decimal | None
    # Partilha ICMS interestadual (EC 87/2015) -- só relevantes/emitidos
    # quando a UF do destinatário difere da UF do emitente E o destinatário
    # não tem IE (não contribuinte). Fora disso, devem ser None.
    valor_icms_uf_remetente: Decimal | None
    valor_icms_uf_destino: Decimal | None
    valor_fcp: Decimal | None


@dataclass
class NfeData:
    # Ambiente/controle
    tp_amb: int                    # 1=produção, 2=homologação
    c_uf_emit: str                 # código IBGE (2 dígitos) da UF do emitente
    dh_emi: datetime
    serie: str
    numero: int

    # Emitente
    emit_cnpj: str
    emit_ie: str
    emit_crt: int                  # 1=SN, 2=SN excesso sublimite, 3=Regime Normal
    emit_uf: str                   # sigla (ex.: "PA") -- usada pra decidir partilha interestadual

    # Destinatário
    dest_cpf_cnpj: str
    dest_nome: str
    dest_uf: str
    dest_ie: str | None             # None => não contribuinte de ICMS (indIEDest=9)

    itens: list[NfeItemData]


def _el(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    node = etree.SubElement(parent, f"{{{NFE_NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def _gerar_c_nf(data: NfeData) -> str:
    """Código numérico (cNF) determinístico derivado de série+número.

    Em produção, o cNF deveria ser gerado uma única vez e persistido junto
    da emissão (mesmo padrão do dps_id em app/worker.py), pra que reenvio
    após rejeição reaproveite a mesma chave (idempotência -- ver Global
    Constraints do plano). Essa persistência é responsabilidade da camada
    de worker/infraestrutura, fora deste módulo de montagem de XML; aqui
    apenas derivamos um valor estável a partir de série+número, suficiente
    pra chave ser determinística dentro deste módulo.
    """
    base = f"{_digits(data.serie)}{data.numero}".zfill(8)
    return base[-8:]


def chave_de_acesso(data: NfeData, c_nf: str) -> str:
    """Monta a chave de acesso de 44 dígitos (algoritmo padrão das NTs da NF-e)."""
    uf = _digits(data.c_uf_emit)
    if len(uf) != 2:
        raise ValueError(
            f"código IBGE da UF do emitente inválido: '{data.c_uf_emit}' tem {len(uf)} "
            "dígitos, precisa ter exatamente 2"
        )
    cnpj = _digits(data.emit_cnpj)
    if len(cnpj) != 14:
        raise ValueError(
            f"CNPJ do emitente inválido: '{data.emit_cnpj}' tem {len(cnpj)} dígitos, "
            "precisa ter exatamente 14"
        )
    c_nf_digitos = _digits(c_nf)
    if len(c_nf_digitos) != 8:
        raise ValueError(
            f"código numérico (cNF) inválido: '{c_nf}' tem {len(c_nf_digitos)} dígitos, "
            "precisa ter exatamente 8"
        )

    aamm = data.dh_emi.strftime("%y%m")
    serie = _digits(data.serie).zfill(3)
    numero = str(data.numero).zfill(9)
    tp_emis = "1"  # emissão normal -- sem contingência neste MVP

    chave_sem_dv = f"{uf}{aamm}{cnpj}55{serie}{numero}{tp_emis}{c_nf_digitos}"
    return chave_sem_dv + _dv_mod11(chave_sem_dv)


def _add_det(inf: etree._Element, item: NfeItemData, difal: bool) -> None:
    """`difal`: interestadual E destinatário não contribuinte -- único caso em
    que o grupo ICMSUFDest (partilha EC 87/2015) existe."""
    det = _el(inf, "det")
    det.set("nItem", str(item.n_item))

    prod = _el(det, "prod")
    _el(prod, "cProd", item.c_prod)
    _el(prod, "xProd", item.descricao)
    _el(prod, "NCM", _digits(item.ncm))
    _el(prod, "CFOP", _digits(item.cfop))
    _el(prod, "uCom", item.unidade)
    _el(prod, "qCom", f"{item.quantidade:.4f}")
    _el(prod, "vUnCom", f"{item.valor_unitario:.4f}")
    _el(prod, "vProd", f"{item.valor_total:.2f}")

    imposto = _el(det, "imposto")
    icms = _el(imposto, "ICMS")

    if item.cst_icms is not None and item.csosn_icms is not None:
        raise ValueError(
            "item não pode ter CST e CSOSN de ICMS ao mesmo tempo (CST é do Regime "
            "Normal, CSOSN é do Simples Nacional)"
        )
    if item.cst_icms is None and item.csosn_icms is None:
        raise ValueError(
            "item de ICMS precisa de CST ou CSOSN informado (CST pro Regime Normal, "
            "CSOSN pro Simples Nacional)"
        )

    if item.cst_icms is not None:
        cst = _digits(item.cst_icms)
        # zfill silencioso esconderia um código incompleto (mesma lição do
        # cNBS em nfse_core/dps.py) -- erra alto em vez disso.
        if len(cst) != 2:
            raise ValueError(
                f"CST de ICMS inválido: '{item.cst_icms}' tem {len(cst)} dígitos, "
                "precisa ter exatamente 2"
            )
        tem_vbc_vicms = cst in _CST_COM_VBC_VICMS
        grupo = _el(icms, "ICMS40" if cst in _CST_GRUPO_ICMS40 else f"ICMS{cst}")
        _el(grupo, "orig", "0")   # 0 = nacional; sem campo dedicado de origem no MVP
        _el(grupo, "CST", cst)
    else:
        csosn = _digits(item.csosn_icms)
        if len(csosn) != 3:
            raise ValueError(
                f"CSOSN inválido: '{item.csosn_icms}' tem {len(csosn)} dígitos, "
                "precisa ter exatamente 3"
            )
        tem_vbc_vicms = csosn in _CSOSN_COM_VBC_VICMS
        grupo = _el(icms, "ICMSSN102" if csosn in _CSOSN_GRUPO_ICMSSN102 else f"ICMSSN{csosn}")
        _el(grupo, "orig", "0")
        _el(grupo, "CSOSN", csosn)

    # Allow-list: só códigos que TÊM vBC/vICMS no leiaute os recebem. O
    # cálculo (app/adapters/icms.py, que não ramifica por código) preenche
    # base/valor sempre; para os demais códigos eles não vão pro XML.
    if tem_vbc_vicms:
        if item.base_icms is not None:
            _el(grupo, "vBC", f"{item.base_icms:.2f}")
        if item.valor_icms is not None:
            _el(grupo, "vICMS", f"{item.valor_icms:.2f}")

    tem_partilha = any(
        v is not None for v in (item.valor_fcp, item.valor_icms_uf_destino, item.valor_icms_uf_remetente)
    )
    if tem_partilha and not difal:
        raise ValueError(
            f"item {item.n_item} tem valores de partilha do ICMS (DIFAL/ICMSUFDest), mas a "
            "operacao nao e interestadual para nao contribuinte -- partilha so se aplica a "
            "destinatario sem IE em venda interestadual"
        )
    if tem_partilha:
        icms_uf_dest = _el(imposto, "ICMSUFDest")
        if item.valor_fcp is not None:
            _el(icms_uf_dest, "vFCPUFDest", f"{item.valor_fcp:.2f}")
        if item.valor_icms_uf_destino is not None:
            _el(icms_uf_dest, "vICMSUFDest", f"{item.valor_icms_uf_destino:.2f}")
        if item.valor_icms_uf_remetente is not None:
            _el(icms_uf_dest, "vICMSUFRemet", f"{item.valor_icms_uf_remetente:.2f}")


def build_nfe_xml(data: NfeData) -> bytes:
    """Monta o XML da NF-e (sem assinatura). Retorna bytes UTF-8."""
    emit_doc = _digits(data.emit_cnpj)
    if len(emit_doc) != 14:
        raise ValueError(
            f"CNPJ do emitente inválido: '{data.emit_cnpj}' tem {len(emit_doc)} dígitos, "
            "precisa ter exatamente 14"
        )
    dest_doc = _digits(data.dest_cpf_cnpj)
    if len(dest_doc) not in (11, 14):
        raise ValueError(
            f"CPF/CNPJ do destinatário inválido: '{data.dest_cpf_cnpj}' tem "
            f"{len(dest_doc)} dígitos, precisa ter 11 (CPF) ou 14 (CNPJ)"
        )
    if not data.itens:
        raise ValueError("NF-e precisa de ao menos um item")
    if data.dh_emi.tzinfo is None:
        # dhEmi exige offset UTC (ex.: -03:00); naive geraria a tag sem fuso.
        raise ValueError("dh_emi precisa ter timezone (nao pode ser naive)")

    c_nf = _gerar_c_nf(data)
    chave = chave_de_acesso(data, c_nf=c_nf)
    interestadual = data.emit_uf.strip().upper() != data.dest_uf.strip().upper()
    # Mesmo predicado do indIEDest abaixo: sem IE => não contribuinte. Ele
    # decide indFinal e se há DIFAL (ICMSUFDest) -- espelha o gate de
    # app/adapters/icms.py (calcular_icms_item), pra XML e cálculo concordarem.
    dest_contribuinte = bool(data.dest_ie)
    difal = interestadual and not dest_contribuinte

    root = etree.Element(f"{{{NFE_NS}}}NFe", nsmap={None: NFE_NS})
    inf = etree.SubElement(root, f"{{{NFE_NS}}}infNFe", versao="4.00")
    inf.set("Id", f"NFe{chave}")

    ide = _el(inf, "ide")
    _el(ide, "cUF", _digits(data.c_uf_emit).zfill(2))
    _el(ide, "cNF", c_nf)
    _el(ide, "natOp", "VENDA DE MERCADORIA")   # fixo no MVP -- sem campo dedicado ainda
    _el(ide, "mod", "55")
    _el(ide, "serie", str(int(_digits(data.serie) or "1")))
    _el(ide, "nNF", str(data.numero))
    _el(ide, "dhEmi", data.dh_emi.isoformat(timespec="seconds"))
    _el(ide, "tpNF", "1")                      # 1 = saída
    _el(ide, "idDest", "2" if interestadual else "1")
    _el(ide, "tpImp", "1")                     # 1 = DANFE retrato
    _el(ide, "tpEmis", "1")                    # 1 = emissão normal
    _el(ide, "cDV", chave[-1])
    _el(ide, "tpAmb", str(data.tp_amb))
    _el(ide, "finNFe", "1")                    # 1 = NF-e normal
    # indFinal: 1 = consumidor final, 0 = normal. SIMPLIFICAÇÃO: derivado só
    # de ter IE (contribuinte comprando pra uso/consumo próprio também seria
    # consumidor final) -- ver docstring de app/adapters/icms.py. Ordem
    # finNFe -> indFinal -> indPres segue o leiaute 4.00; reconfirmar no spike
    # de homologação da Fase 1 (indPres ainda não é emitido).
    _el(ide, "indFinal", "0" if dest_contribuinte else "1")
    _el(ide, "procEmi", "0")                   # 0 = emissão própria do contribuinte
    _el(ide, "verProc", "NfeCore/1.0")

    emit = _el(inf, "emit")
    _el(emit, "CNPJ", emit_doc)
    if data.emit_ie:
        _el(emit, "IE", _digits(data.emit_ie))
    _el(emit, "CRT", str(data.emit_crt))
    # enderEmit (endereço completo) fica fora do MVP -- NfeData ainda não
    # carrega logradouro/município do emitente. Só a UF, necessária pra
    # decidir a partilha de ICMS interestadual, é emitida aqui.
    _el(emit, "UF", data.emit_uf.strip().upper())

    dest = _el(inf, "dest")
    _el(dest, "CPF" if len(dest_doc) == 11 else "CNPJ", dest_doc)
    _el(dest, "xNome", data.dest_nome[:60])
    if dest_contribuinte:
        _el(dest, "IE", _digits(data.dest_ie))
        _el(dest, "indIEDest", "1")            # 1 = contribuinte de ICMS
    else:
        _el(dest, "indIEDest", "9")            # 9 = não contribuinte
    _el(dest, "UF", data.dest_uf.strip().upper())

    for item in data.itens:
        _add_det(inf, item, difal)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")

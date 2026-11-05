"""Monta `NfeData` a partir do cadastro (Empresa/Cliente/Produto) e do pedido.

Espelha `app/adapters/dps_builder.py`: funcao pura que le os campos dos
models (sem I/O, sem efeitos colaterais) e monta a dataclass de dominio que
`nfe_core.nfe.build_nfe_xml` espera. ICMS-ST (substituicao tributaria) fica
fora de escopo -- um produto marcado como tal é rejeitado aqui com erro
claro, em vez de gerar um XML fiscalmente incorreto.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.adapters.icms import calcular_icms_item
from app.models import AmbienteEnum, Cliente, Empresa, Produto
from nfe_core.nfe import NfeData, NfeItemData

_CENTAVOS = Decimal("0.01")

# CRT (Codigo de Regime Tributario) -- 1=Simples Nacional, 2=Simples Nacional
# com excesso de sublimite: ambos usam CSOSN no item. 3=Regime Normal, usa CST.
_CRT_SIMPLES_NACIONAL = frozenset({1, 2})


@dataclass
class ItemPedido:
    produto_id: uuid.UUID
    quantidade: Decimal
    valor_unitario_override: Decimal | None
    # Aliquota interna do ICMS na UF de destino (%), so usada quando a venda
    # e interestadual (empresa.uf != cliente.uf). O projeto ainda nao tem
    # tabela automatica de aliquota interna por UF (ver app/adapters/icms.py)
    # -- por ora e informada manualmente por quem monta o pedido (equivalente
    # ao "cadastro manual" previsto no design doc da Fase 5). Venda interna
    # ignora este campo. Venda interestadual sem ele levanta
    # AliquotaInterestadualInvalida (ver calcular_icms_item).
    aliquota_interna_destino: Decimal | None = None


def _arredondar(valor: Decimal) -> Decimal:
    return valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def _montar_item(n_item: int, produto: Produto, item: ItemPedido, empresa: Empresa, cliente: Cliente) -> NfeItemData:
    if produto.eh_substituicao_tributaria:
        raise ValueError(
            f"produto '{produto.descricao}' esta marcado com Substituicao Tributaria "
            "(ICMS-ST) -- fora do escopo deste builder, que so trata ICMS normal"
        )

    usa_simples_nacional = empresa.crt in _CRT_SIMPLES_NACIONAL
    cst_icms = None if usa_simples_nacional else produto.cst_icms
    csosn_icms = produto.csosn_icms if usa_simples_nacional else None

    valor_unitario = item.valor_unitario_override
    if valor_unitario is None:
        valor_unitario = produto.valor_unitario_padrao
    if valor_unitario is None:
        raise ValueError(
            f"produto '{produto.descricao}' nao tem valor_unitario_padrao cadastrado "
            "e o item do pedido nao informou valor_unitario_override"
        )
    valor_total = _arredondar(item.quantidade * valor_unitario)

    icms = calcular_icms_item(
        valor_total=valor_total,
        uf_emitente=empresa.uf,
        uf_destino=cliente.uf,
        aliquota_interna_destino=item.aliquota_interna_destino,
        cst_ou_csosn=cst_icms if cst_icms is not None else csosn_icms,
    )

    return NfeItemData(
        n_item=n_item,
        c_prod=produto.codigo_interno,
        descricao=produto.descricao,
        ncm=produto.ncm,
        cfop=produto.cfop_padrao,
        unidade=produto.unidade,
        quantidade=item.quantidade,
        valor_unitario=valor_unitario,
        valor_total=valor_total,
        cst_icms=cst_icms,
        csosn_icms=csosn_icms,
        base_icms=icms.base_icms,
        valor_icms=icms.valor_icms,
        valor_icms_uf_remetente=icms.valor_icms_uf_remetente,
        valor_icms_uf_destino=icms.valor_icms_uf_destino,
        valor_fcp=icms.valor_fcp,
    )


def montar_nfe_data(
    empresa: Empresa,
    cliente: Cliente,
    serie: str,
    numero: int,
    produtos_por_id: dict[uuid.UUID, Produto],
    itens: list[ItemPedido],
) -> NfeData:
    itens_nfe = [
        _montar_item(n_item, produtos_por_id[item.produto_id], item, empresa, cliente)
        for n_item, item in enumerate(itens, start=1)
    ]

    return NfeData(
        tp_amb=1 if empresa.ambiente == AmbienteEnum.producao else 2,
        # Codigo IBGE da UF = os 2 primeiros digitos do codigo IBGE do
        # municipio (padrao nacional) -- evita precisar de uma tabela
        # separada UF->codigo so pra isso.
        c_uf_emit=empresa.municipio_ibge[:2],
        dh_emi=datetime.now(timezone.utc),
        serie=serie,
        numero=numero,
        emit_cnpj=empresa.cnpj,
        emit_ie=empresa.inscricao_estadual,
        emit_crt=empresa.crt,
        emit_uf=empresa.uf,
        dest_cpf_cnpj=cliente.cpf_cnpj,
        dest_nome=cliente.nome,
        dest_uf=cliente.uf,
        dest_ie=cliente.inscricao_estadual,
        itens=itens_nfe,
    )

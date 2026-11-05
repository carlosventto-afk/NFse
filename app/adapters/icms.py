"""Cálculo de ICMS por item de NF-e: operação interna e partilha interestadual.

Operação interna (`uf_emitente == uf_destino`): esta função apenas devolve a
base de cálculo (`valor_total` do item). O valor de ICMS efetivamente devido
depende da alíquota interna da UF envolvida, que o projeto ainda não possui
como tabela automática por UF (ver nota abaixo); por isso `valor_icms` só é
calculado quando o chamador informa esse percentual via
`aliquota_interna_destino` (nessa operação, "destino" é a mesma UF do
emitente). Quando não informado, `valor_icms` volta `None` -- é
responsabilidade do chamador decidir se isso é aceitável, até que exista uma
tabela de alíquotas internas por UF no projeto.

Operação interestadual (EC 87/2015 -- "partilha" do ICMS + FCP): o vendedor
cobra ICMS à alíquota interestadual (tabela pública fixa, só entre UF de
origem e UF de destino -- não depende da mercadoria, exceto pela alíquota de
4% para produto importado, que este módulo NÃO implementa porque
`NfeItemData`/esta função não recebem um flag "importado"). A diferença entre
a alíquota interna do destino (`aliquota_interna_destino`, obrigatória nesse
caso -- OBRIGATORIAMENTE informada pelo chamador, pois o projeto não tem
tabela automática de alíquota interna por UF) e a interestadual é o ICMS
devido à UF de destino (`valor_icms_uf_destino`). Pelo cronograma original da
EC 87/2015 essa diferença era partilhada ano a ano entre origem e destino,
mas o cronograma terminou em 2019: hoje a diferença INTEGRAL vai para o
destino, e a parcela da UF de origem (`valor_icms_uf_remetente`) é
corretamente `Decimal("0")` -- não `None` -- pois `None` significa "a
operação não é interestadual" para o builder de XML (`nfe_core/nfe.py`,
`_add_det`), enquanto `Decimal("0")` significa "é interestadual, e a parcela
da UF de origem hoje é zero".

A TABELA ABAIXO (`ALIQUOTA_INTERESTADUAL_SIMPLIFICADA`) É UMA SIMPLIFICAÇÃO,
NÃO A TABELA OFICIAL COMPLETA: a regra real tem exceções e casos por produto
(ex.: Resolução do Senado 13/2012 pra importados) que não cabem no escopo
desta tarefa. Usamos 7% quando a UF de origem é SP/MG/RJ/RS (Sul/Sudeste,
exceto ES) vendendo para UF de destino do Norte/Nordeste/Centro-Oeste/ES, e
12% como alíquota interestadual geral nos demais pares -- isso PRECISA ser
validado contra a tabela oficial completa da SEFAZ no spike fiscal de
homologação da Fase 1, antes de qualquer emissão real (mesmo aviso dado em
`nfe_core/nfe.py` sobre o leiaute).

FCP (Fundo de Combate à Pobreza): calcular o FCP realmente devido exige saber
se/quanto a UF de destino cobra de adicional e se esse adicional já está
embutido em `aliquota_interna_destino` ou não -- esse detalhamento (tabela de
FCP por UF) está fora do escopo desta tarefa. `valor_fcp` é `Decimal("0")`
por padrão em operação interestadual; se algum dia for preciso computar FCP
de fato, o chamador precisará passar essa informação explicitamente (ver
Review Focus do plano).

`cst_ou_csosn` é recebido pela assinatura (ela é compartilhada com o
restante do pipeline de NF-e), mas esta função não ramifica o cálculo por
CST/CSOSN: tratamento de isenção/suspensão por código (CST 40/41/50 etc.) não
é exigido por nenhum teste desta tarefa e fica fora de escopo (YAGNI) até que
surja um caso de uso real.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# UFs do Sul/Sudeste consideradas "origem" na regra simplificada de 7%.
_UF_SUL_SUDESTE_7PCT_ORIGEM = frozenset({"SP", "MG", "RJ", "RS"})

# UFs do Norte, Nordeste, Centro-Oeste e Espírito Santo -- destino que, saindo
# de SP/MG/RJ/RS, paga alíquota interestadual de 7% em vez de 12%.
_UF_NORTE_NORDESTE_CO_ES_DESTINO = frozenset({
    "AC", "AP", "AM", "PA", "RO", "RR", "TO",          # Norte
    "AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE",  # Nordeste
    "DF", "GO", "MT", "MS",                             # Centro-Oeste
    "ES",                                                # Espírito Santo
})

_CENTAVOS = Decimal("0.01")


class AliquotaInterestadualInvalida(ValueError):
    """Venda interestadual sem a alíquota interna do destino informada."""


@dataclass
class ItemIcmsCalculado:
    base_icms: Decimal | None
    valor_icms: Decimal | None
    valor_icms_uf_remetente: Decimal | None
    valor_icms_uf_destino: Decimal | None
    valor_fcp: Decimal | None


def _arredondar(valor: Decimal) -> Decimal:
    return valor.quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def _aliquota_interestadual(uf_emitente: str, uf_destino: str) -> Decimal:
    """Alíquota interestadual simplificada (ver caveat no docstring do módulo)."""
    if uf_emitente in _UF_SUL_SUDESTE_7PCT_ORIGEM and uf_destino in _UF_NORTE_NORDESTE_CO_ES_DESTINO:
        return Decimal("7")
    return Decimal("12")


def calcular_icms_item(
    valor_total: Decimal,
    uf_emitente: str,
    uf_destino: str,
    aliquota_interna_destino: Decimal | None,
    cst_ou_csosn: str,
) -> ItemIcmsCalculado:
    """Calcula o ICMS de um item: operação interna, ou partilha EC 87/2015 + FCP.

    `cst_ou_csosn` faz parte da assinatura pra compatibilidade com o restante
    do pipeline de NF-e, mas não altera o cálculo nesta versão (ver docstring
    do módulo).
    """
    uf_emitente = uf_emitente.strip().upper()
    uf_destino = uf_destino.strip().upper()
    base_icms = valor_total

    if uf_emitente == uf_destino:
        valor_icms = (
            _arredondar(base_icms * aliquota_interna_destino / Decimal("100"))
            if aliquota_interna_destino is not None
            else None
        )
        return ItemIcmsCalculado(
            base_icms=base_icms,
            valor_icms=valor_icms,
            valor_icms_uf_remetente=None,
            valor_icms_uf_destino=None,
            valor_fcp=None,
        )

    if aliquota_interna_destino is None:
        raise AliquotaInterestadualInvalida(
            "venda interestadual exige a aliquota interna do destino "
            "(aliquota_interna_destino) para calcular a partilha do ICMS "
            "(DIFAL, EC 87/2015)"
        )

    aliquota_interestadual = _aliquota_interestadual(uf_emitente, uf_destino)
    valor_icms = _arredondar(base_icms * aliquota_interestadual / Decimal("100"))
    diferenca_aliquota = aliquota_interna_destino - aliquota_interestadual
    valor_icms_uf_destino = _arredondar(base_icms * diferenca_aliquota / Decimal("100"))

    return ItemIcmsCalculado(
        base_icms=base_icms,
        valor_icms=valor_icms,
        # Cronograma da EC 87/2015 terminou em 2019: hoje a diferença integral
        # vai pro destino, a parcela da UF de origem é zero (não None -- ver
        # docstring do módulo).
        valor_icms_uf_remetente=Decimal("0"),
        valor_icms_uf_destino=valor_icms_uf_destino,
        valor_fcp=Decimal("0"),
    )

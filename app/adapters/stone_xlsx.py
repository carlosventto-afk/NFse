import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl

COLUNAS_OBRIGATORIAS = (
    "DATA DA VENDA",
    "BANDEIRA",
    "PRODUTO",
    "STONE ID",
    "VALOR BRUTO",
    "ULTIMO STATUS",
    "DATA DO ULTIMO STATUS",
)

STATUS_APROVADO = "Aprovada"


class CabecalhoInvalidoError(ValueError):
    """Arquivo nao e um .xlsx valido, ou falta coluna obrigatoria no cabecalho."""


@dataclass
class NotaCandidata:
    stone_charge_id: str
    data_da_venda: datetime
    data_vencimento: date
    data_ultimo_status: datetime
    valor: Decimal
    produto: str
    tipo_produto: str
    bandeira: str | None
    codigo_autorizacao: str | None


@dataclass
class ResultadoParse:
    notas: list[NotaCandidata]
    ignoradas: dict[str, int] = field(
        default_factory=lambda: {
            "status_nao_aprovado": 0, "linha_invalida": 0,
        }
    )


def _normalizar_cabecalho(valor: object) -> str:
    if valor is None:
        return ""
    return "".join(ch for ch in str(valor) if ch.isascii()).strip().upper()


def _derivar_tipo_produto(produto: str) -> str:
    produto_lower = produto.lower()
    if "credito" in produto_lower:
        return "Credito"
    if "debito" in produto_lower:
        return "Debito"
    if "pix" in produto_lower:
        return "PIX"
    return produto


def parsear_relatorio_stone(conteudo: bytes) -> ResultadoParse:
    """Le o relatorio de vendas da Stone (XLSX, aba unica, 1 linha = 1 venda).

    Sem agrupamento por parcela -- diferente do relatorio de recebimentos
    (formato anterior), esse relatorio de vendas ja traz uma linha por
    venda inteira, sem quebrar em parcelas liquidadas separadamente. Nao
    acessa banco: nao sabe se uma nota ja foi emitida antes (isso e
    responsabilidade de quem chama). Nao levanta excecao por causa de uma
    linha invalida -- so por cabecalho incompativel ou arquivo corrompido,
    que invalidam o arquivo inteiro.
    """
    try:
        planilha = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True, read_only=True)
    except Exception as exc:
        raise CabecalhoInvalidoError(f"arquivo nao e um .xlsx valido: {exc}") from exc

    aba = planilha.active
    linhas = aba.iter_rows(values_only=True)
    try:
        cabecalho = next(linhas)
    except StopIteration:
        raise CabecalhoInvalidoError("planilha vazia")

    indice_colunas = {
        _normalizar_cabecalho(valor): posicao for posicao, valor in enumerate(cabecalho)
    }
    faltando = set(COLUNAS_OBRIGATORIAS) - set(indice_colunas)
    if faltando:
        raise CabecalhoInvalidoError(
            f"colunas obrigatorias ausentes no cabecalho: {sorted(faltando)}"
        )
    # O cabecalho do codigo de autorizacao vem com a acentuacao corrompida
    # na exportacao da propria Stone (ex.: "C?DIGO DE AUTORIZA??O") -- casar
    # a string exata seria fragil, entao localiza por conter "AUTORIZA"
    # depois de descartar os caracteres nao-ASCII.
    idx_codigo_autorizacao = next(
        (posicao for cabecalho_norm, posicao in indice_colunas.items() if "AUTORIZA" in cabecalho_norm),
        None,
    )

    def _coluna(linha: tuple, nome: str) -> str:
        valor = linha[indice_colunas[nome]]
        return "" if valor is None else str(valor).strip()

    resultado = ResultadoParse(notas=[])
    for linha in linhas:
        if linha is None or all(valor is None for valor in linha):
            continue
        try:
            status = _coluna(linha, "ULTIMO STATUS")
            if status != STATUS_APROVADO:
                resultado.ignoradas["status_nao_aprovado"] += 1
                continue
            data_da_venda = datetime.strptime(_coluna(linha, "DATA DA VENDA"), "%d/%m/%Y %H:%M")
            data_ultimo_status = datetime.strptime(
                _coluna(linha, "DATA DO ULTIMO STATUS"), "%d/%m/%Y %H:%M",
            )
            valor_bruto = Decimal(_coluna(linha, "VALOR BRUTO").replace(",", "."))
            stone_id = _coluna(linha, "STONE ID")
            if not stone_id:
                raise ValueError("STONE ID vazio")
            produto = _coluna(linha, "PRODUTO")
            if not produto:
                raise ValueError("PRODUTO vazio")
        except (KeyError, ValueError, InvalidOperation):
            resultado.ignoradas["linha_invalida"] += 1
            continue

        bandeira = _coluna(linha, "BANDEIRA") or None
        codigo_autorizacao = (
            (str(linha[idx_codigo_autorizacao]).strip() or None)
            if idx_codigo_autorizacao is not None and linha[idx_codigo_autorizacao] is not None
            else None
        )

        resultado.notas.append(
            NotaCandidata(
                stone_charge_id=stone_id,
                data_da_venda=data_da_venda,
                data_vencimento=data_da_venda.date(),
                data_ultimo_status=data_ultimo_status,
                valor=valor_bruto,
                produto=produto,
                tipo_produto=_derivar_tipo_produto(produto),
                bandeira=bandeira,
                codigo_autorizacao=codigo_autorizacao,
            )
        )

    return resultado

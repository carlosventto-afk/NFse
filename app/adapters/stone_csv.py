import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

COLUNAS_OBRIGATORIAS = (
    "CATEGORIA",
    "DATA DA VENDA",
    "STONE ID",
    "QTD DE PARCELAS",
    "Nº DA PARCELA",
    "VALOR BRUTO",
    "ÚLTIMO STATUS",
    "DATA DO ÚLTIMO STATUS",
)


class CabecalhoInvalidoError(ValueError):
    """Arquivo nao esta em UTF-8, ou falta coluna obrigatoria no cabecalho."""


@dataclass
class NotaCandidata:
    stone_charge_id: str
    data_da_venda: datetime
    data_ultimo_status: datetime
    valor: Decimal


@dataclass
class ResultadoParse:
    notas: list[NotaCandidata]
    ignoradas: dict[str, int] = field(
        default_factory=lambda: {
            "status_nao_pago": 0, "categoria_nao_venda": 0, "linha_invalida": 0,
        }
    )


def parsear_relatorio_stone(conteudo: bytes) -> ResultadoParse:
    """Le o relatorio de recebimentos da Stone (CSV, ';', UTF-8 com BOM).

    Nao acessa banco: nao sabe se uma nota ja foi emitida antes (isso e
    responsabilidade de quem chama, que tem acesso ao banco). Nao levanta
    excecao por causa de uma linha invalida — so por cabecalho incompativel
    ou encoding errado, que invalidam o arquivo inteiro.
    """
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CabecalhoInvalidoError(f"arquivo nao esta em UTF-8: {exc}") from exc

    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    colunas_presentes = set(leitor.fieldnames or [])
    faltando = set(COLUNAS_OBRIGATORIAS) - colunas_presentes
    if faltando:
        raise CabecalhoInvalidoError(
            f"colunas obrigatorias ausentes no cabecalho: {sorted(faltando)}"
        )

    resultado = ResultadoParse(notas=[])
    grupos: dict[tuple, list[tuple[int, str, Decimal, datetime, datetime]]] = {}
    ordem_grupos: list[tuple] = []

    for linha in leitor:
        try:
            status = linha["ÚLTIMO STATUS"].strip()
            categoria = linha["CATEGORIA"].strip()
            if status != "Pago":
                resultado.ignoradas["status_nao_pago"] += 1
                continue
            if categoria != "Venda":
                resultado.ignoradas["categoria_nao_venda"] += 1
                continue
            data_da_venda = datetime.strptime(
                linha["DATA DA VENDA"].strip(), "%d/%m/%Y %H:%M:%S"
            )
            data_ultimo_status = datetime.strptime(
                linha["DATA DO ÚLTIMO STATUS"].strip(), "%d/%m/%Y %H:%M:%S"
            )
            valor = Decimal(linha["VALOR BRUTO"].strip().replace(",", "."))
            qtd_parcelas = int(linha["QTD DE PARCELAS"].strip())
            numero_parcela = int(linha["Nº DA PARCELA"].strip())
            stone_id = linha["STONE ID"].strip()
            if not stone_id:
                raise ValueError("STONE ID vazio")
        except (KeyError, ValueError, InvalidOperation):
            resultado.ignoradas["linha_invalida"] += 1
            continue

        if qtd_parcelas <= 1:
            chave = ("unico", stone_id)
        else:
            chave = ("grupo", data_da_venda.isoformat(), qtd_parcelas)

        if chave not in grupos:
            grupos[chave] = []
            ordem_grupos.append(chave)
        grupos[chave].append((numero_parcela, stone_id, valor, data_da_venda, data_ultimo_status))

    for chave in ordem_grupos:
        itens = sorted(grupos[chave], key=lambda item: item[0])
        _numero_parcela, stone_charge_id, _valor, data_da_venda, data_ultimo_status = itens[0]
        valor_total = sum((item[2] for item in itens), Decimal("0"))
        resultado.notas.append(
            NotaCandidata(
                stone_charge_id=stone_charge_id,
                data_da_venda=data_da_venda,
                data_ultimo_status=data_ultimo_status,
                valor=valor_total,
            )
        )

    return resultado

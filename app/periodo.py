"""Conversao de datas de calendario brasileiro para limites de timestamptz.

`Emissao.criada_em` e `timestamptz` e os filtros da API chegam como `date`
(calendario do usuario, que esta no Brasil). Comparar um `date` direto contra
um `timestamptz` faz o Postgres converter usando o `TimeZone` da SESSAO — UTC
neste deploy, nao BRT. Uma nota emitida as 21:30 BRT do ultimo dia do mes fica
gravada como ~00:30 UTC do dia seguinte e cairia no MES ERRADO do relatorio.

Ancorar os limites explicitamente em BRT resolve para os dois lados (listagem
e dashboard) sem depender da configuracao do servidor.
"""
from datetime import date, datetime, time, timedelta, timezone

# Brasil nao tem mais horario de verao desde 2019 (Decreto 9.772/2019), entao
# um offset fixo de -03:00 descreve o horario oficial de Brasilia hoje.
FUSO_BRT = timezone(timedelta(hours=-3))


def inicio_do_dia_brt(dia: date) -> datetime:
    """00:00:00 BRT do dia — limite INFERIOR inclusivo."""
    return datetime.combine(dia, time.min, tzinfo=FUSO_BRT)


def fim_do_dia_brt(dia: date) -> datetime:
    """00:00:00 BRT do dia SEGUINTE — limite SUPERIOR exclusivo.

    Exclusivo de proposito: pegar tudo ate 23:59:59.999999 com `<=` deixaria
    escapar os microssegundos finais do dia.
    """
    return datetime.combine(dia + timedelta(days=1), time.min, tzinfo=FUSO_BRT)

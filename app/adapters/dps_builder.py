from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import AmbienteEnum, Empresa
from nfse_core import DpsData


@dataclass
class DadosEmissao:
    tomador_cpf_cnpj: str | None
    tomador_nome: str | None
    tomador_email: str | None
    descricao: str
    valor: Decimal
    competencia: date


def montar_dps_data(empresa: Empresa, serie: str, numero: int, dados: DadosEmissao) -> DpsData:
    return DpsData(
        tp_amb=1 if empresa.ambiente == AmbienteEnum.producao else 2,
        dh_emi=datetime.now(timezone.utc),
        serie=serie,
        numero=numero,
        competencia=dados.competencia,
        prest_cnpj=empresa.cnpj,
        prest_im=empresa.inscricao_municipal,
        c_loc_emi=empresa.municipio_ibge,
        op_simp_nac=empresa.op_simp_nac,
        toma_cpf_cnpj=dados.tomador_cpf_cnpj,
        toma_nome=dados.tomador_nome,
        toma_email=dados.tomador_email,
        c_trib_nac=empresa.codigo_tributacao,
        x_desc_serv=dados.descricao,
        v_serv=dados.valor,
    )

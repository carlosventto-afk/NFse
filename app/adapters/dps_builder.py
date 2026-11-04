from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import AmbienteEnum, Empresa, ProvedorEmissao
from nfse_core import DpsData

# Municipios cujo CNC (Cadastro Nacional de Contribuintes) na SEFIN Nacional
# ainda nao tem "informacoes complementares" registradas -- confirmado ao
# vivo em Belem (04/11/2026, erro E0120 "IM do prestador nao deve ser
# informado, pois nao existem informacoes complementares registradas no CNC
# NFS-e do municipio emissor") ao forcar o endpoint nacional generico
# (ProvedorEmissao.nacional). No endpoint PROPRIO de Belem (ProvedorEmissao
# .direto) o IM e aceito normalmente -- a omissao so vale pro caminho
# nacional generico.
MUNICIPIOS_SEM_CNC_NACIONAL = {"1501402"}  # Belem/PA


@dataclass
class DadosEmissao:
    tomador_cpf_cnpj: str | None
    tomador_nome: str | None
    tomador_email: str | None
    descricao: str
    valor: Decimal
    competencia: date
    dh_emi: datetime | None = None


def montar_dps_data(empresa: Empresa, serie: str, numero: int, dados: DadosEmissao) -> DpsData:
    usa_endpoint_nacional_generico = (
        ProvedorEmissao(empresa.provedor_emissao or ProvedorEmissao.direto) == ProvedorEmissao.nacional
    )
    omitir_im = usa_endpoint_nacional_generico and empresa.municipio_ibge in MUNICIPIOS_SEM_CNC_NACIONAL
    return DpsData(
        tp_amb=1 if empresa.ambiente == AmbienteEnum.producao else 2,
        dh_emi=dados.dh_emi or datetime.now(timezone.utc),
        serie=serie,
        numero=numero,
        competencia=dados.competencia,
        prest_cnpj=empresa.cnpj,
        prest_im=None if omitir_im else empresa.inscricao_municipal,
        c_loc_emi=empresa.municipio_ibge,
        c_loc_prestacao=empresa.local_prestacao_ibge or "",
        op_simp_nac=empresa.op_simp_nac,
        reg_ap_trib_sn=empresa.regime_apuracao_sn if empresa.op_simp_nac == 3 else None,
        toma_cpf_cnpj=dados.tomador_cpf_cnpj,
        toma_nome=dados.tomador_nome,
        toma_email=dados.tomador_email,
        c_trib_nac=empresa.codigo_tributacao,
        c_trib_mun=empresa.codigo_tributacao_municipal,
        c_nbs=empresa.nbs_code,
        x_desc_serv=dados.descricao,
        v_serv=dados.valor,
        ibs_cbs_cst=str(empresa.ibs_cbs_cst) if empresa.ibs_cbs_cst is not None else None,
        ibs_cbs_class_trib=(
            str(empresa.ibs_cbs_classificacao) if empresa.ibs_cbs_classificacao is not None else None
        ),
        ibs_cbs_cod_ind_op=empresa.ibs_cbs_codigo_indicador_operacao,
    )

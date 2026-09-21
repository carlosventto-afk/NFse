"""Provisionamento de uma empresa na Spedy: criar o cadastro la, subir o
certificado A1 ja usado no caminho direto, e configurar a serie/numeracao.
Chamado uma unica vez, de forma sincrona e explicita, quando o admin liga
`provedor_emissao=spedy` em PUT /empresas/mim -- nunca de dentro do worker."""
from __future__ import annotations

import asyncio
import base64

from app.adapters.spedy_client import SpedyClient, SpedyError
from app.config import Settings
from app.models import AmbienteEnum, Empresa

# Confirmado ao vivo (16/09): a Spedy aplica um limite de rajada por segundo
# alem do limite geral por minuto (que a resposta expoe via cabecalhos
# X-Rate-Limit-*) -- 3-5 chamadas seguidas sem pausa (criar empresa, apagar
# orfa, subir certificado, configurar) podem estourar esse limite mesmo com
# sobra no limite por minuto.
_INTERVALO_ENTRE_CHAMADAS_SEGUNDOS = 1.0


_MAPA_REGIME_APURACAO_SN = {
    1: "federalAndMunicipalBySimplesNacional",
    2: "federalBySimplesAndIssqnByNfse",
    3: "federalAndMunicipalByNfse",
}


def montar_dados_regime_tributario(empresa: Empresa) -> dict:
    """Mapeia op_simp_nac/regime_apuracao_sn para os campos de regime
    tributario que a Spedy guarda no CADASTRO da empresa (taxRegime,
    specialTaxRegime, simplesNacionalTaxRegime -- nao por nota).

    Confirmado ao vivo (Belem, CNPJ 49055093000140, erro E188 "Opcao simples
    nacional conflita com o regime especial de tributacao informado"): sem
    esses campos a prefeitura assume um regime especial (05-MEI ou 06-ME/EPP)
    por conta propria, que conflita com a ausencia de "optante pelo Simples"
    do nosso lado. Valores de enum confirmados na doc da Spedy
    (alterar-empresa)."""
    if empresa.op_simp_nac == 1:
        return {"taxRegime": "regimeNormal", "specialTaxRegime": "noSpecialRegime"}
    if empresa.op_simp_nac == 2:
        return {"taxRegime": "simplesNacionalMEI", "specialTaxRegime": "individualMicroenterprise"}
    dados: dict = {"taxRegime": "simplesNacional", "specialTaxRegime": "microenterpriseAndSmallBusiness"}
    if empresa.regime_apuracao_sn in _MAPA_REGIME_APURACAO_SN:
        dados["simplesNacionalTaxRegime"] = _MAPA_REGIME_APURACAO_SN[empresa.regime_apuracao_sn]
    return dados


def _chave_mestre(ambiente: str, settings: Settings) -> str:
    chave = (
        settings.spedy_api_key_master_producao if ambiente == "producao"
        else settings.spedy_api_key_master_homologacao
    )
    if not chave:
        raise SpedyError(f"chave mestre da Spedy nao configurada para o ambiente {ambiente}")
    return chave


async def provisionar_empresa(
    empresa: Empresa, pfx_base64: str, senha: str | None, settings: Settings,
) -> tuple[str, str]:
    if not empresa.razao_social:
        raise SpedyError("razao_social e obrigatoria para provisionar a empresa na Spedy")

    ambiente = AmbienteEnum(empresa.ambiente).value
    chave_mestre = _chave_mestre(ambiente, settings)
    dados_empresa = {
        "name": empresa.razao_social,
        "legalName": empresa.razao_social,
        "federalTaxNumber": empresa.cnpj,
        "cityTaxNumber": empresa.inscricao_municipal,
        "address": {
            "street": empresa.logradouro or "",
            "district": empresa.bairro or "",
            "postalCode": empresa.cep or "",
            "number": empresa.numero or "S/N",
            "city": {"code": empresa.municipio_ibge},
        },
        **montar_dados_regime_tributario(empresa),
    }

    cliente_mestre = SpedyClient(ambiente, chave_mestre)
    try:
        try:
            criada = await cliente_mestre.criar_empresa(dados_empresa)
        except SpedyError as exc:
            if "já possui uma conta" not in str(exc):
                raise
            # Orfa de uma tentativa anterior que criou a empresa na Spedy mas
            # falhou antes de terminar o resto do provisionamento (ex.:
            # certificado invalido). A chave daquela tentativa nunca foi
            # capturada -- a Spedy so devolve a chave da empresa uma vez, na
            # criacao, sem endpoint pra recupera-la depois -- a unica saida e
            # apagar a orfa e recriar do zero. Confirmado ao vivo (16/09):
            # aconteceu de verdade em producao, mais de uma vez na mesma
            # sessao de testes.
            orfas = await cliente_mestre.listar_empresas_por_cnpj(empresa.cnpj)
            for orfa in orfas:
                await cliente_mestre.excluir_empresa(orfa["id"])
                await asyncio.sleep(_INTERVALO_ENTRE_CHAMADAS_SEGUNDOS)
            criada = await cliente_mestre.criar_empresa(dados_empresa)

        spedy_empresa_id = criada["id"]
        api_key = criada["apiCredentials"]["apiKey"]

        # Confirmado ao vivo em producao (16/09): ao contrario do que a doc
        # publica sugere (usar a X-Api-Key da empresa recem-criada), tanto
        # adicionar_certificado quanto configurar_nfse devolvem 403 "Acesso
        # nao autorizado" com a chave da empresa -- so funcionam com a chave
        # MESTRE. A chave da empresa (api_key acima) so e usada depois, nas
        # operacoes de emissao/consulta/cancelamento (ver app/worker.py).
        pfx_bytes = base64.b64decode(pfx_base64)

        # As 3 chamadas de provisionamento disparadas em sequencia rapida
        # (sem pausa) bateram um limite de rajada por segundo da Spedy (HTTP
        # 429) bem no ultimo passo -- confirmado ao vivo que a MESMA chamada,
        # feita isolada/espacada, funciona normalmente. Um intervalo pequeno
        # entre cada chamada evita a rajada sem tornar o provisionamento
        # perceptivelmente mais lento (e uma acao unica do admin, nao algo
        # que roda no worker).
        await asyncio.sleep(_INTERVALO_ENTRE_CHAMADAS_SEGUNDOS)
        await cliente_mestre.adicionar_certificado(
            spedy_empresa_id, pfx_bytes, senha or "",
        )
        await asyncio.sleep(_INTERVALO_ENTRE_CHAMADAS_SEGUNDOS)
        await cliente_mestre.configurar_nfse(spedy_empresa_id, {
            "series": empresa.serie,
            "environmentType": "production" if ambiente == "producao" else "simulation",
            "nextNumber": empresa.proximo_numero,
        })
    finally:
        await cliente_mestre.close()

    return spedy_empresa_id, api_key

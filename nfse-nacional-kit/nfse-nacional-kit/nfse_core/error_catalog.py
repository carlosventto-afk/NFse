"""Tradução de códigos de erro/alerta da SEFIN Nacional para mensagens claras.

Não existe uma tabela oficial única e publicada com todos os códigos de erro
do Sistema Nacional NFS-e (verificado: nem no manual da API, nem nos ANEXOS,
nem nos swaggers públicos) — este catálogo é construído incrementalmente a
partir dos erros realmente encontrados em producao/homologacao.
Código desconhecido cai no fallback genérico: mostra o código e a descrição
originais da SEFIN, sem inventar explicação para o que não conhecemos.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict


@dataclass
class ErrorTranslation:
    titulo: str
    explicacao: str
    acao_sugerida: str


CATALOGO: dict[str, ErrorTranslation] = {
    "E0008": ErrorTranslation(
        titulo="Data/hora de emissão no futuro",
        explicacao="O relógio do servidor que gerou a nota está à frente do relógio da SEFIN Nacional.",
        acao_sugerida="Costuma ser um problema pontual de sincronismo — tente emitir novamente em "
                       "alguns instantes. Se persistir, contate o suporte técnico.",
    ),
    "E0084": ErrorTranslation(
        titulo="CNPJ sem estabelecimento no município nesta competência",
        explicacao="A SEFIN não encontrou, na data de competência informada, um vínculo entre o CNPJ "
                   "do prestador e o município emissor (cadastro CNPJ/CNC).",
        acao_sugerida="Confira o município cadastrado na unidade e se o CNPJ tem mesmo domicílio "
                       "fiscal lá na Receita Federal. Em ambiente de teste (produção restrita), essa "
                       "limitação pode ser do próprio ambiente — consulte o suporte da SEFIN Nacional.",
    ),
    "E0099": ErrorTranslation(
        titulo="Prestador não cadastrado no ambiente (CNC)",
        explicacao="O município emissor não tem o cadastro do prestador (CNPJ + Inscrição Municipal) "
                   "no Cadastro Nacional de Contribuintes deste ambiente.",
        acao_sugerida="Emita uma nota pelo portal oficial 'Emissor Nacional Web' pra ativar o cadastro, "
                       "ou peça à prefeitura pra regularizar o CNC.",
    ),
    "E0120": ErrorTranslation(
        titulo="Inscrição Municipal não deve ser informada",
        explicacao="Para este município/ambiente, o cadastro não tem informações complementares (IM) "
                   "— enviar a IM nesse caso é rejeitado.",
        acao_sugerida="Remova a Inscrição Municipal dos dados fiscais da unidade e emita novamente.",
    ),
    "E0202": ErrorTranslation(
        titulo="Prestador e tomador são a mesma pessoa",
        explicacao="A SEFIN não permite autofaturamento — o CNPJ/CPF do prestador não pode ser igual "
                   "ao do tomador do serviço.",
        acao_sugerida="Corrija o responsável financeiro do contrato para uma pessoa diferente do prestador.",
    ),
    "E0712": ErrorTranslation(
        titulo="Indicador de tributos incompatível com Simples Nacional",
        explicacao="Empresas ME/EPP optantes pelo Simples Nacional não podem usar o indicador "
                   "simplificado de tributos — é exigido o detalhamento em percentual.",
        acao_sugerida="Ajuste interno do sistema — se aparecer, atualize o sistema para a versao mais "
                       "recente do módulo de NFS-e.",
    ),
    "E0714": ErrorTranslation(
        titulo="Erro na assinatura digital",
        explicacao="A SEFIN não conseguiu validar a assinatura do XML — geralmente causado por "
                   "caracteres especiais no texto ou uma forma de canonicalização diferente da esperada.",
        acao_sugerida="Verifique se a descrição do serviço tem caracteres incomuns (acentos, travessões). "
                       "Se persistir, contate o suporte tecnico.",
    ),
    "E1235": ErrorTranslation(
        titulo="Estrutura do XML inválida",
        explicacao="O documento enviado não segue o formato esperado pela SEFIN (elemento raiz ou "
                   "campo incorreto).",
        acao_sugerida="Problema técnico interno — contate o suporte tecnico com o codigo completo do erro.",
    ),
    "E3317": ErrorTranslation(
        titulo="Certificado digital expirado",
        explicacao="O certificado A1 usado para assinar o documento já venceu.",
        acao_sugerida="Renove o certificado digital A1 e carregue o novo arquivo em Configurações → "
                       "Integrações → NFS-e (ou na unidade, se for certificado próprio).",
    ),
    "E999": ErrorTranslation(
        titulo="Erro não catalogado da SEFIN",
        explicacao="A SEFIN recusou a nota com um erro genérico, sem detalhar a causa — geralmente "
                   "indica um campo obrigatório ausente ou mal formatado no XML.",
        acao_sugerida="Tente novamente. Se persistir, contate o suporte tecnico informando o codigo "
                       "E999 e o horário da tentativa.",
    ),
}

FALLBACK = ErrorTranslation(
    titulo="Erro não catalogado",
    explicacao="A SEFIN Nacional recusou a operação com este código, que ainda não tem uma "
               "tradução específica neste catálogo.",
    acao_sugerida="Leia a descrição original abaixo. Se não conseguir resolver, contate o suporte "
                   "técnico informando o código e a descrição exatos.",
)


def translate(codigo: str, descricao: str = "") -> dict:
    t = CATALOGO.get((codigo or "").upper(), FALLBACK)
    return {"codigo": codigo, "descricao_original": descricao, **asdict(t)}


def translate_erros(erros) -> list[dict]:
    """`erros` é a lista tolerante já parseada da resposta da SEFIN — cada item
    pode ter chaves em variações de nome/maiúsculas (Codigo/codigo/Código)."""
    out: list[dict] = []
    if not erros:
        return out
    if isinstance(erros, dict):
        erros = [erros]
    if isinstance(erros, str):
        return [translate("?", erros)]
    for e in erros:
        if not isinstance(e, dict):
            out.append(translate("?", str(e)))
            continue
        codigo = e.get("Codigo") or e.get("codigo") or e.get("Código") or e.get("código") or "?"
        descricao = e.get("Descricao") or e.get("descricao") or e.get("Descrição") or e.get("descrição") or ""
        complemento = e.get("complemento") or e.get("Complemento")
        item = translate(codigo, descricao)
        if complemento and complemento != descricao:
            item["complemento"] = complemento
        out.append(item)
    return out


def translate_erros_json(erros) -> str | None:
    """Versão pronta para gravar em coluna Text (JSON serializado)."""
    traduzidos = translate_erros(erros)
    return json.dumps(traduzidos, ensure_ascii=False) if traduzidos else None


def summarize_for_exception(erros) -> str:
    """Mensagem curta e amigável pra embutir em ValueError/HTTPException —
    usa o título+explicação do PRIMEIRO erro traduzido, com o código bruto no
    final (pra quem for procurar suporte/reportar)."""
    traduzidos = translate_erros(erros)
    if not traduzidos:
        return str(erros)
    primeiro = traduzidos[0]
    partes = [f"{primeiro['titulo']} ({primeiro['codigo']})", primeiro["explicacao"]]
    if primeiro.get("acao_sugerida"):
        partes.append(f"Sugestão: {primeiro['acao_sugerida']}")
    if len(traduzidos) > 1:
        partes.append(f"(+{len(traduzidos) - 1} outro(s) erro(s) — veja o histórico de emissões para detalhes)")
    return " ".join(partes)

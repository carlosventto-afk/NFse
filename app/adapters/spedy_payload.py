"""Mapeia Empresa/Emissao para o payload de POST /service-invoices da Spedy.
Ao contrario do caminho direto (nfse_core/dps.py monta XML), aqui os dados
vao inline no JSON -- a Spedy nao exige cliente/produto pre-cadastrados."""
from __future__ import annotations

import uuid
from datetime import datetime, time

from app.models import Cliente, Emissao, Empresa
from app.periodo import FUSO_BRT


def _federal_service_code_lc116(codigo_tributacao: str) -> str:
    """Deriva o codigo LC 116/03 (formato 'XX.XX', ex.: '14.10') a partir do
    cTribNac nacional de 6 digitos ja cadastrado na empresa (ex.: '141001').

    Confirmado na doc oficial da Spedy (24/09,
    https://docs.spedy.com.br/api-reference/nfs-e/criar-nfs-e.md):
    federalServiceCode e o "Codigo do Item da Lista de Servico (LC 116/03)",
    formato com ponto -- NAO o cTribNac de 6 digitos que mandavamos antes
    (mesmo valor usado no XML do caminho direto/SEFIN, onde cTribNac de 6
    digitos e o formato certo). Suspeita de ser a causa do SPD999 ("erro ao
    estabelecer comunicacao com o servico") recorrente em Belem: o valor
    "existe" como string, so estava no formato errado, gerando um erro
    generico do lado da Spedy/prefeitura em vez de uma rejeicao especifica
    de campo.
    """
    digitos = codigo_tributacao.strip()
    if len(digitos) < 4:
        return digitos
    return f"{int(digitos[:2])}.{digitos[2:4]}"


def montar_payload_spedy(empresa: Empresa, emissao: Emissao, cliente: Cliente | None = None) -> dict:
    cidade = empresa.local_prestacao_ibge or empresa.municipio_ibge
    payload: dict = {
        # UUID novo a cada chamada, de proposito -- NAO usar str(emissao.id).
        # Confirmado ao vivo (24/09): a Spedy trata integrationId como chave
        # de idempotencia. Reaproveitar o id da emissao (estavel entre
        # tentativas) fazia o "Reemitir" nunca reenviar de verdade -- a Spedy
        # so devolvia o MESMO resultado (mesmo id/rps) da tentativa rejeitada
        # original, sem nunca tentar de novo com a prefeitura.
        "integrationId": str(uuid.uuid4()),
        "description": emissao.descricao,
        "effectiveDate": datetime.combine(emissao.competencia, time.min, tzinfo=FUSO_BRT).isoformat(),
        "total": {"invoiceAmount": float(emissao.valor)},
        "city": {"code": cidade},
        "location": {"code": cidade},
        "taxationType": "taxationInMunicipality",
        "federalServiceCode": _federal_service_code_lc116(empresa.codigo_tributacao),
        "issue": True,
    }
    if emissao.numero is not None:
        payload["rpsNumber"] = emissao.numero
    if emissao.serie:
        payload["rpsSeries"] = emissao.serie
    if empresa.aliquota_iss is not None:
        payload["total"]["issRate"] = float(empresa.aliquota_iss)
    if empresa.codigo_tributacao_municipal:
        payload["cityServiceCode"] = empresa.codigo_tributacao_municipal
    if empresa.cnae:
        payload["cnaeCode"] = empresa.cnae
    # Sempre manda receiver, mesmo sem CPF/CNPJ do tomador (caso das notas
    # importadas da planilha de vendas, cliente "nao identificado"): suspeita
    # levantada ao vivo (23/09) de que a ausencia total do bloco e o que faz
    # a SEFIN de Belem devolver SPD999 ("erro ao estabelecer comunicacao com
    # o servico") em vez de autorizar. federalTaxNumber/email so entram
    # quando existem -- nunca manda null explicito (mesmo padrao do resto
    # deste payload, ver cityServiceCode/cnaeCode acima).
    receiver: dict = {"name": emissao.tomador_nome or "Consumidor nao identificado"}
    if emissao.tomador_cpf_cnpj:
        receiver["federalTaxNumber"] = emissao.tomador_cpf_cnpj
    if emissao.tomador_email:
        receiver["email"] = emissao.tomador_email
    # Telefone/endereco vem do cadastro do Cliente (nao da Emissao, que so
    # denormaliza cpf_cnpj/nome/email) -- so existe quando a emissao esta
    # linkada a um cliente cadastrado (emissao.cliente_id). Notas importadas
    # da planilha de vendas/webhook, sem cliente vinculado, seguem sem esses
    # campos (Spedy trata como opcionais).
    if cliente is not None:
        if cliente.telefone:
            receiver["phoneNumber"] = cliente.telefone
        endereco: dict = {}
        if cliente.cep:
            endereco["postalCode"] = cliente.cep
        if cliente.logradouro:
            endereco["street"] = cliente.logradouro
        if cliente.numero:
            endereco["number"] = cliente.numero
        if cliente.complemento:
            endereco["additionalInformation"] = cliente.complemento
        if cliente.bairro:
            endereco["district"] = cliente.bairro
        if cliente.municipio_ibge:
            endereco["city"] = {"code": cliente.municipio_ibge}
        if endereco:
            receiver["address"] = endereco
    payload["receiver"] = receiver
    return payload

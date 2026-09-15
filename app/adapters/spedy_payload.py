"""Mapeia Empresa/Emissao para o payload de POST /service-invoices da Spedy.
Ao contrario do caminho direto (nfse_core/dps.py monta XML), aqui os dados
vao inline no JSON -- a Spedy nao exige cliente/produto pre-cadastrados."""
from __future__ import annotations

from datetime import datetime, time, timezone

from app.models import Emissao, Empresa


def montar_payload_spedy(empresa: Empresa, emissao: Emissao) -> dict:
    cidade = empresa.local_prestacao_ibge or empresa.municipio_ibge
    payload: dict = {
        "integrationId": str(emissao.id),
        "description": emissao.descricao,
        "effectiveDate": datetime.combine(emissao.competencia, time.min, tzinfo=timezone.utc).isoformat(),
        "total": {"invoiceAmount": float(emissao.valor)},
        "city": {"code": cidade},
        "location": "serviceProvisionMunicipality" if empresa.local_prestacao_ibge else "companyMunicipality",
        "taxationType": "taxationInMunicipality",
        "federalServiceCode": empresa.codigo_tributacao,
        "issue": True,
    }
    if empresa.codigo_tributacao_municipal:
        payload["cityServiceCode"] = empresa.codigo_tributacao_municipal
    if emissao.tomador_cpf_cnpj:
        payload["receiver"] = {
            "federalTaxNumber": emissao.tomador_cpf_cnpj,
            "name": emissao.tomador_nome,
            "email": emissao.tomador_email,
        }
    return payload

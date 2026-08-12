"""Bootstrap de uma empresa (fora da API — roda por quem tem o .pfx em mãos).

Uso:
    python scripts/criar_empresa.py --cnpj 12345678000199 --im 123456 \
        --municipio 3550308 --regime 3 --cod-tributacao 140106 \
        --descricao "Servicos de lavagem de roupa" --ambiente homologacao \
        --pfx caminho/certificado.pfx --senha-certificado "..." \
        --admin-email admin@empresa.com --admin-senha "..."
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import cifrar, hash_senha
from app.db import SessionLocal
from app.models import AmbienteEnum, Empresa, PapelUsuario, Usuario
from nfse_core import CertificateError, conferir_titularidade, inspecionar


async def criar_empresa(
    session: AsyncSession,
    *,
    cnpj: str,
    inscricao_municipal: str,
    municipio_ibge: str,
    op_simp_nac: int,
    codigo_tributacao: str,
    descricao_servico_padrao: str,
    ambiente: str,
    pfx_base64: str,
    senha_certificado: str,
    webhook_token: str,
    admin_email: str,
    admin_senha: str,
) -> Empresa:
    try:
        info = inspecionar(pfx_base64, senha_certificado)
    except CertificateError as exc:
        raise ValueError(f"Certificado invalido: {exc}") from exc

    aviso_titularidade = conferir_titularidade(info, cnpj)
    if aviso_titularidade:
        raise ValueError(aviso_titularidade)
    if info.expirado:
        raise ValueError(f"Certificado ja esta vencido em {info.valido_ate:%d/%m/%Y}")

    fernet_key = _fernet_key_do_ambiente()

    empresa = Empresa(
        cnpj=cnpj,
        inscricao_municipal=inscricao_municipal,
        municipio_ibge=municipio_ibge,
        op_simp_nac=op_simp_nac,
        codigo_tributacao=codigo_tributacao,
        descricao_servico_padrao=descricao_servico_padrao,
        ambiente=AmbienteEnum(ambiente),
        certificado_pfx_cifrado=cifrar(pfx_base64, fernet_key),
        certificado_senha_cifrada=cifrar(senha_certificado, fernet_key),
        certificado_valido_ate=info.valido_ate,
        webhook_token_hash=hash_senha(webhook_token),
    )
    session.add(empresa)
    await session.flush()

    admin = Usuario(
        empresa_id=empresa.id,
        email=admin_email,
        senha_hash=hash_senha(admin_senha),
        papel=PapelUsuario.admin,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(empresa)
    return empresa


def _fernet_key_do_ambiente() -> str:
    from app.config import get_settings

    return get_settings().fernet_key


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cnpj", required=True)
    parser.add_argument("--im", required=True, dest="inscricao_municipal")
    parser.add_argument("--municipio", required=True, dest="municipio_ibge")
    parser.add_argument("--regime", required=True, type=int, dest="op_simp_nac")
    parser.add_argument("--cod-tributacao", required=True, dest="codigo_tributacao")
    parser.add_argument("--descricao", required=True, dest="descricao_servico_padrao")
    parser.add_argument("--ambiente", required=True, choices=["homologacao", "producao"])
    parser.add_argument("--pfx", required=True, type=Path, dest="pfx_path")
    parser.add_argument("--senha-certificado", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-senha", required=True)
    parser.add_argument("--webhook-token", default=None)
    args = parser.parse_args()

    pfx_base64 = base64.b64encode(args.pfx_path.read_bytes()).decode()
    webhook_token = args.webhook_token or secrets.token_urlsafe(32)

    async with SessionLocal() as session:
        empresa = await criar_empresa(
            session,
            cnpj=args.cnpj,
            inscricao_municipal=args.inscricao_municipal,
            municipio_ibge=args.municipio_ibge,
            op_simp_nac=args.op_simp_nac,
            codigo_tributacao=args.codigo_tributacao,
            descricao_servico_padrao=args.descricao_servico_padrao,
            ambiente=args.ambiente,
            pfx_base64=pfx_base64,
            senha_certificado=args.senha_certificado,
            webhook_token=webhook_token,
            admin_email=args.admin_email,
            admin_senha=args.admin_senha,
        )

    print(f"Empresa criada: {empresa.id} (CNPJ {empresa.cnpj})")
    if not args.webhook_token:
        print(f"Token do webhook (guarde, so aparece agora): {webhook_token}")
        print(f"URL do webhook na Stone: /webhooks/stone/{empresa.id}")


if __name__ == "__main__":
    asyncio.run(_main())

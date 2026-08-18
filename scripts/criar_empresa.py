"""Bootstrap de uma empresa (fora da API — roda por quem tem o .pfx em mãos).

O titular precisa já existir no sistema (criado por convite aceito — ver
POST /convites) e ter um plano vinculado com limite de empresas disponível.

Uso:
    python scripts/criar_empresa.py --cnpj 12345678000199 --im 123456 \
        --municipio 3550308 --regime 3 --cod-tributacao 140106 \
        --descricao "Servicos de lavagem de roupa" --ambiente homologacao \
        --pfx caminho/certificado.pfx --senha-certificado "..." \
        --titular-email titular@empresa.com
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import secrets
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import cifrar, hash_senha
from app.db import SessionLocal
from app.models import AmbienteEnum, Empresa, PapelUsuario, Plano, Usuario, UsuarioEmpresa
from nfse_core import CertificateError, conferir_titularidade, inspecionar


async def criar_empresa(
    session: AsyncSession,
    *,
    cnpj: str,
    inscricao_municipal: str | None,
    municipio_ibge: str,
    local_prestacao_ibge: str | None = None,
    op_simp_nac: int,
    codigo_tributacao: str,
    descricao_servico_padrao: str,
    ambiente: str,
    pfx_base64: str,
    senha_certificado: str,
    webhook_token: str,
    titular_email: str,
) -> Empresa:
    titular = (
        await session.execute(select(Usuario).where(Usuario.email == titular_email))
    ).scalar_one_or_none()
    if titular is None:
        raise ValueError(f"Nenhum usuario encontrado com o e-mail {titular_email}")
    if titular.plano_id is None:
        raise ValueError(f"Usuario {titular_email} nao tem plano vinculado")

    plano = await session.get(Plano, titular.plano_id)
    empresas_do_titular = (
        await session.execute(
            select(func.count()).select_from(Empresa).where(Empresa.titular_id == titular.id)
        )
    ).scalar_one()
    if empresas_do_titular >= plano.limite_empresas:
        raise ValueError(
            f"Titular {titular_email} ja atingiu o limite de {plano.limite_empresas} "
            f"empresa(s) do plano {plano.nome}"
        )

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
        local_prestacao_ibge=local_prestacao_ibge,
        op_simp_nac=op_simp_nac,
        codigo_tributacao=codigo_tributacao,
        descricao_servico_padrao=descricao_servico_padrao,
        ambiente=AmbienteEnum(ambiente),
        certificado_pfx_cifrado=cifrar(pfx_base64, fernet_key),
        certificado_senha_cifrada=cifrar(senha_certificado, fernet_key),
        certificado_valido_ate=info.valido_ate,
        webhook_token_hash=hash_senha(webhook_token),
        titular_id=titular.id,
    )
    session.add(empresa)
    await session.flush()

    session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=PapelUsuario.admin))
    await session.commit()
    await session.refresh(empresa)
    return empresa


def _fernet_key_do_ambiente() -> str:
    from app.config import get_settings

    return get_settings().fernet_key


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cnpj", required=True)
    parser.add_argument("--im", required=False, default=None, dest="inscricao_municipal")
    parser.add_argument("--municipio", required=True, dest="municipio_ibge")
    parser.add_argument(
        "--local-prestacao", required=False, default=None, dest="local_prestacao_ibge",
    )
    parser.add_argument("--regime", required=True, type=int, dest="op_simp_nac")
    parser.add_argument("--cod-tributacao", required=True, dest="codigo_tributacao")
    parser.add_argument("--descricao", required=True, dest="descricao_servico_padrao")
    parser.add_argument("--ambiente", required=True, choices=["homologacao", "producao"])
    parser.add_argument("--pfx", required=True, type=Path, dest="pfx_path")
    parser.add_argument("--senha-certificado", required=True)
    parser.add_argument("--titular-email", required=True, dest="titular_email")
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
            local_prestacao_ibge=args.local_prestacao_ibge,
            op_simp_nac=args.op_simp_nac,
            codigo_tributacao=args.codigo_tributacao,
            descricao_servico_padrao=args.descricao_servico_padrao,
            ambiente=args.ambiente,
            pfx_base64=pfx_base64,
            senha_certificado=args.senha_certificado,
            webhook_token=webhook_token,
            titular_email=args.titular_email,
        )

    print(f"Empresa criada: {empresa.id} (CNPJ {empresa.cnpj})")
    if not args.webhook_token:
        print(f"Token do webhook (guarde, so aparece agora): {webhook_token}")
        print(f"URL do webhook na Stone: /webhooks/stone/{empresa.id}")


if __name__ == "__main__":
    asyncio.run(_main())

"""Emissão de uma NFS-e de ponta a ponta, do zero.

    python exemplos/01_emitir_nota.py

Antes de rodar, copie `.env.example` para `.env` e preencha. Comece SEMPRE em
`homologacao` (produção restrita) — a nota emitida em `producao` é um documento
fiscal de verdade e cancelá-la depois é burocracia.

Este arquivo existe para você ver o fluxo inteiro numa tela só. No seu sistema,
os dados de `DpsData` virão do seu banco, não de constantes.
"""
import asyncio
import os
import sys
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfse_core import (  # noqa: E402
    DpsData, SefinClient, SefinError, build_dps_xml,
    erros_de_falha, ler_resposta_emissao, sign_dps,
)

BRT = timezone(timedelta(hours=-3))


def env(nome: str, obrigatorio: bool = True) -> str:
    valor = os.getenv(nome, "")
    if obrigatorio and not valor:
        raise SystemExit(f"Falta a variável {nome} — veja o .env.example")
    return valor


def carregar_dotenv() -> None:
    caminho = Path(__file__).resolve().parent.parent / ".env"
    if not caminho.exists():
        raise SystemExit("Crie o arquivo .env a partir do .env.example antes de rodar.")
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip())


async def main() -> None:
    carregar_dotenv()

    ambiente = env("NFSE_AMBIENTE")          # homologacao | producao
    pfx_b64 = env("NFSE_CERT_PFX_BASE64")
    senha = env("NFSE_CERT_SENHA", obrigatorio=False)

    # ── 1. Os dados da nota ───────────────────────────────────────────────────
    # No seu sistema isto vem do banco: quem é o cliente, o que foi vendido,
    # quanto custou. Aqui é fixo só para o exemplo rodar.
    dados = DpsData(
        tp_amb=1 if ambiente == "producao" else 2,
        dh_emi=datetime.now(BRT),
        serie=env("NFSE_SERIE"),
        numero=int(env("NFSE_NUMERO")),      # SEQUENCIAL e único por série — ver docs
        competencia=date.today().replace(day=1),

        prest_cnpj=env("NFSE_PRESTADOR_CNPJ"),
        prest_im=env("NFSE_PRESTADOR_IM", obrigatorio=False) or None,
        c_loc_emi=env("NFSE_MUNICIPIO_IBGE"),
        op_simp_nac=int(env("NFSE_OP_SIMP_NAC")),

        toma_cpf_cnpj=env("NFSE_TOMADOR_DOC"),
        toma_nome=env("NFSE_TOMADOR_NOME"),
        toma_email=env("NFSE_TOMADOR_EMAIL", obrigatorio=False) or None,

        c_trib_nac=env("NFSE_COD_TRIBUTACAO"),
        x_desc_serv=env("NFSE_DESCRICAO_SERVICO"),
        v_serv=Decimal(env("NFSE_VALOR")),
    )

    # ── 2. Monta o XML ────────────────────────────────────────────────────────
    xml = build_dps_xml(dados)
    print(f"DPS montada - Id: {dados.dps_id}")

    # ── 3. Assina com o certificado A1 ────────────────────────────────────────
    assinado = sign_dps(xml, pfx_b64, senha)
    Path("ultima_dps_assinada.xml").write_bytes(assinado)
    print("DPS assinada -> ultima_dps_assinada.xml")

    # ── 4. Envia para a SEFIN ─────────────────────────────────────────────────
    cliente = SefinClient(ambiente, pfx_b64, senha)
    try:
        bruta = await cliente.emitir_dps(assinado)
    except SefinError as exc:
        print(f"\n[ERRO] Falha de comunicacao: {exc}")
        for erro in erros_de_falha(exc):     # às vezes a causa real vem no corpo
            print(f"  [{erro['codigo']}] {erro['titulo']}")
        return
    finally:
        await cliente.close()

    # ── 5. Lê o resultado ─────────────────────────────────────────────────────
    # `ler_resposta_emissao` absorve as variações de nome dos campos entre
    # versões do manual — ver nfse_core/resposta.py.
    resultado = ler_resposta_emissao(bruta)

    if resultado.autorizada:
        print(f"\n[OK] NFS-e emitida! Chave de acesso: {resultado.chave_acesso}")
        if resultado.numero_nfse:
            print(f"     Numero da NFS-e: {resultado.numero_nfse}")
        if resultado.xml_nfse:
            Path("nfse_autorizada.xml").write_bytes(resultado.xml_nfse)
            print("     XML autorizado -> nfse_autorizada.xml  (este e o documento fiscal)")
        return

    print(f"\n[ERRO] Rejeitada (HTTP {resultado.http_status}):")
    for erro in resultado.erros:
        print(f"\n  [{erro['codigo']}] {erro['titulo']}")
        print(f"  {erro['explicacao']}")
        print(f"  -> {erro['acao_sugerida']}")
    if not resultado.erros:
        print(f"  Resposta crua: {resultado.bruta}")


if __name__ == "__main__":
    asyncio.run(main())

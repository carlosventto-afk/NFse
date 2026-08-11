"""Consulta de NFS-e e de DPS.

    python exemplos/03_consultar.py nfse <chave-de-acesso-50-digitos>
    python exemplos/03_consultar.py dps  <id-da-dps-45-chars>

A consulta por DPS é a sua saída de emergência: se você enviou a DPS e não sabe
se ela virou nota (timeout, processo morreu, resposta perdida), **não reenvie às
cegas** — pergunte. `GET /dps/{id}` devolve a chave de acesso se a nota já
existir. Reenviar produz `E0202` (duplicada) ou, pior, uma nota duplicada.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfse_core import SefinClient, SefinError, ler_resposta_emissao  # noqa: E402


def carregar_dotenv() -> None:
    caminho = Path(__file__).resolve().parent.parent / ".env"
    if not caminho.exists():
        raise SystemExit("Crie o arquivo .env a partir do .env.example antes de rodar.")
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip())


async def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("nfse", "dps"):
        raise SystemExit(
            "Uso:\n"
            "  python exemplos/03_consultar.py nfse <chave-de-acesso>\n"
            "  python exemplos/03_consultar.py dps  <id-da-dps>"
        )
    tipo, identificador = sys.argv[1], sys.argv[2]

    carregar_dotenv()
    ambiente = os.environ["NFSE_AMBIENTE"]
    pfx_b64 = os.environ["NFSE_CERT_PFX_BASE64"]
    senha = os.environ.get("NFSE_CERT_SENHA") or None

    cliente = SefinClient(ambiente, pfx_b64, senha)
    try:
        if tipo == "nfse":
            bruta = await cliente.consultar_nfse(identificador)
        else:
            bruta = await cliente.consultar_dps(identificador)
    except SefinError as exc:
        print(f"[ERRO] {exc}")
        return
    finally:
        await cliente.close()

    resultado = ler_resposta_emissao(bruta)
    if resultado.chave_acesso:
        print(f"[OK] Nota encontrada. Chave: {resultado.chave_acesso}")
        if resultado.xml_nfse:
            destino = Path(f"nfse_{resultado.chave_acesso[:12]}.xml")
            destino.write_bytes(resultado.xml_nfse)
            print(f"     XML -> {destino}")
    elif tipo == "dps":
        print("Esta DPS ainda NAO virou nota — pode enviar com seguranca.")
    else:
        print(f"Nada encontrado (HTTP {resultado.http_status}).")
        for erro in resultado.erros:
            print(f"  [{erro['codigo']}] {erro['titulo']}")


if __name__ == "__main__":
    asyncio.run(main())

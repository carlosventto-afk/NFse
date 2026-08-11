"""Cancelamento de uma NFS-e já emitida.

    python exemplos/02_cancelar_nota.py <chave-de-acesso-50-digitos>

Cancelamento é um EVENTO (e101101) registrado sobre a nota, não um "delete".
A nota continua existindo, com o evento anexado.

Prazo: cada município define o seu (comumente até o dia 10 do mês seguinte à
competência). Passado o prazo, o caminho é a substituição, não o cancelamento.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nfse_core import (  # noqa: E402
    EventoCancelamentoData, SefinClient, SefinError,
    build_evento_cancelamento_xml, ler_resposta_evento, sign_evento,
)

BRT = timezone(timedelta(hours=-3))


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
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python exemplos/02_cancelar_nota.py <chave-de-acesso>")
    chave = sys.argv[1]

    carregar_dotenv()
    ambiente = os.environ["NFSE_AMBIENTE"]
    pfx_b64 = os.environ["NFSE_CERT_PFX_BASE64"]
    senha = os.environ.get("NFSE_CERT_SENHA") or None

    dados = EventoCancelamentoData(
        chave_nfse=chave,
        tp_amb=1 if ambiente == "producao" else 2,
        dh_evento=datetime.now(BRT),
        autor_cpf_cnpj=os.environ["NFSE_PRESTADOR_CNPJ"],
        c_motivo="1",                                    # 1=Erro na emissao
        x_motivo="Cancelamento por erro na emissao da nota",
    )

    xml = build_evento_cancelamento_xml(dados)
    assinado = sign_evento(xml, pfx_b64, senha)
    print(f"Pedido de evento montado e assinado - Id: {dados.id_ped_reg}")

    cliente = SefinClient(ambiente, pfx_b64, senha)
    try:
        bruta = await cliente.registrar_evento(chave, assinado)
    except SefinError as exc:
        print(f"\n[ERRO] Falha de comunicacao: {exc}")
        return
    finally:
        await cliente.close()

    resultado = ler_resposta_evento(bruta)
    if resultado.registrado:
        print("\n[OK] Cancelamento registrado.")
        if resultado.xml_evento:
            Path("evento_cancelamento.xml").write_bytes(resultado.xml_evento)
            print("     XML do evento -> evento_cancelamento.xml")
        return

    print(f"\n[ERRO] Rejeitado (HTTP {resultado.http_status}):")
    for erro in resultado.erros:
        print(f"\n  [{erro['codigo']}] {erro['titulo']}")
        print(f"  {erro['explicacao']}")
        print(f"  -> {erro['acao_sugerida']}")


if __name__ == "__main__":
    asyncio.run(main())

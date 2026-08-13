import pytest

from app import email as modulo_email


@pytest.mark.asyncio
async def test_enviar_convite_chama_aiosmtplib_com_destinatario_e_link(monkeypatch):
    chamadas = []

    async def _send_falso(mensagem, *, hostname, port, username, password, use_tls):
        chamadas.append(
            {
                "to": mensagem["To"], "from": mensagem["From"], "subject": mensagem["Subject"],
                "corpo": mensagem.get_content(), "hostname": hostname, "port": port,
            }
        )

    monkeypatch.setattr(modulo_email.aiosmtplib, "send", _send_falso)

    await modulo_email.enviar_convite("novo@teste.com", "https://nfse.gestaotecnologia.com/aceitar-convite?token=abc")

    assert len(chamadas) == 1
    assert chamadas[0]["to"] == "novo@teste.com"
    assert "https://nfse.gestaotecnologia.com/aceitar-convite?token=abc" in chamadas[0]["corpo"]

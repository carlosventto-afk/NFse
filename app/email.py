from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings


async def enviar_convite(destinatario: str, link: str) -> None:
    settings = get_settings()
    mensagem = EmailMessage()
    mensagem["From"] = settings.smtp_user
    mensagem["To"] = destinatario
    mensagem["Subject"] = "Convite - NFS-e Automatizada"
    mensagem.set_content(
        "Voce foi convidado a acessar o sistema de NFS-e.\n\n"
        f"Clique no link abaixo para aceitar o convite:\n{link}\n\n"
        "Este link expira em 7 dias."
    )
    await aiosmtplib.send(
        mensagem,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=True,
    )

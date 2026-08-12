import bcrypt
from cryptography.fernet import Fernet


def cifrar(valor: str, chave: str) -> str:
    return Fernet(chave.encode()).encrypt(valor.encode()).decode()


def decifrar(token: str, chave: str) -> str:
    return Fernet(chave.encode()).decrypt(token.encode()).decode()


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def verificar_senha(senha: str, hash_: str) -> bool:
    """Falso para credencial invalida — nunca levanta.

    O bcrypt 5 levanta ValueError acima de 72 bytes. Como o segredo chega de
    fora (senha do login, header X-Webhook-Token), deixar a excecao subir
    viraria 500 em vez de 401/404. E "senha maior que 72 bytes" so pode estar
    errada: `hash_senha` tambem recusaria gerar um hash desses.
    """
    try:
        return bcrypt.checkpw(senha.encode(), hash_.encode())
    except ValueError:
        return False

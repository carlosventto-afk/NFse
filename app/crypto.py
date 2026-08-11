import bcrypt
from cryptography.fernet import Fernet


def cifrar(valor: str, chave: str) -> str:
    return Fernet(chave.encode()).encrypt(valor.encode()).decode()


def decifrar(token: str, chave: str) -> str:
    return Fernet(chave.encode()).decrypt(token.encode()).decode()


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def verificar_senha(senha: str, hash_: str) -> bool:
    return bcrypt.checkpw(senha.encode(), hash_.encode())

import pytest
from cryptography.fernet import Fernet

from app.crypto import cifrar, decifrar, hash_senha, verificar_senha


def test_cifrar_decifrar_recupera_valor_original():
    chave = Fernet.generate_key().decode()
    token = cifrar("conteudo-secreto", chave)
    assert token != "conteudo-secreto"
    assert decifrar(token, chave) == "conteudo-secreto"


def test_hash_senha_verifica_correta_e_rejeita_errada():
    hash_ = hash_senha("minha-senha-forte")
    assert verificar_senha("minha-senha-forte", hash_)
    assert not verificar_senha("senha-errada", hash_)

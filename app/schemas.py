import re
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, field_validator


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioCriarIn(BaseModel):
    email: EmailStr
    senha: str
    papel: str = "operador"

    @field_validator("senha")
    @classmethod
    def senha_minima(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("senha precisa ter ao menos 8 caracteres")
        return v

    @field_validator("papel")
    @classmethod
    def papel_valido(cls, v: str) -> str:
        if v not in ("admin", "operador"):
            raise ValueError("papel deve ser admin ou operador")
        return v


class UsuarioOut(BaseModel):
    id: uuid.UUID
    email: str
    papel: str

    model_config = {"from_attributes": True}


class EmissaoManualIn(BaseModel):
    cpf_cnpj: str | None = None
    nome: str
    email: str | None = None
    descricao: str
    valor: Decimal
    competencia: date

    @field_validator("cpf_cnpj")
    @classmethod
    def cpf_cnpj_valido(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        digitos = _somente_digitos(v)
        if len(digitos) not in (11, 14):
            raise ValueError("cpf_cnpj, quando informado, deve ter 11 (CPF) ou 14 (CNPJ) digitos")
        return digitos

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("valor deve ser positivo")
        return v


class EmissaoOut(BaseModel):
    id: uuid.UUID
    origem: str
    status: str
    serie: str | None
    numero: int | None
    chave_acesso: str | None
    tomador_cpf_cnpj: str | None
    tomador_nome: str | None
    descricao: str
    valor: Decimal
    competencia: date
    erros: str | None

    model_config = {"from_attributes": True}

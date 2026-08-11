import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, field_validator


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

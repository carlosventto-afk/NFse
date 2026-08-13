import re
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator

# Os limites abaixo espelham a largura das colunas em app/models.py. Sem eles,
# entrada maior que a coluna nao vira 422 (erro do cliente) e sim 500 — o
# Postgres so reclama na hora do INSERT (StringDataRightTruncationError).
TAMANHO_NOME = 300        # Emissao.tomador_nome String(300)
TAMANHO_DESCRICAO = 2000  # Emissao.descricao String(2000)
TAMANHO_EMAIL = 80        # Emissao.tomador_email String(80)
TAMANHO_EMAIL_USUARIO = 255  # Usuario.email String(255)
# Emissao.valor e Numeric(14, 2): 12 digitos inteiros + 2 decimais. Acima
# disso o proprio Postgres recusa (numeric field overflow). O limite aqui e
# so a barreira contra o 500 — nao e regra de negocio.
VALOR_MAXIMO = Decimal("999999999999.99")
# bcrypt recusa segredo com mais de 72 bytes (levanta ValueError em hashpw).
TAMANHO_SENHA_MAX = 72


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ConviteCriarIn(BaseModel):
    email: EmailStr = Field(max_length=TAMANHO_EMAIL_USUARIO)
    papel: str | None = None
    plano_id: uuid.UUID | None = None

    @field_validator("papel")
    @classmethod
    def papel_valido(cls, v: str | None) -> str | None:
        if v is not None and v not in ("admin", "operador"):
            raise ValueError("papel deve ser admin ou operador")
        return v


class ConviteOut(BaseModel):
    id: uuid.UUID
    email: str
    empresa_id: uuid.UUID | None
    papel: str | None
    expira_em: datetime

    model_config = {"from_attributes": True}


class ConviteAceitarIn(BaseModel):
    token: str
    senha: str | None = Field(default=None, max_length=TAMANHO_SENHA_MAX)

    @field_validator("senha")
    @classmethod
    def senha_valida(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("senha precisa ter ao menos 8 caracteres")
        if len(v.encode()) > TAMANHO_SENHA_MAX:
            raise ValueError(f"senha nao pode passar de {TAMANHO_SENHA_MAX} bytes")
        return v


class ClienteCriarIn(BaseModel):
    cpf_cnpj: str | None = Field(default=None, max_length=14)
    nome: str = Field(max_length=TAMANHO_NOME)
    email: str | None = Field(default=None, max_length=TAMANHO_EMAIL)
    telefone: str | None = Field(default=None, max_length=20)
    inscricao_estadual: str | None = Field(default=None, max_length=20)
    inscricao_municipal: str | None = Field(default=None, max_length=20)
    logradouro: str | None = Field(default=None, max_length=200)
    numero: str | None = Field(default=None, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str | None = Field(default=None, max_length=100)
    municipio_ibge: str | None = Field(default=None, max_length=7)
    uf: str | None = Field(default=None, max_length=2)
    cep: str | None = Field(default=None, max_length=8)

    @field_validator("cpf_cnpj")
    @classmethod
    def cpf_cnpj_valido(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        digitos = _somente_digitos(v)
        if len(digitos) not in (11, 14):
            raise ValueError("cpf_cnpj, quando informado, deve ter 11 (CPF) ou 14 (CNPJ) digitos")
        return digitos


class ClienteAtualizarIn(ClienteCriarIn):
    ativo: bool = True


class ClienteOut(BaseModel):
    id: uuid.UUID
    cpf_cnpj: str | None
    nome: str
    email: str | None
    telefone: str | None
    inscricao_estadual: str | None
    inscricao_municipal: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    municipio_ibge: str | None
    uf: str | None
    cep: str | None
    ativo: bool

    model_config = {"from_attributes": True}


class EmpresaVinculadaOut(BaseModel):
    empresa_id: uuid.UUID
    cnpj: str
    papel: str


class TrocarEmpresaIn(BaseModel):
    empresa_id: uuid.UUID


class EmissaoManualIn(BaseModel):
    cpf_cnpj: str | None = Field(default=None, max_length=20)
    nome: str = Field(max_length=TAMANHO_NOME)
    email: str | None = Field(default=None, max_length=TAMANHO_EMAIL)
    descricao: str = Field(max_length=TAMANHO_DESCRICAO)
    valor: Decimal = Field(le=VALOR_MAXIMO)
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

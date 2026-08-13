import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class AmbienteEnum(str, enum.Enum):
    homologacao = "homologacao"
    producao = "producao"


class StatusEmissao(str, enum.Enum):
    pendente = "pendente"
    autorizada = "autorizada"
    rejeitada = "rejeitada"
    cancelada = "cancelada"
    cancelamento_pendente = "cancelamento_pendente"
    erro_cancelamento = "erro_cancelamento"


class OrigemEmissao(str, enum.Enum):
    webhook = "webhook"
    manual = "manual"
    csv = "csv"


class PapelUsuario(str, enum.Enum):
    admin = "admin"
    operador = "operador"


class Plano(Base):
    __tablename__ = "planos"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    limite_empresas: Mapped[int] = mapped_column(nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)


class Empresa(Base):
    __tablename__ = "empresas"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    inscricao_municipal: Mapped[str] = mapped_column(String(20), nullable=False)
    municipio_ibge: Mapped[str] = mapped_column(String(7), nullable=False)
    op_simp_nac: Mapped[int] = mapped_column(nullable=False)
    codigo_tributacao: Mapped[str] = mapped_column(String(6), nullable=False)
    descricao_servico_padrao: Mapped[str] = mapped_column(String(2000), nullable=False)
    ambiente: Mapped[AmbienteEnum] = mapped_column(
        String(20), default=AmbienteEnum.homologacao, nullable=False
    )
    serie: Mapped[str] = mapped_column(String(5), default="1", nullable=False)
    proximo_numero: Mapped[int] = mapped_column(default=1, nullable=False)
    certificado_pfx_cifrado: Mapped[str] = mapped_column(Text, nullable=False)
    certificado_senha_cifrada: Mapped[str | None] = mapped_column(Text, nullable=True)
    certificado_valido_ate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    webhook_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Responsavel pela licenca desta empresa — conta contra plano.limite_empresas
    # do titular. Nullable no banco por decisao do plano de implementacao
    # (docs/superpowers/plans/2026-08-12-multiempresa-licenciamento-plan.md) —
    # a obrigatoriedade real vem de scripts/criar_empresa.py.
    titular_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    emissoes: Mapped[list["Emissao"]] = relationship(back_populates="empresa")
    usuario_empresas: Mapped[list["UsuarioEmpresa"]] = relationship(back_populates="empresa")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    eh_admin_plataforma: Mapped[bool] = mapped_column(default=False, nullable=False)
    plano_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("planos.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    usuario_empresas: Mapped[list["UsuarioEmpresa"]] = relationship(back_populates="usuario")


class UsuarioEmpresa(Base):
    __tablename__ = "usuario_empresas"
    __table_args__ = (
        UniqueConstraint("usuario_id", "empresa_id", name="uq_usuario_empresa"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    papel: Mapped[PapelUsuario] = mapped_column(String(20), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)

    usuario: Mapped["Usuario"] = relationship(back_populates="usuario_empresas")
    empresa: Mapped["Empresa"] = relationship(back_populates="usuario_empresas")


class Convite(Base):
    __tablename__ = "convites"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    empresa_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("empresas.id"), nullable=True)
    papel: Mapped[PapelUsuario | None] = mapped_column(String(20), nullable=True)
    plano_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("planos.id"), nullable=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    aceito_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_por_usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)


class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (
        Index(
            "ix_clientes_empresa_cpf_cnpj",
            "empresa_id", "cpf_cnpj",
            unique=True,
            postgresql_where=text("cpf_cnpj IS NOT NULL"),
        ),
        Index(
            "ix_clientes_empresa_padrao_csv",
            "empresa_id",
            unique=True,
            postgresql_where=text("eh_padrao_csv = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    nome: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str | None] = mapped_column(String(80), nullable=True)
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inscricao_estadual: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inscricao_municipal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    logradouro: Mapped[str | None] = mapped_column(String(200), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    complemento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(100), nullable=True)
    municipio_ibge: Mapped[str | None] = mapped_column(String(7), nullable=True)
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    eh_padrao_csv: Mapped[bool] = mapped_column(default=False, nullable=False)
    ativo: Mapped[bool] = mapped_column(default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_agora, onupdate=_agora, nullable=False
    )


class Emissao(Base):
    __tablename__ = "emissoes"
    __table_args__ = (
        Index(
            "ix_emissoes_empresa_stone_charge_id",
            "empresa_id", "stone_charge_id",
            unique=True,
            postgresql_where=text("stone_charge_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("empresas.id"), nullable=False)
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clientes.id"), nullable=True)
    origem: Mapped[OrigemEmissao] = mapped_column(String(20), nullable=False)
    stone_charge_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[StatusEmissao] = mapped_column(String(30), nullable=False)
    serie: Mapped[str | None] = mapped_column(String(5), nullable=True)
    numero: Mapped[int | None] = mapped_column(nullable=True)
    dps_id: Mapped[str | None] = mapped_column(String(45), nullable=True)
    chave_acesso: Mapped[str | None] = mapped_column(String(50), nullable=True)
    xml_dps: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    xml_nfse: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    erros: Mapped[str | None] = mapped_column(Text, nullable=True)
    tomador_cpf_cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True)
    tomador_nome: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tomador_email: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descricao: Mapped[str] = mapped_column(String(2000), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    competencia: Mapped[date] = mapped_column(Date, nullable=False)
    criada_por_usuario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora, nullable=False)
    atualizada_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_agora, onupdate=_agora, nullable=False
    )
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cancelada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    empresa: Mapped["Empresa"] = relationship(back_populates="emissoes")

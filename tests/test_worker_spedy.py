import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.crypto import cifrar, hash_senha
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, ProvedorEmissao, StatusEmissao, Usuario
from app.adapters.spedy_client import SpedyError
import app.worker as worker


async def _empresa_spedy_e_emissao_pendente(db_session, **overrides_empresa) -> Emissao:
    fernet_key = get_settings().fernet_key
    titular = Usuario(email=f"titular-spedy-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, provedor_emissao=ProvedorEmissao.spedy,
        spedy_empresa_id="spedy-empresa-1",
        spedy_api_key_cifrada=cifrar("spedy-chave-1", fernet_key),
        certificado_pfx_cifrado="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    dados.update(overrides_empresa)
    empresa = Empresa(**dados)
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, tomador_cpf_cnpj="98765432100", tomador_nome="Cliente",
        descricao="Lavagem de roupa", valor=Decimal("49.90"), competencia=date(2026, 9, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_aceita_e_fica_aguardando_confirmacao(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            assert payload["integrationId"] == str(emissao.id)
            return {"_http_status": 200, "id": "nota-spedy-1", "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao
    assert emissao.spedy_nota_id == "nota-spedy-1"


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_rejeicao_sincrona(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            return {
                "_http_status": 400,
                "processingDetail": {"message": "CNPJ do tomador invalido"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert "CNPJ do tomador invalido" in erros[0]["titulo"]
    assert emissao.resposta_bruta is not None


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_grava_requisicao_bruta_ao_aceitar(db_session, monkeypatch):
    # O JSON exato enviado a Spedy precisa ficar gravado (nao so no log
    # efemero do worker) para poder ser exportado como evidencia junto a
    # Spedy/prefeitura quando uma emissao e rejeitada -- mesma motivacao do
    # resposta_bruta, so que do lado da requisicao.
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            return {"_http_status": 200, "id": "nota-spedy-1", "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.requisicao_bruta is not None
    assert json.loads(emissao.requisicao_bruta)["integrationId"] == str(emissao.id)


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_grava_requisicao_bruta_ao_rejeitar(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            return {"_http_status": 400, "processingDetail": {"message": "Atividade nao informada"}}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.requisicao_bruta is not None
    assert json.loads(emissao.requisicao_bruta)["integrationId"] == str(emissao.id)


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_grava_requisicao_bruta_em_falha_de_transporte(db_session, monkeypatch):
    # Mesmo quando a Spedy nunca responde (timeout/DNS), o payload que a
    # gente TENTOU enviar precisa ficar gravado -- e a unica evidencia que
    # sobra desse lado pra investigar com a Spedy.
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            raise SpedyError("falha de rede com a Spedy (ConnectTimeout)")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.requisicao_bruta is not None
    assert json.loads(emissao.requisicao_bruta)["integrationId"] == str(emissao.id)


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_falha_de_transporte(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            raise SpedyError("falha de rede com a Spedy (ConnectTimeout)")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "TRANSPORTE"


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_sem_provisionamento_marca_rejeitada(db_session):
    emissao = await _empresa_spedy_e_emissao_pendente(
        db_session, spedy_empresa_id=None, spedy_api_key_cifrada=None,
    )

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "SPEDY_NAO_PROVISIONADA"


async def _emissao_aguardando_confirmacao(db_session) -> Emissao:
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.aguardando_confirmacao
    emissao.spedy_nota_id = "nota-spedy-1"
    await db_session.commit()
    return emissao


@pytest.mark.asyncio
async def test_confirmacao_spedy_marca_autorizada(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            assert spedy_nota_id == "nota-spedy-1"
            return {"_http_status": 200, "status": "authorized", "accessKey": "chave-final-1"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "chave-final-1"


@pytest.mark.asyncio
async def test_confirmacao_spedy_autorizada_limpa_erro_de_tentativa_anterior(db_session, monkeypatch):
    # Uma nota que foi rejeitada e reemitida com sucesso nao pode continuar
    # mostrando na tela o erro da tentativa ANTERIOR -- confunde o usuario
    # fazendo parecer que uma nota ja autorizada ainda tem problema (caso
    # real: Belem, erro E188 que ficou preso na coluna mesmo apos autorizar).
    emissao = await _emissao_aguardando_confirmacao(db_session)
    emissao.erros = json.dumps([{"codigo": "E188", "titulo": "Opcao simples nacional conflita..."}])
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "authorized", "accessKey": "chave-final-1"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.erros is None


@pytest.mark.asyncio
async def test_confirmacao_spedy_marca_rejeitada(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {
                "_http_status": 200, "status": "rejected",
                "processingDetail": {"code": "SPD123", "message": "servico invalido"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "SPD123"


@pytest.mark.asyncio
async def test_confirmacao_spedy_ainda_processando_nao_conta_como_trabalho(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao


@pytest.mark.asyncio
async def test_confirmacao_spedy_http_erro_nao_resolve_e_nao_derruba(db_session, monkeypatch):
    # Fix I1: consultar_nfse usa o _handle tolerante -- uma chave revogada,
    # 403 ou 404 nunca levanta SpedyError, so devolve um dict sem "status"
    # reconhecivel. Sem tratar _http_status >= 400 explicitamente a linha
    # ficaria presa "pending" pra sempre sem nenhum log explicando o motivo.
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 401}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)
    atualizada_em_antes = emissao.atualizada_em

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao
    assert emissao.chave_acesso is None
    # a linha precisa rotacionar (atualizada_em avanca) mesmo em erro HTTP --
    # senao uma chave revogada prende a linha no topo da fila pra sempre.
    assert emissao.atualizada_em > atualizada_em_antes


@pytest.mark.asyncio
async def test_confirmacao_spedy_chave_nao_decifra_nao_marca_erro(db_session):
    # Fix I6: por aqui a nota JA foi submetida a Spedy antes. Se a chave nao
    # decifra agora (FERNET_KEY rotacionada no meio do caminho), isso nao diz
    # nada sobre o estado real da nota na Spedy -- marcar como rejeitada
    # arrisca um humano reemitir uma nota fiscal que ja existe, duplicando-a.
    # O comportamento seguro e so logar e tentar de novo depois.
    outra_chave = Fernet.generate_key().decode()
    emissao = await _empresa_spedy_e_emissao_pendente(
        db_session, spedy_api_key_cifrada=cifrar("spedy-chave-1", outra_chave),
    )
    emissao.status = StatusEmissao.aguardando_confirmacao
    emissao.spedy_nota_id = "nota-spedy-1"
    atualizada_em_antes = datetime(2020, 1, 1, tzinfo=timezone.utc)
    emissao.atualizada_em = atualizada_em_antes
    await db_session.commit()

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao
    # Fix I2 (rotacao): mesmo sem resolver, atualizada_em precisa avancar --
    # senao essa linha fica presa como a mais antiga da fila pra sempre,
    # nunca deixando outra linha (de outra empresa) ser tentada.
    assert emissao.atualizada_em > atualizada_em_antes


@pytest.mark.asyncio
async def test_confirmacao_spedy_rotaciona_fila_por_atualizada_em(db_session, monkeypatch):
    # Fix I2: order_by(criada_em) faria a linha mais antiga que nunca resolve
    # monopolizar a fila pra sempre, starvando as demais linhas da mesma
    # empresa. order_by(atualizada_em) rotaciona: cada tentativa que nao
    # resolve empurra a linha pro fim da fila.
    emissao_a = await _emissao_aguardando_confirmacao(db_session)
    emissao_a.atualizada_em = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await db_session.commit()

    emissao_b = Emissao(
        empresa_id=emissao_a.empresa_id, origem=OrigemEmissao.manual,
        status=StatusEmissao.aguardando_confirmacao, serie="1", numero=2,
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente",
        descricao="Lavagem de roupa 2", valor=Decimal("49.90"), competencia=date(2026, 9, 1),
        spedy_nota_id="nota-spedy-2",
    )
    db_session.add(emissao_b)
    await db_session.commit()
    emissao_b.atualizada_em = datetime(2026, 1, 2, tzinfo=timezone.utc)
    await db_session.commit()
    await db_session.refresh(emissao_a)
    await db_session.refresh(emissao_b)

    vistas = []

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            vistas.append(spedy_nota_id)
            return {"_http_status": 200, "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)
    assert processou is False
    assert vistas == ["nota-spedy-1"]
    await db_session.refresh(emissao_a)
    await db_session.refresh(emissao_b)
    assert emissao_a.atualizada_em > emissao_b.atualizada_em

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)
    assert processou is False
    assert vistas == ["nota-spedy-1", "nota-spedy-2"]


@pytest.mark.asyncio
async def test_processar_uma_aguardando_confirmacao_spedy_devolve_falso_quando_fila_vazia(db_session):
    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)
    assert processou is False


async def _emissao_cancelamento_pendente_spedy(db_session) -> Emissao:
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.chave_acesso = "chave-final-1"
    emissao.spedy_nota_id = "nota-spedy-1"
    emissao.motivo_cancelamento = "Servico nao prestado"
    await db_session.commit()
    return emissao


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_fica_aguardando_confirmacao(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            assert spedy_nota_id == "nota-spedy-1"
            assert motivo == "Servico nao prestado"
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_rejeicao_sincrona(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            return {
                "_http_status": 400,
                "errors": [{"message": "A nota fiscal não pode ser cancelada."}],
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento
    erros = json.loads(emissao.erros)
    assert "não pode ser cancelada" in erros[0]["titulo"]


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_falha_de_transporte(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            raise SpedyError("falha de rede")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_marca_cancelada(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceled"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelada
    assert emissao.cancelada_em is not None


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_ainda_processando_nao_conta_como_trabalho(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_grava_resposta_bruta_mesmo_sem_resolver(db_session, monkeypatch):
    # Caso real: uma nota ficou presa em "cancelamento_aguardando_confirmacao"
    # por mais de um dia sem NENHUMA evidencia acessivel do que a Spedy
    # estava respondendo de verdade nessa consulta -- so log efemero. A
    # resposta crua precisa ficar gravada a cada tentativa (nao so quando
    # finalmente resolve), pro "Resposta SEFIN" mostrar o estado atual.
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.resposta_bruta is not None
    assert json.loads(emissao.resposta_bruta) == {"_http_status": 200, "status": "canceling"}


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_recusado_definitivamente_marca_erro(db_session, monkeypatch):
    # Caso real (Belem): a Spedy devolve status="authorized" (a nota em si
    # continua autorizada) mas processingDetail.status="failed" quando o
    # CANCELAMENTO especificamente e recusado (prazo expirado, L999). Antes
    # dessa correcao a nota ficava presa em cancelamento_aguardando_confirmacao
    # pra sempre, porque so "status": "canceled" era tratado como terminal.
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {
                "_http_status": 200, "status": "authorized",
                "processingDetail": {
                    "status": "failed", "code": "L999",
                    "message": "O prazo para cancelamento desta nota expirou.",
                },
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "L999"
    assert "prazo" in erros[0]["titulo"]


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_http_erro_nao_resolve_e_nao_derruba(db_session, monkeypatch):
    # Mirror do teste equivalente pra emissao (Fix I1): 401/403/404 no
    # consultar_nfse nao pode ser confundido com "ainda processando" silencioso.
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 401}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)
    atualizada_em_antes = emissao.atualizada_em

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao
    assert emissao.atualizada_em > atualizada_em_antes


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_chave_nao_decifra_nao_marca_erro(db_session):
    # Mirror do teste equivalente pra emissao (Fix I6): o cancelamento ja foi
    # submetido a Spedy antes -- se a chave nao decifra agora, marcar
    # erro_cancelamento arrisca esconder um cancelamento que ja aconteceu do
    # lado da Spedy. O seguro e so logar e tentar de novo depois.
    outra_chave = Fernet.generate_key().decode()
    emissao = await _empresa_spedy_e_emissao_pendente(
        db_session, spedy_api_key_cifrada=cifrar("spedy-chave-1", outra_chave),
    )
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    emissao.chave_acesso = "chave-final-1"
    emissao.spedy_nota_id = "nota-spedy-1"
    emissao.motivo_cancelamento = "Servico nao prestado"
    atualizada_em_antes = datetime(2020, 1, 1, tzinfo=timezone.utc)
    emissao.atualizada_em = atualizada_em_antes
    await db_session.commit()

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao
    # Fix I2 (rotacao): ver comentario equivalente no teste de emissao acima.
    assert emissao.atualizada_em > atualizada_em_antes

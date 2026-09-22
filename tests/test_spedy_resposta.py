from app.adapters.spedy_resposta import chave_acesso_de, interpretar_status_cancelamento, interpretar_status_emissao


def test_interpreta_autorizada():
    assert interpretar_status_emissao({"status": "authorized"}) == "authorized"


def test_interpreta_rejeitada():
    assert interpretar_status_emissao({"status": "rejected"}) == "rejected"
    assert interpretar_status_emissao({"status": "denied"}) == "rejected"


def test_interpreta_ainda_processando():
    assert interpretar_status_emissao({"status": "enqueued"}) == "pending"
    assert interpretar_status_emissao({"status": "processing"}) == "pending"
    assert interpretar_status_emissao({}) == "pending"


def test_chave_acesso_tenta_varios_campos():
    assert chave_acesso_de({"accessKey": "abc"}) == "abc"
    assert chave_acesso_de({"chaveAcesso": "def"}) == "def"
    assert chave_acesso_de({}) is None


def test_interpreta_cancelamento_confirmado():
    assert interpretar_status_cancelamento({"status": "canceled"}) == "canceled"


def test_interpreta_cancelamento_ainda_processando():
    assert interpretar_status_cancelamento({"status": "authorized"}) == "pending"
    assert interpretar_status_cancelamento({"status": "canceling"}) == "pending"
    assert interpretar_status_cancelamento({}) == "pending"


def test_interpreta_cancelamento_falhou_definitivamente():
    # Confirmado ao vivo (Belem, nota CNPJ 49055093000140): a Spedy devolve
    # status="authorized" no nivel superior (a NOTA continua autorizada) mas
    # com processingDetail.status == "failed" quando o CANCELAMENTO em si e
    # recusado -- nesse caso, prazo de cancelamento expirado (L999). Sem
    # tratar isso como estado terminal, a nota ficava presa em
    # "aguardando confirmacao" pra sempre (ficou mais de um dia assim).
    bruta = {
        "status": "authorized",
        "processingDetail": {
            "status": "failed", "code": "L999",
            "message": "O prazo para cancelamento desta nota expirou, entre em contato com a prefeitura.",
        },
    }
    assert interpretar_status_cancelamento(bruta) == "failed"


def test_chave_acesso_nao_usa_number_como_fallback():
    # Fix I8: "number" e o numero sequencial de RPS/NFS-e da Spedy, sem
    # relacao com "chave de acesso". Confirmado ao vivo: uma resposta
    # REJEITADA no sandbox trazia "number": 0 -- se isso caisse aqui como
    # fallback, gravaria um numero sequencial como se fosse a chave de acesso
    # real, o unico lugar desta integracao onde um palpite nao confirmado
    # falharia calado em vez de visivel.
    assert chave_acesso_de({"number": 0}) is None
    assert chave_acesso_de({"number": 12345}) is None

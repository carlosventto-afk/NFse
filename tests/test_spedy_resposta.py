from app.adapters.spedy_resposta import chave_acesso_de, interpretar_status_emissao


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

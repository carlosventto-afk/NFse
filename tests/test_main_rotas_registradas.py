from app.main import app


def test_todas_as_rotas_esperadas_estao_registradas():
    caminhos = set()
    for rota in app.routes:
        if hasattr(rota, "path"):
            caminhos.add(rota.path)
        elif type(rota).__name__ == "_IncludedRouter":
            for contexto in rota.effective_route_contexts():
                caminhos.add(contexto.path)

    esperadas = {
        "/health",
        "/auth/login",
        "/auth/empresas",
        "/auth/trocar-empresa",
        "/convites",
        "/convites/aceitar",
        "/webhooks/stone/{empresa_id}",
        "/emissoes/manual",
        "/emissoes",
        "/emissoes/{emissao_id}/xml",
        "/emissoes/{emissao_id}/pdf",
        "/emissoes/csv/preview",
        "/emissoes/csv/confirmar",
        "/dashboard",
    }
    faltando = esperadas - caminhos
    assert not faltando, f"rotas nao registradas: {faltando}"

    inesperadas = caminhos & {"/usuarios"}
    assert not inesperadas, f"rota removida ainda presente: {inesperadas}"

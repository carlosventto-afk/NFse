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
        "/api/auth/login",
        "/api/auth/empresas",
        "/api/auth/trocar-empresa",
        "/api/convites",
        "/api/convites/aceitar",
        "/api/clientes",
        "/api/clientes/{cliente_id}",
        "/api/empresas",
        "/api/empresas/numeracao",
        "/api/webhooks/stone/{empresa_id}",
        "/api/emissoes/manual",
        "/api/emissoes",
        "/api/emissoes/{emissao_id}/xml",
        "/api/emissoes/{emissao_id}/pdf",
        "/api/emissoes/{emissao_id}/cancelar",
        "/api/emissoes/{emissao_id}",
        "/api/emissoes/csv/preview",
        "/api/emissoes/csv/confirmar",
        "/api/dashboard",
    }
    faltando = esperadas - caminhos
    assert not faltando, f"rotas nao registradas: {faltando}"

    # /assets e /{caminho_completo:path} so existem quando frontend/dist/ ja
    # foi gerado (npm run build) — condicional em app/main.py. Tolerados
    # aqui porque a presenca depende do ambiente, nao sao rotas de API.
    toleradas_spa = {"/assets", "/{caminho_completo:path}"}

    inesperadas = {
        c for c in caminhos
        if c not in esperadas and c not in toleradas_spa
        and not c.startswith("/openapi") and not c.startswith("/docs") and not c.startswith("/redoc")
    }
    assert not inesperadas, f"rotas sem prefixo /api ou inesperadas: {inesperadas}"

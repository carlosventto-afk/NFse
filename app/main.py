from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import auth, clientes, convites, dashboard, emissoes, empresas, webhook_stone

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router, prefix="/api")
app.include_router(convites.router, prefix="/api")
app.include_router(clientes.router, prefix="/api")
app.include_router(empresas.router, prefix="/api")
app.include_router(emissoes.router, prefix="/api")
app.include_router(webhook_stone.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/{caminho_completo:path}")
    async def servir_spa(caminho_completo: str) -> FileResponse:
        # Qualquer rota que nao seja /api, /health ou /assets cai aqui e
        # devolve o index.html — o roteamento de verdade (login, emissoes,
        # etc.) e feito pelo react-router no navegador, nao pelo backend.
        return FileResponse(_FRONTEND_DIST / "index.html")

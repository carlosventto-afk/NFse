from fastapi import FastAPI

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

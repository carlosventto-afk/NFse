from fastapi import FastAPI

from app.routers import auth, dashboard, emissoes, usuarios, webhook_stone

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(emissoes.router)
app.include_router(webhook_stone.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

from fastapi import FastAPI

from app.routers import auth, emissoes, usuarios

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(emissoes.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

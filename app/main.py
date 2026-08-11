from fastapi import FastAPI

from app.routers import auth, usuarios

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router)
app.include_router(usuarios.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

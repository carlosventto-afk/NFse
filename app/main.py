from fastapi import FastAPI

app = FastAPI(title="NFS-e Automatizada")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

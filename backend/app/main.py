from fastapi import FastAPI

app = FastAPI(title="PPT Generator")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}

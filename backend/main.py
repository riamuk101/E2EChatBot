from fastapi import FastAPI
from fastapi.responses import JSONResponse
from api import status_ws, scraper 

app = FastAPI(title="TI Skynet Backend")

@app.get("/healthz", include_in_schema=False, tags=["infra"])
def healthz():
    return {"status": "ok"}

@app.get("/", include_in_schema=False)
def root():
    return JSONResponse({"message": "Skynet backend alive", "docs": "/docs"})

app.include_router(status_ws.router)
app.include_router(scraper.router)

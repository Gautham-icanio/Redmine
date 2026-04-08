from fastapi import FastAPI
from app.routes import router

app = FastAPI(title="EVA Equity Partners API", version="1.0.0")
app.include_router(router, prefix="/api/v1")

@app.get("/")
def root():
    return {"project": "EVA Redmine-GitHub Integration", "status": "running"}

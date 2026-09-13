from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routes import hospital_lookup, bill_translator, explainer, agent

app = FastAPI(title="BillClear")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(hospital_lookup.router, prefix="/api/hospital", tags=["hospital"])
app.include_router(bill_translator.router, prefix="/api/bill", tags=["bill"])
app.include_router(explainer.router, prefix="/api/explain", tags=["explain"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}

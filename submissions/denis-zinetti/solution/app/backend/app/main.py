from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import httpx
import joblib
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "dashboard.json"
MODEL_PATH = ROOT / "data" / "classifier.joblib"
FRONTEND_PATH = ROOT / "static"


def load_data() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"ready": False, "message": "Execute prepare_data.py com os CSVs do Kaggle.", "tickets": []}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


app = FastAPI(title="Suporte & Retenção", version="1.0.0")
if FRONTEND_PATH.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_PATH / "assets"), name="assets")


class DraftRequest(BaseModel):
    ticket_id: int
    instruction: str = Field(default="Produza uma resposta empática, objetiva e sem prometer compensação.")


class ClassificationRequest(BaseModel):
    text: str = Field(min_length=5, max_length=10000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data": "ready" if DATA_PATH.exists() else "missing"}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    data = load_data()
    return {key: data.get(key) for key in ("ready", "message", "overview", "insights", "roi", "churn_validation", "model_metrics")}


@app.get("/api/tickets")
def tickets(
    priority: Annotated[str | None, Query()] = None,
    channel: Annotated[str | None, Query()] = None,
    risk: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 150,
) -> list[dict[str, Any]]:
    items = load_data().get("tickets", [])
    def matches(item: dict[str, Any]) -> bool:
        haystack = f"{item.get('subject', '')} {item.get('customer_name', '')} {item.get('ticket_type', '')}".lower()
        return ((not priority or item["priority"] == priority)
                and (not channel or item["channel"] == channel)
                and (not risk or item["risk"]["level"] == risk)
                and (not search or search.lower() in haystack))
    # A fila é um endpoint de triagem, não uma exportação do dataset inteiro.
    # O artefato mantém todos os tickets para busca de detalhe e reprodução,
    # enquanto esta resposta permanece rápida no navegador.
    return [item for item in items if matches(item)][:limit]


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: int) -> dict[str, Any]:
    for ticket in load_data().get("tickets", []):
        if ticket["id"] == ticket_id:
            return ticket
    raise HTTPException(404, "Ticket não encontrado")


@app.post("/api/classify")
def classify(request: ClassificationRequest) -> dict[str, Any]:
    if not MODEL_PATH.exists():
        raise HTTPException(503, "Modelo ainda não foi preparado")
    model = joblib.load(MODEL_PATH)
    probabilities = model.predict_proba([request.text])[0]
    labels = model.named_steps["classifier"].classes_
    order = probabilities.argsort()[::-1][:3]
    confidence = float(probabilities[order[0]])
    return {"category": str(labels[order[0]]), "confidence": round(confidence, 3), "needs_review": confidence < .70, "alternatives": [{"category": str(labels[i]), "confidence": round(float(probabilities[i]), 3)} for i in order]}


@app.post("/api/copilot/draft")
async def draft_reply(request: DraftRequest) -> dict[str, Any]:
    ticket = ticket_detail(request.ticket_id)
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    context = "\n".join(f"- {x['subject']}: {x['resolution']}" for x in ticket.get("similar", []) if x.get("resolution"))
    prompt = f"""Você é um copiloto de suporte. Gere somente um rascunho de resposta ao cliente em português.
Não prometa compensação, prazo ou mudança de cobrança. Seja empático, breve e peça confirmação quando necessário.
Ticket: {ticket['description']}
Tipo: {ticket['ticket_type']}; classificação sugerida: {ticket['classification']['category']}; prioridade: {ticket['priority']}; risco: {ticket['risk']['level']}.
Instrução do agente: {request.instruction}
Casos resolvidos similares:\n{context or 'Nenhum caso semelhante disponível.'}"""
    if not api_key:
        return {"mode": "fallback", "draft": "Copiloto LLM não configurado. Revise o contexto e responda com uma atualização objetiva, confirme o próximo passo e não prometa compensações.", "guardrail": "Rascunho não enviado automaticamente."}
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "temperature": 0.2, "messages": [{"role": "system", "content": "Você é um assistente seguro de suporte."}, {"role": "user", "content": prompt}]},
        )
    response.raise_for_status()
    return {"mode": "llm", "draft": response.json()["choices"][0]["message"]["content"], "guardrail": "Rascunho não enviado automaticamente."}


@app.get("/{path:path}")
def spa(path: str):
    index = FRONTEND_PATH / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(503, "Frontend ainda não foi compilado")

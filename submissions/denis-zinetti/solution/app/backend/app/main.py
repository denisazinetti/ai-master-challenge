from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
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
STATE_PATH = Path(os.getenv("STATE_DIR", str(ROOT / "state"))) / "copilot_drafts.json"

_cached_model = None
_drafts_lock = Lock()


def get_model():
    global _cached_model
    if _cached_model is None:
        if not MODEL_PATH.exists():
            return None
        _cached_model = joblib.load(MODEL_PATH)
    return _cached_model


def load_data() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"ready": False, "message": "Execute prepare_data.py com os CSVs do Kaggle.", "tickets": []}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def load_drafts() -> dict[str, dict[str, Any]]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_draft(ticket_id: int, draft: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _drafts_lock:
        drafts = load_drafts()
        drafts[str(ticket_id)] = draft
        temporary_path = STATE_PATH.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(STATE_PATH)


app = FastAPI(title="Suporte & Retenção", version="1.0.0")
if FRONTEND_PATH.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_PATH / "assets"), name="assets")


class DraftRequest(BaseModel):
    ticket_id: int
    instruction: str = Field(default="Produza uma resposta empática, objetiva e sem prometer compensação.")
    force_regenerate: bool = False


class ClassificationRequest(BaseModel):
    text: str = Field(min_length=5, max_length=10000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data": "ready" if DATA_PATH.exists() else "missing"}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    data = load_data()
    return {key: data.get(key) for key in ("ready", "message", "overview", "insights", "roi", "churn_validation", "model_metrics", "triage_insights")}


def compute_queue(item: dict[str, Any]) -> str:
    is_billing = item.get("ticket_type") == "Billing inquiry"
    is_critical = item.get("priority") == "Critical"
    is_high_risk = item.get("risk", {}).get("level") == "Alto"
    needs_rev = bool(item.get("classification", {}).get("needs_review", False))
    if needs_rev:
        return "Mesa de Triagem (Revisão NLP)"
    if is_high_risk or is_critical:
        return "Mesa Estratégica CS & Retenção"
    if is_billing:
        return "Fila Financeiro & Billing"
    cat = item.get("classification", {}).get("category", "Geral")
    if cat in ("Hardware", "Access", "Storage"):
        return f"Fila N1 · {cat}"
    return f"Fila N2 · {cat}"


@app.get("/api/tickets")
def tickets(
    priority: Annotated[str | None, Query()] = None,
    channel: Annotated[str | None, Query()] = None,
    risk: Annotated[str | None, Query()] = None,
    review: Annotated[str | None, Query()] = None,
    pipeline: Annotated[str | None, Query()] = None,
    queue: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=300)] = 150,
) -> list[dict[str, Any]]:
    items = load_data().get("tickets", [])
    def matches(item: dict[str, Any]) -> bool:
        cls_info = item.get("classification") or {}
        haystack = f"{item.get('subject', '')} {item.get('customer_name', '')} {item.get('ticket_type', '')} {cls_info.get('category', '')}".lower()
        needs_rev = bool(cls_info.get("needs_review", False))
        is_billing = item.get("ticket_type") == "Billing inquiry"
        is_critical = item.get("priority") == "Critical"
        is_high_risk = item.get("risk", {}).get("level") == "Alto"
        is_human_locked = is_billing or is_critical or is_high_risk

        queue_ok = True
        if queue == "triage":
            queue_ok = needs_rev
        elif queue == "copilot":
            queue_ok = (not is_human_locked) and (not needs_rev)
        elif queue == "cs_retention":
            queue_ok = is_high_risk or is_critical
        elif queue == "finance":
            queue_ok = is_billing

        pipeline_ok = True
        if pipeline == "copilot":
            pipeline_ok = (not is_human_locked) and (not needs_rev)
        elif pipeline == "needs_review":
            pipeline_ok = needs_rev
        elif pipeline == "human":
            pipeline_ok = is_human_locked

        review_ok = True
        if review == "needs_review":
            review_ok = needs_rev
        elif review == "confident":
            review_ok = not needs_rev

        return ((not priority or item["priority"] == priority)
                and (not channel or item["channel"] == channel)
                and (not risk or item["risk"]["level"] == risk)
                and queue_ok
                and pipeline_ok
                and review_ok
                and (not search or search.lower() in haystack))

    results = []
    for item in items:
        if matches(item):
            enriched = dict(item)
            enriched["auto_queue"] = compute_queue(item)
            results.append(enriched)
            if len(results) >= limit:
                break
    return results


@app.get("/api/tickets/{ticket_id}")
def ticket_detail(ticket_id: int) -> dict[str, Any]:
    for ticket in load_data().get("tickets", []):
        if ticket["id"] == ticket_id:
            result = dict(ticket)
            saved_draft = load_drafts().get(str(ticket_id))
            if saved_draft:
                result["copilot_draft"] = saved_draft
            return result
    raise HTTPException(404, "Ticket não encontrado")


@app.post("/api/classify")
def classify(request: ClassificationRequest) -> dict[str, Any]:
    model = get_model()
    if model is None:
        raise HTTPException(503, "Modelo ainda não foi preparado")
    probabilities = model.predict_proba([request.text])[0]
    labels = model.named_steps["classifier"].classes_
    order = probabilities.argsort()[::-1][:3]
    confidence = float(probabilities[order[0]])
    return {"category": str(labels[order[0]]), "confidence": round(confidence, 3), "needs_review": confidence < .70, "alternatives": [{"category": str(labels[i]), "confidence": round(float(probabilities[i]), 3)} for i in order]}


@app.get("/api/model-metrics")
def model_metrics() -> dict[str, Any]:
    data = load_data()
    metrics = data.get("model_metrics")
    if not metrics:
        raise HTTPException(503, "Métricas do modelo não disponíveis")
    return metrics


@app.post("/api/copilot/draft")
async def draft_reply(request: DraftRequest) -> dict[str, Any]:
    ticket = ticket_detail(request.ticket_id)
    saved_draft = ticket.get("copilot_draft")
    if saved_draft and not request.force_regenerate:
        return saved_draft

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    context = "\n".join(f"- #{x['id']}: {x['subject']} ({x['pattern']})" for x in ticket.get("similar", []))
    playbook = ticket.get("response_playbook", {}).get("instructions", "Confirme a solicitação, informe o próximo passo e peça confirmação quando necessário.")
    prompt = f"""Você é um copiloto de suporte. Gere somente um rascunho de resposta ao cliente em português.
Não prometa compensação, prazo ou mudança de cobrança. Seja empático, breve e peça confirmação quando necessário.
Ticket: {ticket['description']}
Tipo: {ticket['ticket_type']}; classificação sugerida: {ticket['classification']['category']}; prioridade: {ticket['priority']}; risco: {ticket['risk']['level']}.
Instrução do agente: {request.instruction}
Padrão de resposta: {playbook}
Casos do mesmo padrão de atendimento:\n{context or 'Nenhum caso validado para este padrão.'}"""
    if not api_key:
        result = {"mode": "fallback", "draft": "Copiloto LLM não configurado. Revise o contexto e responda com uma atualização objetiva, confirme o próximo passo e não prometa compensações.", "guardrail": "Rascunho não enviado automaticamente."}
    else:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "temperature": 0.2, "messages": [{"role": "system", "content": "Você é um assistente seguro de suporte."}, {"role": "user", "content": prompt}]},
            )
        response.raise_for_status()
        result = {"mode": "llm", "draft": response.json()["choices"][0]["message"]["content"], "guardrail": "Rascunho não enviado automaticamente."}

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["model"] = model if api_key else None
    save_draft(request.ticket_id, result)
    return result


@app.get("/{path:path}")
def spa(path: str):
    index = FRONTEND_PATH / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(503, "Frontend ainda não foi compilado")

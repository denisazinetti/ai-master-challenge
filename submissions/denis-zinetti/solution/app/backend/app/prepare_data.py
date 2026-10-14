from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from app.scoring import calculate_risk

OUT = Path(__file__).resolve().parent / "data"


def post_response_hours(first_response: object, resolution: object) -> float:
    """Dataset 1 stores timestamps, not raw durations."""
    start, end = pd.to_datetime(first_response, errors="coerce"), pd.to_datetime(resolution, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return 0.0
    delta = (end - start).total_seconds() / 3600
    return round(delta + 24 if delta < 0 else delta, 2)


def train_classifier(path: Path) -> tuple[dict, Pipeline]:
    df = pd.read_csv(path).dropna(subset=["Document", "Topic_group"])
    x_train, x_test, y_train, y_test = train_test_split(df.Document.astype(str), df.Topic_group.astype(str), test_size=.2, random_state=42, stratify=df.Topic_group)
    # SGD with log-loss is multinomial logistic regression optimized for a
    # reproducible build on a laptop/VPS, rather than a notebook-only model.
    model = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=60000, sublinear_tf=True)), ("classifier", SGDClassifier(loss="log_loss", max_iter=500, tol=1e-3, class_weight="balanced", random_state=42))])
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    report = classification_report(y_test, predictions, output_dict=True, zero_division=0)
    labels = sorted(df.Topic_group.unique())
    metrics = {"algorithm": "TF-IDF (1–2 grams) + regressão logística (SGD)", "train_rows": int(len(x_train)), "test_rows": int(len(x_test)), "accuracy": round(float(accuracy_score(y_test, predictions)), 4), "macro_f1": round(float(f1_score(y_test, predictions, average="macro")), 4), "by_category": {label: {"precision": round(report[label]["precision"], 3), "recall": round(report[label]["recall"], 3), "f1": round(report[label]["f1-score"], 3)} for label in labels}, "labels": labels, "confusion_matrix": confusion_matrix(y_test, predictions, labels=labels).tolist(), "note": "O modelo foi validado no Dataset 2. As sugestões nos tickets do Dataset 1 são experimentais e exigem revisão humana."}
    return metrics, model


def churn_validation(churn_dir: Path) -> dict:
    accounts = pd.read_csv(churn_dir / "ravenstack_accounts.csv")
    subscriptions = pd.read_csv(churn_dir / "ravenstack_subscriptions.csv")
    tickets = pd.read_csv(churn_dir / "ravenstack_support_tickets.csv")
    account_ticket = tickets.groupby("account_id").agg(ticket_count=("ticket_id", "count"), avg_resolution=("resolution_time_hours", "mean"), avg_first_response=("first_response_time_minutes", "mean"), avg_satisfaction=("satisfaction_score", "mean"), escalation_rate=("escalation_flag", "mean")).reset_index()
    revenue = subscriptions.groupby("account_id").agg(arr=("arr_amount", "sum")).reset_index()
    merged = accounts.merge(account_ticket, on="account_id", how="left").merge(revenue, on="account_id", how="left").fillna({"ticket_count": 0, "arr": 0})
    grouped = merged.groupby("churn_flag").agg(accounts=("account_id", "count"), tickets_per_account=("ticket_count", "mean"), resolution_hours=("avg_resolution", "mean"), first_response_minutes=("avg_first_response", "mean"), satisfaction=("avg_satisfaction", "mean"), escalation_rate=("escalation_rate", "mean"), arr=("arr", "sum")).round(2).reset_index()
    return {"method": "Join por account_id entre contas, chamados e assinaturas do Challenge 001.", "comparison": grouped.to_dict(orient="records"), "limitation": "Associações entre suporte e churn neste dataset sintético não demonstram causalidade e não são transferidas para os tickets do Challenge 002."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--classifier", type=Path, required=True)
    parser.add_argument("--churn-dir", type=Path, required=True)
    args = parser.parse_args()
    support = pd.read_csv(args.support)
    # The raw file has response/resolution timestamps but no ticket-opened time.
    # Never fabricate time-to-first-response from them.
    support["first_response_hours"] = np.nan
    support["resolution_hours"] = [post_response_hours(first, resolution) for first, resolution in zip(support["First Response Time"], support["Time to Resolution"])]
    support["satisfaction"] = pd.to_numeric(support["Customer Satisfaction Rating"], errors="coerce")
    support["customer_ticket_count"] = support.groupby("Customer Email")["Ticket ID"].transform("count")
    response_p75, resolution_p75 = 0.0, support.resolution_hours[support.resolution_hours > 0].quantile(.75)
    rows = []
    for _, row in support.iterrows():
        item = {"id": int(row["Ticket ID"]), "customer_name": row["Customer Name"], "customer_email": row["Customer Email"], "subject": row["Ticket Subject"], "description": row["Ticket Description"], "resolution": row["Resolution"] if pd.notna(row["Resolution"]) else "", "ticket_type": row["Ticket Type"], "status": row["Ticket Status"], "priority": row["Ticket Priority"], "channel": row["Ticket Channel"], "first_response_hours": round(float(row.first_response_hours), 2), "resolution_hours": round(float(row.resolution_hours), 2), "satisfaction": None if pd.isna(row.satisfaction) else float(row.satisfaction), "customer_ticket_count": int(row.customer_ticket_count)}
        item["risk"] = calculate_risk(item, response_p75, resolution_p75).__dict__
        rows.append(item)
    model_metrics, classifier = train_classifier(args.classifier)
    probabilities = classifier.predict_proba(support["Ticket Description"].fillna("").astype(str))
    classes = classifier.named_steps["classifier"].classes_
    for item, probability in zip(rows, probabilities):
        best = int(np.argmax(probability))
        item["classification"] = {"category": str(classes[best]), "confidence": round(float(probability[best]), 3), "needs_review": bool(probability[best] < .70)}
    rows.sort(key=lambda x: (-x["risk"]["score"], -x["resolution_hours"]))
    closed_by_type: dict[str, list[dict]] = {}
    for candidate in rows:
        if candidate["status"] == "Closed" and candidate["resolution"]:
            closed_by_type.setdefault(candidate["ticket_type"], []).append(candidate)
    # Retrieval is precomputed only for the visible high-priority workbench. This
    # keeps the demo fast without pretending that every historical ticket needs AI.
    retrieval_ids = {item["id"] for item in rows[:500]}
    for item in rows:
        if item["id"] not in retrieval_ids:
            item["similar"] = []
            continue
        needle = set(str(item["description"]).lower().split())
        candidates = closed_by_type.get(item["ticket_type"], [])[:1000]
        scored = sorted(((len(needle & set(str(other["description"]).lower().split())), other) for other in candidates if other["id"] != item["id"]), key=lambda x: x[0], reverse=True)
        item["similar"] = [{"id": other["id"], "subject": other["subject"], "resolution": other["resolution"], "similarity": score} for score, other in scored[:3] if score > 0]
    risk_counts = pd.Series([x["risk"]["level"] for x in rows]).value_counts().to_dict()
    priority_group = support.groupby(["Ticket Channel", "Ticket Priority"], dropna=False).agg(tickets=("Ticket ID", "count"), avg_resolution_hours=("resolution_hours", "mean"), csat=("satisfaction", "mean")).round(2).reset_index().sort_values("avg_resolution_hours", ascending=False).head(8)
    avg_resolution = float(support.resolution_hours.mean())
    above_p75 = int((support.resolution_hours > resolution_p75).sum())
    eligible = int(((support["Ticket Type"] != "Billing inquiry") & (support["Ticket Priority"].isin(["Low", "Medium"]))).sum())
    roi = {"assumptions": {"eligible_tickets_month": round(eligible / 12), "automation_assist_rate": 0.35, "minutes_saved_per_ticket": 6, "cost_per_hour_usd": 18, "retention_intervention_rate": 0.03}, "scenarios": [{"name": "Conservador", "automation_rate": .2, "minutes_saved": 3, "retention_rate": .01}, {"name": "Base", "automation_rate": .35, "minutes_saved": 6, "retention_rate": .03}, {"name": "Ambicioso", "automation_rate": .5, "minutes_saved": 9, "retention_rate": .05}]}
    for scenario in roi["scenarios"]:
        monthly_hours = roi["assumptions"]["eligible_tickets_month"] * scenario["automation_rate"] * scenario["minutes_saved"] / 60
        scenario["monthly_hours_released"] = round(monthly_hours, 1)
        scenario["annual_capacity_value_usd"] = round(monthly_hours * 12 * roi["assumptions"]["cost_per_hour_usd"])
    overview = {"tickets": len(rows), "avg_first_response_hours": None, "avg_resolution_hours": round(avg_resolution, 2), "avg_csat": round(float(support.satisfaction.mean()), 2), "high_risk": int(risk_counts.get("Alto", 0)), "risk_counts": risk_counts, "above_resolution_p75": above_p75, "data_quality_note": "O dataset fornece timestamps de resposta, mas não a abertura do ticket; por isso, o tempo até primeira resposta não é estimado."}
    insights = [{"title": "Fila lenta", "detail": f"{above_p75:,} tickets superam {resolution_p75:.1f}h entre primeira resposta e resolução (P75).", "action": "Priorizar roteamento e resposta assistida nessa cauda."}, {"title": "Automação com limite", "detail": f"{eligible:,} tickets de baixa/média prioridade não financeiros são elegíveis para assistência.", "action": "Manter billing, críticos e baixa confiança sob revisão humana."}, {"title": "Retenção antes do cancelamento", "detail": f"{risk_counts.get('Alto', 0):,} tickets concentram sinais operacionais de risco alto.", "action": "Acionar playbook de CS com contexto do chamado."}]
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(classifier, OUT / "classifier.joblib")
    output = {"ready": True, "overview": overview, "tickets": rows, "priority_breakdown": priority_group.to_dict(orient="records"), "insights": insights, "roi": roi, "churn_validation": churn_validation(args.churn_dir), "model_metrics": model_metrics}
    (OUT / "dashboard.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {OUT / 'dashboard.json'} with {len(rows)} tickets")


if __name__ == "__main__":
    main()

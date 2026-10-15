from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from scipy import stats
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.base import clone
from sklearn.pipeline import Pipeline

from app import diagnostics
from app.scoring import calculate_risk

OUT = Path(__file__).resolve().parent / "data"


def normalized_subject(subject: object) -> str:
    """Use the stable issue theme, not noisy free-text resolutions, for grouping."""
    return " ".join(re.findall(r"[a-z0-9]+", str(subject).lower()))


def response_playbook(item: dict) -> dict[str, str]:
    category = item["classification"]["category"]
    ticket_type = item["ticket_type"]
    if ticket_type == "Technical issue":
        instructions = "Confirme o sintoma e o impacto, informe a próxima verificação técnica e peça confirmação após a ação."
    elif ticket_type in {"Product inquiry", "Cancellation request"}:
        instructions = "Confirme a necessidade, apresente a orientação aplicável e peça a informação mínima necessária para concluir o atendimento."
    else:
        instructions = "Reconheça a solicitação, confirme os dados relevantes e informe o próximo passo sem prometer compensação, prazo ou mudança de cobrança."
    return {"title": f"Padrão de resposta · {category}", "instructions": instructions}


def train_classifier(path: Path) -> tuple[dict, Pipeline]:
    df = pd.read_csv(path).dropna(subset=["Document", "Topic_group"])
    x_train, x_test, y_train, y_test = train_test_split(df.Document.astype(str), df.Topic_group.astype(str), test_size=.2, random_state=42, stratify=df.Topic_group)
    # SGD with log-loss is multinomial logistic regression optimized for a
    # reproducible build on a laptop/VPS, rather than a notebook-only model.
    model = Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=60000, sublinear_tf=True)), ("classifier", SGDClassifier(loss="log_loss", max_iter=500, tol=1e-3, class_weight="balanced", random_state=42))])
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    test_probabilities = model.predict_proba(x_test)
    report = classification_report(y_test, predictions, output_dict=True, zero_division=0)
    labels = sorted(df.Topic_group.unique())
    metrics = {"algorithm": "TF-IDF (1–2 grams) + regressão logística (SGD)", "train_rows": int(len(x_train)), "test_rows": int(len(x_test)), "accuracy": round(float(accuracy_score(y_test, predictions)), 4), "macro_f1": round(float(f1_score(y_test, predictions, average="macro")), 4), "by_category": {label: {"precision": round(report[label]["precision"], 3), "recall": round(report[label]["recall"], 3), "f1": round(report[label]["f1-score"], 3)} for label in labels}, "labels": labels, "confusion_matrix": confusion_matrix(y_test, predictions, labels=labels).tolist(), "threshold_curve": diagnostics.confidence_threshold_curve(y_test, test_probabilities, model.named_steps["classifier"].classes_), "note": "O modelo foi validado no Dataset 2. As sugestões nos tickets do Dataset 1 são experimentais e exigem revisão humana."}
    # Honest numbers come from the hold-out split above; the model that serves requests is refit on every labelled row.
    production = clone(model).fit(df.Document.astype(str), df.Topic_group.astype(str))
    metrics["production_fit_rows"] = int(len(df))
    return metrics, production


def churn_validation(churn_dir: Path) -> dict:
    accounts = pd.read_csv(churn_dir / "ravenstack_accounts.csv")
    subscriptions = pd.read_csv(churn_dir / "ravenstack_subscriptions.csv")
    tickets = pd.read_csv(churn_dir / "ravenstack_support_tickets.csv")
    account_ticket = tickets.groupby("account_id").agg(ticket_count=("ticket_id", "count"), avg_resolution=("resolution_time_hours", "mean"), avg_first_response=("first_response_time_minutes", "mean"), avg_satisfaction=("satisfaction_score", "mean"), escalation_rate=("escalation_flag", "mean")).reset_index()
    revenue = subscriptions.groupby("account_id").agg(arr=("arr_amount", "sum")).reset_index()
    usage = pd.read_csv(churn_dir / "ravenstack_feature_usage.csv").merge(subscriptions[["subscription_id", "account_id"]], on="subscription_id", how="left")
    account_usage = usage.groupby("account_id").agg(usage_events=("usage_id", "count"), usage_errors=("error_count", "sum")).reset_index()
    merged = accounts.merge(account_ticket, on="account_id", how="left").merge(revenue, on="account_id", how="left").merge(account_usage, on="account_id", how="left").fillna({"ticket_count": 0, "arr": 0, "usage_events": 0, "usage_errors": 0})
    grouped = merged.groupby("churn_flag").agg(accounts=("account_id", "count"), tickets_per_account=("ticket_count", "mean"), resolution_hours=("avg_resolution", "mean"), first_response_minutes=("avg_first_response", "mean"), satisfaction=("avg_satisfaction", "mean"), escalation_rate=("escalation_rate", "mean"), arr=("arr", "sum")).round(2).reset_index()
    tests = []
    for label, column in (("Tickets por conta", "ticket_count"), ("Resolução média (h)", "avg_resolution"), ("1ª resposta média (min)", "avg_first_response"), ("CSAT médio", "avg_satisfaction"), ("Taxa de escalonamento", "escalation_rate"), ("Eventos de uso do produto", "usage_events"), ("Erros de uso do produto", "usage_errors")):
        churned, retained = merged.loc[merged.churn_flag == True, column].dropna(), merged.loc[merged.churn_flag == False, column].dropna()
        tests.append({"metric": label, "churned": round(float(churned.mean()), 2), "retained": round(float(retained.mean()), 2), "p_value": round(float(stats.mannwhitneyu(churned, retained).pvalue), 4)})
    adjusted = diagnostics._bh_adjust([t["p_value"] for t in tests])
    for test, p_adj in zip(tests, adjusted):
        test["p_adjusted"] = round(p_adj, 4)
        test["significant"] = bool(p_adj < diagnostics.ALPHA)
    verdict = ("Churnadas e retidas têm perfil de suporte estatisticamente indistinguível (Mann–Whitney, FDR 5%): a hipótese de que fricção de suporte antecipa churn NÃO é sustentada por este dataset."
               if not any(t["significant"] for t in tests) else "Há diferenças significativas entre churnadas e retidas: " + ", ".join(t["metric"] for t in tests if t["significant"]) + ".")
    # Declared churn reasons: how much churn is attributed to support by the customers themselves?
    events = pd.read_csv(churn_dir / "ravenstack_churn_events.csv")
    reasons = events.reason_code.value_counts()
    churned = merged[merged.churn_flag == True]
    support_accounts = set(events.loc[events.reason_code == "support", "account_id"]) & set(churned.account_id)
    support_arr = float(churned.loc[churned.account_id.isin(support_accounts), "arr"].sum())
    others = churned[~churned.account_id.isin(support_accounts)]
    reason_tests = []
    for label, column in (("Resolução média (h)", "avg_resolution"), ("1ª resposta média (min)", "avg_first_response"), ("CSAT médio", "avg_satisfaction"), ("Tickets por conta", "ticket_count")):
        a, b = churned.loc[churned.account_id.isin(support_accounts), column].dropna(), others[column].dropna()
        reason_tests.append({"metric": label, "support_reason": round(float(a.mean()), 2), "other_reasons": round(float(b.mean()), 2), "p_value": round(float(stats.mannwhitneyu(a, b).pvalue), 4)})
    churn_reasons = {"events": int(len(events)), "by_reason": [{"reason": str(k), "events": int(v), "share": round(float(v / len(events)), 3)} for k, v in reasons.items()],
                     "support_attributed_accounts": len(support_accounts), "churned_accounts": int(len(churned)), "support_attributed_arr": round(support_arr), "churned_arr": round(float(churned.arr.sum())),
                     "support_arr_share": round(support_arr / max(float(churned.arr.sum()), 1), 3), "tests_vs_other_reasons": reason_tests,
                     "note": "Motivo declarado pelo cliente (reason_code). Mede o teto de exposição a suporte, não o ganho de uma intervenção."}
    return {"method": "Join por account_id entre contas, chamados, assinaturas, uso de funcionalidades e eventos de churn do Challenge 001.", "comparison": grouped.to_dict(orient="records"), "tests": tests, "verdict": verdict, "churn_reasons": churn_reasons, "limitation": "Associações entre suporte e churn neste dataset sintético não demonstram causalidade e não são transferidas para os tickets do Challenge 002."}


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
    # Pairs where resolution precedes first response are impossible durations: they become NaN, never "repaired".
    support["resolution_hours"] = [diagnostics.duration_hours(first, resolution) for first, resolution in zip(support["First Response Time"], support["Time to Resolution"])]
    support["resolution_hours"] = pd.to_numeric(support["resolution_hours"], errors="coerce")
    support["satisfaction"] = pd.to_numeric(support["Customer Satisfaction Rating"], errors="coerce")
    support["customer_ticket_count"] = support.groupby("Customer Email")["Ticket ID"].transform("count")
    resolution_p75 = support.resolution_hours.dropna().quantile(.75)
    rows = []
    for _, row in support.iterrows():
        item = {"id": int(row["Ticket ID"]), "customer_name": row["Customer Name"], "customer_email": row["Customer Email"], "subject": row["Ticket Subject"], "description": row["Ticket Description"], "resolution": row["Resolution"] if pd.notna(row["Resolution"]) else "", "ticket_type": row["Ticket Type"], "status": row["Ticket Status"], "priority": row["Ticket Priority"], "channel": row["Ticket Channel"], "first_response_hours": None, "resolution_hours": None if pd.isna(row.resolution_hours) else round(float(row.resolution_hours), 2), "satisfaction": None if pd.isna(row.satisfaction) else float(row.satisfaction), "customer_ticket_count": int(row.customer_ticket_count)}
        item["risk"] = calculate_risk(item, resolution_p75).__dict__
        rows.append(item)
    model_metrics, classifier = train_classifier(args.classifier)
    probabilities = classifier.predict_proba(support["Ticket Description"].fillna("").astype(str))
    classes = classifier.named_steps["classifier"].classes_
    for item, probability in zip(rows, probabilities):
        best = int(np.argmax(probability))
        item["classification"] = {"category": str(classes[best]), "confidence": round(float(probability[best]), 3), "needs_review": bool(probability[best] < diagnostics.REVIEW_THRESHOLD)}
    rows.sort(key=lambda x: (-x["risk"]["score"], -(x["resolution_hours"] or 0)))
    # Lexical retrieval over Dataset 1 text performs at chance level (see retrieval_eval), so no "similar cases" are attached to its tickets.
    for item in rows:
        item["similar"] = []
        item["response_playbook"] = response_playbook(item)

    open_items = [item for item in rows if item["status"] != "Closed"]
    bottleneck_groups: dict[tuple[str, str], list[dict]] = {}
    for item in open_items:
        bottleneck_groups.setdefault((item["ticket_type"], item["subject"]), []).append(item)
    bottlenecks = []
    for (ticket_type, subject), grouped_items in bottleneck_groups.items():
        high_risk = sum(item["risk"]["level"] == "Alto" for item in grouped_items)
        critical = sum(item["priority"] == "Critical" for item in grouped_items)
        count = len(grouped_items)
        if critical or high_risk:
            action = "Priorizar na fila e definir responsável."
        elif count >= 3:
            action = "Criar macro e revisar causa raiz."
        else:
            action = "Monitorar recorrência antes de padronizar."
        bottlenecks.append({
            "subject": subject,
            "ticket_type": ticket_type,
            "open_tickets": count,
            "high_risk": high_risk,
            "critical": critical,
            "avg_resolution_hours": (round(float(np.mean(valid)), 1) if (valid := [item["resolution_hours"] for item in grouped_items if item["resolution_hours"] is not None]) else None),
            "action": action,
        })
    bottlenecks.sort(key=lambda item: (-item["critical"], -item["high_risk"], -item["open_tickets"], -(item["avg_resolution_hours"] or 0)))
    risk_distribution = [{"name": level, "value": sum(item["risk"]["level"] == level for item in open_items)} for level in ("Alto", "Médio", "Baixo")]
    triage_insights = {
        "scope": "Tickets ainda não encerrados",
        "open_tickets": len(open_items),
        "high_risk": sum(item["risk"]["level"] == "Alto" for item in open_items),
        "critical": sum(item["priority"] == "Critical" for item in open_items),
        "recurring_themes": sum(item["open_tickets"] >= 3 for item in bottlenecks),
        "risk_distribution": risk_distribution,
        "bottlenecks": bottlenecks[:5],
        "source_note": "Leitura operacional do dataset de demonstração; valide os temas com dados de produção antes de alterar processos ou capacidade.",
        "limitation": "O dataset não informa a abertura do ticket; por isso não há tendência temporal ou SLA de primeira resposta nesta visão.",
    }
    risk_counts = pd.Series([x["risk"]["level"] for x in rows]).value_counts().to_dict()
    backlog = diagnostics.backlog_summary(support)
    priority_group = support.groupby(["Ticket Channel", "Ticket Priority"], dropna=False).agg(tickets=("Ticket ID", "count"), avg_resolution_hours=("resolution_hours", "mean"), csat=("satisfaction", "mean")).round(2).reset_index().sort_values("avg_resolution_hours", ascending=False).head(8)
    avg_resolution = float(support.resolution_hours.mean())
    above_p75 = int((support.resolution_hours > resolution_p75).sum())
    valid_resolutions = int(support.resolution_hours.notna().sum())
    eligible = int(((support["Ticket Type"] != "Billing inquiry") & (support["Ticket Priority"].isin(["Low", "Medium"]))).sum())
    roi = {"assumptions": {"eligible_tickets_month": round(eligible / 12), "automation_assist_rate": 0.35, "minutes_saved_per_ticket": 6, "cost_per_hour_usd": 18, "retention_intervention_rate": 0.03}, "scenarios": [{"name": "Conservador", "automation_rate": .2, "minutes_saved": 3, "retention_rate": .01}, {"name": "Base", "automation_rate": .35, "minutes_saved": 6, "retention_rate": .03}, {"name": "Ambicioso", "automation_rate": .5, "minutes_saved": 9, "retention_rate": .05}]}
    # The file has 8.5k tickets while the briefing describes ~30k/year: report both volumes instead of picking the flattering one.
    brief_annual_tickets = 30000
    roi["volumes"] = {"dataset_tickets": len(rows), "brief_tickets_per_year": brief_annual_tickets, "eligible_share": round(eligible / len(rows), 3)}
    roi["assumptions"]["eligible_tickets_month_brief"] = round(brief_annual_tickets * eligible / len(rows) / 12)
    for scenario in roi["scenarios"]:
        for suffix, monthly_tickets in (("", roi["assumptions"]["eligible_tickets_month"]), ("_brief", roi["assumptions"]["eligible_tickets_month_brief"])):
            monthly_hours = monthly_tickets * scenario["automation_rate"] * scenario["minutes_saved"] / 60
            scenario["monthly_hours_released" + suffix] = round(monthly_hours, 1)
            scenario["annual_capacity_value_usd" + suffix] = round(monthly_hours * 12 * roi["assumptions"]["cost_per_hour_usd"])
    overview = {"tickets": len(rows), "avg_first_response_hours": None, "avg_resolution_hours": round(avg_resolution, 2), "valid_resolution_pairs": valid_resolutions, "avg_csat": round(float(support.satisfaction.mean()), 2), "high_risk": int(risk_counts.get("Alto", 0)), "risk_counts": risk_counts, "above_resolution_p75": above_p75, "data_quality_note": "O dataset fornece timestamps de resposta, mas não a abertura do ticket; por isso, o tempo até primeira resposta não é estimado. Pares com resolução anterior à primeira resposta foram descartados."}
    insights = [{"title": "Fila que não anda", "detail": f"{backlog['not_closed']:,} de {len(rows):,} tickets ({backlog['share']:.0%}) não estão encerrados e a taxa é praticamente igual em Critical e Low (p={backlog['priority_chi2_p']:.2f}).", "action": "A prioridade declarada não muda o que é atendido: priorize pelo índice de risco."}, {"title": "Automação com limite", "detail": f"{eligible:,} tickets de baixa/média prioridade não financeiros são elegíveis para assistência.", "action": "Manter billing, críticos e baixa confiança sob revisão humana."}, {"title": "Retenção antes do cancelamento", "detail": f"{risk_counts.get('Alto', 0):,} tickets concentram sinais operacionais de risco alto.", "action": "Acionar playbook de CS com contexto do chamado."}]
    reference = pd.read_csv(args.classifier).dropna(subset=["Document", "Topic_group"])
    train_ref = reference.sample(frac=.8, random_state=42)
    held_out = reference.drop(train_ref.index).sample(1500, random_state=7)
    eval_index = diagnostics.SimilarCaseIndex(train_ref.Document, train_ref.Topic_group)
    found = eval_index.search(held_out.Document.tolist(), k=3)
    hits = sum(m["label"] == label for matches, label in zip(found, held_out.Topic_group) for m in matches)
    retrieved = sum(len(matches) for matches in found)
    support_closed = support[support["Ticket Status"] == "Closed"]
    retrieval_eval = {
        "dataset2": {"k": 3, "queries": len(held_out), "precision_at_k": round(hits / max(retrieved, 1), 3), "chance": round(float((reference.Topic_group.value_counts(normalize=True) ** 2).sum()), 3), "method": "TF-IDF cosine; índice com 80% dos tickets, consultas em tickets não vistos."},
        "dataset1": {**diagnostics.SimilarCaseIndex(support_closed["Ticket Description"], support_closed["Ticket Subject"]).leave_one_out(), "target": "mesmo Ticket Subject"},
        "conclusion": "A recuperação de casos similares funciona no texto do Dataset 2 e fica no nível do acaso no Dataset 1; por isso ela é exposta no classificador (Dataset 2) e não nos tickets do Dataset 1.",
    }
    auto_coverage = next(row["coverage"] for row in model_metrics["threshold_curve"] if row["threshold"] == diagnostics.REVIEW_THRESHOLD)
    waste = diagnostics.waste_estimate(support, auto_coverage)
    OUT.mkdir(parents=True, exist_ok=True)
    joblib.dump(diagnostics.SimilarCaseIndex(reference.Document, reference.Topic_group), OUT / "similar_cases.joblib", compress=3)
    joblib.dump(classifier, OUT / "classifier.joblib")
    output = {"ready": True, "overview": overview, "tickets": rows, "priority_breakdown": priority_group.to_dict(orient="records"), "insights": insights, "roi": roi, "churn_validation": churn_validation(args.churn_dir), "model_metrics": model_metrics, "triage_insights": triage_insights, "data_audit": diagnostics.data_audit(support), "csat_drivers": diagnostics.csat_drivers(support), "backlog": backlog, "channel_priority_matrix": diagnostics.channel_priority_matrix(support), "text_signal_check": diagnostics.text_signal_check(support), "retrieval_eval": retrieval_eval, "waste": waste, "combination_ranking": diagnostics.combination_ranking(support)}
    (OUT / "dashboard.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {OUT / 'dashboard.json'} with {len(rows)} tickets")


if __name__ == "__main__":
    main()

"""Statistical diagnostics for the support dataset.

Everything here is computed at build time from the raw CSVs. The goal is to
state what the data can and cannot support before any automation is proposed.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

ALPHA = 0.05
# Below this classifier confidence a ticket goes to human triage. 0.5 keeps ~97% accuracy on auto-routed
# tickets while covering ~55% of volume (see confidence_threshold_curve); 0.7 would cover only ~25%.
REVIEW_THRESHOLD = 0.5


def duration_hours(first_response: object, resolution: object) -> float | None:
    """Hours between the two timestamps, or None when the pair is not a valid duration.

    The raw file stores timestamps, not durations, and no ticket-opened time.
    When "resolution" precedes "first response" the pair is impossible, so it is
    discarded instead of being "repaired" (e.g. by adding 24h).
    """
    start, end = pd.to_datetime(first_response, errors="coerce"), pd.to_datetime(resolution, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return None
    delta = (end - start).total_seconds() / 3600
    return round(delta, 2) if delta >= 0 else None


def _bh_adjust(p_values: list[float]) -> list[float]:
    """Benjamini–Hochberg adjusted p-values (false-discovery-rate control)."""
    n = len(p_values)
    order = np.argsort(p_values)
    adjusted = np.empty(n)
    running = 1.0
    for rank, idx in reversed(list(enumerate(order, start=1))):
        running = min(running, p_values[idx] * n / rank)
        adjusted[idx] = running
    return adjusted.tolist()


def data_audit(support: pd.DataFrame) -> dict[str, Any]:
    first = pd.to_datetime(support["First Response Time"], errors="coerce")
    resolved = pd.to_datetime(support["Time to Resolution"], errors="coerce")
    both = first.notna() & resolved.notna()
    delta = (resolved - first)[both].dt.total_seconds() / 3600
    per_customer = support.groupby("Customer Email").size()
    closed = support["Ticket Status"] == "Closed"
    description = support["Ticket Description"].fillna("")
    return {
        "tickets": int(len(support)),
        "closed": int(closed.sum()),
        "closed_share": round(float(closed.mean()), 3),
        "csat_coverage_closed": round(float(support.loc[closed, "Customer Satisfaction Rating"].notna().mean()), 3),
        "csat_on_non_closed": int(support.loc[~closed, "Customer Satisfaction Rating"].notna().sum()),
        "timestamp_pairs": int(both.sum()),
        "resolution_before_first_response": int((delta < 0).sum()),
        "resolution_before_first_response_share": round(float((delta < 0).mean()), 3),
        "max_gap_hours": round(float(delta.abs().max()), 1),
        "single_ticket_customers_share": round(float((per_customer == 1).mean()), 3),
        "unfilled_template_placeholders": int(description.str.contains(r"\{[a-z_]+\}", regex=True).sum()),
        "findings": [
            "O arquivo traz timestamps de primeira resposta e resolução, mas não a abertura do ticket: não existe SLA de primeira resposta.",
            "Em cerca de metade dos pares, a resolução é anterior à primeira resposta. Esses pares são descartados, não ‘corrigidos’.",
            "CSAT existe apenas em tickets encerrados; o restante do funil não tem nota.",
            "Quase todos os clientes têm um único ticket: recorrência não é um sinal utilizável neste dataset.",
        ],
    }


def _group_summary(df: pd.DataFrame, column: str, min_n: int = 30) -> list[dict[str, Any]]:
    rows = []
    for value, group in df.groupby(column, observed=True):
        n = len(group)
        if n < min_n:
            continue
        mean = float(group["csat"].mean())
        ci = 1.96 * float(group["csat"].std(ddof=1)) / np.sqrt(n)
        rows.append({"segment": str(value), "n": int(n), "csat": round(mean, 2), "ci95": round(ci, 2)})
    return sorted(rows, key=lambda r: r["csat"])


def csat_drivers(support: pd.DataFrame) -> dict[str, Any]:
    """Which variables explain CSAT? Kruskal–Wallis per variable, FDR-corrected, plus effect size."""
    closed = support[support["Ticket Status"] == "Closed"].copy()
    closed["csat"] = pd.to_numeric(closed["Customer Satisfaction Rating"], errors="coerce")
    closed = closed.dropna(subset=["csat"])
    closed["resolution_hours"] = [duration_hours(a, b) for a, b in zip(closed["First Response Time"], closed["Time to Resolution"])]
    closed["age_band"] = pd.cut(closed["Customer Age"], [0, 25, 35, 45, 55, 120], labels=["≤25", "26–35", "36–45", "46–55", "56+"])
    valid = closed["resolution_hours"].notna()
    closed["resolution_band"] = pd.cut(closed["resolution_hours"], [-0.01, 4, 8, 12, 24], labels=["≤4h", "4–8h", "8–12h", "12–24h"])

    variables = [
        ("Canal", "Ticket Channel"), ("Prioridade", "Ticket Priority"), ("Tipo de ticket", "Ticket Type"),
        ("Assunto", "Ticket Subject"), ("Produto", "Product Purchased"), ("Gênero", "Customer Gender"),
        ("Faixa etária", "age_band"), ("Tempo pós-1ª resposta", "resolution_band"),
    ]
    results, p_values = [], []
    for label, column in variables:
        sample = closed[valid] if column == "resolution_band" else closed
        groups = [g["csat"].to_numpy() for _, g in sample.groupby(column, observed=True) if len(g) >= 5]
        h, p = stats.kruskal(*groups)
        n = sum(len(g) for g in groups)
        eta_sq = max(0.0, (h - len(groups) + 1) / (n - len(groups)))  # Kruskal–Wallis epsilon²/eta² approximation
        results.append({"variable": label, "n": int(n), "levels": len(groups), "p_value": float(p), "effect_size": round(float(eta_sq), 4),
                        "segments": _group_summary(sample, column)})
        p_values.append(float(p))
    for item, adjusted in zip(results, _bh_adjust(p_values)):
        item["p_adjusted"] = round(adjusted, 4)
        item["p_value"] = round(item["p_value"], 4)
        item["significant"] = bool(adjusted < ALPHA)
    results.sort(key=lambda r: r["p_adjusted"])

    rho, rho_p = stats.spearmanr(closed.loc[valid, "resolution_hours"], closed.loc[valid, "csat"])
    significant = [r["variable"] for r in results if r["significant"]]
    dist = closed["csat"].value_counts(normalize=True).sort_index()
    return {
        "n": int(len(closed)),
        "mean_csat": round(float(closed["csat"].mean()), 2),
        "distribution": [{"rating": int(k), "share": round(float(v), 3)} for k, v in dist.items()],
        "variables": results,
        "resolution_spearman": {"rho": round(float(rho), 3), "p_value": round(float(rho_p), 4), "n": int(valid.sum())},
        "significant_variables": significant,
        "alpha": ALPHA,
        "conclusion": (
            f"Nenhuma das {len(results)} variáveis testadas explica o CSAT após correção de múltiplas comparações (FDR 5%)."
            if not significant
            else f"Variáveis com efeito detectável após correção FDR 5%: {', '.join(significant)}."
        ),
        "method": "Kruskal–Wallis por variável (tickets encerrados com nota), p-valor ajustado por Benjamini–Hochberg; tamanho de efeito ε²; Spearman para tempo × CSAT.",
    }


def channel_priority_matrix(support: pd.DataFrame) -> list[dict[str, Any]]:
    frame = support.copy()
    frame["resolution_hours"] = [duration_hours(a, b) for a, b in zip(frame["First Response Time"], frame["Time to Resolution"])]
    frame["csat"] = pd.to_numeric(frame["Customer Satisfaction Rating"], errors="coerce")
    frame["not_closed"] = frame["Ticket Status"] != "Closed"
    grouped = frame.groupby(["Ticket Channel", "Ticket Priority"]).agg(
        tickets=("Ticket ID", "count"), backlog=("not_closed", "mean"), resolution_hours=("resolution_hours", "mean"),
        csat=("csat", "mean"), valid_pairs=("resolution_hours", "count"),
    ).round(3).reset_index()
    return [{"channel": r["Ticket Channel"], "priority": r["Ticket Priority"], "tickets": int(r["tickets"]), "backlog_share": float(r["backlog"]),
             "resolution_hours": None if pd.isna(r["resolution_hours"]) else float(r["resolution_hours"]),
             "csat": None if pd.isna(r["csat"]) else float(r["csat"]), "valid_pairs": int(r["valid_pairs"])} for _, r in grouped.iterrows()]


def backlog_summary(support: pd.DataFrame) -> dict[str, Any]:
    """Reliable bottleneck signal: unresolved share by priority/type (status is clean in this dataset)."""
    not_closed = support["Ticket Status"] != "Closed"
    by_priority = support.assign(nc=not_closed).groupby("Ticket Priority")["nc"].agg(["sum", "count"])
    by_type = support.assign(nc=not_closed).groupby("Ticket Type")["nc"].agg(["sum", "count"])
    chi2_p = float(stats.chi2_contingency(pd.crosstab(support["Ticket Priority"], not_closed))[1])
    pack = lambda frame: [{"name": str(k), "not_closed": int(r["sum"]), "tickets": int(r["count"]), "share": round(float(r["sum"] / r["count"]), 3)} for k, r in frame.iterrows()]
    return {"not_closed": int(not_closed.sum()), "share": round(float(not_closed.mean()), 3),
            "pending_customer": int((support["Ticket Status"] == "Pending Customer Response").sum()),
            "critical_not_closed": int(((support["Ticket Priority"] == "Critical") & not_closed).sum()), "priority_chi2_p": round(chi2_p, 4),
            "by_priority": pack(by_priority), "by_type": pack(by_type)}


def text_signal_check(support: pd.DataFrame) -> dict[str, Any]:
    """Can the text of Dataset 1 predict its own labels? If not, text-based automation cannot be validated there."""
    text = support["Ticket Description"].fillna("").astype(str).str.replace(r"\{[a-z_]+\}", " ", regex=True)
    results = []
    for label, column in (("Tipo de ticket", "Ticket Type"), ("Assunto", "Ticket Subject")):
        y = support[column].astype(str)
        x_train, x_test, y_train, y_test = train_test_split(text, y, test_size=.25, random_state=42, stratify=y)
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        clf = LogisticRegression(max_iter=300).fit(vec.fit_transform(x_train), y_train)
        accuracy = float((clf.predict(vec.transform(x_test)) == y_test).mean())
        results.append({"target": label, "classes": int(y.nunique()), "accuracy": round(accuracy, 3), "chance": round(1 / y.nunique(), 3),
                        "majority_baseline": round(float(y_test.value_counts(normalize=True).iloc[0]), 3)})
    return {"results": results,
            "conclusion": "O texto do Dataset 1 prevê o próprio tipo/assunto apenas no nível do acaso: ele não carrega sinal de categoria. "
                          "A classificação por texto é validada no Dataset 2; no Dataset 1 ela é usada com revisão humana obrigatória."}


def confidence_threshold_curve(y_true: pd.Series, probabilities: np.ndarray, classes: np.ndarray) -> list[dict[str, Any]]:
    """Coverage × accuracy trade-off: justifies the human-review threshold with held-out data."""
    predicted = classes[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    correct = predicted == y_true.to_numpy()
    rows = []
    for threshold in (0.0, .4, .5, .6, .7, .8, .9):
        mask = confidence >= threshold
        rows.append({"threshold": threshold, "coverage": round(float(mask.mean()), 3),
                     "accuracy": round(float(correct[mask].mean()), 4) if mask.any() else None,
                     "sent_to_review": round(float(1 - mask.mean()), 3)})
    return rows


class SimilarCaseIndex:
    """TF-IDF cosine retrieval over labelled texts, with an offline held-out check."""

    def __init__(self, texts: pd.Series, labels: pd.Series):
        self.texts = texts.fillna("").astype(str).reset_index(drop=True)
        self.labels = labels.astype(str).reset_index(drop=True)
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=50000, sublinear_tf=True, stop_words="english")
        self.matrix = self.vectorizer.fit_transform(self.texts.str.replace(r"\{[a-z_]+\}", " ", regex=True))

    def search(self, texts: list[str] | pd.Series, k: int = 3, exclude_self: bool = False) -> list[list[dict[str, Any]]]:
        cleaned = pd.Series(list(texts)).fillna("").astype(str).str.replace(r"\{[a-z_]+\}", " ", regex=True)
        vectors = self.vectorizer.transform(cleaned)
        results: list[list[dict[str, Any]]] = []
        for start in range(0, vectors.shape[0], 400):
            scores = (vectors[start:start + 400] @ self.matrix.T).toarray()
            for offset, row in enumerate(scores):
                if exclude_self:
                    row[start + offset] = -1
                top = np.argpartition(row, -k)[-k:]
                top = top[np.argsort(row[top])[::-1]]
                results.append([{"index": int(i), "score": round(float(row[i]), 3), "label": self.labels.iloc[i], "text": self.texts.iloc[i]} for i in top if row[i] > 0.05])
        return results

    def leave_one_out(self, k: int = 3, sample: int = 1500) -> dict[str, Any]:
        """Share of retrieved neighbours carrying the query's own label, versus the chance level of random retrieval."""
        picks = self.texts.sample(min(sample, len(self.texts)), random_state=42).index
        found = self.search(self.texts.loc[picks], k=k, exclude_self=False)
        hits = total = 0
        for idx, matches in zip(picks, found):
            for match in matches:
                if match["index"] == idx:
                    continue
                hits += match["label"] == self.labels.loc[idx]
                total += 1
        chance = float((self.labels.value_counts(normalize=True) ** 2).sum())
        return {"k": k, "queries": int(len(picks)), "precision_at_k": round(hits / max(total, 1), 3), "chance": round(chance, 3)}


def combination_ranking(support: pd.DataFrame, min_valid: int = 10, top: int = 8) -> dict[str, Any]:
    """Worst channel × priority × type combinations by valid post-response time, tested against shuffled data.

    The ranking is only reported as a finding if the worst combination is worse than what random shuffling
    of the same durations produces; otherwise it is labelled as noise.
    """
    frame = support.copy()
    frame["hours"] = [duration_hours(a, b) for a, b in zip(frame["First Response Time"], frame["Time to Resolution"])]
    frame["csat"] = pd.to_numeric(frame["Customer Satisfaction Rating"], errors="coerce")
    valid = frame.dropna(subset=["hours"]).copy()
    keys = ["Ticket Channel", "Ticket Priority", "Ticket Type"]
    grouped = valid.groupby(keys).agg(n=("hours", "count"), mean_hours=("hours", "mean"), sd=("hours", "std"), csat=("csat", "mean")).reset_index()
    grouped = grouped[grouped.n >= min_valid].copy()
    grouped["ci95"] = 1.96 * grouped.sd / np.sqrt(grouped.n)
    ranked = grouped.sort_values("mean_hours", ascending=False)

    labels = valid[keys].astype(str).agg("|".join, axis=1).to_numpy()
    sizes = pd.Series(labels).value_counts()
    eligible_labels = set(sizes[sizes >= min_valid].index)
    mask = np.array([label in eligible_labels for label in labels])
    values, groups = valid["hours"].to_numpy()[mask], labels[mask]
    rng = np.random.default_rng(42)

    def worst_mean(vals: np.ndarray) -> float:
        return float(pd.Series(vals).groupby(groups).mean().max())

    observed = worst_mean(values)
    null = np.array([worst_mean(rng.permutation(values)) for _ in range(500)])
    p_value = float((null >= observed).mean())
    return {
        "valid_pairs": int(len(valid)), "combinations": int(len(grouped)), "min_valid": min_valid,
        "worst": [{"channel": r["Ticket Channel"], "priority": r["Ticket Priority"], "type": r["Ticket Type"], "n": int(r["n"]),
                   "mean_hours": round(float(r["mean_hours"]), 1), "ci95": round(float(r["ci95"]), 1), "csat": None if pd.isna(r["csat"]) else round(float(r["csat"]), 2)}
                  for _, r in ranked.head(top).iterrows()],
        "overall_mean_hours": round(float(valid["hours"].mean()), 1),
        "worst_mean_hours": round(observed, 1), "null_worst_mean_hours": round(float(null.mean()), 1), "permutation_p": round(p_value, 3),
        "is_signal": bool(p_value < ALPHA),
        "conclusion": ("A pior combinação é pior do que o acaso produziria: há gargalo localizado."
                       if p_value < ALPHA else
                       "A pior combinação não é pior do que o ranking obtido embaralhando os próprios tempos: a ordem abaixo é ruído amostral (n pequeno por célula) e não deve orientar ação."),
        "method": f"Média do tempo pós-1ª resposta (pares válidos) por canal × prioridade × tipo, células com n ≥ {min_valid}; teste de permutação (500 embaralhamentos) para a pior média.",
    }


# Planning assumptions, not measured values: the dataset has no agent-effort data. Exposed in the UI so they can be challenged.
EFFORT_ASSUMPTIONS = {"cost_per_hour_usd": 18, "manual_triage_minutes": 2, "draft_minutes": 6, "draft_assist_rate": 0.35, "backlog_retouch_minutes": 5, "backlog_retouches_per_month": 1}


def waste_estimate(support: pd.DataFrame, auto_route_coverage: float, brief_annual_tickets: int = 30000) -> dict[str, Any]:
    """Recoverable agent hours (assumption-based) plus customer waiting time (data-based, valid pairs only)."""
    a = EFFORT_ASSUMPTIONS
    total = len(support)
    not_closed = float((support["Ticket Status"] != "Closed").mean())
    eligible = float(((support["Ticket Type"] != "Billing inquiry") & support["Ticket Priority"].isin(["Low", "Medium"])).mean())
    components = [
        {"key": "backlog", "name": "Retrabalho do backlog parado", "lever": "Processo (não é IA)", "basis_share": not_closed, "minutes": a["backlog_retouch_minutes"] * a["backlog_retouches_per_month"] / 12,
         "assumption": f"{a['backlog_retouches_per_month']} releitura/mês por ticket não encerrado × {a['backlog_retouch_minutes']} min"},
        {"key": "triage", "name": "Triagem manual de tickets roteáveis", "lever": "IA: classificador ≥ limiar", "basis_share": auto_route_coverage, "minutes": a["manual_triage_minutes"],
         "assumption": f"{a['manual_triage_minutes']} min por ticket × cobertura automática medida ({auto_route_coverage:.0%}, Dataset 2)"},
        {"key": "draft", "name": "Redação de respostas elegíveis", "lever": "IA: copiloto com revisão", "basis_share": eligible * a["draft_assist_rate"], "minutes": a["draft_minutes"],
         "assumption": f"{a['draft_minutes']} min × {a['draft_assist_rate']:.0%} de assistência × tickets Low/Medium não financeiros ({eligible:.0%})"},
    ]
    for volume_key, tickets_year in (("dataset", total), ("brief", brief_annual_tickets)):
        for c in components:
            if c["key"] == "backlog":
                # Stock of not-closed tickets re-read N times a month for 12 months.
                hours_year = tickets_year * c["basis_share"] * a["backlog_retouches_per_month"] * a["backlog_retouch_minutes"] * 12 / 60
            else:
                hours_year = tickets_year * c["basis_share"] * c["minutes"] / 60
            c[f"hours_year_{volume_key}"] = round(hours_year)
            c[f"usd_year_{volume_key}"] = round(hours_year * a["cost_per_hour_usd"])

    frame = support.copy()
    frame["hours"] = [duration_hours(x, y) for x, y in zip(frame["First Response Time"], frame["Time to Resolution"])]
    valid = frame.dropna(subset=["hours"])
    median = float(valid["hours"].median())
    excess = (valid["hours"] - median).clip(lower=0)
    biggest = max(components, key=lambda c: c["hours_year_brief"])
    return {
        "assumptions": a, "components": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items()} for c in components],
        "ai_hours_year_dataset": sum(c["hours_year_dataset"] for c in components if c["key"] != "backlog"), "ai_usd_year_dataset": sum(c["usd_year_dataset"] for c in components if c["key"] != "backlog"),
        "ai_hours_year_brief": sum(c["hours_year_brief"] for c in components if c["key"] != "backlog"), "ai_usd_year_brief": sum(c["usd_year_brief"] for c in components if c["key"] != "backlog"),
        "backlog_sensitivity": [{"retouches_per_month": t, "hours_year_dataset": round(total * not_closed * t * a["backlog_retouch_minutes"] * 12 / 60), "hours_year_brief": round(brief_annual_tickets * not_closed * t * a["backlog_retouch_minutes"] * 12 / 60)} for t in (0.5, 1, 2)],
        "total_hours_year_dataset": sum(c["hours_year_dataset"] for c in components), "total_usd_year_dataset": sum(c["usd_year_dataset"] for c in components),
        "total_hours_year_brief": sum(c["hours_year_brief"] for c in components), "total_usd_year_brief": sum(c["usd_year_brief"] for c in components),
        "largest_component": biggest["name"],
        "customer_wait": {"valid_pairs": int(len(valid)), "median_hours": round(median, 1), "mean_hours": round(float(valid["hours"].mean()), 1),
                          "excess_hours_over_median": round(float(excess.sum())), "excess_share_of_total": round(float(excess.sum() / valid["hours"].sum()), 3),
                          "note": "Tempo de espera do cliente (não esforço do agente), só nos pares de timestamp válidos; não é extrapolado."},
        "caveat": "Horas de agente são estimativas por premissa (o dataset não mede esforço). Mudar as premissas muda o resultado de forma proporcional.",
    }

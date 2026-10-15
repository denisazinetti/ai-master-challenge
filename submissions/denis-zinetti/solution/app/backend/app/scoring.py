from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RiskResult:
    score: int
    level: str
    factors: list[dict[str, Any]]


def calculate_risk(ticket: dict[str, Any], resolution_p75: float) -> RiskResult:
    """Operational retention-risk index; it is deliberately not a churn probability.

    It is a transparent triage rule, not a fitted model: Dataset 1 shows no statistically
    detectable driver of CSAT (see diagnostics.csat_drivers), so the weights encode business policy.
    """
    factors: list[dict[str, Any]] = []
    score = 0
    priority_points = {"Critical": 25, "High": 16, "Medium": 8, "Low": 2}
    priority = str(ticket.get("priority", "Low"))
    points = priority_points.get(priority, 2)
    score += points
    if points >= 16:
        factors.append({"label": f"Prioridade {priority}", "points": points, "kind": "risk"})

    resolution = float(ticket.get("resolution_hours") or 0)
    if resolution_p75 and resolution > resolution_p75:
        score += 18
        factors.append({"label": "Resolução acima do P75", "points": 18, "kind": "risk"})

    satisfaction = ticket.get("satisfaction")
    if satisfaction is not None and float(satisfaction) <= 2:
        score += 20
        factors.append({"label": "CSAT baixo (1–2)", "points": 20, "kind": "risk"})
    elif satisfaction is not None and float(satisfaction) >= 4:
        score -= 8
        factors.append({"label": "CSAT alto (4–5)", "points": -8, "kind": "protective"})

    recurrence = int(ticket.get("customer_ticket_count") or 1)
    if recurrence >= 3:
        score += 15
        factors.append({"label": f"Recorrência: {recurrence} tickets", "points": 15, "kind": "risk"})

    status = str(ticket.get("status"))
    if status == "Open":
        score += 12
        factors.append({"label": "Aguardando atendimento (Open)", "points": 12, "kind": "risk"})
    elif status != "Closed":
        score += 4
        factors.append({"label": "Aguardando o cliente (Pending)", "points": 4, "kind": "risk"})

    score = max(0, min(100, score))
    # Open tickets carry no CSAT or duration, so their ceiling is priority + status + recurrence (52).
    # Thresholds are set so that "Alto" is reachable by them: a Critical ticket waiting on us scores 37.
    level = "Alto" if score >= 37 else "Médio" if score >= 22 else "Baixo"
    return RiskResult(score=score, level=level, factors=factors)

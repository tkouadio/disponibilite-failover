import os
import asyncio
import time
from collections import deque
from fastapi import FastAPI, HTTPException, Query
import httpx

app = FastAPI(title="Supervisor Router (Failover)")

PRIMARY_URL = os.getenv("PRIMARY_URL", "http://service-a:8000").rstrip("/")
SECONDARY_URL = os.getenv("SECONDARY_URL", "http://service-b:8000").rstrip("/")
HEALTH_INTERVAL = float(os.getenv("HEALTH_INTERVAL_SECONDS", "2"))
REQ_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "1"))
PREFER_PRIMARY = os.getenv("PREFER_PRIMARY", "true").lower() == "true"

# Journal des requêtes (pour calculer les métriques de résilience)
# Chaque entrée: {ts, path, status, routed_to, target, note}
REQUEST_LOG_MAX = int(os.getenv("REQUEST_LOG_MAX", "2000"))
request_log = deque(maxlen=REQUEST_LOG_MAX)

# État global du routeur
state = {
    "primary_up": False,
    "secondary_up": False,
    "last_check_ts": 0.0,
    "last_route": None,
    "last_route_reason": None,

    # Stimulus (panne simulée)
    "failure_injected_ts": None,       # t0
    "failure_injected_target": None,   # "PRIMARY"
}

client: httpx.AsyncClient | None = None


def log_request(status: int, routed_to: str | None, target: str | None, note: str | None = None):
    request_log.append({
        "ts": time.time(),
        "status": status,
        "routed_to": routed_to,
        "target": target,
        "note": note,
    })


async def check_health(base_url: str) -> bool:
    assert client is not None
    try:
        r = await client.get(f"{base_url}/health", timeout=REQ_TIMEOUT)
        return r.status_code == 200 and r.json().get("status") == "UP"
    except Exception:
        return False


async def health_loop():
    while True:
        p = await check_health(PRIMARY_URL)
        s = await check_health(SECONDARY_URL)
        state["primary_up"] = p
        state["secondary_up"] = s
        state["last_check_ts"] = time.time()
        await asyncio.sleep(HEALTH_INTERVAL)


@app.on_event("startup")
async def on_startup():
    global client
    client = httpx.AsyncClient()
    asyncio.create_task(health_loop())


@app.on_event("shutdown")
async def on_shutdown():
    global client
    if client is not None:
        await client.aclose()
        client = None


def choose_target() -> tuple[str, str, str]:
    """
    Returns (target_url, routed_to, reason)
    """
    p, s = state["primary_up"], state["secondary_up"]

    if PREFER_PRIMARY:
        if p:
            return PRIMARY_URL, "PRIMARY", "Primary is UP (preferred)"
        if s:
            return SECONDARY_URL, "SECONDARY", "Primary is DOWN -> failover to Secondary"
    else:
        if s:
            return SECONDARY_URL, "SECONDARY", "Secondary is UP (preferred)"
        if p:
            return PRIMARY_URL, "PRIMARY", "Secondary is DOWN -> fallback to Primary"

    return "", "", "No backend is healthy"


@app.get("/")
def home():
    return {
        "message": "Supervisor Router OK",
        "try": {
            "status": "/status",
            "route": "/route",
            "health": "/health",
            "demo_order": "/orders/1003",
            "stimulus_fail_primary": "/stimulus/fail-primary",
            "metrics": "/metrics",
        },
    }


@app.get("/status")
def status():
    target, routed_to, reason = choose_target()
    return {
        "primary": {"url": PRIMARY_URL, "up": state["primary_up"]},
        "secondary": {"url": SECONDARY_URL, "up": state["secondary_up"]},
        "policy": {"prefer_primary": PREFER_PRIMARY},
        "current_decision": {"target": target, "routed_to": routed_to, "reason": reason},
        "last": {"route": state["last_route"], "reason": state["last_route_reason"]},
        "last_check_ts": state["last_check_ts"],
        "stimulus": {
            "failure_injected_ts": state["failure_injected_ts"],
            "failure_injected_target": state["failure_injected_target"],
        },
        "log": {"size": len(request_log), "max": REQUEST_LOG_MAX},
    }


@app.get("/health")
def router_health():
    return {
        "status": "UP",
        "primary_up": state["primary_up"],
        "secondary_up": state["secondary_up"],
        "primary_url": PRIMARY_URL,
        "secondary_url": SECONDARY_URL,
        "health_interval_seconds": HEALTH_INTERVAL,
        "request_timeout_seconds": REQ_TIMEOUT,
        "prefer_primary": PREFER_PRIMARY,
        "last_check_ts": state["last_check_ts"],
        "last_route": state["last_route"],
        "last_route_reason": state["last_route_reason"],
    }


@app.get("/route")
def route_info():
    target, routed_to, reason = choose_target()
    return {"target": target, "routed_to": routed_to, "reason": reason}


# -------------------------
# Stimulus manuel (Panne)
# -------------------------

@app.post("/stimulus/fail-primary")
async def stimulus_fail_primary(reason: str = Query(default="manual", description="Raison affichée dans la panne simulée")):
    """
    Déclenche une panne simulée sur le service primaire (Service A),
    en appelant son endpoint /stimulus/fail.

    Exigence de l'énoncé: stimulus manuel déclenchant une défaillance simulée.
    """
    assert client is not None

    # 1) Appel du service primaire pour le mettre en panne
    try:
        r = await client.post(f"{PRIMARY_URL}/stimulus/fail", params={"reason": reason}, timeout=REQ_TIMEOUT)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail={"message": "Primary did not accept stimulus", "status": r.status_code})
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Unable to reach primary to inject failure")

    # 2) Enregistrer l’instant d’injection (t0)
    state["failure_injected_ts"] = time.time()
    state["failure_injected_target"] = "PRIMARY"

    return {
        "ok": True,
        "injected_at_ts": state["failure_injected_ts"],
        "target": "PRIMARY",
        "primary_response": r.json(),
        "next": "Call /orders/1003 repeatedly, then check /metrics",
    }


@app.post("/stimulus/recover-primary")
async def stimulus_recover_primary():
    """Remet le service primaire en état normal."""
    assert client is not None
    try:
        r = await client.post(f"{PRIMARY_URL}/stimulus/recover", timeout=REQ_TIMEOUT)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Primary did not recover")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Unable to reach primary to recover")

    return {"ok": True, "primary_response": r.json()}


@app.post("/stimulus/reset-metrics")
def stimulus_reset_metrics():
    """Réinitialise le journal des requêtes et les marqueurs de panne (utile pour refaire une démo propre)."""
    request_log.clear()
    state["failure_injected_ts"] = None
    state["failure_injected_target"] = None
    return {"ok": True, "message": "Metrics + stimulus markers reset"}


# -------------------------
# Endpoint métier routé
# -------------------------

@app.get("/orders/{order_id}")
async def routed_get_order(order_id: int):
    target, routed_to, reason = choose_target()
    if not target:
        log_request(status=503, routed_to=None, target=None, note="no_healthy_backend")
        raise HTTPException(status_code=503, detail="No healthy backend available")

    assert client is not None

    # 1) Tentative sur la cible choisie
    try:
        r = await client.get(f"{target}/orders/{order_id}", timeout=REQ_TIMEOUT)

        if r.status_code == 404:
            log_request(status=404, routed_to=routed_to, target=target, note="not_found")
            raise HTTPException(status_code=404, detail="Order not found")

        if r.status_code != 200:
            # Backend répond mais en erreur (500, etc.)
            log_request(status=r.status_code, routed_to=routed_to, target=target, note="backend_error")
            raise HTTPException(status_code=502, detail="Backend error")

        data = r.json()
        data["routed_to"] = routed_to
        data["route_reason"] = reason

        state["last_route"] = routed_to
        state["last_route_reason"] = reason

        log_request(status=200, routed_to=routed_to, target=target, note=None)
        return data

    except httpx.RequestError:
        # 2) Failover immédiat (Si le service tombe entre 2 health checks)
        fallback = SECONDARY_URL if target == PRIMARY_URL else PRIMARY_URL
        fallback_to = "SECONDARY" if routed_to == "PRIMARY" else "PRIMARY"

        # Petite sécurité : Si le fallback est DOWN selon l’état, inutile d’insister
        if fallback_to == "PRIMARY" and not state["primary_up"]:
            log_request(status=503, routed_to=fallback_to, target=fallback, note="fallback_primary_down")
            raise HTTPException(status_code=503, detail="Primary is down and request failed")
        if fallback_to == "SECONDARY" and not state["secondary_up"]:
            log_request(status=503, routed_to=fallback_to, target=fallback, note="fallback_secondary_down")
            raise HTTPException(status_code=503, detail="Secondary is down and request failed")

        try:
            r2 = await client.get(f"{fallback}/orders/{order_id}", timeout=REQ_TIMEOUT)
            if r2.status_code == 200:
                data = r2.json()
                data["routed_to"] = fallback_to
                data["route_reason"] = "Immediate failover after request error"
                data["note"] = "Backend failed between health checks"

                state["last_route"] = fallback_to
                state["last_route_reason"] = "Immediate failover after request error"

                log_request(status=200, routed_to=fallback_to, target=fallback, note="immediate_failover")
                return data
            else:
                log_request(status=r2.status_code, routed_to=fallback_to, target=fallback, note="fallback_non_200")
        except Exception:
            log_request(status=503, routed_to=fallback_to, target=fallback, note="fallback_exception")

        raise HTTPException(status_code=503, detail="Failover attempt failed")


# -----------
# Métriques
# -----------

@app.get("/metrics")
def metrics(
    pre_window_s: float = Query(default=2.0, ge=0.0, description="Secondes avant la panne pour la fenêtre de calcul"),
    post_window_s: float = Query(default=10.0, ge=0.0, description="Secondes après la panne pour la fenêtre de calcul"),
):
    """
    (1) Temps de bascule Tbascule:
        - Tbascule_200_spare: t(first 200 from SECONDARY after injection) - t(injection)
        - Tbascule_from_first_error: t(first 200 from SECONDARY) - t(first error after injection)
          (les deux sont acceptables selon l’énoncé)

    (2) Taux d'erreurs pendant la bascule Ebascule:
        - % de requêtes échouées (status != 200) dans la fenêtre [t0-pre ; t0+post]
    """
    t0 = state["failure_injected_ts"]
    if t0 is None:
        raise HTTPException(status_code=400, detail="No failure injected yet. Call /stimulus/fail-primary first.")

    window_start = t0 - pre_window_s
    window_end = t0 + post_window_s

    # Filtrer les requêtes dans la fenêtre
    entries = [e for e in request_log if window_start <= e["ts"] <= window_end]
    total = len(entries)
    failed = sum(1 for e in entries if e["status"] != 200)

    # t_first_error: Première entrée en erreur après t0
    t_first_error = None
    for e in request_log:
        if e["ts"] >= t0 and e["status"] != 200:
            t_first_error = e["ts"]
            break

    # t_first_success_spare: Première réponse 200 venant du SECONDARY après t0
    t_first_success_spare = None
    for e in request_log:
        if e["ts"] >= t0 and e["status"] == 200 and e["routed_to"] == "SECONDARY":
            t_first_success_spare = e["ts"]
            break

    tbascule_200_spare = None
    if t_first_success_spare is not None:
        tbascule_200_spare = round(t_first_success_spare - t0, 4)

    tbascule_from_first_error = None
    if t_first_success_spare is not None and t_first_error is not None:
        tbascule_from_first_error = round(t_first_success_spare - t_first_error, 4)

    ebascule = None
    if total > 0:
        ebascule = round((failed / total) * 100.0, 2)

    return {
        "stimulus": {
            "injected_at_ts": t0,
            "window": {"start_ts": window_start, "end_ts": window_end, "pre_s": pre_window_s, "post_s": post_window_s},
        },
        "Tbascule": {
            "tbascule_200_spare_s": tbascule_200_spare,
            "tbascule_from_first_error_s": tbascule_from_first_error,
            "t_first_error_ts": t_first_error,
            "t_first_success_spare_ts": t_first_success_spare,
            "note": "Two definitions provided; both are acceptable per the statement.",
        },
        "Ebascule": {
            "total_requests_in_window": total,
            "failed_requests_in_window": failed,
            "error_rate_percent": ebascule,
            "definition": "status != 200 is considered a failure (includes timeouts, 5xx mapped to 502/503).",
        },
        "log": {"size": len(request_log), "max": REQUEST_LOG_MAX},
    }

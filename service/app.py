import os
import time
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Orders Service")

SERVICE_NAME = os.getenv("SERVICE_NAME", "Service")

# Optionnel: Simuler une latence (en ms) via variable d'environnement
SIMULATED_LATENCY_MS = int(os.getenv("SIMULATED_LATENCY_MS", "0"))

# État de panne simulée (stimulus manuel)
_failure_state = {
    "failed": False,
    "since_ts": None,
    "reason": None,
}

ORDERS = {
    1001: {"order_id": 1001, "status": "CREATED", "amount": 59.99},
    1002: {"order_id": 1002, "status": "PAID", "amount": 120.00},
    1003: {"order_id": 1003, "status": "SHIPPED", "amount": 250.75},
}

def _maybe_sleep():
    if SIMULATED_LATENCY_MS > 0:
        time.sleep(SIMULATED_LATENCY_MS / 1000.0)

def _ensure_not_failed():
    if _failure_state["failed"]:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Simulated failure",
                "service": SERVICE_NAME,
                "since_ts": _failure_state["since_ts"],
                "reason": _failure_state["reason"],
            },
        )

@app.get("/")
def home():
    return {
        "message": f"{SERVICE_NAME} OK",
        "try": ["/health", "/info", "/orders/1003", "/stimulus/status"],
    }

@app.get("/health")
def health():
    # Important: Si en panne, /health doit échouer pour que le routeur détecte la défaillance
    _maybe_sleep()
    _ensure_not_failed()
    return {"status": "UP", "service": SERVICE_NAME, "timestamp": time.time()}

@app.get("/info")
def info():
    return {
        "service": SERVICE_NAME,
        "simulated_latency_ms": SIMULATED_LATENCY_MS,
        "endpoints": [
            "/",
            "/health",
            "/info",
            "/orders/{order_id}",
            "/stimulus/fail",
            "/stimulus/recover",
            "/stimulus/status",
        ],
    }

@app.get("/stimulus/status")
def stimulus_status():
    return {
        "service": SERVICE_NAME,
        "failed": _failure_state["failed"],
        "since_ts": _failure_state["since_ts"],
        "reason": _failure_state["reason"],
    }

@app.post("/stimulus/fail")
def stimulus_fail(reason: str = "manual"):
    # Déclenchement manuel d’une panne simulée
    _failure_state["failed"] = True
    _failure_state["since_ts"] = time.time()
    _failure_state["reason"] = reason
    return {"ok": True, **stimulus_status()}

@app.post("/stimulus/recover")
def stimulus_recover():
    # Retour à la normale
    _failure_state["failed"] = False
    _failure_state["since_ts"] = None
    _failure_state["reason"] = None
    return {"ok": True, **stimulus_status()}

@app.get("/orders/{order_id}")
def get_order(order_id: int):
    _maybe_sleep()
    _ensure_not_failed()

    if order_id not in ORDERS:
        raise HTTPException(status_code=404, detail="Order not found")

    data = dict(ORDERS[order_id])
    data["served_by"] = SERVICE_NAME
    data["timestamp"] = time.time()
    return data

"""Prediction API.

Endpoints
  GET  /healthz   liveness: the process is up
  GET  /readyz    readiness: the model is loaded and can serve traffic
  GET  /version   which model is running and how it scored
  POST /predict   score one or more tumour measurements
  GET  /metrics   Prometheus metrics
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

MODEL_DIR = Path(os.getenv("MODEL_DIR", "artifacts"))
# |z-score| above this on any feature marks a request as out of distribution.
OOD_Z = float(os.getenv("OOD_Z_THRESHOLD", "6"))


# --- logging: one JSON object per line, easy for log tools to parse -----------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"level": record.levelname, "msg": record.getMessage(), "logger": record.name}
        entry.update(getattr(record, "extra_fields", {}))
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
log = logging.getLogger("api")
log.handlers = [handler]
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))
log.propagate = False

# --- metrics -----------------------------------------------------------------
REQUESTS = Counter("api_requests_total", "HTTP requests", ["path", "method", "status"])
LATENCY = Histogram("api_request_seconds", "Request latency", ["path"])
PREDICTIONS = Counter("model_predictions_total", "Predictions served", ["label"])
OOD = Counter("model_out_of_distribution_total", "Rows far outside the training data")


class State:
    model = None
    meta: dict = {}
    mean: np.ndarray | None = None
    std: np.ndarray | None = None


def load_model(model_dir: Path | None = None) -> None:
    model_dir = model_dir or MODEL_DIR
    State.model = joblib.load(model_dir / "model.joblib")
    State.meta = json.loads((model_dir / "metadata.json").read_text())
    State.mean = np.array(State.meta["train_mean"])
    State.std = np.where(np.array(State.meta["train_std"]) == 0, 1, State.meta["train_std"])
    log.info("model loaded", extra={"extra_fields": {"model_version": State.meta["model_version"]}})


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_model()
    except FileNotFoundError:
        # Stay up but not ready, so Kubernetes keeps traffic away instead of crash-looping.
        log.error("model files missing", extra={"extra_fields": {"model_dir": str(MODEL_DIR)}})
    yield


app = FastAPI(title="Model delivery pipeline", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def observe(request: Request, call_next):
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    REQUESTS.labels(path, request.method, str(response.status_code)).inc()
    LATENCY.labels(path).observe(elapsed)
    response.headers["x-request-id"] = rid
    if State.meta:
        response.headers["x-model-version"] = State.meta["model_version"]
    if path not in ("/healthz", "/readyz", "/metrics"):
        log.info(
            "request",
            extra={
                "extra_fields": {
                    "request_id": rid,
                    "path": path,
                    "status": response.status_code,
                    "ms": round(elapsed * 1000, 1),
                }
            },
        )
    return response


class PredictRequest(BaseModel):
    # Each row is the 30 measurements in the order listed by GET /version.
    rows: list[list[float]] = Field(..., min_length=1, max_length=1000)


class Prediction(BaseModel):
    label: str
    probability_benign: float
    out_of_distribution: bool


class PredictResponse(BaseModel):
    model_version: str
    predictions: list[Prediction]


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    if State.model is None:
        raise HTTPException(503, "model not loaded")
    return {"status": "ready", "model_version": State.meta["model_version"]}


@app.get("/version")
def version():
    if not State.meta:
        raise HTTPException(503, "model not loaded")
    keep = ("model_version", "trained_at", "data_fingerprint", "metrics", "features", "classes")
    return {k: State.meta[k] for k in keep}


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if State.model is None:
        raise HTTPException(503, "model not loaded")
    n_features = len(State.meta["features"])
    if any(len(r) != n_features for r in req.rows):
        raise HTTPException(422, f"each row needs exactly {n_features} values")

    X = np.array(req.rows, dtype=float)
    if not np.isfinite(X).all():
        raise HTTPException(422, "values must be finite numbers")
    proba = State.model.predict_proba(X)[:, 1]
    z = np.abs((X - State.mean) / State.std)
    ood = (z > OOD_Z).any(axis=1)

    classes = State.meta["classes"]
    out = []
    for p, o in zip(proba, ood, strict=False):
        label = classes[int(p >= 0.5)]
        PREDICTIONS.labels(label).inc()
        if o:
            OOD.inc()
        out.append(
            Prediction(
                label=label, probability_benign=round(float(p), 4), out_of_distribution=bool(o)
            )
        )
    return PredictResponse(model_version=State.meta["model_version"], predictions=out)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

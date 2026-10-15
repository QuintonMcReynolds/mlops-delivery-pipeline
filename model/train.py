"""Train the model, evaluate it, and refuse to ship it if it is not good enough.

Writes two files to artifacts/:
  model.joblib   the fitted pipeline
  metadata.json  version, metrics, feature names and a hash of the training data

Run:  python -m model.train            (exit code 1 if the quality gate fails)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# The quality gate: CI fails if the new model scores below these on held-out data.
MIN_AUC = 0.97
MIN_ACCURACY = 0.93
SEED = 42


def data_fingerprint(X: np.ndarray, y: np.ndarray) -> str:
    """Short hash of the training data, so every model can be traced to its data."""
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(X).tobytes())
    h.update(np.ascontiguousarray(y).tobytes())
    return h.hexdigest()[:12]


def train(out_dir: Path, version: str) -> dict:
    data = load_breast_cancer()
    X, y = data.data, data.target
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=SEED
    )

    pipe = Pipeline(
        [
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, C=0.5, random_state=SEED)),
        ]
    )
    pipe.fit(X_train, y_train)

    proba = pipe.predict_proba(X_test)[:, 1]
    metrics = {
        "auc": round(float(roc_auc_score(y_test, proba)), 4),
        "accuracy": round(float(accuracy_score(y_test, proba >= 0.5)), 4),
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
    }

    # Per-feature mean/std of the training data. The API compares live requests
    # against these to flag inputs that look nothing like what the model saw.
    meta = {
        "model_version": version,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data_fingerprint": data_fingerprint(X_train, y_train),
        "features": list(data.feature_names),
        "classes": list(data.target_names),
        "metrics": metrics,
        "train_mean": X_train.mean(axis=0).round(6).tolist(),
        "train_std": X_train.std(axis=0).round(6).tolist(),
        "gate": {"min_auc": MIN_AUC, "min_accuracy": MIN_ACCURACY},
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, out_dir / "model.joblib")
    (out_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    return meta


def passes_gate(metrics: dict) -> bool:
    return metrics["auc"] >= MIN_AUC and metrics["accuracy"] >= MIN_ACCURACY


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts")
    ap.add_argument("--version", default="dev")
    args = ap.parse_args()

    meta = train(Path(args.out), args.version)
    m = meta["metrics"]
    print(
        f"model {meta['model_version']}: AUC={m['auc']} accuracy={m['accuracy']} "
        f"(gate: AUC>={MIN_AUC}, accuracy>={MIN_ACCURACY})"
    )
    if not passes_gate(m):
        print("QUALITY GATE FAILED: model not good enough to ship", file=sys.stderr)
        return 1
    print("quality gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

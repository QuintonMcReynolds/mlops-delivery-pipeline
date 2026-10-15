import json

import joblib

from model.train import MIN_ACCURACY, MIN_AUC, passes_gate, train


def test_training_writes_artifacts(model_dir):
    assert (model_dir / "model.joblib").exists()
    meta = json.loads((model_dir / "metadata.json").read_text())
    assert meta["model_version"] == "test"
    assert len(meta["features"]) == 30
    assert len(meta["train_mean"]) == len(meta["train_std"]) == 30


def test_model_meets_quality_gate(model_dir):
    meta = json.loads((model_dir / "metadata.json").read_text())
    assert meta["metrics"]["auc"] >= MIN_AUC
    assert meta["metrics"]["accuracy"] >= MIN_ACCURACY


def test_gate_rejects_weak_model():
    assert not passes_gate({"auc": 0.80, "accuracy": 0.99})
    assert not passes_gate({"auc": 0.99, "accuracy": 0.50})


def test_training_is_reproducible(tmp_path):
    a = train(tmp_path / "a", "a")
    b = train(tmp_path / "b", "b")
    assert a["data_fingerprint"] == b["data_fingerprint"]
    assert a["metrics"] == b["metrics"]


def test_saved_model_predicts(model_dir, sample_rows):
    model = joblib.load(model_dir / "model.joblib")
    assert model.predict_proba(sample_rows).shape == (3, 2)

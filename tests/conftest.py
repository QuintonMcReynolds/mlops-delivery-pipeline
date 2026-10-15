import pytest
from fastapi.testclient import TestClient

from app import main
from model.train import train


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("artifacts")
    train(d, "test")
    return d


@pytest.fixture()
def client(model_dir, monkeypatch):
    monkeypatch.setattr(main, "MODEL_DIR", model_dir)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_rows():
    from sklearn.datasets import load_breast_cancer

    return load_breast_cancer().data[:3].tolist()

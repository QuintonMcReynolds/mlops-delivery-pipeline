.PHONY: install lint test train run smoke docker compose tf-check
VENV ?= .venv
PY := $(VENV)/bin/python

install:            ## create the virtualenv and install everything
	python3 -m venv $(VENV) && $(VENV)/bin/pip install -r requirements-dev.txt

lint:               ## style + common bug checks
	$(VENV)/bin/ruff check . && $(VENV)/bin/ruff format --check .

test:               ## unit + API tests with coverage
	$(PY) -m pytest

train:              ## train the model and apply the quality gate
	$(PY) -m model.train --version local

run: train          ## serve the API on http://localhost:8000/docs
	$(VENV)/bin/uvicorn app.main:app --reload --port 8000

smoke:              ## smoke test a running API
	scripts/smoke_test.sh http://localhost:8000

docker:             ## build and run the container
	docker build -t model-api:local . && docker run --rm -p 8000:8000 model-api:local

compose:            ## API + Prometheus + Grafana
	docker compose up --build

tf-check:           ## validate the Terraform without touching AWS
	cd terraform && terraform fmt -check && terraform init -backend=false && terraform validate

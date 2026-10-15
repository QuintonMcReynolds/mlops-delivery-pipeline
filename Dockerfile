# syntax=docker/dockerfile:1

# ---- Stage 1: install dependencies and train the model ----------------------
FROM python:3.12-slim AS build
WORKDIR /src
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install -r requirements.txt
COPY model/ model/
ARG MODEL_VERSION=dev
# The quality gate runs here too: a bad model fails the image build.
RUN /venv/bin/python -m model.train --out /artifacts --version "${MODEL_VERSION}"

# ---- Stage 2: small runtime image, no build tools, non-root user ------------
FROM python:3.12-slim AS runtime
ARG MODEL_VERSION=dev
LABEL org.opencontainers.image.title="mlops-delivery-pipeline" \
      org.opencontainers.image.version="${MODEL_VERSION}"
RUN useradd --create-home --uid 10001 app
WORKDIR /srv
COPY --from=build /venv /venv
COPY --from=build /artifacts /srv/artifacts
COPY app/ app/
ENV PATH=/venv/bin:$PATH MODEL_DIR=/srv/artifacts PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz').status != 200)"
# One process per container: Prometheus counters live in process memory, so with
# several workers each scrape would see only one worker's numbers. Scale with
# more replicas instead (the Kubernetes HPA does this).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

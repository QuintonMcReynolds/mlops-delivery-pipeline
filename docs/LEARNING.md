# Learning DevOps with this repo

Eight steps, from "it runs on my laptop" to "it deploys itself safely". Each step has:
**Idea** (the concept), **Look at** (files in this repo), **Try it** (an exercise) and **Say it** (how to explain it in an interview).

Do them in order. Each one takes 30–60 minutes.

---

## 1. Tests and a quality gate

**Idea.** Automated tests catch mistakes before users do. For ML, "the code works" is not enough: the *model* also has to be good enough. A quality gate is a test that fails if the model's score drops below a set bar.

**Look at.** `tests/test_api.py`, `tests/test_model.py`, `model/train.py` (`MIN_AUC`, `passes_gate`), `pyproject.toml` (coverage floor).

**Try it.**
1. `make install && make test`. Read the coverage table: which lines aren't tested?
2. Break the model on purpose: in `model/train.py` change `C=0.5` to `C=0.00001`. Run `make train`. The gate should fail with exit code 1. Change it back.
3. Write a new test: `/predict` with 5 rows returns 5 predictions.

**Say it.** "Every push runs lint, 17 tests with an 85 % coverage floor, and a model quality gate, so a code change that quietly makes the model worse can't be merged."

---

## 2. Continuous integration (GitHub Actions)

**Idea.** CI runs your checks on a clean machine on every push and pull request, so "works on my machine" doesn't count. A workflow is a list of jobs; jobs run in parallel unless one `needs` another.

**Look at.** `.github/workflows/ci.yml`. Find the four jobs and the `needs:` lines. Notice `concurrency` (old runs are cancelled) and `permissions` (the token gets read-only access by default).

**Try it.**
1. Open the **Actions** tab on GitHub and click the latest run. Find the job graph.
2. Make a branch, add a failing test (`assert 1 == 2`), push, open a pull request. Watch CI turn red, then fix it.
3. In Settings → Branches, add a rule on `main` requiring the CI checks to pass before merging.

**Say it.** "Jobs fan out in parallel, and the publish job only runs when tests, infra checks and the container job all pass, and only on main."

---

## 3. Containers (Docker)

**Idea.** A container packages the app with its exact Python version and libraries, so it runs the same everywhere. A **multi-stage** build installs and trains in a big stage, then copies only the result into a small final image.

**Look at.** `Dockerfile`, `.dockerignore`. Note: non-root user (`USER 10001`), `HEALTHCHECK`, training (and the quality gate) runs during the build, and no compilers or tests end up in the final image.

**Try it.** (Install Docker Desktop first.)
1. `make docker`, then `make smoke` in another terminal.
2. `docker images model-api` shows the size. Try a single-stage build (delete the second `FROM` and the `COPY --from` lines) and compare.
3. `docker run --rm model-api:local whoami`. Why is it not `root`?

**Say it.** "Multi-stage build, non-root, read-only filesystem at runtime; the model is trained and gated inside the build, so every image is traceable to a commit and a data fingerprint."

---

## 4. Security scanning and supply chain

**Idea.** Your image contains hundreds of packages you didn't write. Scanners compare them against known-vulnerability databases (CVEs). Pinning versions makes builds repeatable; Dependabot opens pull requests when updates are available.

**Look at.** The "Security scan" step in `ci.yml` (Trivy), `requirements.txt` (exact versions), `.github/dependabot.yml`.

**Try it.**
1. Read the Trivy output in a CI run.
2. Pin an old, vulnerable version (for example `starlette==0.27.0` added to `requirements.txt`) on a branch and push. Watch the scan fail. Revert.
3. In Settings → Code security, turn on Dependabot alerts and secret scanning.

**Say it.** "The image is scanned on every build and CI fails on fixable high or critical CVEs; Dependabot keeps dependencies, actions and the base image current."

---

## 5. Kubernetes

**Idea.** Kubernetes keeps a set number of copies of your container running, restarts them if they die, sends traffic only to healthy ones, and replaces them one at a time when you deploy.

Key objects here:
- **Deployment**: "run 2 copies of this image"; `maxUnavailable: 0` means never drop below 2 during an update.
- **Probes**: *startup* (has it booted?), *liveness* (is it stuck? restart it), *readiness* (can it take traffic?).
- **Service**: one stable address in front of the pods.
- **HPA**: add pods when CPU goes over 70 %.
- **PodDisruptionBudget**: keep at least 1 pod during node maintenance.

**Look at.** `k8s/`. Then the "Deploy to Kubernetes" and "Zero-downtime rolling update" steps in `ci.yml`, which create a real cluster with **kind** (Kubernetes in Docker) for each run.

**Try it.** (Needs Docker + `kind` + `kubectl`.)
1. `kind create cluster`, `docker build -t model-api:ci .`, `kind load docker-image model-api:ci`.
2. Apply with the image swapped, as in `ci.yml`. Watch with `kubectl -n model-service get pods -w`.
3. Delete a pod (`kubectl delete pod ...`) and watch Kubernetes replace it.
4. Set `MODEL_DIR` to a wrong path in the Deployment. The pods start but never become Ready, and the old ones keep serving. That's readiness probes and `maxUnavailable: 0` working together.

**Say it.** "CI spins up a kind cluster, deploys the manifests, waits for the rollout, then changes config under live traffic to prove the rolling update drops no requests."

---

## 6. Monitoring and alerting

**Idea.** Once it's live you need to know when it breaks without staring at it. The service exposes numbers (metrics); Prometheus collects them; Grafana graphs them; alert rules notify someone when a number crosses a line. The classic signals: traffic, errors, latency, saturation. For ML add **drift**: are inputs still like the training data?

**Look at.** `app/main.py` (the `Counter`/`Histogram` metrics and JSON logging), `monitoring/alerts.yml`, `monitoring/grafana/dashboards/model-service.json`.

**Try it.**
1. `make compose`, open Grafana at http://localhost:3000 and the "Model service" dashboard.
2. Send traffic: `for i in $(seq 200); do make -s smoke >/dev/null; done`.
3. Send out-of-distribution rows (multiply the values by 1000) and watch the drift panel rise.
4. In Prometheus (http://localhost:9090) → Alerts, see which rules exist and their state.

**Say it.** "The API exports RED metrics plus an out-of-distribution counter; alert rules page on a > 5 % error rate and open a ticket on latency or input drift."

---

## 7. Infrastructure as code (Terraform)

**Idea.** Instead of clicking around the AWS console, you describe the infrastructure in files. Terraform compares the files with what exists and makes only the changes needed (`plan` shows them, `apply` does them). The files are reviewed and versioned like code.

**Look at.** `terraform/main.tf`. Follow the chain: ECR (image registry) → ECS cluster → task definition (what to run) → service (how many, behind which load balancer) → autoscaling. Notice the security groups: the internet can reach only the load balancer, and only the load balancer can reach the containers.

**Try it.**
1. Install Terraform. Run `make tf-check`. This needs no AWS account.
2. Add a variable `log_retention_days` and use it in `aws_cloudwatch_log_group`. Run `terraform fmt` and `validate`.
3. *(Optional, costs a little money: about $1–2 a day while running.)* With an AWS account: set up GitHub OIDC (search "configure OpenID Connect in Amazon Web Services" in the GitHub docs), add the `AWS_ROLE_ARN` variable, run the **Deploy to AWS** workflow with `plan`, then `apply`, try the URL it outputs, then **`destroy`** the same day.

**Say it.** "The AWS stack is Terraform: Fargate behind an ALB with circuit-breaker rollback and target-tracking autoscaling; deploys go through a manual workflow using OIDC, so there are no long-lived cloud keys in GitHub."

---

## 8. Releases

**Idea.** Every image is tagged with the commit SHA (exactly which code), plus `latest` on main and a semantic version (`1.2.0`) when you tag a release. Rolling back means deploying an older tag.

**Look at.** The `publish` job in `ci.yml` (`docker/metadata-action`). Then the **Packages** section of the repo page on GitHub.

**Try it.**
1. `git tag v1.0.0 && git push origin v1.0.0`. Watch a `1.0.0` image appear under Packages.
2. Pull it: `docker pull ghcr.io/quintonmcreynolds/mlops-delivery-pipeline:1.0.0`.
3. Write down how you would roll back Kubernetes to the previous image (hint: `kubectl rollout undo`).

**Say it.** "Images are immutable and traceable: SHA tags for every main build, semver tags for releases, and rollback is redeploying a previous tag."

---

### Glossary

| Term | Meaning |
|---|---|
| CI / CD | Continuous integration (test every change) / continuous delivery (every passing change is ready to deploy) |
| Artifact | Something a build produces: a model file, a test report, an image |
| Image / container | The packaged app / a running copy of it |
| Registry | Where images are stored (GHCR, ECR, Docker Hub) |
| Probe | A check Kubernetes runs against your app to decide if it's alive or ready |
| IaC | Infrastructure as code (Terraform here) |
| OIDC | Lets GitHub prove to AWS who it is, so you don't store passwords/keys |
| CVE | A publicly listed security vulnerability |
| Drift | Live inputs (or outcomes) moving away from what the model was trained on |

#!/usr/bin/env bash
# Hit a running API and fail loudly if anything looks wrong.
#   scripts/smoke_test.sh http://localhost:8000
set -euo pipefail
BASE="${1:-http://localhost:8000}"

echo "waiting for $BASE/readyz"
for i in $(seq 1 30); do
  if curl -fsS "$BASE/readyz" >/dev/null 2>&1; then break; fi
  [ "$i" = 30 ] && { echo "API never became ready"; exit 1; }
  sleep 2
done

curl -fsS "$BASE/healthz"; echo
curl -fsS "$BASE/version" | python3 -c 'import json,sys; v=json.load(sys.stdin); print("model", v["model_version"], v["metrics"])'

# First row of the training data: a known malignant case (30 features).
ROW='[17.99,10.38,122.8,1001.0,0.1184,0.2776,0.3001,0.1471,0.2419,0.07871,1.095,0.9053,8.589,153.4,0.006399,0.04904,0.05373,0.01587,0.03003,0.006193,25.38,17.33,184.6,2019.0,0.1622,0.6656,0.7119,0.2654,0.4601,0.1189]'
RESP=$(curl -fsS -X POST "$BASE/predict" -H 'content-type: application/json' -d "{\"rows\": [$ROW]}")
echo "$RESP"
echo "$RESP" | python3 -c 'import json,sys; p=json.load(sys.stdin)["predictions"][0]; assert p["label"]=="malignant", p; print("prediction OK")'

# Bad input must be rejected, not crash the server.
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/predict" -H 'content-type: application/json' -d '{"rows": [[1, 2]]}')
[ "$CODE" = 422 ] || { echo "expected 422 for bad input, got $CODE"; exit 1; }

curl -fsS "$BASE/metrics" | grep -q model_predictions_total
echo "smoke test passed"

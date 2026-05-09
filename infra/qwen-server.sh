#!/usr/bin/env bash
# Запуск vLLM-контейнера с Qwen на машине RTX 5090.
# Запускать от имени пользователя с доступом к docker на 100.110.246.46.
#
# Использование:
#   ssh roman@100.110.246.46 "bash ~/ai-orchestrator/infra/qwen-server.sh"
# или локально если находишься на той машине:
#   bash infra/qwen-server.sh

set -euo pipefail

CONTAINER_NAME="qwen-server"
MODEL_PATH="/models/qwen"
PORT=8020

docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER_NAME" \
  --gpus all \
  --restart unless-stopped \
  -v "$MODEL_PATH:$MODEL_PATH" \
  -p "127.0.0.1:${PORT}:${PORT}" \
  vllm/vllm-openai:latest \
    --model "$MODEL_PATH" \
    --served-model-name qwen \
    --port "$PORT" \
    --gpu-memory-utilization 0.95 \
    --max-model-len 32768

echo "qwen-server started. Waiting for readiness..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Ready after ${i}s"
    exit 0
  fi
  sleep 5
done
echo "WARNING: server did not respond after 150s, check docker logs $CONTAINER_NAME"

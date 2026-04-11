#!/usr/bin/env bash
# Три варианта QLoRA для сравнения в облаке (разные seed / learning rate).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DATA_JSONL="${DATA_JSONL:-data/sft/train_val.jsonl}"
MODEL="${MODEL_NAME:-Qwen/Qwen2.5-7B-Instruct}"

run_one () {
  local name="$1"
  shift
  accelerate launch training/train_qlora.py \
    --model_name "$MODEL" \
    --dataset_jsonl "$DATA_JSONL" \
    --output_dir "runs/${name}" \
    "$@"
}

run_one "qlora_seed42_lr2e4" --seed 42 --learning_rate 2e-4 --max_steps 500
run_one "qlora_seed43_lr2e4" --seed 43 --learning_rate 2e-4 --max_steps 500
run_one "qlora_seed42_lr1e4" --seed 42 --learning_rate 1e-4 --max_steps 500

echo "Done. Check runs/qlora_* for adapters."

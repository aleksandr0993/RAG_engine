#!/usr/bin/env python3
"""
QLoRA SFT для Linux/GPU (облако). На macOS без CUDA bitsandbytes обычно недоступен —
запускайте в Docker или на GPU-инстансе.

Пример:
  accelerate launch training/train_qlora.py \\
    --model_name Qwen/Qwen2.5-7B-Instruct \\
    --dataset_jsonl data/sft/train_val.jsonl \\
    --output_dir runs/qlora-run1 \\
    --max_steps 500
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import Dataset


def main() -> None:
    import torch
    from peft import LoraConfig, TaskType
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from trl import SFTTrainer

    p = argparse.ArgumentParser()
    p.add_argument("--model_name", required=True)
    p.add_argument("--dataset_jsonl", required=True, type=Path)
    p.add_argument("--output_dir", required=True, type=Path)
    p.add_argument("--max_seq_length", type=int, default=2048)
    p.add_argument("--max_steps", type=int, default=500)
    p.add_argument("--learning_rate", type=float, default=2e-4)
    p.add_argument("--per_device_train_batch_size", type=int, default=1)
    p.add_argument("--gradient_accumulation_steps", type=int, default=8)
    p.add_argument("--lora_r", type=int, default=32)
    p.add_argument("--lora_alpha", type=int, default=64)
    p.add_argument("--lora_dropout", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rows: list[dict] = []
    with args.dataset_jsonl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    ds = Dataset.from_list(rows)
    original_columns = list(ds.column_names)

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def add_text(batch: dict) -> dict:
        texts = [
            tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            for msgs in batch["messages"]
        ]
        return {"text": texts}

    ds = ds.map(add_text, batched=True, remove_columns=original_columns)

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )

    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        warmup_ratio=0.03,
        logging_steps=10,
        save_steps=100,
        seed=args.seed,
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=True,
        report_to="none",
        remove_unused_columns=False,
    )

    common = dict(
        model=model,
        args=training_args,
        train_dataset=ds,
        peft_config=peft_config,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
    )
    try:
        trainer = SFTTrainer(processing_class=tokenizer, **common)
    except TypeError:
        trainer = SFTTrainer(tokenizer=tokenizer, **common)
    trainer.train()
    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    print(f"Saved adapter and tokenizer to {args.output_dir}")


if __name__ == "__main__":
    main()

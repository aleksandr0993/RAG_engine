#!/usr/bin/env python3
"""Прогон тестового split: normalized JSONL → pred.jsonl для evaluate.py."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.guardrails import validate_raw_by_format  # noqa: E402
from homework_reviewer_llm.prompts import build_user_prompt_ru, system_prompt_for_format  # noqa: E402
from homework_reviewer_llm.schema import NormalizedRecord  # noqa: E402


def main() -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    p = argparse.ArgumentParser()
    p.add_argument("--model_name", required=True)
    p.add_argument("--adapter_path", type=Path, default=None)
    p.add_argument("--input-jsonl", required=True, type=Path, help="test.jsonl / hard.jsonl")
    p.add_argument("--output-jsonl", required=True, type=Path)
    p.add_argument("--output-format", choices=("v1", "v2"), default="v1")
    p.add_argument("--max_new_tokens", type=int, default=1024)
    p.add_argument(
        "--guardrail-stats",
        action="store_true",
        help="В stderr: число записей, не прошедших guardrails/парсинг",
    )
    args = p.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if args.adapter_path is None:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_name, device_map="auto", trust_remote_code=True
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_name,
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(model, str(args.adapter_path))

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    guardrail_fail = 0
    system = system_prompt_for_format(args.output_format)
    with args.input_jsonl.open(encoding="utf-8") as fin, args.output_jsonl.open(
        "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = NormalizedRecord.model_validate_json(line)
            user = build_user_prompt_ru(
                assignment_prompt=rec.assignment_prompt,
                rubric_text=rec.rubric_text,
                submission_text=rec.submission_text,
                revision_history=rec.revision_history,
                student_profile=rec.student_profile,
                output_format=args.output_format,
            )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(prompt, return_tensors="pt")
            if torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
            gen = tokenizer.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)
            raw = gen.strip()
            fout.write(json.dumps({"id": rec.id, "raw": raw}, ensure_ascii=False) + "\n")
            if args.guardrail_stats:
                gr, _err = validate_raw_by_format(raw, output_format=args.output_format)
                if not gr.ok:
                    guardrail_fail += 1

    print("Wrote", args.output_jsonl)
    if args.guardrail_stats:
        print(f"# guardrail_failures: {guardrail_fail}", file=sys.stderr)


if __name__ == "__main__":
    main()

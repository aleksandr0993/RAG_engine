#!/usr/bin/env python3
"""
MVP: сгенерировать ревью (JSON v1 или гибрид v2) по одной работе.

Пример:
  python scripts/inference_mvp.py \\
    --model_name Qwen/Qwen2.5-7B-Instruct \\
    --adapter_path runs/qlora-run1 \\
    --submission_file data/samples/submission.txt \\
    --assignment_file data/samples/assignment.txt \\
    --output-format v2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from homework_reviewer_llm.guardrails import validate_raw_by_format  # noqa: E402
from homework_reviewer_llm.prompts import build_user_prompt_ru, system_prompt_for_format  # noqa: E402
from homework_reviewer_llm.schema import try_parse_review_json, try_parse_review_json_v2  # noqa: E402


def main() -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    p = argparse.ArgumentParser()
    p.add_argument("--model_name", required=True)
    p.add_argument("--adapter_path", type=Path, default=None, help="Каталог с LoRA-адаптером")
    p.add_argument("--submission_file", required=True, type=Path)
    p.add_argument("--assignment_file", type=Path)
    p.add_argument("--rubric_file", type=Path)
    p.add_argument("--revision_history_file", type=Path)
    p.add_argument("--student_profile_file", type=Path)
    p.add_argument("--output-format", choices=("v1", "v2"), default="v1")
    p.add_argument("--max_new_tokens", type=int, default=1024)
    p.add_argument("--device_map", default="auto")
    p.add_argument(
        "--guardrails",
        action="store_true",
        help="Проверить ответ через guardrails (stderr)",
    )
    p.add_argument(
        "--fail-on-guardrails",
        action="store_true",
        help="Код выхода 2 при нарушении guardrails после успешного JSON-парса",
    )
    args = p.parse_args()

    submission = args.submission_file.read_text(encoding="utf-8")
    assignment = args.assignment_file.read_text(encoding="utf-8") if args.assignment_file else None
    rubric = args.rubric_file.read_text(encoding="utf-8") if args.rubric_file else None
    rev = (
        args.revision_history_file.read_text(encoding="utf-8")
        if args.revision_history_file
        else None
    )
    prof = (
        args.student_profile_file.read_text(encoding="utf-8")
        if args.student_profile_file
        else None
    )

    user = build_user_prompt_ru(
        assignment_prompt=assignment,
        rubric_text=rubric,
        submission_text=submission,
        revision_history=rev,
        student_profile=prof,
        output_format=args.output_format,
    )
    system = system_prompt_for_format(args.output_format)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if args.adapter_path is None:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_name,
            device_map=args.device_map,
            trust_remote_code=True,
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_name,
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map=args.device_map,
            trust_remote_code=True,
        )
        model = PeftModel.from_pretrained(model, str(args.adapter_path))

    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(prompt, return_tensors="pt")
    if torch.cuda.is_available():
        inputs = {k: v.cuda() for k, v in inputs.items()}

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )
    gen = tokenizer.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)
    print(gen.strip())

    if args.output_format == "v2":
        parsed, err = try_parse_review_json_v2(gen)
        score = parsed.overall_score if parsed else None
    else:
        parsed, err = try_parse_review_json(gen)
        score = parsed.overall_score if parsed else None

    if err:
        print("\n# parse_warning:", err, file=sys.stderr)
    else:
        print("\n# json_ok overall_score=", score, file=sys.stderr)
        if args.guardrails or args.fail_on_guardrails:
            gr, _pe = validate_raw_by_format(gen, output_format=args.output_format)
            for w in gr.warnings:
                print("# guardrail_warning:", w, file=sys.stderr)
            for e in gr.errors:
                print("# guardrail_error:", e, file=sys.stderr)
            if args.fail_on_guardrails and not gr.ok:
                raise SystemExit(2)


if __name__ == "__main__":
    main()

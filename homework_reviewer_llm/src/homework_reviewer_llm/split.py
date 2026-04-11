"""Разбиение train/val/test без утечки по student_id и assignment_id."""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict

from homework_reviewer_llm.schema import NormalizedRecord


def _stable_float(seed: str, key: str) -> float:
    h = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(h[:12], 16) / float(0xFFFFFFFFFFFF)


def leak_safe_split(
    records: list[NormalizedRecord],
    *,
    seed: str = "homework-reviewer-llm",
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    holdout_assignments_ratio: float = 0.0,
) -> list[NormalizedRecord]:
    """
    Студент не попадает одновременно в train и val/test.
    Если holdout_assignments_ratio > 0, часть заданий целиком уходит только в test
    (assignment_id не встречается в train/val).
    """
    if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-6:
        raise ValueError("train_ratio + val_ratio + test_ratio must equal 1.0")

    by_student: dict[str, list[NormalizedRecord]] = defaultdict(list)
    for r in records:
        by_student[r.student_id].append(r)

    student_ids = sorted(by_student.keys())
    rng = random.Random(seed)
    rng.shuffle(student_ids)

    n = len(student_ids)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    train_students = set(student_ids[:n_train])
    val_students = set(student_ids[n_train : n_train + n_val])
    test_students = set(student_ids[n_train + n_val :])

    assignment_test_only: set[str] = set()
    if holdout_assignments_ratio > 0:
        all_aids = sorted({r.assignment_id for r in records})
        for aid in all_aids:
            if _stable_float(seed, f"aid:{aid}") < holdout_assignments_ratio:
                assignment_test_only.add(aid)

    out: list[NormalizedRecord] = []
    for r in records:
        if r.student_id in train_students:
            split = "train"
        elif r.student_id in val_students:
            split = "val"
        else:
            split = "test"

        # Все работы по этому assignment_id только в test (нет задания в train/val).
        if r.assignment_id in assignment_test_only:
            split = "test"

        out.append(r.model_copy(update={"split": split}))
    return out


def leak_safe_split_strict_both(
    records: list[NormalizedRecord],
    *,
    seed: str = "homework-reviewer-llm-strict",
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    test_assignment_pool_ratio: float = 0.35,
) -> tuple[list[NormalizedRecord], int]:
    """
    Одновременно:
    - студенты train/val/test не пересекаются;
    - задания делятся на train_pool и test_pool (непересекающиеся множества assignment_id);
    - train: только train_students × train_pool;
    - val: только val_students × train_pool;
    - test: только test_students × test_pool.

    Строки вне этих комбинаций отбрасываются (возвращается их число как второй элемент).
    """
    if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-6:
        raise ValueError("train_ratio + val_ratio + test_ratio must equal 1.0")

    student_ids = sorted({r.student_id for r in records})
    rng = random.Random(seed)
    rng.shuffle(student_ids)
    n = len(student_ids)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    train_students = set(student_ids[:n_train])
    val_students = set(student_ids[n_train : n_train + n_val])
    test_students = set(student_ids[n_train + n_val :])

    all_aids = sorted({r.assignment_id for r in records})
    if len(all_aids) < 2:
        raise ValueError("leak_safe_split_strict_both requires at least 2 distinct assignment_id values")
    rng.shuffle(all_aids)
    n_test_a = max(1, int(round(len(all_aids) * test_assignment_pool_ratio)))
    n_test_a = min(n_test_a, len(all_aids) - 1)
    test_assignments = set(all_aids[:n_test_a])
    train_assignments = set(all_aids[n_test_a:])

    out: list[NormalizedRecord] = []
    dropped = 0
    for r in records:
        st, aid = r.student_id, r.assignment_id
        if st in train_students and aid in train_assignments:
            split = "train"
        elif st in val_students and aid in train_assignments:
            split = "val"
        elif st in test_students and aid in test_assignments and test_assignments:
            split = "test"
        else:
            dropped += 1
            continue
        out.append(r.model_copy(update={"split": split}))
    return out, dropped


def mark_hard_subset(
    records: list[NormalizedRecord],
    *,
    seed: str = "hard",
    fraction: float = 0.05,
) -> list[NormalizedRecord]:
    """Помечает часть записей split=hard (для стресс-теста), только из test."""
    result: list[NormalizedRecord] = []
    for r in records:
        if r.split != "test":
            result.append(r)
            continue
        if _stable_float(seed, r.id) < fraction:
            result.append(r.model_copy(update={"split": "hard"}))
        else:
            result.append(r)
    return result

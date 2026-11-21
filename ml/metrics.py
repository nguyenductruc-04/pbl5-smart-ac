"""Chi so danh gia cho bai toan 3 lop (am hon / giu nguyen / mat hon)."""
from __future__ import annotations

import math
from collections.abc import Sequence

NAMES = ("am hon", "giu nguyen", "mat hon")


def accuracy(y: Sequence[int], pred: Sequence[int]) -> float:
    return sum(a == b for a, b in zip(y, pred, strict=True)) / len(y)


def macro_f1(y: Sequence[int], pred: Sequence[int], k: int = 3) -> float:
    """Trung binh F1 cua tung lop: khong bi "dep gia" khi mot lop chiem da so."""
    f1s = []
    for c in range(k):
        tp = sum(1 for a, b in zip(y, pred, strict=True) if a == c and b == c)
        fp = sum(1 for a, b in zip(y, pred, strict=True) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, pred, strict=True) if a == c and b != c)
        if tp + fp + fn == 0:
            continue
        f1s.append(2 * tp / (2 * tp + fp + fn))
    return sum(f1s) / len(f1s)


def log_loss(y: Sequence[int], proba: Sequence[Sequence[float]]) -> float:
    """Phat nang khi mo hinh tu tin ma sai. Thap hon = tot hon. Doan bua 3 lop deu nhau = ln 3 = 1.10."""
    return -sum(math.log(max(p[c], 1e-12)) for c, p in zip(y, proba, strict=True)) / len(y)


def confusion(y: Sequence[int], pred: Sequence[int], k: int = 3) -> list[list[int]]:
    m = [[0] * k for _ in range(k)]
    for a, b in zip(y, pred, strict=True):
        m[a][b] += 1
    return m


def summarize(y: Sequence[int], proba: Sequence[Sequence[float]]) -> dict:
    pred = [max(range(3), key=lambda c, p=p: p[c]) for p in proba]
    return {"n": len(y), "accuracy": accuracy(y, pred), "macro_f1": macro_f1(y, pred),
            "log_loss": log_loss(y, proba)}

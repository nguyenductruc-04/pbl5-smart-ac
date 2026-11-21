"""
Danh gia trung thuc mo hinh ca nhan hoa tren phieu cam nhan cua nguoi dung.

    python ml/evaluate_personal.py --db ~/pbl5-smart-ac/gateway/pbl5.db --room room01

Cach danh gia "tuan tu" (prequential): voi moi phieu, mo hinh chi duoc hoc tu cac phieu TRUOC no,
roi doan phieu do. Giong het cach he thong dung that ngoai doi, va khong bao gio dung tuong lai de doan qua khu.

So sanh 4 cach doan:
  personal    mo hinh chung + lech ca nhan hoc tu phieu truoc do (cai he thong dung)
  population  chi mo hinh chung tu ASHRAE (khong ca nhan hoa)
  majority    lop ma nguoi nay hay chon nhat cho toi luc do
  band_23_26  luat co dinh: <23 do muon am hon, >26 do muon mat hon
Ket qua ghi vao docs/ml/personal-evaluation.md (+ .png).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "ml"))

from comfort import load_prior, personalize  # noqa: E402
from metrics import confusion, summarize  # noqa: E402
from votes import load_votes, synthetic_info  # noqa: E402

MIN_VOTES = 20


def band_rule(ta: float) -> list[float]:
    k = 0 if ta < 23 else 2 if ta > 26 else 1
    p = [0.2, 0.2, 0.2]
    p[k] = 0.6
    return p


def prequential(votes):
    prior, _ = load_prior()
    preds = {"personal": [], "population": [], "majority": [], "band_23_26": []}
    trace = []
    counts = [1, 1, 1]                               # lam tron Laplace cho moc "majority"
    for i, v in enumerate(votes):
        pers = personalize(prior, votes[:i], now=v.ts)
        preds["personal"].append(pers.model.proba(v.ta, v.rh))
        preds["population"].append(prior.proba(v.ta, v.rh))
        total = sum(counts)
        preds["majority"].append([c / total for c in counts])
        preds["band_23_26"].append(band_rule(v.ta))
        counts[v.cls] += 1
        trace.append((i, pers.shift, pers.shift_sd))
    final = personalize(prior, votes, now=votes[-1].ts)
    return prior, preds, trace, final


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--room", default="room01")
    ap.add_argument("--out", default=str(ROOT / "docs" / "ml" / "personal-evaluation.md"))
    args = ap.parse_args()

    votes = load_votes(args.db, args.room)
    synth = synthetic_info(args.db)
    if len(votes) < 2:
        sys.exit(f"Moi co {len(votes)} phieu. Can it nhat {MIN_VOTES} phieu de danh gia co y nghia.")
    if len(votes) < MIN_VOTES:
        print(f"CANH BAO: chi co {len(votes)} phieu (< {MIN_VOTES}), ket qua chua dang tin.")

    prior, preds, trace, final = prequential(votes)
    y = [v.cls for v in votes]
    table = {name: summarize(y, p) for name, p in preds.items()}
    for name, r in table.items():
        print(f"{name:11} acc={r['accuracy']:.3f} macroF1={r['macro_f1']:.3f} logloss={r['log_loss']:.3f}")
    print(f"Lech ca nhan cuoi cung: {final.shift:+.2f} +- {final.shift_sd:.2f} do C, do nhay {final.scale:.2f}"
          f" ({len(votes)} phieu)")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig_path = out.with_suffix(".png")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.4))
    xs = [t[0] for t in trace]
    a1.plot(xs, [t[1] for t in trace], color="#0A6C8C", linewidth=2, label="Ước lượng")
    a1.fill_between(xs, [t[1] - t[2] for t in trace], [t[1] + t[2] for t in trace], color="#0A6C8C", alpha=0.15)
    if synth and "true_shift_c" in synth:
        a1.axhline(float(synth["true_shift_c"]), color="#B5530E", linestyle="--", label="Giá trị thật (mô phỏng)")
    a1.set_xlabel("Số phiếu đã có")
    a1.set_ylabel("Lệch cá nhân (°C)")
    a1.legend(fontsize=8)
    a1.grid(alpha=0.25)
    for name, color in (("personal", "#0A6C8C"), ("population", "#6C7C86"), ("majority", "#C2601A")):
        cum, acc = [], 0.0
        for i, (c, p) in enumerate(zip(y, preds[name], strict=True)):
            acc += -__import__("math").log(max(p[c], 1e-12))
            cum.append(acc / (i + 1))
        a2.plot(range(len(cum)), cum, color=color, linewidth=2, label=name)
    a2.set_xlabel("Số phiếu đã có")
    a2.set_ylabel("Log-loss trung bình (thấp hơn là tốt)")
    a2.legend(fontsize=8)
    a2.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_path, dpi=150)

    rows = "\n".join(f"| {n} | {r['accuracy']:.3f} | {r['macro_f1']:.3f} | {r['log_loss']:.3f} |"
                     for n, r in table.items())
    pred_p = [max(range(3), key=lambda c, p=p: p[c]) for p in preds["personal"]]
    cm = confusion(y, pred_p)
    counts = [y.count(c) for c in range(3)]
    span_days = (votes[-1].ts - votes[0].ts) / 86400
    warn = ""
    if synth:
        warn = (f"\n> **DỮ LIỆU MÔ PHỎNG.** Phiếu được sinh bởi `ml/simulate_votes.py` (lệch thật "
                f"{synth.get('true_shift_c')} °C, độ nhạy thật {synth.get('true_scale', '?')}). Kết quả chỉ chứng minh quy trình hoạt động đúng, "
                "không chứng minh mô hình hợp với người thật.\n")
    elif len(votes) < MIN_VOTES:
        warn = f"\n> **Chưa đủ dữ liệu:** mới có {len(votes)} phiếu (cần ít nhất {MIN_VOTES}).\n"
    rh_now = votes[-1].rh
    lo, hi = final.model.comfort_band(rh_now)
    out.write_text(f"""# Đánh giá mô hình cá nhân hóa

Sinh tự động bởi `ml/evaluate_personal.py`. Đừng sửa tay.
{warn}
- Dữ liệu: {len(votes)} phiếu của phòng `{args.room}` trong {span_days:.1f} ngày. Muốn ấm hơn: {counts[0]}, dễ chịu: {counts[1]}, muốn mát hơn: {counts[2]}.
- Cách đánh giá: tuần tự (prequential). Mỗi phiếu được đoán bằng mô hình chỉ học từ các phiếu trước nó.

## Kết quả

| Cách đoán | Accuracy | Macro-F1 | Log-loss |
|---|---|---|---|
{rows}

`personal`: mô hình hệ thống dùng. `population`: chỉ mô hình chung từ ASHRAE. `majority`: lớp người này hay chọn nhất cho tới lúc đó. `band_23_26`: luật cố định.

Ma trận nhầm lẫn của `personal` (hàng: thật, cột: đoán; thứ tự ấm hơn / dễ chịu / mát hơn): `{cm}`.

## Sở thích đã học

- Lệch so với người trung bình: **{final.shift:+.2f} ± {final.shift_sd:.2f} °C** (dương: thích ấm hơn). Độ nhạy: {final.scale:.2f} lần đám đông.
- Ở độ ẩm {rh_now:.0f} %: nhiệt độ trung tính {final.model.neutral_temp(rh_now):.1f} °C, vùng dễ chịu {lo:.1f}–{hi:.1f} °C.

![Lệch cá nhân và log-loss theo số phiếu](personal-evaluation.png)
""", encoding="utf-8")
    print(f"Da ghi {out}")


if __name__ == "__main__":
    main()

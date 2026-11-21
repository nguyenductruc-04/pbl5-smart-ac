"""
Hoc MO HINH CHUNG tu ASHRAE DB II va danh gia trung thuc truoc khi dung lam nen cho ca nhan hoa.

    pip install -r ml/requirements.txt
    python ml/train_prior.py            # ghi gateway/comfort_prior.json va docs/ml/population-model.md

Danh gia: kiem dinh cheo 5 phan CHIA THEO TOA NHA (khong de cung toa nha vua o train vua o test),
so voi hai moc don gian: luon doan lop pho bien nhat, va mot luat nguong co dinh 23-26 do C.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import matplotlib
import numpy as np
from scipy.optimize import minimize

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "ml"))

import ashrae  # noqa: E402
from comfort import ComfortModel  # noqa: E402
from metrics import summarize  # noqa: E402

T_REF, H_REF = 26.0, 60.0
OUT_JSON = ROOT / "gateway" / "comfort_prior.json"
OUT_DOC = ROOT / "docs" / "ml" / "population-model.md"
OUT_FIG = ROOT / "docs" / "ml" / "population-model.png"


def _unpack(p):
    w_t, w_h, theta0, log_gap = p
    return w_t, w_h, theta0, theta0 + np.exp(log_gap)


def _nll(p, ta, rh, cls):
    w_t, w_h, t0, t1 = _unpack(p)
    z = w_t * (ta - T_REF) + w_h * (rh - H_REF) / 10.0
    c0 = 1 / (1 + np.exp(-(t0 - z)))
    c1 = 1 / (1 + np.exp(-(t1 - z)))
    probs = np.stack([c0, c1 - c0, 1 - c1], axis=1)
    return -np.mean(np.log(np.clip(probs[np.arange(len(cls)), cls], 1e-12, None)))


def fit(ta, rh, cls) -> ComfortModel:
    res = minimize(_nll, x0=np.array([0.3, 0.0, -1.0, 0.7]), args=(ta, rh, cls), method="L-BFGS-B")
    w_t, w_h, t0, t1 = _unpack(res.x)
    return ComfortModel(float(w_t), float(w_h), float(t0), float(t1), T_REF, H_REF)


def baseline_majority(train_cls, n):
    counts = np.bincount(train_cls, minlength=3) / len(train_cls)
    return [list(counts)] * n


def baseline_band(ta, lo=23.0, hi=26.0, conf=0.6):
    """Luat co dinh: duoi 23 do muon am hon, tren 26 do muon mat hon, con lai giu nguyen."""
    out = []
    other = (1 - conf) / 2
    for t in ta:
        k = 0 if t < lo else 2 if t > hi else 1
        p = [other] * 3
        p[k] = conf
        out.append(p)
    return out


def grouped_folds(groups, k=5, seed=0):
    rng = np.random.default_rng(seed)
    uniq = rng.permutation(np.unique(groups))
    for i in range(k):
        test_groups = set(uniq[i::k])
        mask = np.array([g in test_groups for g in groups])
        yield ~mask, mask


def main() -> None:
    df = ashrae.load()
    ta, rh, cls, groups = df.ta.to_numpy(), df.rh.to_numpy(), df.cls.to_numpy(), df.building_id.to_numpy()
    print(f"{len(df)} phieu, {len(np.unique(groups))} toa nha")

    results = {"model": [], "majority": [], "band_23_26": []}
    for tr, te in grouped_folds(groups):
        m = fit(ta[tr], rh[tr], cls[tr])
        y = cls[te].tolist()
        results["model"].append(summarize(y, [m.proba(a, b) for a, b in zip(ta[te], rh[te], strict=True)]))
        results["majority"].append(summarize(y, baseline_majority(cls[tr], len(y))))
        results["band_23_26"].append(summarize(y, baseline_band(ta[te])))
    table = {name: {k: float(np.mean([r[k] for r in rs])) for k in ("accuracy", "macro_f1", "log_loss")}
             for name, rs in results.items()}
    for name, row in table.items():
        print(f"{name:12} acc={row['accuracy']:.3f} macroF1={row['macro_f1']:.3f} logloss={row['log_loss']:.3f}")

    model = fit(ta, rh, cls)
    info = {
        "dataset": "ASHRAE Global Thermal Comfort Database II v2.1.0",
        "source": f"https://github.com/{ashrae.REPO}/tree/{ashrae.COMMIT}",
        "doi": "10.6078/D1F671",
        "subset": "thermal_preference with ta and rh; climates: " + ", ".join(ashrae.CLIMATES),
        "n_votes": int(len(df)), "n_buildings": int(len(np.unique(groups))),
        "trained": date.today().isoformat(),
        "cv_building_grouped_5fold": table,
        "params": model.as_dict(),
    }
    OUT_JSON.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"Da ghi {OUT_JSON}")
    write_report(df, model, table)


def write_report(df, model: ComfortModel, table: dict) -> None:
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    temps = np.linspace(18, 34, 161)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, rh in zip(axes, (50, 75), strict=True):
        probs = np.array([model.proba(t, rh) for t in temps])
        for i, (label, color) in enumerate((("Muốn ấm hơn", "#C2601A"), ("Giữ nguyên", "#6C7C86"),
                                            ("Muốn mát hơn", "#0E7FA6"))):
            ax.plot(temps, probs[:, i], color=color, linewidth=2, label=label)
        bins = np.arange(18, 35, 1.0)
        sub = df[(df.rh - rh).abs() <= 10]
        idx = np.digitize(sub.ta, bins)
        for c, color in ((0, "#C2601A"), (1, "#6C7C86"), (2, "#0E7FA6")):
            xs, ys = [], []
            for b in range(1, len(bins)):
                sel = sub.cls[idx == b]
                if len(sel) >= 30:
                    xs.append(bins[b - 1] + 0.5)
                    ys.append((sel == c).mean())
            ax.scatter(xs, ys, color=color, s=14, alpha=0.6)
        lo, hi = model.comfort_band(rh)
        ax.axvspan(lo, hi, color="#1D7443", alpha=0.08, label="Vùng dễ chịu")
        ax.set_title(f"Độ ẩm {rh} % (đường: mô hình, chấm: tỷ lệ thực tế)", fontsize=10)
        ax.set_xlabel("Nhiệt độ không khí (°C)")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Xác suất")
    axes[0].legend(fontsize=8, loc="center left")
    fig.tight_layout()
    fig.savefig(OUT_FIG, dpi=150)

    rows = "\n".join(
        f"| {name} | {r['accuracy']:.3f} | {r['macro_f1']:.3f} | {r['log_loss']:.3f} |"
        for name, r in table.items())
    bands = "\n".join(
        f"| {rh} % | {model.neutral_temp(rh):.1f} °C | {model.comfort_band(rh)[0]:.1f}–{model.comfort_band(rh)[1]:.1f} °C"
        f" | {model.setpoint(rh, 16, 30)} °C |"
        for rh in (40, 60, 80))
    OUT_DOC.write_text(f"""# Mô hình chung (population model)

Sinh tự động bởi `ml/train_prior.py`. Đừng sửa tay.

- Dữ liệu: ASHRAE Global Thermal Comfort Database II v2.1.0 ([DOI 10.6078/D1F671](https://doi.org/10.6078/D1F671)), {len(df)} phiếu "muốn ấm hơn / giữ nguyên / muốn mát hơn" có nhiệt độ và độ ẩm, ở {df.building_id.nunique()} tòa nhà thuộc vùng khí hậu nhiệt đới và cận nhiệt đới gió mùa.
- Mô hình: hồi quy logistic thứ bậc, đầu vào nhiệt độ không khí và độ ẩm. Tham số: `w_t={model.w_t:.3f}` /°C, `w_h={model.w_h:.3f}` /10 %RH, ngưỡng `{model.theta0:.3f}`, `{model.theta1:.3f}`.

## Đánh giá (kiểm định chéo 5 phần, chia theo tòa nhà)

| Cách đoán | Accuracy | Macro-F1 | Log-loss |
|---|---|---|---|
{rows}

`majority`: luôn đoán lớp phổ biến nhất. `band_23_26`: luật cố định (dưới 23 °C muốn ấm hơn, trên 26 °C muốn mát hơn). Log-loss thấp hơn là tốt hơn; đoán bừa ba lớp đều nhau cho ln 3 ≈ 1,10.

Mô hình chung không đoán được nhiều cho từng người: cùng một nhiệt độ, người này muốn mát hơn, người kia muốn giữ nguyên. Đó là lý do hệ thống cá nhân hóa bằng phiếu của chính người dùng.

## Nhiệt độ dễ chịu theo mô hình chung

| Độ ẩm | Nhiệt độ trung tính | Vùng dễ chịu | Nhiệt độ đặt gợi ý |
|---|---|---|---|
{bands}

*Nhiệt độ trung tính*: nơi khả năng "muốn ấm hơn" và "muốn mát hơn" bằng nhau. *Vùng dễ chịu*: khả năng muốn đổi theo mỗi hướng không quá 30 %. *Nhiệt độ đặt gợi ý*: mức ấm nhất còn trong vùng dễ chịu, để tiết kiệm điện.

Hệ số độ ẩm gần bằng 0: trong dữ liệu này, độ ẩm gần như không làm đổi mong muốn khi đã biết nhiệt độ. Mô hình vẫn giữ biến này để cá nhân hóa sau.

![Xác suất theo nhiệt độ](population-model.png)
""", encoding="utf-8")
    print(f"Da ghi {OUT_DOC}")


if __name__ == "__main__":
    main()

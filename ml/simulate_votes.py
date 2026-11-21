"""
Tao mot BAN SAO database co them phieu cam nhan MO PHONG, de thu toan bo quy trinh khi chua du phieu that.

    python ml/simulate_votes.py --src ~/pbl5-smart-ac/gateway/pbl5.db --out /tmp/sim.db --shift 1.5 --n 80

- KHONG BAO GIO ghi vao database goc: --out phai la file chua ton tai.
- "Nguoi dung ao" tra loi theo mo hinh chung lech `--shift` do C (duong = thich am hon) va nhay hon
  dam dong `--scale` lan.
- Dung nhiet do / do am THAT trong telemetry cua database nguon neu co; khong co thi tu sinh.
- Database moi duoc danh dau la mo phong (bang ml_meta) -> bao cao danh gia se ghi ro.
Ket qua tren du lieu mo phong chi chung minh QUY TRINH dung, khong chung minh mo hinh hop voi nguoi that.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "ml"))

import store  # noqa: E402
from comfort import CLASSES, load_prior  # noqa: E402
from votes import META_SQL  # noqa: E402

CODE = {0: 1, 1: 0, 2: -1}          # chi so lop -> ma luu trong DB


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="database cua gateway (chi doc)")
    ap.add_argument("--out", required=True, help="file database moi (phai chua ton tai)")
    ap.add_argument("--room", default="room01")
    ap.add_argument("--shift", type=float, default=1.5, help="so thich that cua nguoi ao (do C)")
    ap.add_argument("--scale", type=float, default=2.5,
                    help="do nhay cua nguoi ao: mot nguoi nhat quan hon ca dam dong (>1)")
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--days", type=float, default=14)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} da ton tai. Chon ten file khac (khong ghi de).")
    if out.resolve() == Path(args.src).resolve():
        sys.exit("--out trung --src: tu choi ghi vao database goc.")

    src = sqlite3.connect(f"file:{args.src}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()
    store.init(dst)
    dst.execute(META_SQL)
    # Ban sao chi chua phieu MO PHONG: bo phieu that (neu co) de ket qua khong bi lan
    dst.execute("DELETE FROM comfort_votes")

    rng = random.Random(args.seed)
    prior, _ = load_prior()
    person = replace(prior, shift=args.shift, scale=args.scale)
    rows = dst.execute("SELECT ts, temp, hum FROM telemetry WHERE room=? AND simulated=0 ORDER BY ts",
                       (args.room,)).fetchall()
    if len(rows) < 50:
        print("Telemetry that qua it -> tu sinh nhiet do 24-33 do C")
        now = __import__("time").time()
        rows = [(now - rng.uniform(0, args.days * 86400), rng.uniform(24, 33), rng.uniform(55, 85))
                for _ in range(args.n * 5)]
    picks = sorted(rng.sample(rows, min(args.n, len(rows))))
    counts = [0, 0, 0]
    for ts, ta, rh in picks:
        p = person.proba(ta, rh)
        cls = rng.choices(range(3), weights=p)[0]
        counts[cls] += 1
        dst.execute("INSERT INTO comfort_votes(ts, room, vote, temp, hum, presence, telemetry_age_s)"
                    " VALUES (?,?,?,?,?,1,0)", (ts, args.room, CODE[cls], ta, rh))
    dst.executemany("INSERT OR REPLACE INTO ml_meta(key, value) VALUES (?,?)",
                    [("synthetic", "1"), ("true_shift_c", str(args.shift)),
                     ("true_scale", str(args.scale)), ("seed", str(args.seed))])
    dst.commit()
    dst.close()
    print(f"Da tao {out}: {len(picks)} phieu mo phong (" +
          ", ".join(f"{CLASSES[i]}={counts[i]}" for i in range(3)) + f"), shift that = {args.shift} do C")


if __name__ == "__main__":
    main()

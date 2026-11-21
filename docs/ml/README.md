# Mô hình tiện nghi (M6)

Thiết kế: [ADR 0004](../adr/0004-comfort-model.md). Mã chạy trên Pi: `gateway/comfort.py`, `gateway/advisor.py`. Mã chạy trên laptop: `ml/`.

## Học lại mô hình chung (không bắt buộc)

`gateway/comfort_prior.json` đã có sẵn trong repo. Chỉ cần chạy lại nếu đổi cách lọc dữ liệu:

```bash
pip install -r ml/requirements.txt
python ml/train_prior.py
```

Script tải bộ ASHRAE DB II từ kho của nhóm tác giả (commit cố định) vào `ml/data/` (không commit), rồi ghi `gateway/comfort_prior.json` và `docs/ml/population-model.md`.

## Đánh giá trên phiếu thật

Chép database từ Pi về laptop (chỉ đọc, không ảnh hưởng hệ thống đang chạy):

```bash
scp pi:pbl5-smart-ac/gateway/pbl5.db ./pbl5-copy.db
python ml/evaluate_personal.py --db pbl5-copy.db --room room01
```

Kết quả ghi vào `docs/ml/personal-evaluation.md` và `.png`. Cần ít nhất 20 phiếu; báo cáo tự ghi rõ nếu chưa đủ.

## Thử quy trình bằng dữ liệu mô phỏng

```bash
python ml/simulate_votes.py --src pbl5-copy.db --out sim.db --shift 1.5 --n 80
python ml/evaluate_personal.py --db sim.db --out docs/ml/personal-evaluation-synthetic.md
```

`simulate_votes.py` không bao giờ ghi vào database gốc. Báo cáo sinh từ database mô phỏng được đánh dấu **DỮ LIỆU MÔ PHỎNG**: nó chỉ chứng minh quy trình chạy đúng, không phải kết quả với người thật.

## Trích dẫn dữ liệu

Parkinson T., Tartarini F., Földváry Ličina V. et al. (2022). *ASHRAE global database of thermal comfort field measurements* [Dataset]. Dryad. https://doi.org/10.6078/D1F671

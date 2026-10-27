# PBL5 – Milestone 1: ESP32-S3 ⇄ MQTT ⇄ Raspberry Pi

Mục tiêu của bước này là thông đường truyền hai chiều trước khi lắp cảm biến và mạch IR:

```
ESP32-S3 ──telemetry──► Mosquitto (Pi) ──► gateway.py ──► SQLite
ESP32-S3 ◄──command──── Mosquitto (Pi) ◄── send_command.py
ESP32-S3 ──command_result──► Pi  (đo được độ trễ lệnh)
```

Chưa có cảm biến SHT41 thì ESP32 tự gửi **dữ liệu giả lập** (`"sim": true`), nên bạn test được ngay.

```
pbl5/
├── firmware/room_node/      # Sketch Arduino cho ESP32-S3
│   ├── room_node.ino
│   └── config.h             # SỬA Wi-Fi, IP Pi, mật khẩu MQTT ở đây
└── gateway/                 # Chạy trên Raspberry Pi
    ├── mosquitto/pbl5.conf  # cấu hình broker
    ├── mosquitto/acl        # phân quyền topic
    ├── gateway.py           # nhận dữ liệu, kiểm tra, lưu SQLite
    ├── send_command.py      # gửi lệnh thử, đo độ trễ
    ├── simulate_node.py     # node giả lập (test Pi khi chưa nạp ESP32)
    ├── show_data.py         # xem nhanh dữ liệu đã lưu
    ├── settings.py, .env.example, requirements.txt
    └── pbl5-gateway.service # chạy gateway tự động khi Pi khởi động
```

---

## Bước 1 – Chuẩn bị Raspberry Pi

1. Dùng **Raspberry Pi Imager** cài **Raspberry Pi OS Lite (64-bit)**. Trong phần cài đặt nâng cao: đặt hostname `pbl5-gateway`, username `pi`, bật SSH, nhập Wi-Fi.
2. Trên máy tính: `ssh pi@pbl5-gateway.local`
3. Xem IP của Pi bằng lệnh `hostname -I`. Nên vào router đặt **IP cố định (DHCP reservation)** cho Pi, vì ESP32 sẽ kết nối tới IP này.
4. Cài gói cần thiết:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y mosquitto mosquitto-clients python3-venv sqlite3 git
```

## Bước 2 – Copy project lên Pi

Giải nén file zip trên máy tính, rồi từ thư mục chứa `pbl5`:

```bash
scp -r pbl5-smart-ac pi@pbl5-gateway.local:~/
```

## Bước 3 – Cấu hình Mosquitto (broker MQTT)

```bash
cd ~/pbl5-smart-ac/gateway

# Tạo tài khoản: 'gateway' cho Pi, 'room01' cho node phòng 1 (sẽ hỏi mật khẩu)
sudo mosquitto_passwd -c /etc/mosquitto/passwd gateway
sudo mosquitto_passwd /etc/mosquitto/passwd room01

sudo cp mosquitto/pbl5.conf /etc/mosquitto/conf.d/pbl5.conf
sudo cp mosquitto/acl /etc/mosquitto/acl

# Bắt buộc: file phải thuộc user mosquitto, nếu không broker sẽ không đọc được
sudo chown mosquitto:mosquitto /etc/mosquitto/passwd /etc/mosquitto/acl
sudo chmod 0700 /etc/mosquitto/passwd /etc/mosquitto/acl

sudo systemctl restart mosquitto
sudo systemctl status mosquitto --no-pager   # phải thấy "active (running)"
```

> Lưu ý: dùng `-c` **chỉ ở lệnh đầu tiên**, vì `-c` tạo file mới và xóa các tài khoản cũ. Khi thêm phòng 2 thì chạy `sudo mosquitto_passwd /etc/mosquitto/passwd room02` (không có `-c`).

## Bước 4 – Chạy Gateway

```bash
cd ~/pbl5-smart-ac/gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env          # điền MQTT_PASS = mật khẩu của user gateway

python gateway.py
```

### Test Pi trước khi nạp ESP32 (nên làm)

Mở thêm 2 cửa sổ SSH (nhớ `cd ~/pbl5-smart-ac/gateway && source .venv/bin/activate`):

```bash
# Cửa sổ 2: node giả lập
python simulate_node.py --room room01 --password <mật khẩu room01> --interval 5

# Cửa sổ 3: gửi lệnh thử
python send_command.py --room room01 --power on --mode cool --temp 26 --fan auto
python show_data.py
```

Kết quả đúng: `gateway.py` in ra các dòng `temp=... hum=...`, còn `send_command.py` in `command_result sau ... ms`. Tắt node giả lập (Ctrl+C) trước khi chạy ESP32 thật. Nếu để cả hai cùng chạy với `room01`, mỗi lệnh sẽ nhận hai kết quả và trạng thái online/offline sẽ bị lẫn.

## Bước 5 – Nạp firmware ESP32-S3

1. Cài **Arduino IDE 2**. Vào *Boards Manager*, cài **esp32 by Espressif Systems**.
2. Vào *Library Manager*, cài: **PubSubClient** (Nick O'Leary), **ArduinoJson** (Benoit Blanchon, bản 7.x), **Adafruit SHT4x Library** (đồng ý cài kèm thư viện phụ thuộc).
3. Mở `firmware/room_node/room_node.ino`, copy `config.example.h` thành `config.h` rồi sửa:
   - `WIFI_SSID`, `WIFI_PASS`: Wi-Fi **2.4 GHz** (ESP32 không bắt được 5 GHz).
   - `MQTT_HOST`: IP của Pi.
   - `MQTT_PASS`: mật khẩu của user `room01`.
4. Chọn board **ESP32S3 Dev Module** và cổng COM. Nếu cắm vào cổng có chữ **USB** (không phải **UART/COM**) trên DevKit thì bật *Tools → USB CDC On Boot: Enabled* để xem được Serial.
5. Upload, mở Serial Monitor tốc độ **115200**.

Serial Monitor đúng sẽ hiện:

```
[SENSOR] Khong thay SHT4x -> dung du lieu GIA LAP
[WiFi] OK, IP = 192.168.1.xx, RSSI = -52 dBm
[MQTT] OK, da subscribe home/room01/command
[TX] {"seq":1,"temp":28.03,"hum":64.2,"presence":null,"sim":true,...}
```

Sau đó chạy `python send_command.py --room room01 --temp 25` trên Pi. Serial Monitor sẽ in dòng `[RX] cmd_id=...`.

## Xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân hay gặp |
|---|---|
| `[WiFi] That bai` | Sai SSID/mật khẩu, hoặc Wi-Fi chỉ phát 5 GHz |
| `[MQTT] That bai, state = -2` | Sai IP Pi, Pi chưa chạy Mosquitto, hoặc firewall/router chặn cổng 1883 |
| `state = 4` hoặc `5` | Sai mật khẩu MQTT, hoặc `ROOM_ID` khác username đã tạo |
| Mosquitto không khởi động | Chạy `sudo journalctl -u mosquitto -n 30`. Hay gặp nhất là quên `chown` file passwd/acl |
| Gateway in `Ket noi broker that bai: Not authorized` | Sai `MQTT_PASS` trong `.env` |
| Kiểm tra trực tiếp trên Pi | `mosquitto_sub -u gateway -P <pass> -t 'home/#' -v` |

## Chạy gateway tự động (khi đã ổn)

```bash
sudo cp pbl5-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pbl5-gateway
journalctl -u pbl5-gateway -f
```

## Topic MQTT

| Topic | Chiều | Nội dung |
|---|---|---|
| `home/{room}/telemetry` | Node → Pi | `{"seq","temp","hum","presence","sim","rssi","uptime_s"}` |
| `home/{room}/command` | Pi → Node | `{"cmd_id","power","mode","temp","fan","source","ts"}` |
| `home/{room}/command_result` | Node → Pi | `{"cmd_id","ok","ir_sent","note"}` |
| `home/{room}/status` | Node → Pi | `online` / `offline` (retained, Last Will) |

ACL chỉ cho mỗi node ghi và đọc topic của **chính phòng mình**: node `room01` không thể giả mạo dữ liệu của `room02`.

## Các milestone tiếp theo

1. **Milestone 1 (bước này):** đường truyền ESP32 ⇄ Pi, lưu database.
2. **Milestone 2 – IR:** lắp mắt thu IR, giải mã remote Daikin để xác định đúng giao thức; lắp mạch LED IR + BJT, phát lệnh thật thay cho dòng `TODO` trong `onMessage()`.
3. **Milestone 3 – Cảm biến thật:** SHT41 (I2C, chân 8/9) và HLK-LD2410 (UART).
4. **Milestone 4 – Safety Layer + API:** FastAPI, trạng thái dự kiến, chống short-cycling, phân quyền.
5. **Milestone 5 – App/Dashboard.**
6. **Milestone 6 – Thu thập dữ liệu và huấn luyện mô hình gợi ý.**

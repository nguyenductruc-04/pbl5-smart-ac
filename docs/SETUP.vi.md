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

1. Cài **Arduino IDE 2**. Vào *Boards Manager*, cài **esp32 by Espressif Systems**.Cài **esp32 by Espressif bản 2.0.17. Bản 3.x chưa tương thích với IRremoteESP8266.**
2. Vào *Library Manager*, cài: **PubSubClient** (Nick O'Leary), **ArduinoJson** (Benoit Blanchon, bản 7.x), **Adafruit SHT4x Library** (đồng ý cài kèm thư viện phụ thuộc).
   - Mạch IR (LED phát GPIO 4, mắt thu TSOP38238 GPIO 5): xem `docs/hardware/ir-circuit.md`.
   - Trong `config.h`, thêm khối `// --- IR ---` từ `config.example.h`.
3. Mở `firmware/room_node/room_node.ino`, copy `config.example.h` thành `config.h` rồi sửa:
   - `WIFI_SSID`, `WIFI_PASS`: Wi-Fi **2.4 GHz** (ESP32 không bắt được 5 GHz).
   - `MQTT_HOSTNAME`: hostname của Pi (mặc định `gateway`). ESP32 tự tìm IP qua mDNS, không cần ghi IP.
   - `MQTT_HOST_FALLBACK`: IP dự phòng khi mạng chặn mDNS (mặc định `10.42.0.1`, địa chỉ của Pi khi phát Wi-Fi dự phòng).
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

## Bước 6 – Wi-Fi dự phòng `SmartAC-Backup` (v0.4.0)

Khi Pi mất Wi-Fi nhà quá 2 phút, Pi tự phát mạng `SmartAC-Backup` (Pi có IP cố định **10.42.0.1**).
Cứ 5 phút, Pi tắt mạng này khoảng 45 giây để thử kết nối lại Wi-Fi nhà.

> Khi thử nghiệm phần này, **cắm sẵn màn hình và bàn phím vào Pi**. Cấu hình mạng sai có thể làm bạn mất SSH.

### 6.1 Kiểm tra gói cần thiết

```bash
dpkg -l dnsmasq-base | tail -1      # dòng cuối bắt đầu bằng "ii" là đã cài
sudo apt install -y dnsmasq-base    # nếu chưa có (NetworkManager cần gói này để cấp IP cho thiết bị)
```

### 6.2 Tạo cấu hình AP (chỉ làm một lần)

Đặt mật khẩu riêng (ít nhất 8 ký tự), **không ghi vào repo**:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name SmartAC-Backup autoconnect no \
  ssid SmartAC-Backup 802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn \
  wifi-sec.pairwise ccmp wifi-sec.group ccmp wifi-sec.psk "MAT_KHAU_AP"
```

- `autoconnect no`: chỉ watchdog mới được bật AP.
- `band bg`: 2.4 GHz, ESP32 mới thấy được.
- `ipv4.method shared`: Pi làm router, tự cấp IP 10.42.0.x cho thiết bị kết nối vào.
- `proto rsn` + `ccmp`: bắt buộc WPA2/AES. Thiếu hai tùy chọn này AP có thể phát WPA1 và ESP32 (core 2.0.x, mặc định yêu cầu ≥ WPA2) sẽ không kết nối (lý do 201).




### 6.3 Thử bật/tắt AP bằng tay (màn hình + bàn phím)

```bash
sudo nmcli connection up SmartAC-Backup     # Pi rời Wi-Fi nhà, phát SmartAC-Backup
hostname -I                                 # phải có 10.42.0.1
sudo nmcli connection down SmartAC-Backup   # tắt AP, NetworkManager tự nối lại Wi-Fi nhà
```

Trong lúc AP bật: điện thoại/laptop thấy và kết nối được `SmartAC-Backup`; từ laptop `ssh truc0404@10.42.0.1` vào được Pi.

### 6.4 Chạy watchdog như dịch vụ

```bash
cd ~/pbl5-smart-ac/gateway
sudo cp pbl5-netwatch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pbl5-netwatch
journalctl -u pbl5-netwatch -f
```

### 6.5 Kiểm tra tự động chuyển mạng

Làm trên **màn hình + bàn phím của Pi** (Pi sẽ rời mạng). Theo dõi log ở một console (`journalctl -u pbl5-netwatch -f`),
gõ lệnh ở console khác (**Alt+F2**, quay lại bằng **Alt+F1**). Thay `Mai` bằng tên kết nối Wi-Fi nhà
(`nmcli -f NAME,TYPE,AUTOCONNECT connection show`); tắt các mạng đã lưu khác (ví dụ hotspot điện thoại) trong lúc test.

Không tắt được router thật thì giả lập mất mạng bằng cách tạm cấm Pi tự kết nối vào Wi-Fi nhà:

| Bài | Lệnh | Kết quả đúng trong log |
|---|---|---|
| 1. Mất mạng lâu | `sudo nmcli connection modify Mai connection.autoconnect no` rồi `sudo nmcli connection down Mai` | Sau ~2 phút: `Mat Wi-Fi nha -> bat AP du phong` |
| 2. Vẫn mất mạng | (giữ nguyên) | Mỗi ~5 phút: `Tat AP de thu ket noi lai Wi-Fi nha` → `Khong ket noi duoc Wi-Fi nha nao` → AP bật lại |
| 3. Có mạng trở lại | `sudo nmcli connection modify Mai connection.autoconnect yes` | Ở lần thử kế tiếp: `Thu ket noi 'Mai'` → `Da ve Wi-Fi nha 'Mai'`, AP biến mất |
| 4. Mất mạng ngắn | `sudo nmcli connection down Mai; sleep 60; sudo nmcli connection up Mai` | Không có dòng `bat AP` |

Test xong kiểm tra `nmcli -f NAME,AUTOCONNECT connection show`: `Mai` phải là **yes**.

Khi Pi đang ở chế độ AP thì không có Internet (Tailscale không dùng được); vào Pi bằng cách kết nối laptop vào `SmartAC-Backup`
rồi `ssh truc0404@10.42.0.1`.

### 6.6 Node tự chuyển sang mạng dự phòng và nhận Wi-Fi từ Pi

**Cập nhật quyền MQTT** (node được đọc `config`, ghi `config_result` của chính phòng mình):

```bash
cd ~/pbl5-smart-ac/gateway
sudo cp mosquitto/acl /etc/mosquitto/acl
sudo chown mosquitto:mosquitto /etc/mosquitto/acl && sudo chmod 0700 /etc/mosquitto/acl
sudo systemctl restart mosquitto
```

**`config.h` của node:** thêm `BACKUP_SSID`, `BACKUP_PASS` (đúng mật khẩu AP đặt ở mục 6.2), `WIFI_CONNECT_TIMEOUT_MS`,
`WIFI_HOME_RETRY_MS`, `WIFI_BROKER_LOST_MS` từ `config.example.h`; đặt `MQTT_HOST_FALLBACK "10.42.0.1"`.

- `WIFI_SSID`/`WIFI_PASS` chỉ dùng ở **lần khởi động đầu tiên**; sau đó node dùng Wi-Fi lưu trong bộ nhớ (NVS).
- Muốn node quay lại giá trị trong `config.h`: nhấn **RESET**, rồi giữ nút **BOOT** khoảng 2 giây trong 3 giây đầu
  (Serial Monitor in `DA XOA Wi-Fi luu trong NVS`). Không giữ BOOT *trong lúc* nhấn RESET (sẽ vào chế độ nạp code).

**Gửi Wi-Fi nhà mới xuống node** (mật khẩu được hỏi, không hiện trên màn hình):

```bash
python push_wifi.py --room room01 --ssid "TEN_WIFI"
python push_wifi.py --room room01 --clear     # xóa cấu hình đang chờ trên broker nếu node chưa phản hồi
```

Node **thử kết nối trước**: được thì lưu và báo `OK`; sai mật khẩu thì giữ Wi-Fi cũ và báo `connect_failed`.
Cấu hình được gửi dạng *retained* nên node đang offline sẽ nhận khi kết nối lại; nhận được kết quả thì script xóa
ngay bản tin khỏi broker. Mật khẩu đi qua MQTT không mã hóa trong mạng nội bộ (hướng phát triển: MQTT over TLS).
Nếu script báo *Chua nhan ket qua* (vd. node đã sang mạng mà Pi chưa ở đó), sau khi xong việc hãy chạy `--clear` để mật khẩu không nằm lại trên broker.

**Kiểm tra** (Serial Monitor + log `journalctl -u pbl5-netwatch -f`; giả lập mất Wi-Fi nhà như mục 6.5):

| Bài | Làm gì | Kết quả đúng |
|---|---|---|
| 1 | Pi và node đang ở Wi-Fi nhà; giả lập mất Wi-Fi nhà trên Pi (6.5 bài 1) | Pi bật AP; ~2 phút sau node: `Khong toi duoc broker tren Wi-Fi nha -> thu mang du phong` → `OK 'SmartAC-Backup'` → `Dang dung MANG DU PHONG` → `[MQTT] OK` (broker `10.42.0.1` hoặc `gateway.local`) |
| 2 | Khôi phục Wi-Fi nhà trên Pi (6.5 bài 3) | Pi về Wi-Fi nhà; AP tắt nên node mất mạng → tự về Wi-Fi nhà, MQTT kết nối lại |
| 3 | `push_wifi.py` với **sai mật khẩu** | `THAT BAI: connect_failed`; node vẫn ở mạng cũ |
| 4 | `push_wifi.py` với một Wi-Fi 2.4 GHz **khác** mà Pi cũng đang vào được (vd. hotspot) | `OK`; node chuyển mạng; khởi động lại node vẫn dùng mạng mới |
| 5 | Nhấn RESET, rồi giữ BOOT ~2 s trong 3 giây đầu | `DA XOA Wi-Fi luu trong NVS`, node về Wi-Fi trong `config.h` và ở yên đó; nếu broker còn cấu hình cũ thì in `da xu ly truoc do -> bo qua` |

## Bước 7: Cảm biến nhiệt độ, độ ẩm và hiện diện

Sơ đồ nối dây, lý do thiết kế và cách đặt cảm biến: [hardware/sensors.md](hardware/sensors.md).

### 7.1 Nối dây

**Rút USB trước khi nối.** Mọi cảm biến lấy nguồn từ chân 3V3 của ESP32. Không dùng nguồn ngoài và **không cấp 5 V cho LD2420**.

| Từ | Tới ESP32-S3 |
|---|---|
| SHT3x VIN, GND, SDA, SCL | 3V3, GND, GPIO 8, GPIO 9 |
| LD2420 3V3, GND, OT1, OT2 | 3V3, GND, GPIO 6, GPIO 7 (chân RX để trống) |

Trước khi cắm USB, dùng đồng hồ đo thông mạch giữa 3V3 và GND: không được kêu.

### 7.2 Kiểm tra bằng `sensor_check`

1. Arduino IDE: cài thêm thư viện **Adafruit SHT31 Library** (chọn Install all khi được hỏi).
2. Mở `firmware/tools/sensor_check/sensor_check.ino` và nạp vào ESP32.
3. Mở Serial Monitor (115200). Trong 10 giây đầu, **đi lại trước LD2420** ở khoảng cách 1–2 m.

| Phần | Kết quả đúng | Nếu sai |
|---|---|---|
| 1. I²C | `Thay thiet bi o 0x44`, ba dòng `Doc thu` có nhiệt độ hợp lý | Không thấy: kiểm tra dây, thử đảo SDA và SCL |
| 2. LD2420 | `=> TX (UART) la GPIO 6, OUT (co nguoi) la GPIO 7` (hoặc ngược lại) | `luon o muc thap`: kiểm tra nguồn 3V3 của LD2420 |
| 3. UART | `DOC DUOC` ở 115200 hoặc 256000 | Không giải mã được cũng không sao |
| 4. Theo dõi | Đi ra khỏi phòng thì sau một lúc in `khong co nguoi`, quay lại thì in `CO NGUOI` | |

Ghi lại: chân OUT/TX, tốc độ baud, và **thời gian giữ "có người"** (số giây trong ngoặc của dòng `khong co nguoi`) vào bảng "Kết quả đo" của `docs/hardware/sensors.md`.

### 7.3 Cập nhật `config.h` và nạp firmware chính

Chép phần **Cảm biến** từ `config.example.h` sang `config.h` (thay hai dòng `I2C_SDA_PIN`, `I2C_SCL_PIN` cũ). Đặt `PRESENCE_OUT_PIN` và `PRESENCE_TX_PIN` đúng như `sensor_check` báo. Nạp `firmware/room_node`.

Serial Monitor phải in:
```
[SENSOR] Tim thay SHT3x (dia chi 0x44)
[PRESENCE] LD2420 OUT GPIO 7, TX GPIO 6
[PRESENCE] LD2420 hoat dong
```
Nếu thấy dòng `[CFG] config.h CU`, nghĩa là `config.h` chưa có các mục mới.

### 7.4 Kiểm thử trên Pi

Trên Pi: `journalctl -u pbl5-gateway -f` (hoặc chạy `python gateway.py` nếu chưa cài dịch vụ).

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Để yên 1 phút | Telemetry mỗi 30 s: nhiệt độ thật, `nguoi=CO` hoặc `nguoi=khong`, không có chữ `(gia lap)` |
| 2 | Hà hơi hoặc áp ngón tay vào SHT3x khoảng 10 giây | Nhiệt độ và độ ẩm tăng, rồi giảm dần |
| 3 | Rời khỏi tầm cảm biến, chờ hết thời gian giữ | Có một bản tin **ngay lúc** chuyển sang `nguoi=khong`, không đợi đủ 30 s |
| 4 | Quay lại | Có bản tin ngay với `nguoi=CO` |
| 5 | Rút dây 3V3 của LD2420 | Serial: `Mat tin hieu LD2420`; Pi: `nguoi=?` (không phải `khong`) |
| 6 | Cắm lại | `LD2420 hoat dong`, có lại `CO`/`khong` |
| 7 | Rút dây SDA của SHT3x | Serial: `loi 3 lan lien tiep`; ngừng gửi telemetry (không có số giả) |
| 8 | Cắm lại, chờ tối đa 30 s | `Da tim lai cam bien SHT3x`, telemetry gửi lại |
| 9 | `python show_data.py` | Có cột `nguoi`, và mục "Du lieu that da thu" |

### 7.5 Bắt đầu thu dữ liệu cho AI

- Đặt node ở vị trí cố định (xem phần "Đặt cảm biến" trong `hardware/sensors.md`) và cấp nguồn liên tục bằng một sạc USB, không dùng laptop.
- Đảm bảo `pbl5-gateway` chạy như dịch vụ (Bước 5) để Pi ghi dữ liệu cả khi bạn không mở SSH.
- Ghi ngày bắt đầu thu dữ liệu vào báo cáo. `python show_data.py` cho biết đã thu được bao nhiêu ngày dữ liệu thật.

## Bước 8: Safety Layer và REST API

Từ bước này, mọi lệnh điều khiển đi qua REST API trên Pi. API kiểm tra lệnh bằng Safety Layer trước khi gửi xuống node. Lý do thiết kế: [ADR 0002](adr/0002-safety-layer-and-control-api.md). Mô tả API: [API.md](API.md).

### 8.1 Cài thư viện mới trên Pi

```bash
cd ~/pbl5-smart-ac && git pull
cd gateway && source .venv/bin/activate
pip install -r requirements.txt
```

### 8.2 Tạo khóa API

Chạy lệnh sau **hai lần** để có hai khóa khác nhau:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Mở `nano .env` và thêm (xem mẫu trong `.env.example`):

```
API_KEY=<khóa thứ nhất: cho app/dashboard>
API_KEY_AUTOMATION=<khóa thứ hai: cho luật và AI>
IR_PROTOCOL=DAIKIN
```

File `.env` không được commit. Khi chụp màn hình, nhớ che hai khóa này.

### 8.3 Cập nhật dịch vụ

Từ bản này, dịch vụ `pbl5-gateway` chạy `api.py` thay cho `gateway.py`: một tiến trình vừa thu dữ liệu MQTT vừa phục vụ API. **Không chạy hai file cùng lúc**, vì chúng trùng tên kết nối MQTT và sẽ đá nhau khỏi broker.

```bash
cd ~/pbl5-smart-ac
pgrep -af "gateway.py|api.py"                 # chỉ được thấy tiến trình của dịch vụ
sudo cp gateway/pbl5-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart pbl5-gateway
journalctl -u pbl5-gateway -f
```

Thấy `Uvicorn running on http://0.0.0.0:8000` và các dòng telemetry `nguoi=...` là được. Nếu thay vào đó thấy `Thieu API_KEY`, quay lại mục 8.2. Trên laptop, mở `http://gateway.local:8000/docs` để xem và thử từng endpoint: bấm **Authorize** rồi dán `API_KEY`.

### 8.4 Kiểm thử với node thật

Mở cửa sổ SSH thứ hai trên Pi và đặt biến cho gọn:

```bash
cd ~/pbl5-smart-ac/gateway
set -a; source .env; set +a
K="X-API-Key: $API_KEY"
A="X-API-Key: $API_KEY_AUTOMATION"
B=http://localhost:8000/api/v1
J="Content-Type: application/json"
```

| # | Lệnh | Kết quả đúng |
|---|---|---|
| 1 | `curl $B/health` | `"status":"ok"` |
| 2 | `curl $B/rooms` | `401 UNAUTHORIZED` (thiếu khóa) |
| 3 | `curl -H "$K" $B/rooms/room01` | Có `telemetry` với nhiệt độ thật, `presence` là `true`, `false` hoặc `null` |
| 4 | `curl -H "$K" -H "$J" -d '{"power":"on","temp":25}' $B/rooms/room01/commands` | `"status":"executed"`, Serial của node in `IR DA PHAT` |
| 5 | Ngay sau đó: `curl -H "$K" -H "$J" -d '{"temp":24}' $B/rooms/room01/commands` | `RATE_LIMIT` (gửi quá nhanh) |
| 6 | `curl -H "$K" -H "$J" -d '{"power":"off"}' $B/rooms/room01/commands` | `executed` (tắt luôn được phép) |
| 7 | Ngay sau đó: `curl -H "$K" -H "$J" -d '{"power":"on"}' $B/rooms/room01/commands` | `COMPRESSOR_MIN_OFF`, có `retry_after_s` |
| 8 | Đợi hết 3 phút rồi lặp lại lệnh 7 | `executed` |
| 9 | `curl -H "$A" -H "$J" -d '{"temp":26,"source":"ai"}' $B/rooms/room01/commands` | `MANUAL_HOLD` (người dùng vừa điều chỉnh) |
| 10 | `curl -X DELETE -H "$K" $B/rooms/room01/auto-hold` rồi lặp lại lệnh 9 | `executed`, `"source":"ai"` |
| 11 | `curl -H "$A" -H "$J" -d '{"temp":29,"source":"ai"}' $B/rooms/room01/commands` | `STEP_TOO_LARGE` (tự động chỉ được đổi 1 °C mỗi lần) |
| 12 | Tắt máy lạnh bằng lệnh 6, đợi 3 phút, ra khỏi tầm LD2420 cho tới khi node báo `presence:false`, rồi `curl -H "$A" -H "$J" -d '{"power":"on","source":"rule"}' $B/rooms/room01/commands` | `ROOM_EMPTY` (không tự bật khi phòng trống) |
| 13 | Rút nguồn node, đợi khoảng 1 phút, gửi lại lệnh 4 | `NODE_OFFLINE`, lệnh **không** được xếp hàng |
| 14 | Cắm lại node, đợi online: `curl -H "$K" $B/rooms/room01` | `"uncertain":true` |
| 15 | Lặp lại lệnh 9 | `STATE_UNCERTAIN` cho tới khi người dùng gửi một lệnh |
| 16 | `curl -H "$K" "$B/rooms/room01/decisions?limit=20"` | Nhật ký đủ các quyết định ở trên, kèm mã lý do |

Ở bài 12, nếu bạn đã cấu hình nhưng chưa từng gửi lệnh tự động nào, có thể gặp `RATE_LIMIT` (lệnh tự động cách nhau ít nhất 10 phút). Đợi theo `retry_after_s` rồi thử lại.

Khi có remote Daikin thật: bấm remote, rồi `curl -H "$K" $B/rooms/room01` phải cho `"source":"remote"` và `auto_hold_remaining_s` khoảng 3600. Khi chưa có remote, có thể giả lập:

```bash
mosquitto_pub -u gateway -P "$MQTT_PASS" -t home/room01/ir_event \
  -m '{"protocol":"DAIKIN","power":"on","mode":"cool","temp":25,"fan":"auto"}'
```

### 8.5 Đổi ngưỡng Safety Layer

Mọi ngưỡng nằm trong lớp `Policy` của `gateway/safety.py`. Ghi đè bằng biến `SAFETY_<TÊN_IN_HOA>` trong `.env` (ví dụ `SAFETY_MIN_OFF_S=240`), rồi `sudo systemctl restart pbl5-gateway`. Xem giá trị đang áp dụng: `curl -H "$K" $B/policy`.

### 8.6 Giới hạn đã biết

- API dùng HTTP thường và khóa tĩnh: chỉ dùng trong mạng nội bộ, mạng dự phòng `SmartAC-Backup` hoặc qua Tailscale. Không mở cổng 8000 ra Internet.
- Trạng thái điều hòa là trạng thái **dự kiến** (IR một chiều). Nếu điều hòa lỡ mất tín hiệu, Pi không biết.
- `ROOM_EMPTY` dựa trên giá trị `presence` mới nhất (LD2420 giữ trạng thái "có người" khoảng 15 s). Luật tắt điều hòa khi phòng trống nên đợi phòng trống liên tục 10–15 phút; việc này thuộc rule engine ở các bản sau.
- `send_command.py` không đi qua Safety Layer, chỉ dùng để gỡ lỗi.

## Bước 9: Dashboard và phiếu cảm nhận

Dashboard là một trang web do chính Pi phục vụ: không cần Internet, không cần cài thêm gì. Lý do thiết kế: [ADR 0003](adr/0003-dashboard.md).

### 9.1 Cập nhật

```bash
cd ~/pbl5-smart-ac && git pull
sudo systemctl restart pbl5-gateway
```

### 9.2 Mở dashboard

| Thiết bị đang ở mạng nào | Địa chỉ |
|---|---|
| Cùng Wi-Fi với Pi | `http://gateway.local:8000` |
| Mạng dự phòng `SmartAC-Backup` | `http://10.42.0.1:8000` |
| Ở xa, qua Tailscale | `http://<IP Tailscale của Pi>:8000` |

Nếu điện thoại không mở được `gateway.local`, dùng địa chỉ IP của Pi (xem bằng `hostname -I` trên Pi).

Lần đầu, trang hiện **Thiết lập lần đầu**: tạo tài khoản quản trị bằng mã trên tem (Bước 12.2–12.3). Trước bản 0.9.0 trang hỏi khóa `API_KEY`; khóa vẫn dùng được qua **Dùng khóa API** ở trang đăng nhập. Trên điện thoại, chọn "Thêm vào màn hình chính" trong menu trình duyệt để mở như một ứng dụng.

### 9.3 Kiểm thử

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Nhập khóa sai | Báo "Khóa không đúng", không vào được |
| 2 | Nhập đúng khóa | Thấy nhiệt độ, độ ẩm, có người là số đo thật; biểu đồ 6 giờ / 24 giờ / 7 ngày |
| 3 | Bấm "Bật điều hòa" | "Đã phát lệnh tới điều hòa", Serial của node in `IR DA PHAT` |
| 4 | Bấm `−` ba lần liên tiếp | Số đổi ngay; node chỉ nhận **một** lệnh với giá trị cuối |
| 5 | Đổi chế độ và quạt | Mỗi thay đổi hiện trong "Nhật ký điều khiển" |
| 6 | Tắt rồi bật lại ngay | Bị từ chối, có đếm ngược "Máy nén đang nghỉ" |
| 7 | Bấm "Muốn mát hơn" | "Đã ghi … phòng xx °C", có nút "Hoàn tác", số lần ghi hôm nay tăng 1; ba nút khóa khoảng 5 giây |
| 8 | Bấm "Hoàn tác" | "Đã hoàn tác", số lần ghi giảm 1 |
| 9 | Rút nguồn node, đợi khoảng 1 phút | Chấm trạng thái đỏ, nút điều khiển và nút cảm nhận bị khóa |
| 10 | Cắm lại node | Thông báo "trạng thái có thể đã lệch" cho tới khi gửi một lệnh; nút cảm nhận dùng lại được |
| 11 | Mở cùng lúc trên điện thoại và laptop, điều khiển ở một máy | Máy kia cập nhật trong khoảng 3 giây |
| 12 | `sudo systemctl stop pbl5-gateway` rồi `start` lại | Trang báo mất kết nối tới Pi, rồi tự hồi phục |

### 9.4 Thu nhãn cho AI

Từ hôm nay, mỗi khi thấy **nóng, lạnh, hay dễ chịu**, bấm một nút trong mục "Bạn thấy thế nào?". Mục tiêu khoảng 5–10 lần mỗi ngày, và **bấm cả khi thấy dễ chịu**: nếu chỉ bấm lúc khó chịu, dữ liệu sẽ lệch.

Xem các phiếu đã ghi:
```bash
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8000/api/v1/rooms/room01/comfort?limit=10"
```

### 9.5 Giới hạn đã biết

- Trang hỏi lại Pi mỗi 3 giây, nên thay đổi từ remote hoặc thiết bị khác hiện chậm tối đa 3 giây.
- HTTP thường và khóa tĩnh: chỉ dùng trong mạng nội bộ, mạng dự phòng hoặc qua Tailscale. Nếu mất điện thoại đã lưu khóa, đổi `API_KEY` trong `.env` rồi khởi động lại dịch vụ. Từ bản 0.9.0: mất điện thoại thì quản trị viên xóa hoặc hạ quyền tài khoản đó, hoặc chính bạn đổi mật khẩu (đăng xuất mọi thiết bị khác).


## Bước 10: Gợi ý nhiệt độ (mô hình tiện nghi)

Thiết kế và cách đánh giá: [ADR 0004](adr/0004-comfort-model.md). Hướng dẫn chạy phần học máy: [docs/ml/README.md](ml/README.md).

### 10.1 Cập nhật

```bash
cd ~/pbl5-smart-ac && git pull
sudo systemctl restart pbl5-gateway
```

Không cần cài thêm thư viện trên Pi: mô hình viết bằng Python thuần.

### 10.2 Xem gợi ý

Mở dashboard: thẻ **"Gợi ý cho bạn"** nằm giữa phần điều khiển và phần "Bạn thấy thế nào?".

- Dưới 10 phiếu: dòng cuối ghi "Đang dùng mô hình chung…". Từ 10 phiếu trở đi: "Học từ N phiếu của bạn…".
- Nút **"Áp dụng"** gửi gợi ý như một lệnh của bạn: đi qua Safety Layer, và tạm dừng chế độ tự động 30 phút như mọi lệnh thủ công.

Xem gợi ý thô: `curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/rooms/room01/suggestion`

### 10.3 Kiểm thử

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Mở dashboard | Có thẻ "Gợi ý cho bạn", có "Vùng dễ chịu của bạn: …" |
| 2 | Phòng nóng (khoảng 30 °C trở lên), điều hòa tắt | "Có vẻ hơi nóng với bạn. Nên bật điều hòa ở xx °C", có nút "Áp dụng" |
| 3 | Bấm "Áp dụng" | "Đã phát lệnh tới điều hòa", gợi ý đổi thành "Nhiệt độ đặt hiện tại đang hợp với bạn" |
| 4 | Ghi vài phiếu "Muốn mát hơn" liên tiếp (cách nhau trên 5 giây) | "Vùng dễ chịu của bạn" dịch xuống thấp hơn |
| 5 | `curl` gợi ý như mục 10.2 | `"model": {"votes": N, ...}` khớp số phiếu đã ghi |

### 10.4 Chế độ tự động (tùy chọn)

Mặc định tắt. Bật bằng cách thêm vào `gateway/.env`:
```
ADVISOR_AUTO=1
```
rồi `sudo systemctl restart pbl5-gateway`. Log phải có `Che do tu dong BAT`. Từ đó, mỗi phút hệ thống tự áp dụng gợi ý với nguồn `ai`. Mọi luật của Safety Layer vẫn áp dụng: không chạy khi bạn vừa điều chỉnh, đổi tối đa 1 °C mỗi lần, cách nhau ít nhất 10 phút, không tự bật khi phòng trống. Các lệnh tự động hiện trong nhật ký với nguồn "AI".

### 10.5 Đánh giá trên phiếu thật (sau khoảng 2 tuần, khi có từ 20 phiếu)

Trên laptop:
```bash
pip install -r ml/requirements.txt
scp truc0404@gateway.local:pbl5-smart-ac/gateway/pbl5.db ./pbl5-copy.db
python ml/evaluate_personal.py --db pbl5-copy.db --room room01
```
Kết quả nằm ở `docs/ml/personal-evaluation.md`. Commit file đó kèm ảnh `.png`, rồi đưa bảng kết quả vào báo cáo.

## Bước 11: Khi điều hòa không làm theo, chế độ độc lập, thêm thiết bị bằng QR

Lý do thiết kế: [ADR 0005](adr/0005-missed-ir-commands.md) (lệnh bị điều hòa bỏ lỡ) và [ADR 0006](adr/0006-field-network-and-device-pairing.md) (mạng độc lập, ghép thiết bị). Mô tả API: [API.md](API.md).

### 11.1 Cập nhật Pi

Bản này có thêm thư viện `segno` (tạo mã QR):

```bash
cd ~/pbl5-smart-ac && git pull
cd gateway && source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart pbl5-gateway
sudo systemctl restart pbl5-netwatch
```

`journalctl -u pbl5-netwatch -n 5` phải có `che do=auto`.

### 11.2 Nạp firmware 0.9.0 cho node

Mở `firmware/room_node/room_node.ino`, nạp như mọi lần (`config.h` giữ nguyên). Serial Monitor phải in `=== PBL5 Room Node 0.9.0`.

### 11.3 Kiểm thử

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Trên laptop, bấm **Thêm thiết bị**, dùng camera điện thoại quét mã QR (điện thoại cùng mạng Wi-Fi với Pi) | Điện thoại mở thẳng dashboard, không hỏi đăng nhập (từ bản 0.9.0: đăng nhập thành chính người tạo mã) |
| 2 | Quét lại đúng mã đó bằng thiết bị khác (hoặc tab ẩn danh) | Hiện trang đăng nhập, kèm "Mã QR đã dùng rồi hoặc đã hết hạn…" |
| 3 | Mở **Điều hòa không làm theo?** → **Gửi lại lệnh** | "Đã gửi lại: …". Serial node có dòng `[RX] cmd_id=…`. Nhật ký ghi "Gửi lại. Đã phát lệnh" |
| 4 | Bật → Tắt → Bật lại trong vòng 3 phút | Hiện khung hỏi "Máy nén vừa tắt… Vẫn bật?". Bấm **Vẫn bật**: lệnh được phát, nhật ký ghi "Bạn xác nhận bật lại sớm" |
| 5 | Khi dashboard đang hiện điều hòa bật, bấm **Thực tế điều hòa đang tắt** | Nút chính đổi thành "Bật điều hòa". Serial node **không** có dòng `[RX]` mới. Nhật ký ghi "Bạn báo điều hòa thực tế đang tắt" |
| 6 | Trong mục **Mạng của Pi** của dashboard, chọn **Độc lập** → đọc khung hướng dẫn → **Chuyển** | Dòng trạng thái ghi "Đang chuyển sang chế độ Độc lập…"; trong khoảng 15 giây Pi phát `SmartAC-Backup`, trang mất kết nối kèm hướng dẫn vào `SmartAC-Backup`. Serial node: `[NET] Pi bao sap phat mang rieng`, rồi `[NET] Di theo Pi sang mang du phong` và `[MQTT] OK` trong **khoảng 20–40 giây** (firmware cũ: khoảng 2,5 phút) |
| 7 | Rút điện node rồi cắm lại | Node vào thẳng `SmartAC-Backup` (lần trước đã ở mạng này), không thử Wi-Fi nhà trước |
| 8 | Để yên 10 phút. Điện thoại vào `SmartAC-Backup`, mở `http://10.42.0.1:8000` | Dashboard không báo mất kết nối lần nào. Serial node **không** có dòng `Thay Wi-Fi nha -> thu quay ve` (trước bản này, cứ 5 phút node lại rời mạng của Pi để thử Wi-Fi nhà) |
| 9 | Vẫn ở `SmartAC-Backup`, mở `http://10.42.0.1:8000`, chọn **Tự động** → **Chuyển** | Pi tắt `SmartAC-Backup` và vào lại Wi-Fi nhà trong khoảng 1 phút; node đi theo; điện thoại vào lại Wi-Fi nhà, mở `http://gateway.local:8000`, mục Mạng ghi "Pi đang dùng Wi-Fi nhà" |

### 11.4 Đi thử nghiệm ở nơi không có Wi-Fi nhà

1. Ở nhà: trên dashboard chọn **Mạng của Pi → Độc lập → Chuyển**. Lựa chọn được lưu, nên rút điện mang đi Pi vẫn ở chế độ độc lập.
2. Mang theo Pi, node và một sạc dự phòng hai cổng.
3. Cắm điện, đợi khoảng 1 phút. Điện thoại vào `SmartAC-Backup`, mở `http://10.42.0.1:8000`. Nếu điện thoại chưa đăng nhập ở địa chỉ này, đăng nhập bằng tài khoản, hoặc quét QR từ một thiết bị đã đăng nhập.
4. Nếu dashboard báo **đồng hồ Raspberry Pi lệch**, đừng ghi phiếu cảm nhận trong buổi đó (giờ ghi sẽ sai). Pi không có pin đồng hồ, và ở chế độ độc lập không có Internet để chỉnh giờ.
5. Về nhà: mở `http://10.42.0.1:8000`, chọn **Tự động → Chuyển**. Quên bước này thì Pi sẽ không quay về Wi-Fi nhà.

Ba chế độ:

| Chế độ | Pi làm gì | Mở dashboard ở đâu | Khi nào dùng |
|---|---|---|---|
| **Tự động** (mặc định) | Dùng Wi-Fi nhà; mất Wi-Fi nhà quá 2 phút thì tự phát `SmartAC-Backup`, cứ 5 phút thử quay về | `http://gateway.local:8000`, hoặc `http://10.42.0.1:8000` khi Pi đang phát mạng riêng | Hằng ngày ở nhà |
| **Độc lập** | Phát `SmartAC-Backup` ngay, không bao giờ dùng Wi-Fi nhà, không có Internet | Vào `SmartAC-Backup`, mở `http://10.42.0.1:8000` | Đi thử nghiệm, buổi bảo vệ |
| **Chỉ Wi-Fi nhà** | Không bao giờ phát mạng riêng | `http://gateway.local:8000` | Khi mạng riêng gây phiền, hoặc cần chắc Pi luôn ở mạng nhà |

`NETWORK_MODE` trong `gateway/.env` chỉ là chế độ mặc định khi chưa chọn trên dashboard. Muốn bỏ lựa chọn trên dashboard và quay về giá trị trong `.env`: `rm ~/pbl5-smart-ac/gateway/network_mode`.

### 11.5 Giới hạn đã biết

- Mã QR **Thêm thiết bị** đăng nhập thiết bị kia thành chính bạn. Chỉ quét trên thiết bị của mình; người khác nên tự tạo tài khoản (Bước 12).
- "Vẫn bật" bỏ qua thời gian nghỉ của máy nén do Pi tính; điều hòa vẫn tự có trễ bảo vệ riêng (phần lớn các máy), nhưng đừng bật tắt liên tục.
- Đồng bộ trạng thái chỉ sửa màn hình; nếu báo sai thì lệnh tiếp theo hoặc lần bấm remote sẽ sửa lại.

## Bước 12: Tài khoản, tem thiết lập và nút reset

Lý do thiết kế: [ADR 0007](adr/0007-user-accounts.md). Từ bản này mỗi người có tài khoản riêng thay cho khóa API dùng chung:

| Quyền | Được làm |
|---|---|
| **Quản trị viên** | Mọi thứ: điều khiển, đổi chế độ mạng, duyệt và cấp quyền tài khoản |
| **Thành viên** | Điều khiển điều hòa, ghi phiếu cảm nhận, thêm thiết bị của mình bằng QR |
| **Khách** | Chỉ xem |

Giống thiết bị thật: người đầu tiên **nhận chủ** Pi bằng mã in trên tem; người khác tự tạo tài khoản rồi chờ quản trị viên duyệt; quên mật khẩu quản trị thì **giữ nút reset 10 giây**.

### 12.1 Cập nhật Pi

Không thêm thư viện mới:

```bash
cd ~/pbl5-smart-ac && git pull
sudo systemctl restart pbl5-gateway
```

Database cũ được nâng cấp tự động (thêm bảng tài khoản, thêm cột người gửi cho phiếu cảm nhận); dữ liệu cũ giữ nguyên.

### 12.2 In tem thiết lập

Trên Pi, **không dùng sudo** (file mã phải thuộc user `truc0404`):

```bash
cd ~/pbl5-smart-ac/gateway
.venv/bin/python setup_label.py
```

Script hỏi mật khẩu Wi-Fi `SmartAC-Backup` để in lên tem (Enter để bỏ qua, viết tay sau), rồi in mã thiết lập và mã QR ra terminal, và ghi file `setup_label.svg` (70 × 45 mm). Lấy file về laptop để in:

```bash
# chạy trên laptop
scp truc0404@gateway.local:~/pbl5-smart-ac/gateway/setup_label.svg .
```

Mở file bằng trình duyệt, in ở tỉ lệ 100 %, dán vào mặt dưới hoặc bên trong hộp Pi, rồi xóa file ở cả hai máy (`rm setup_label.svg`). Tem có hai mã QR: mã bên trái cho app Android (bản 0.10.0), mã bên phải để camera điện thoại vào thẳng Wi-Fi `SmartAC-Backup`.

**Tem là bí mật**, giống mật khẩu Wi-Fi in sau router: đừng chụp gửi lên mạng hay đưa vào báo cáo (ảnh minh họa thì che mã). Mã thiết lập nằm trong `gateway/setup_code`, không vào git.

### 12.3 Thiết lập lần đầu (nhận chủ)

1. Mở `http://gateway.local:8000`. Dashboard hiện **Thiết lập lần đầu**.
2. Nhập mã trên tem (không phân biệt hoa thường, có hay không có gạch ngang đều được), tên đăng nhập (vd. `truc`), mật khẩu ít nhất 8 ký tự.
3. Bấm **Tạo tài khoản quản trị**: vào thẳng dashboard, góc trên hiện tên của bạn.

Từ lúc này trang thiết lập bị khóa: người khác có tem cũng không tạo được quản trị viên nữa.

Các trình duyệt đã lưu khóa API từ trước vẫn dùng được (khóa có quyền quản trị). Muốn chuyển sang tài khoản: bấm tên ở góc trên (hiện **Khóa API**) → **Đăng xuất** → đăng nhập.

### 12.4 Thêm người dùng

1. Người kia mở dashboard trên điện thoại của họ (cùng mạng với Pi) → **Tạo tài khoản** → điền tên, mật khẩu → **Gửi yêu cầu**.
2. Trên dashboard của bạn hiện "Có 1 tài khoản đang chờ bạn duyệt" → **Xem** → trong mục **Thành viên** bấm **Duyệt thành viên** hoặc **Duyệt khách** (hoặc **Từ chối**).
3. Người kia đăng nhập bằng tên và mật khẩu vừa tạo.

Đổi quyền hoặc xóa tài khoản bất cứ lúc nào trong mục **Thành viên**; thay đổi có hiệu lực ngay ở lần tải tiếp theo của họ. Luôn phải còn ít nhất một quản trị viên.

Đổi mật khẩu: bấm tên ở góc trên → **Đổi mật khẩu**. Các thiết bị khác của bạn sẽ bị đăng xuất.

### 12.5 Nút reset

Cần: **1 nút nhấn 4 chân 6×6 mm hoặc 12×12 mm** (loại nào cũng được) và **2 dây cái–cái** (hoặc hàn dây vào nút). Không cần điện trở: Pi dùng điện trở kéo lên bên trong.

| Chân nút | Nối vào Pi 5 |
|---|---|
| Một chân | **GPIO 17**, chân vật lý số **11** |
| Chân chéo đối diện | **GND**, chân vật lý số **9** |

Nút 4 chân: hai chân cùng một cạnh dài thường nối sẵn với nhau, nên dùng hai chân **chéo nhau** cho chắc. Chân 1 là chân góc gần khe thẻ nhớ, hàng trong (số lẻ); chân 9 và 11 là chân thứ 5 và thứ 6 của hàng đó tính từ chân 1. Không chắc thì gõ `pinout` trên Pi để xem sơ đồ chân.

Cài dịch vụ:

```bash
cd ~/pbl5-smart-ac/gateway
groups truc0404                      # phải có "gpio"; nếu chưa: sudo usermod -aG gpio truc0404
python3 -c "import gpiozero"         # Raspberry Pi OS có sẵn; nếu lỗi: sudo apt install python3-gpiozero
sudo cp pbl5-reset.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pbl5-reset
journalctl -u pbl5-reset -f
```

Log phải có `Cho nut reset o GPIO 17`. Nhấn nhanh một lần: log ghi `Nut reset duoc nhan`. Giữ 10 giây: `da xoa N tai khoan`.

Reset **chỉ xóa tài khoản và phiên đăng nhập**, đồng thời bỏ chế độ mạng đã chọn trên dashboard (về `NETWORK_MODE` trong `.env`). Số đo, nhật ký lệnh và phiếu cảm nhận giữ nguyên. Mã thiết lập không đổi nên tem cũ vẫn dùng được.

### 12.6 Cho app Android tự tìm thấy Pi

```bash
cd ~/pbl5-smart-ac/gateway
sudo cp pbl5.avahi.service /etc/avahi/services/pbl5.service
sudo apt install -y avahi-utils      # chỉ để kiểm tra
avahi-browse -rt _pbl5._tcp
```

Phải thấy `Dieu hoa thong minh (gateway)` với `port = [8000]`. Avahi tự nạp file, không cần khởi động lại.

### 12.7 Kiểm thử

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Pi chưa có chủ: mở dashboard | Hiện **Thiết lập lần đầu** |
| 2 | Nhập sai mã trên tem | "Mã thiết lập không đúng…" |
| 3 | Nhập đúng mã, tạo tài khoản quản trị | Vào dashboard, góc trên hiện tên bạn, có mục **Thành viên** |
| 4 | Thiết bị thứ hai: **Tạo tài khoản** `lan`, rồi thử đăng nhập | "Tài khoản đang chờ quản trị viên duyệt…" |
| 5 | Quản trị viên bấm **Duyệt khách** cho `lan`; `lan` đăng nhập | `lan` xem được nhưng nút bật/tắt, nhiệt độ, phiếu cảm nhận đều mờ, có thông báo "tài khoản khách" |
| 6 | Đổi `lan` thành **Thành viên**; `lan` tải lại trang | `lan` điều khiển được; mục **Mạng của Pi** vẫn không đổi được (chỉ quản trị viên) |
| 7 | `lan` ghi một phiếu cảm nhận | `curl` phiếu mới nhất (xem dưới) có `"username": "lan"` |
| 8 | Nhập sai mật khẩu 5 lần cho một tên | Lần thứ 6: "Sai mật khẩu quá nhiều lần… Thử lại sau 5:00" |
| 9 | Giữ nút reset 10 giây, tải lại dashboard | Hiện **Thiết lập lần đầu**; biểu đồ, nhật ký vẫn còn |

```bash
# Kiểm thử 7 (trên Pi)
KEY=$(grep '^API_KEY=' ~/pbl5-smart-ac/gateway/.env | cut -d= -f2)
curl -s -H "X-API-Key: $KEY" "http://localhost:8000/api/v1/rooms/room01/comfort?limit=1"
```

### 12.8 Giới hạn đã biết

- Dashboard vẫn chạy `http://`, không mã hóa. Dùng trong mạng nhà và mạng `SmartAC-Backup` (có mật khẩu WPA2); không mở cổng ra Internet.
- Ai có tem và vào được mạng của Pi thì nhận chủ được **khi Pi chưa có chủ hoặc vừa reset**. Sau khi thiết lập, tem không còn tác dụng cho tới lần reset sau.
- Ai cầm được Pi thì vẫn có toàn quyền (nút reset, thẻ nhớ), như mọi thiết bị trong nhà.

## Bước 13: Dùng từ xa qua Internet (Cloudflare Tunnel)

Lý do thiết kế: [ADR 0008](adr/0008-remote-access.md). Pi tự kết nối **ra** Cloudflare, nên không phải mở cổng trên router và vẫn chạy khi nhà mạng dùng CGNAT. Dashboard và app có địa chỉ HTTPS cố định, ví dụ `https://ac.ductruc.site`, dùng được cả khi điện thoại đang dùng 4G.

Cần: tên miền đã ở trạng thái **Active** trong tài khoản Cloudflare, và Pi đang ở Wi-Fi nhà có Internet.

### 13.1 Tạo tunnel trên Cloudflare

Giao diện Cloudflare đổi thường xuyên; tên mục dưới đây theo giao diện tháng 11/2026.

1. Dashboard Cloudflare (trang có danh sách tên miền) → menu trái **Networking → Tunnels** → **Create Tunnel**, đặt tên `pbl5-pi`. (Cách cũ, vẫn dùng được: **Zero Trust → Networks → Connectors → Cloudflare Tunnels**.)
2. Chọn hệ điều hành **Debian**, kiến trúc **arm64-bit**. Trang hiện lệnh cài `cloudflared` và lệnh `sudo cloudflared service install <token>`.
3. **Token là bí mật** (ai có nó thì chạy được tunnel của bạn): chỉ dán vào terminal của Pi, đừng gửi cho ai, đừng đưa vào git hay báo cáo. Có thể xem lại lệnh này bất cứ lúc nào trong trang của tunnel.

### 13.2 Cài trên Pi

SSH vào Pi, dán **lần lượt** các khối lệnh vừa copy. Kiểm tra:

```bash
sudo systemctl status cloudflared --no-pager | head -5   # active (running)
```

Trên trang Cloudflare, tunnel chuyển sang **Healthy**.

### 13.3 Gắn tên miền vào Pi

Trong trang của tunnel, thêm một **published application** (route):

| Ô | Giá trị |
|---|---|
| Subdomain | `ac` |
| Domain | `ductruc.site` |
| Path | để trống |
| Service URL | **`http://localhost:8000`** (phải ghi `http://`) |
| Additional application settings | để mặc định; **không bật Access** (app Android không qua được trang đăng nhập của Access) |

Bấm **Add route**. Cloudflare tự tạo bản ghi DNS và chứng chỉ HTTPS.

Nên chỉnh thêm trong trang của tên miền `ductruc.site`:

| Ở đâu | Làm gì | Vì sao |
|---|---|---|
| Caching → Cache Rules | Hostname bằng `ac.ductruc.site` → **Bypass cache** | Không thì sau khi cập nhật Pi, dashboard có thể vẫn chạy `app.js` cũ vài giờ |
| Security → Bots | **Bot Fight Mode: Off** | Có thể chặn app Android (lỗi 403 dù mật khẩu đúng) |
| SSL/TLS → Edge Certificates | **Always Use HTTPS: On** | `http://` tự chuyển sang `https://` |
| DNS → Settings | **DNSSEC: Enable** | Chống giả mạo tên miền |
| Security → WAF → Rate limiting (tùy chọn) | `/api/v1/auth/login`, 10 lần/phút mỗi IP → Block 1 phút | Thêm một lớp chống dò mật khẩu |

Báo cho gateway địa chỉ này, để app tự học và dùng khi ra ngoài:

```bash
cd ~/pbl5-smart-ac/gateway
echo 'PUBLIC_URL=https://ac.ductruc.site' >> .env
sudo systemctl restart pbl5-gateway
curl -s http://localhost:8000/api/v1/setup/status   # có "public_url": "https://ac.ductruc.site"
```

### 13.4 Kiểm thử

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Điện thoại tắt Wi-Fi, dùng 4G, mở `https://ac.ductruc.site` | Dashboard hiện trang đăng nhập, có ổ khóa HTTPS, không còn lỗi SSL của Brave |
| 2 | Đăng nhập, bấm Bật/Tắt | Lệnh chạy như ở nhà (chậm hơn khoảng 0,1–0,3 giây) |
| 3 | App: mở một lần khi ở Wi-Fi nhà (để app học địa chỉ), rồi tắt Wi-Fi, mở lại app | App vào thẳng màn hình điều khiển qua 4G, **không** phải đăng nhập lại |
| 4 | Đang mở app, bật lại Wi-Fi nhà | Sau vài giây app tự chuyển sang nói chuyện thẳng với Pi trong mạng nhà |
| 5 | Pi chưa có chủ (vừa reset), thử **Thiết lập lần đầu** qua 4G | "Thiết lập lần đầu chỉ làm được khi điện thoại ở cùng mạng…" |

### 13.5 Giới hạn đã biết

- Trang đăng nhập giờ ai trên Internet cũng mở được. Bảo vệ: mật khẩu băm scrypt, khóa tên 5 phút sau 5 lần sai, tài khoản mới phải chờ duyệt, thiết lập lần đầu chỉ trong mạng nhà. Đặt mật khẩu quản trị dài, không dùng lại mật khẩu ở nơi khác.
- Mất Internet ở nhà thì chỉ dùng được trong mạng nhà hoặc `SmartAC-Backup`, như trước.
- Tên miền hết hạn thì chỉ mất truy cập từ xa. Đổi tên miền: sửa Public Hostname trên Cloudflare và `PUBLIC_URL` trong `.env`.

## Bước 14: Nhận diện điều hòa (đổi giao thức IR không cần nạp lại firmware)

Lý do thiết kế: [ADR 0009](adr/0009-ir-protocol-detection.md). Từ bản 0.11.0, node nhớ giao thức IR trong bộ nhớ trong; đổi được trên dashboard hoặc app (chỉ quản trị viên).

### 14.1 Nạp firmware 0.11.0 cho node (một lần)

Mở `firmware/room_node/room_node.ino`, nạp như mọi lần (`config.h` giữ nguyên). Serial Monitor phải in `=== PBL5 Room Node 0.11.0` và dòng `[IR] Giao thuc … (model …)`, với giao thức là `IR_PROTOCOL` đang đặt trong `config.h` (ví dụ `DAIKIN`, hoặc `ELECTRA_AC` nếu đã sửa khi thử máy Casper). Sau khoảng 30 giây, mục **Điều hòa trong phòng** trên dashboard hiện đúng giao thức đó.

`config.h` chỉ được đọc **ở lần khởi động đầu tiên** của firmware 0.11.0. Từ đó node dùng giao thức lưu trong bộ nhớ trong, nên sửa `IR_PROTOCOL` trong `config.h` rồi nạp lại **không còn tác dụng**: đổi giao thức trên dashboard hoặc app.

### 14.2 Nhận diện remote

1. Dashboard (hoặc app) → mục **Điều hòa trong phòng** → **Nhận diện remote**.
2. Trong 60 giây: cầm remote của điều hòa, chĩa vào node (cách 1–2 m), bấm nút nguồn hoặc đổi nhiệt độ 2–3 lần.
3. Danh sách hiện các giao thức node nghe được:
   - Dòng có **"Remote vừa gửi: bật, mát, 25 °C"**: so với màn hình remote. **Khớp** thì bấm **Dùng giao thức này**. **Không khớp** (nhiệt độ vô lý như 37 °C): thư viện đoán sai giao thức, như trường hợp Casper; thử chọn theo hãng ở bước 14.4.
   - Dòng **UNKNOWN / "không phải giao thức điều hòa đã biết"**: node nghe thấy nhưng thư viện chưa hỗ trợ remote này; thử chọn theo hãng.
   - Không có dòng nào: đứng gần hơn, chĩa thẳng vào mắt thu (U2) của node.

### 14.3 Thử và xác nhận

Sau khi bấm **Dùng giao thức này**, bấm **Bật thử** (hoặc **Tắt thử**), nghe điều hòa bíp và nhìn đèn dàn lạnh.

- Có phản ứng → **Điều hòa đã phản ứng**. Mục này ghi "… đã xác nhận điều hòa nhận lệnh".
- Không phản ứng → **Không phản ứng**, rồi thử giao thức khác (dòng tiếp theo trong danh sách, hoặc theo hãng). Kiểm tra cả khoảng cách và hướng LED (Bước kiểm thử IR trong `docs/hardware/ir-circuit.md`).

### 14.4 Chọn theo hãng

**Chọn giao thức theo hãng** → chọn hãng → thử lần lượt từ dòng đầu, mỗi lần **Bật thử** cho tới khi điều hòa phản ứng. Hãng lắp ráp lại (Casper, Nagakawa, Funiki…) không có trong danh sách: dùng nhận diện.

### 14.5 Kiểm thử

| # | Thao tác | Kết quả đúng |
|---|---|---|
| 1 | Nhận diện, bấm remote TV | Hiện dòng NEC (hoặc tương tự), "không phải giao thức điều hòa"; trạng thái điều hòa không đổi |
| 2 | Nhận diện, bấm remote điều hòa | Hiện giao thức điều hòa và trạng thái vừa bấm |
| 3 | Dùng giao thức, Bật thử | Điều hòa bíp (nếu đúng giao thức) |
| 4 | Rút điện node, cắm lại | Serial Monitor in đúng giao thức vừa chọn (đã lưu) |
| 5 | Chọn một giao thức không tồn tại qua API (`PUT …/ir` với `"protocol": "ABC"`) | `422 PROTOCOL_NOT_SUPPORTED` |

## Xử lý lỗi thường gặp

**Dashboard trên điện thoại báo `ERR_SSL_PROTOCOL_ERROR` / "không thể cung cấp kết nối an toàn"**
- Trình duyệt (thường là Brave) tự đổi `http://` thành `https://`, còn dashboard chạy `http://`. Gõ đầy đủ `http://10.42.0.1:8000`; nếu vẫn lỗi, bấm biểu tượng sư tử và tắt Shields cho trang này, hoặc tắt "Nâng cấp kết nối lên HTTPS" trong cài đặt Brave, hoặc dùng Chrome.

**Vào `SmartAC-Backup` rồi mà trang không tải được**
- Mạng của Pi không có Internet, Android có thể tự chuyển sang dữ liệu di động. Khi điện thoại hỏi "Mạng này không có Internet. Vẫn kết nối?", chọn **Có** và **Không hỏi lại**, hoặc tắt dữ liệu di động khi thử nghiệm.

**Mở `http://10.42.0.1:8000` thì dashboard bắt đăng nhập lại, dù ở nhà đã đăng nhập**
- Trình duyệt nhớ phiên đăng nhập **theo từng địa chỉ**: `gateway.local`, IP của Pi trong mạng nhà và `10.42.0.1` là ba "trang" khác nhau. Đăng nhập lại bằng tên và mật khẩu (từ bản 0.9.0 không còn phải tìm khóa API). Khi chuyển sang **Độc lập** trên dashboard, bấm đường dẫn **"Mở dashboard ở mạng mới"** hiện ở đầu trang thì không phải đăng nhập lại. App Android (bản 0.10.0) sẽ không gặp chuyện này.

**Quên mật khẩu**
- Người khác: quản trị viên xóa tài khoản đó trong mục **Thành viên**, người đó tạo lại.
- Quản trị viên duy nhất: giữ nút reset trên Pi 10 giây (Bước 12.5), rồi thiết lập lại bằng mã trên tem. Hoặc, nếu còn SSH vào Pi: dùng khóa API trên dashboard (**Dùng khóa API** ở trang đăng nhập, khóa là `API_KEY` trong `gateway/.env`) rồi đặt quyền quản trị cho tài khoản khác.

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

## Các milestone

1. **Milestone 1:** đường truyền ESP32 ⇄ Pi, lưu database (v0.1.x). Mở rộng: mDNS (v0.2.0).
2. **Milestone 2 – IR:** giải mã và phát lệnh IR điều hòa (v0.3.0). Mở rộng: mạng dự phòng (v0.4.0).
3. **Milestone 3 – Cảm biến thật:** SHT3x (I2C, chân 8/9) và HLK-LD2420 (v0.5.0).
4. **Milestone 4 – Safety Layer + API:** FastAPI, trạng thái dự kiến, chống short-cycling, phân quyền (v0.6.0).
5. **Milestone 5 – Dashboard và phiếu cảm nhận** (v0.7.0).
6. **Milestone 6 – Mô hình tiện nghi và gợi ý nhiệt độ** (v0.8.0). Mở rộng: lệnh bị bỏ lỡ, chế độ mạng, tài khoản người dùng (v0.9.0); app Android và truy cập từ xa (v0.10.0); nhận diện giao thức IR (v0.11.0).

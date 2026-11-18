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

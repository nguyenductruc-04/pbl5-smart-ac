/* Dashboard dieu hoa thong minh.
 * Khong dung thu vien ngoai va khong can buoc build: Pi phuc vu thang cac file nay, ke ca khi mat Internet.
 * Moi noi dung dong deu ghi bang textContent (khong innerHTML) vi phien dang nhap nam trong trinh duyet.
 */
"use strict";

const API = "api/v1";
const POLL_MS = 3000;
const MODES = [["cool", "Mát"], ["dry", "Khô"], ["fan", "Quạt"], ["auto", "Tự động"], ["heat", "Sưởi"]];
const FANS = [["auto", "Tự động"], ["low", "Thấp"], ["mid", "Vừa"], ["high", "Cao"]];
const RANGES = [[6, "6 giờ"], [24, "24 giờ"], [168, "7 ngày"]];
const SOURCE = { app: "Ứng dụng", cli: "Dòng lệnh", remote: "Remote", rule: "Luật tự động", ai: "AI", sync: "Bạn đồng bộ" };
const MODE_PHRASE = { cool: "làm mát", dry: "hút ẩm", fan: "chỉ quạt", auto: "tự động", heat: "sưởi" };
const FAN_PHRASE = { auto: "tự động", low: "thấp", mid: "vừa", high: "cao" };
// Giai thich ma loi cua Safety Layer bang loi nguoi dung hieu duoc
const REASON = {
  NODE_OFFLINE: "Node của phòng đang mất kết nối nên lệnh không được gửi.",
  BROKER_UNAVAILABLE: "Raspberry Pi đang mất kết nối nội bộ (MQTT). Thử lại sau ít giây.",
  NODE_TIMEOUT: "Node không trả lời. Không chắc điều hòa đã nhận lệnh.",
  NODE_ERROR: "Node nhận lệnh nhưng không phát được tín hiệu hồng ngoại.",
  RATE_LIMIT: "Lệnh gửi quá dày.",
  COMPRESSOR_MIN_OFF: "Máy nén vừa tắt và cần nghỉ trước khi bật lại.",
  COMPRESSOR_MIN_ON: "Máy nén vừa chạy nên chế độ tự động chưa được tắt.",
  TEMP_OUT_OF_RANGE: "Nhiệt độ nằm ngoài khoảng cho phép.",
  MANUAL_HOLD: "Người dùng vừa điều chỉnh nên chế độ tự động tạm dừng.",
  STATE_UNCERTAIN: "Không chắc trạng thái điều hòa nên chế độ tự động chưa được chạy.",
  TELEMETRY_STALE: "Số đo cảm biến quá cũ để tự động quyết định.",
  ROOM_EMPTY: "Phòng không có người nên không tự động bật.",
  STEP_TOO_LARGE: "Chế độ tự động chỉ được đổi 1 °C mỗi lần.",
  NO_CHANGE: "Bỏ qua vì trùng trạng thái hiện tại.",
  UNAUTHORIZED: "Cần đăng nhập.",
  SESSION_INVALID: "Phiên đăng nhập đã hết hạn hoặc đã bị đăng xuất. Đăng nhập lại.",
  LOGIN_FAILED: "Sai tên đăng nhập hoặc mật khẩu.",
  LOGIN_LOCKED: "Sai mật khẩu quá nhiều lần.",
  ACCOUNT_PENDING: "Tài khoản đang chờ quản trị viên duyệt. Nhờ quản trị viên mở mục Thành viên và cấp quyền cho bạn.",
  USERNAME_TAKEN: "Tên đăng nhập này đã có người dùng. Chọn tên khác.",
  BAD_USERNAME: "Tên đăng nhập 3–32 ký tự: chữ thường không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang.",
  BAD_PASSWORD: "Mật khẩu cần 8–128 ký tự và không được trùng tên đăng nhập.",
  SETUP_CODE_INVALID: "Mã thiết lập không đúng. Xem lại tem dán trên Raspberry Pi.",
  SETUP_TOO_MANY: "Nhập sai mã quá nhiều lần.",
  ALREADY_CLAIMED: "Raspberry Pi này đã có quản trị viên. Đăng nhập, hoặc giữ nút reset trên Pi 10 giây để thiết lập lại.",
  NOT_CLAIMED: "Raspberry Pi chưa được thiết lập. Tạo tài khoản quản trị bằng mã trên tem trước.",
  REGISTER_TOO_MANY: "Có quá nhiều lượt đăng ký.",
  TOO_MANY_PENDING: "Đang có quá nhiều tài khoản chờ duyệt. Nhờ quản trị viên duyệt hoặc xóa bớt.",
  LAST_ADMIN: "Phải còn ít nhất một quản trị viên. Cấp quyền quản trị cho người khác trước.",
  USER_NOT_FOUND: "Tài khoản này không còn nữa.",
  WRONG_PASSWORD: "Mật khẩu hiện tại không đúng.",
  NOT_YOUR_VOTE: "Chỉ người gửi phiếu mới hoàn tác được.",
  HTTP_422: "Thông tin chưa hợp lệ. Tên đăng nhập 3–32 ký tự, mật khẩu 8–128 ký tự.",
  NETWORK: "Không kết nối được tới Raspberry Pi.",
  VOTE_TOO_FAST: "Vừa ghi xong, chờ vài giây rồi bấm lại.",
  UNDO_EXPIRED: "Đã quá 2 phút nên không hoàn tác được nữa.",
  VOTE_NOT_FOUND: "Phiếu này không còn nữa.",
  NO_STATE: "Chưa biết trạng thái điều hòa nên chưa có gì để gửi lại. Hãy bật hoặc tắt một lần.",
  CONFIRM_NOT_ALLOWED: "Chỉ người dùng mới được xác nhận bật lại sớm.",
  FORBIDDEN: "Tài khoản của bạn không có quyền làm việc đó.",
  PAIR_INVALID: "Mã QR đã dùng rồi hoặc đã hết hạn. Tạo mã mới trên thiết bị đã đăng nhập.",
  PAIR_TOO_MANY: "Thử sai quá nhiều lần. Chờ một phút rồi quét lại.",
};

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
const saved = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* che do rieng tu */ } },
};

const S = {
  token: saved.get("pbl5.token") || "",   // phien dang nhap tai khoan
  key: saved.get("pbl5.key") || "",       // khoa API (cong cu quan ly Pi), chi dung khi khong co phien
  me: null,                               // GET /auth/me
  members: [],                            // GET /users (chi quan tri vien)
  room: saved.get("pbl5.room") || "",
  hours: Number(saved.get("pbl5.hours")) || 24,
  policy: null,
  snap: null,        // GET /rooms/{room}
  snapAt: 0,         // performance.now() luc nhan snap, de dem nguoc giua hai lan hoi
  linkOk: true,
  pending: {},       // cac truong nguoi dung vua doi, chua duoc Pi xac nhan
  sending: false,
  again: false,
  timer: 0,
  lastSendAt: -1e9,  // performance.now() cua lan gui gan nhat, de tu gian cach theo Safety Layer
  ticks: 0,
  series: null,
  suggestion: null,
  votesToday: 0,
  lastVote: null,    // phieu vua ghi trong phien nay (de hoan tac)
  lastVoteAt: 0,     // performance.now() luc ghi
  voting: false,
  voteCooldownUntil: 0,   // khoa nut vai giay sau moi lan ghi, tranh bam dup
  confirmBody: null,      // lenh bat dang cho nguoi dung xac nhan (may nen vua tat)
  net: null,              // GET /system/network
  netAsk: null,           // che do mang dang cho xac nhan
  netSwitch: null,        // vua chuyen sang che do nay (de huong dan khi trang mat ket noi)
  netLink: null,          // duong dan sang dia chi moi kem ma ghep, de khong phai nhap lai khoa
  clockSkew: 0,           // dong ho Pi lech dong ho thiet bi nay (giay)
};

// ------------------------------------------------------------------ goi API
function authHeader() {
  if (S.token) return { Authorization: `Bearer ${S.token}` };
  return S.key ? { "X-API-Key": S.key } : {};
}
const mayControl = () => Boolean(S.me && (S.me.role === "admin" || S.me.role === "member"));
const isAdmin = () => Boolean(S.me && S.me.role === "admin");
const needsLogin = (e) => ["UNAUTHORIZED", "SESSION_INVALID", "ACCOUNT_PENDING"].includes(e.code);

async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      method,
      cache: "no-store",
      headers: { ...authHeader(), ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw Object.assign(new Error("network"), { code: "NETWORK" });
  }
  let data = null;
  try { data = await res.json(); } catch { /* khong phai JSON */ }
  if (!res.ok) {
    const err = (data && data.error) || {};
    throw Object.assign(new Error(err.message || res.statusText), {
      status: res.status, code: err.code || `HTTP_${res.status}`, retryAfter: err.retry_after_s,
      canConfirm: Boolean(err.can_confirm),
    });
  }
  return data;
}

const explain = (e) => {
  let text = REASON[e.code] || `Lệnh không thực hiện được (${e.code}).`;
  if (e.retryAfter && e.code !== "RATE_LIMIT") text += ` Thử lại sau ${clock(e.retryAfter)}.`;
  return text;
};

// ------------------------------------------------------------------ dinh dang
const num = (v, digits) => v.toLocaleString("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pad = (n) => String(n).padStart(2, "0");
function clock(seconds) {                       // 135 -> "2:15", 2400 -> "40 phút"
  const s = Math.max(0, Math.round(seconds));
  if (s >= 600) return `${Math.round(s / 60)} phút`;
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}
function ago(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} giây trước`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} phút trước`;
  return `${Math.round(seconds / 3600)} giờ trước`;
}
function when(ts, withDate) {
  const d = new Date(ts * 1000);
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const sameDay = d.toDateString() === new Date().toDateString();
  return withDate || !sameDay ? `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${hm}` : hm;
}
function describe(state) {
  if (!state || state.power === "off") return "tắt điều hòa";
  if (state.mode === "fan") return `bật chỉ quạt, quạt ${FAN_PHRASE[state.fan] || state.fan}`;
  return `bật ${MODE_PHRASE[state.mode] || state.mode} ${state.temp} °C, quạt ${FAN_PHRASE[state.fan] || state.fan}`;
}

// ------------------------------------------------------------------ trang thai hien thi
const elapsed = () => (performance.now() - S.snapAt) / 1000;
const nodeOnline = () => Boolean(S.snap && S.snap.node.status === "online");
function view() {
  const p = S.policy || {};
  const base = (S.snap && S.snap.ac) ||
    { power: "off", mode: p.default_mode || "cool", temp: p.default_temp || 26, fan: p.default_fan || "auto" };
  return { ...base, ...S.pending };
}

function setSnap(snap) {
  S.snap = snap;
  S.snapAt = performance.now();
}

// ------------------------------------------------------------------ ve giao dien
function segmented(container, options, onPick) {
  for (const [value, label] of options) {
    const b = el("button", { type: "button", textContent: label });
    b.dataset.value = value;
    b.setAttribute("role", "radio");
    b.addEventListener("click", () => onPick(value));
    container.append(b);
  }
}
function markSegment(container, value) {
  for (const b of container.children) b.setAttribute("aria-checked", String(b.dataset.value === String(value)));
}

function setNotices(list) {
  const box = $("notices");
  const keep = new Set(list.map((n) => n.id));
  for (const node of [...box.children]) if (!keep.has(node.dataset.id)) node.remove();
  for (const n of list) {
    let node = [...box.children].find((c) => c.dataset.id === n.id);
    if (!node) {
      node = el("div", { className: "notice" }, el("span"));
      node.dataset.id = n.id;
      if (n.action) node.append(el("button", { type: "button", textContent: n.action.label, onclick: n.action.run }));
      if (n.link) node.append(el("a", { href: n.link.href, textContent: n.link.label, className: "notice-link" }));
      box.append(node);
    }
    node.classList.toggle("bad", Boolean(n.bad));
    if (node.firstChild.textContent !== n.text) node.firstChild.textContent = n.text;
  }
}

function render() {
  if (!S.snap) return;
  const { node, telemetry: tel, ac, safety } = S.snap;
  const v = view();
  const online = nodeOnline();
  const dt = elapsed();
  const p = S.policy || { temp_min: 16, temp_max: 30 };

  // --- thanh tren
  const link = $("link");
  link.dataset.state = !S.linkOk ? "error" : online ? "online" : "offline";
  $("link-text").textContent = !S.linkOk ? "Mất kết nối tới Pi" : online ? "Node đang kết nối" : "Node mất kết nối";

  // --- thong bao
  const notices = [];
  const compressorWait = safety.compressor_ready_in_s - dt;
  const holdLeft = safety.auto_hold_remaining_s - dt;
  if (!S.linkOk && S.netSwitch) {
    notices.push({ id: `net-${S.netSwitch}`, bad: true, text: NET_LOST[S.netSwitch],
                   link: S.netLink ? { href: S.netLink, label: "Mở dashboard ở mạng mới" } : null });
  }
  else if (!S.linkOk) notices.push({ id: "link", bad: true, text: "Không kết nối được tới Raspberry Pi. Trang đang tự thử lại." });
  if (Math.abs(S.clockSkew) > 120) {
    notices.push({ id: "clock", text: `Đồng hồ của Raspberry Pi đang lệch ${clock(Math.abs(S.clockSkew))} so với thiết bị này, nên số đo và phiếu cảm nhận sẽ ghi sai giờ. Cho Pi vào mạng có Internet để tự chỉnh giờ.` });
  }
  else if (!online) notices.push({ id: "offline", bad: true, text: "Node của phòng đang mất kết nối. Điều hòa giữ nguyên trạng thái hiện tại và remote vẫn dùng được." });
  else if (ac && ac.uncertain) {
    notices.push({ id: "uncertain", text: "Trạng thái điều hòa hiển thị ở đây có thể đã lệch với thực tế." +
      (mayControl() ? " Gửi một lệnh bất kỳ, hoặc mở \"Điều hòa không làm theo?\" để sửa." : "") });
  }
  if (online && compressorWait > 0 && v.power === "off") {
    notices.push({ id: "compressor", text: `Máy nén đang nghỉ thêm ${clock(compressorWait)}. Cần bật ngay thì bấm Bật rồi xác nhận.` });
  }
  if (safety.automation_enabled && holdLeft > 0) {
    const who = safety.auto_hold_source === "remote" ? "remote" : "ứng dụng";
    notices.push({
      id: "hold",
      text: `Chế độ tự động tạm dừng thêm ${clock(holdLeft)} vì vừa có người điều chỉnh bằng ${who}.`,
      action: mayControl() ? { label: "Cho tự động chạy lại", run: clearHold } : null,
    });
  }
  if (S.me && S.me.role === "guest") {
    notices.push({ id: "guest", text: "Bạn đang dùng tài khoản khách nên chỉ xem được. Nhờ quản trị viên cấp quyền thành viên nếu cần điều khiển." });
  }
  const waiting = S.members.filter((u) => u.role === "pending").length;
  if (isAdmin() && waiting) {
    notices.push({
      id: `pending-${waiting}`,
      text: `Có ${waiting} tài khoản đang chờ bạn duyệt.`,
      action: { label: "Xem", run: () => $("members").scrollIntoView({ behavior: "smooth", block: "start" }) },
    });
  }
  setNotices(notices);
  // Lap lai ngay trong muc Mang: nguoi dung vua bam Chuyen o cuoi trang, khong thay thong bao o dau trang
  const lost = !S.linkOk && S.netSwitch;
  $("net-lost").hidden = !lost;
  if (lost) {
    $("net-lost-text").textContent = NET_LOST[S.netSwitch];
    $("net-lost-link").hidden = !S.netLink;
    if (S.netLink) $("net-lost-link").href = S.netLink;
  }

  // --- dieu khien
  const canControl = S.linkOk && online && mayControl();
  const on = v.power === "on";
  const power = $("power");
  power.disabled = !canControl;
  power.setAttribute("aria-pressed", String(on));
  $("power-text").textContent = on ? "Tắt điều hòa" : "Bật điều hòa";
  $("tuning").disabled = !canControl || !on;
  $("ac-summary").textContent = !ac ? "Chưa biết trạng thái điều hòa"
    : `${SOURCE[ac.source] || ac.source} đặt lúc ${when(ac.since)}`;
  $("resend").disabled = !canControl || !ac || S.sending;
  $("sync-power").disabled = !S.linkOk || S.sending || !mayControl();
  $("sync-power").textContent = on ? "Thực tế điều hòa đang tắt" : "Thực tế điều hòa đang bật";

  const sp = $("setpoint");
  sp.replaceChildren(String(v.temp), el("small", { textContent: "°C" }));
  const range = $("temp-range");
  range.min = p.temp_min; range.max = p.temp_max;
  if (document.activeElement !== range || !range.matches(":active")) range.value = v.temp;
  range.setAttribute("aria-valuetext", `${v.temp} độ C`);
  $("temp-down").disabled = v.temp <= p.temp_min;
  $("temp-up").disabled = v.temp >= p.temp_max;
  markSegment($("mode"), v.mode);
  markSegment($("fan"), v.fan);

  // --- thang nhiet: moc nhiet do phong va khoang cach toi nhiet do dat
  const span = p.temp_max - p.temp_min;
  const pct = (t) => Math.min(100, Math.max(0, ((t - p.temp_min) / span) * 100));
  const roomMark = $("scale-room");
  const gap = $("scale-gap");
  if (tel) {
    const x = pct(tel.temp);
    roomMark.hidden = false;
    roomMark.style.left = `${x}%`;
    roomMark.dataset.edge = x < 12 ? "left" : x > 88 ? "right" : "";
    $("scale-room-text").textContent = `Phòng ${num(tel.temp, 1)}°`;
    const a = pct(v.temp);
    gap.style.left = `${Math.min(a, x)}%`;
    gap.style.width = on ? `${Math.abs(x - a)}%` : "0";
  } else {
    roomMark.hidden = true;
    gap.style.width = "0";
  }

  // --- so do
  const reading = (id, text, unit) => $(id).replaceChildren(text, ...(unit ? [el("small", { textContent: unit })] : []));
  if (tel) {
    reading("r-temp", num(tel.temp, 1), "°C");
    reading("r-hum", num(tel.hum, 0), "%");
    reading("r-presence", tel.presence === null ? "Chưa rõ" : tel.presence ? "Có" : "Không");
    $("r-age").textContent = `Cập nhật ${ago(tel.age_s + dt)}.` +
      (tel.simulated ? " Số đo đang là giả lập vì node chưa gắn cảm biến." : "");
  } else {
    reading("r-temp", "–"); reading("r-hum", "–"); reading("r-presence", "–");
    $("r-age").textContent = "Chưa nhận được số đo nào từ node.";
  }
}

// ------------------------------------------------------------------ phieu cam nhan (nhan cho AI)
const VOTE_LABEL = { cooler: "Muốn mát hơn", comfortable: "Dễ chịu", warmer: "Muốn ấm hơn" };
const UNDO_WINDOW_S = 120;

function voteStatus(text, kind = "") {
  const box = document.querySelector(".vote-status");
  $("vote-text").textContent = text;
  box.dataset.kind = kind;
}

function canVote() {
  if (!S.snap || !S.linkOk || !nodeOnline() || !mayControl()) return false;
  const tel = S.snap.telemetry;
  const stale = (S.policy && S.policy.telemetry_stale_s) || 120;
  return Boolean(tel) && tel.age_s + elapsed() <= stale;
}

function renderVotes() {
  const ok = canVote();
  const cooling = performance.now() < S.voteCooldownUntil;
  for (const b of $("votes").children) b.disabled = !ok || S.voting || cooling;
  const recent = S.lastVote && (performance.now() - S.lastVoteAt) / 1000 < UNDO_WINDOW_S;
  $("vote-undo").hidden = !recent;
  for (const b of $("votes").children) b.setAttribute("aria-pressed", String(Boolean(recent && b.dataset.vote === S.lastVote.vote)));
  if (!ok && !$("vote-text").textContent) voteStatus("Chưa có số đo mới từ node nên chưa ghi được.");
  if (ok && $("vote-text").textContent === "Chưa có số đo mới từ node nên chưa ghi được.") voteStatus("");
  $("vote-count").textContent = S.votesToday ? `Hôm nay bạn đã ghi ${S.votesToday} lần.` : "Hôm nay chưa ghi lần nào.";
}

async function loadVotes() {
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  try {
    const r = await api(`/rooms/${S.room}/comfort?limit=1000&since=${midnight.getTime() / 1000}`);
    S.votesToday = r.items.length;
  } catch { /* lan sau thu lai */ }
  renderVotes();
}

async function castVote(vote) {
  if (S.voting) return;
  S.voting = true;
  renderVotes();
  try {
    const v = await api(`/rooms/${S.room}/comfort`, { method: "POST", body: { vote } });
    S.lastVote = v;
    S.lastVoteAt = performance.now();
    S.voteCooldownUntil = S.lastVoteAt + 5000;
    S.votesToday += 1;
    loadSuggestion();
    voteStatus(`Đã ghi "${VOTE_LABEL[v.vote]}" lúc ${when(v.ts)}, phòng ${num(v.temp, 1)} °C.`, "ok");
  } catch (e) {
    if (needsLogin(e)) signedOut(explain(e));
    else if (e.code === "TELEMETRY_STALE") voteStatus("Chưa có số đo mới từ node nên phiếu chưa được ghi.", "bad");
    else if (e.code === "VOTE_TOO_FAST") voteStatus(REASON.VOTE_TOO_FAST, "bad");
    else voteStatus(explain(e), "bad");
  } finally {
    S.voting = false;
    renderVotes();
  }
}

async function undoVote() {
  if (!S.lastVote) return;
  try {
    await api(`/rooms/${S.room}/comfort/${S.lastVote.id}`, { method: "DELETE" });
    S.votesToday = Math.max(0, S.votesToday - 1);
    voteStatus("Đã hoàn tác phiếu vừa ghi.");
  } catch (e) {
    voteStatus(explain(e), "bad");
  }
  S.lastVote = null;
  renderVotes();
}

// ------------------------------------------------------------------ goi y (M6)
const MODE_NAME = { cool: "mát", dry: "khô", auto: "tự động", fan: "quạt", heat: "sưởi" };

function adviceText(s) {
  const t = s.target;
  const room = s.room_temp == null ? "" : `Phòng ${num(s.room_temp, 1)} °C. `;
  switch (s.reason) {
    case "TOO_WARM": return `${room}Có vẻ hơi nóng với bạn. Nên bật điều hòa ở ${t.temp} °C.`;
    case "WARMER_SETPOINT": return `Có thể tăng lên ${t.temp} °C mà vẫn dễ chịu, đỡ tốn điện.`;
    case "COOLER_SETPOINT": return `${room}Nên giảm nhiệt độ đặt xuống ${t.temp} °C.`;
    case "ROOM_EMPTY_LONG": return "Phòng đã trống hơn 15 phút. Nên tắt điều hòa.";
    case "SLIGHTLY_WARM": {
      const hi = num(s.comfort_band[1], 1);
      const p = s.comfort ? ` (khả năng bạn muốn mát hơn: ${Math.round(s.comfort.cooler * 100)} %)` : "";
      return `${room}Ấm hơn vùng dễ chịu của bạn (trên ${hi} °C) nhưng chưa nóng hẳn${p}. Nếu thấy nóng, có thể bật ở ${t.temp} °C.`;
    }
    case "COMFORTABLE": return `${room}Phòng đang dễ chịu với bạn, chưa cần bật điều hòa.`;
    case "TOO_COOL_AC_OFF": return `${room}Phòng hơi mát với bạn.`;
    case "SETPOINT_OK": return "Nhiệt độ đặt hiện tại đang hợp với bạn.";
    case "ROOM_EMPTY": return "Phòng đang trống, chưa có gợi ý.";
    case "MODE_NOT_SUPPORTED": return `Gợi ý chỉ áp dụng cho chế độ mát, khô hoặc tự động (đang ở ${MODE_NAME[S.snap?.ac?.mode] || "chế độ khác"}).`;
    default: return "Chưa có số đo mới nên chưa có gợi ý.";
  }
}

function renderAdvice() {
  const s = S.suggestion;
  $("advice").hidden = !s;
  if (!s) return;
  $("advice-text").textContent = adviceText(s);
  const offered = s.action !== "none" || s.reason === "SLIGHTLY_WARM";   // SLIGHTLY_WARM: chi de nghi, khong tu lam
  const canApply = s.target && offered && !s.auto && S.linkOk && nodeOnline() && mayControl();
  $("advice-apply").hidden = !canApply;
  const [lo, hi] = s.comfort_band;
  const m = s.model;
  let why = `Vùng dễ chịu của bạn: ${num(lo, 1)}–${num(hi, 1)} °C. `;
  why += m.personal
    ? `Học từ ${m.votes} phiếu của bạn và dữ liệu khảo sát tiện nghi ASHRAE.`
    : `Đang dùng mô hình chung từ dữ liệu khảo sát ASHRAE; sẽ hợp với bạn hơn khi có từ 10 phiếu (hiện có ${m.votes}).`;
  if (s.auto) why += " Chế độ tự động đang bật: hệ thống tự áp dụng gợi ý, qua Safety Layer.";
  $("advice-why").textContent = why;
}

async function loadSuggestion() {
  try {
    S.suggestion = await api(`/rooms/${S.room}/suggestion`);
  } catch { /* giu goi y cu */ }
  renderAdvice();
}

function applyAdvice() {
  const t = S.suggestion && S.suggestion.target;
  if (!t) return;
  change({ ...t }, 0);
}

function feedback(text, kind = "") {
  const f = $("feedback");
  f.textContent = text;
  f.dataset.kind = kind;
}

// ------------------------------------------------------------------ gui lenh
// Nguoi dung co the bam + nhieu lan lien tiep: gom lai va chi gui trang thai cuoi cung.
function change(patch, delay) {
  Object.assign(S.pending, patch);
  render();
  // Tu gian cach theo gioi han tan suat cua Pi de khong bi tu choi (lenh tat thi khong bi gioi han)
  if (S.pending.power !== "off" && S.policy) {
    const since = performance.now() - S.lastSendAt;
    delay = Math.max(delay, S.policy.manual_min_interval_s * 1000 + 150 - since);
  }
  clearTimeout(S.timer);
  S.timer = setTimeout(flush, delay);
}

async function flush() {
  clearTimeout(S.timer);
  if (S.sending) { S.again = true; return; }
  const body = { ...S.pending };
  if (!Object.keys(body).length) return;
  S.sending = true;
  feedback("Đang gửi lệnh…");
  let waitMs = 0;
  try {
    const r = await api(`/rooms/${S.room}/commands`, { method: "POST", body });
    S.lastSendAt = performance.now();
    for (const k of Object.keys(body)) if (S.pending[k] === body[k]) delete S.pending[k];
    setSnap(r.room);
    feedback(`Đã phát lệnh tới điều hòa (${r.latency_ms} ms).`, "ok");
  } catch (e) {
    if (e.code === "RATE_LIMIT" && e.retryAfter) {
      waitMs = e.retryAfter * 1000 + 100;          // tu gui lai trang thai moi nhat khi het han
      feedback("Đang chờ để gửi lệnh…");
    } else if (e.code === "COMPRESSOR_MIN_OFF" && e.canConfirm) {
      S.pending = {};
      askConfirm(body, e.retryAfter);
    } else if (needsLogin(e)) {
      S.pending = {};
      signedOut(explain(e));
    } else {
      S.pending = {};
      feedback(explain(e), "bad");
      refresh();
    }
  } finally {
    S.sending = false;
    render();
    loadLog();
    loadSuggestion();
    if (waitMs) S.timer = setTimeout(flush, waitMs);
    else if (S.again && Object.keys(S.pending).length) change({}, 0);
    S.again = false;
  }
}

// ------------------------------------------------------------------ khi dieu hoa khong lam theo
// Bat lai som khi may nen vua tat: Pi hoi lai thay vi cam (dong ho co the dang tinh tu mot lan tat
// ma dieu hoa chua he nhan). Lenh tu dong khong bao gio duoc xac nhan kieu nay.
function askConfirm(body, waitS) {
  S.confirmBody = body;
  $("confirm-text").textContent = `Máy nén vừa tắt, còn ${clock(waitS || 0)} nữa mới hết thời gian nghỉ. ` +
    "Nếu điều hòa vừa bỏ lỡ lệnh thì thật ra máy nén chưa chạy. Phần lớn điều hòa cũng tự chờ trước khi chạy lại máy nén. Vẫn bật?";
  $("confirm").hidden = false;
  feedback("");
  $("confirm-yes").focus();
}

function closeConfirm(text) {
  $("confirm").hidden = true;
  S.confirmBody = null;
  if (text) feedback(text);
}

// Chay mot thao tac gui len Pi, hien ket qua o dong phan hoi, roi lam moi giao dien
async function act(label, run) {
  if (S.sending) return;
  S.sending = true;
  feedback(label);
  render();
  try {
    await run();
  } catch (e) {
    if (needsLogin(e)) signedOut(explain(e));
    else feedback(explain(e), "bad");
    refresh();
  } finally {
    S.sending = false;
    render();
    loadLog();
    loadSuggestion();
  }
}

function sendConfirmed() {
  const body = S.confirmBody;
  closeConfirm();
  if (!body) return;
  act("Đang gửi lệnh…", async () => {
    const r = await api(`/rooms/${S.room}/commands`, { method: "POST", body: { ...body, confirm: true } });
    S.lastSendAt = performance.now();
    setSnap(r.room);
    feedback(`Đã phát lệnh tới điều hòa (${r.latency_ms} ms).`, "ok");
  });
}

function resendState() {
  act("Đang gửi lại…", async () => {
    const r = await api(`/rooms/${S.room}/commands/resend`, { method: "POST" });
    S.lastSendAt = performance.now();
    setSnap(r.room);
    feedback(`Đã gửi lại: ${describe(r.requested)}.`, "ok");
  });
}

function syncPower() {
  const power = view().power === "on" ? "off" : "on";
  act("Đang cập nhật…", async () => {
    setSnap(await api(`/rooms/${S.room}/ac-state`, { method: "PUT", body: { power } }));
    S.pending = {};
    feedback(`Đã ghi nhận điều hòa đang ${power === "on" ? "bật" : "tắt"}. Không có tín hiệu nào được phát.`, "ok");
  });
}

async function clearHold() {
  try {
    setSnap(await api(`/rooms/${S.room}/auto-hold`, { method: "DELETE" }));
    feedback("Chế độ tự động được chạy lại.", "ok");
  } catch (e) {
    feedback(explain(e), "bad");
  }
  render();
}

// ------------------------------------------------------------------ nhat ky
async function loadLog() {
  let decisions, commands, remote;
  try {
    [decisions, commands, remote] = await Promise.all([
      api(`/rooms/${S.room}/decisions?limit=30`),
      api(`/rooms/${S.room}/commands?limit=40`),
      api(`/rooms/${S.room}/ir-events?limit=10`),
    ]);
  } catch { return; }
  const results = new Map(commands.items.map((c) => [c.cmd_id, c]));
  const now = Date.now() / 1000;
  const rows = decisions.items.map((d) => {
    let verdict = d.verdict, why = REASON[d.code] || d.code;
    const how = { RESEND: "Gửi lại. ", EARLY_START_CONFIRMED: "Bạn xác nhận bật lại sớm. " }[d.code] || "";
    if (d.verdict === "sync") {
      const actual = d.requested && d.requested.power === "on" ? "bật" : "tắt";
      return { ts: d.ts, who: "Bạn", what: `báo điều hòa thực tế đang ${actual}`, verdict,
               why: "Chỉ sửa trạng thái trên màn hình, không phát tín hiệu." };
    }
    if (d.verdict === "allow") {
      const c = results.get(d.cmd_id);
      if (c && c.ok) { why = `${how}Đã phát lệnh (${c.latency_ms} ms).`; }
      else if (c && c.ok === false) { verdict = "fail"; why = REASON.NODE_ERROR; }
      else if (now - d.ts < 8) { why = "Đang chờ node trả lời."; }
      else { verdict = "fail"; why = REASON.NODE_TIMEOUT; }
    }
    return { ts: d.ts, who: SOURCE[d.source] || d.source, what: describe(d.requested), verdict, why };
  });
  for (const r of remote.items) {
    rows.push({ ts: r.ts, who: SOURCE.remote, what: describe(r), verdict: "allow", why: "Người dùng bấm remote, node nghe được." });
  }
  rows.sort((a, b) => b.ts - a.ts);
  const list = $("log");
  list.replaceChildren(...rows.slice(0, 30).map((r) => {
    const li = el("li", {},
      el("time", { textContent: when(r.ts), dateTime: new Date(r.ts * 1000).toISOString() }),
      el("span", { className: "what" }, el("b", { textContent: r.who }), ` ${r.what}`),
      el("span", { className: "why", textContent: r.why }));
    li.dataset.verdict = r.verdict;
    return li;
  }));
  $("log-empty").hidden = rows.length > 0;
}

// ------------------------------------------------------------------ bieu do
const SVG = "http://www.w3.org/2000/svg";
const svg = (tag, attrs = {}) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};

function niceTicks(min, max, count) {
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(Math.round(t * 100) / 100);
  return ticks;
}

function drawChart(host, series, field, colorVar, unit, digits) {
  host.replaceChildren();
  const pts = series.items;
  if (pts.length < 2) {
    host.append(el("div", { className: "none", textContent: "Chưa đủ số đo trong khoảng thời gian này." }));
    return;
  }
  const W = host.clientWidth, H = host.clientHeight;
  const m = { l: 34, r: 8, t: 8, b: 20 };
  const values = pts.map((p) => p[field]);
  let lo = Math.min(...values), hi = Math.max(...values);
  const padY = Math.max((hi - lo) * 0.15, field === "temp" ? 0.5 : 2);
  lo -= padY; hi += padY;
  const x = (ts) => m.l + ((ts - series.since) / (series.until - series.since)) * (W - m.l - m.r);
  const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": host.previousElementSibling.textContent });

  for (const t of niceTicks(lo, hi, 3)) {
    root.append(svg("line", { class: "grid", x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }));
    const label = svg("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" });
    label.textContent = num(t, t % 1 ? 1 : 0);
    root.append(label);
  }
  const hours = (series.until - series.since) / 3600;
  for (let i = 0; i <= 4; i += W < 460 ? 2 : 1) {      // man hinh hep: 3 nhan thay vi 5
    const ts = series.since + ((series.until - series.since) * i) / 4;
    const label = svg("text", { x: x(ts), y: H - 4, "text-anchor": i === 0 ? "start" : i === 4 ? "end" : "middle" });
    label.textContent = when(ts, hours > 24);
    root.append(label);
  }
  // Ngat duong ve o nhung khoang mat du lieu (node offline) thay vi noi thang qua
  const gapS = Math.max(series.bucket_s * 2.5, 180);
  let d = "";
  pts.forEach((p, i) => {
    const jump = i === 0 || p.ts - pts[i - 1].ts > gapS;
    d += `${jump ? "M" : "L"}${x(p.ts).toFixed(1)},${y(p[field]).toFixed(1)}`;
  });
  root.append(svg("path", { class: "series", d, stroke: `var(${colorVar})` }));

  const cross = svg("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" });
  const dot = svg("circle", { class: "pt", r: 4.5, fill: `var(${colorVar})`, visibility: "hidden" });
  root.append(cross, dot);
  const tip = el("div", { className: "tip", hidden: true });
  host.append(root, tip);

  const hover = (ev) => {
    const box = host.getBoundingClientRect();
    const px = ev.clientX - box.left;
    let best = pts[0];
    for (const p of pts) if (Math.abs(x(p.ts) - px) < Math.abs(x(best.ts) - px)) best = p;
    const bx = x(best.ts), by = y(best[field]);
    cross.setAttribute("x1", bx); cross.setAttribute("x2", bx); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", bx); dot.setAttribute("cy", by); dot.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = `${num(best[field], digits)} ${unit}, ${when(best.ts, hours > 24)}`;
    tip.style.left = `${Math.min(W - 70, Math.max(70, bx))}px`;
    tip.style.top = `${Math.max(22, by - 8)}px`;
  };
  const leave = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); };
  host.onpointermove = hover;
  host.onpointerdown = hover;
  host.onpointerleave = leave;
}

function drawSeries() {
  if (!S.series) return;
  drawChart($("chart-temp"), S.series, "temp", "--series-temp", "°C", 1);
  drawChart($("chart-hum"), S.series, "hum", "--series-hum", "%", 0);
  const body = $("series-table").tBodies[0];
  body.replaceChildren(...[...S.series.items].reverse().map((p) => el("tr", {},
    el("td", { textContent: when(p.ts, true) }), el("td", { textContent: num(p.temp, 1) }), el("td", { textContent: num(p.hum, 0) }))));
}

async function loadSeries() {
  try {
    S.series = await api(`/rooms/${S.room}/telemetry/series?hours=${S.hours}&points=${Math.min(300, Math.max(60, Math.round($("chart-temp").clientWidth / 3)))}`);
    drawSeries();
  } catch { /* giu bieu do cu, lan sau thu lai */ }
}

// ------------------------------------------------------------------ vong lap cap nhat
async function refresh() {
  try {
    const snap = await api(`/rooms/${S.room}`);
    if (!S.sending) setSnap(snap);
    S.linkOk = true;
    S.netSwitch = null;
  } catch (e) {
    if (needsLogin(e)) return signedOut(explain(e));
    S.linkOk = false;
  }
  render();
}

async function tick() {
  if (!document.hidden && S.snap) {
    S.ticks += 1;
    await refresh();
    if (S.ticks % 4 === 0) loadLog();
    if (S.ticks % 2 === 0) loadSuggestion();
    if (S.ticks % 20 === 0) loadSeries();
    const netPending = S.net && S.net.status && S.net.status.mode !== S.net.mode;
    if (S.ticks % (netPending ? 2 : 10) === 0) loadNet();
    if (S.ticks % 100 === 0) checkClock();
    if (isAdmin() && S.ticks % 10 === 0) loadMembers();
  }
  setTimeout(tick, POLL_MS);
}

function showEmpty(text) {
  $("app").hidden = true;
  $("empty").hidden = false;
  $("empty").textContent = text;
}

async function start() {
  let rooms;
  try {
    [S.me, S.policy, { rooms }] = await Promise.all([api("/auth/me"), api("/policy"), api("/rooms")]);
  } catch (e) {
    if (needsLogin(e)) return signedOut(explain(e));
    showEmpty("Không kết nối được tới Raspberry Pi. Kiểm tra Pi đang bật và dịch vụ pbl5-gateway đang chạy, rồi tải lại trang.");
    return;
  }
  showAccount();
  if (isAdmin()) loadMembers();
  if (!rooms.length) {
    showEmpty("Chưa có node nào từng kết nối tới Pi. Cấp nguồn cho node của phòng, đợi node báo online rồi tải lại trang.");
    return;
  }
  if (!rooms.some((r) => r.room === S.room)) S.room = rooms[0].room;
  const select = $("room-select");
  select.replaceChildren(...rooms.map((r) => el("option", { value: r.room, textContent: r.room })));
  select.value = S.room;
  select.hidden = rooms.length < 2;

  const ticks = $("scale-ticks");
  const span = S.policy.temp_max - S.policy.temp_min;
  ticks.replaceChildren();
  for (let t = S.policy.temp_min; t <= S.policy.temp_max; t += 2) {
    const tickEl = el("span", { textContent: String(t) });
    tickEl.style.left = `${((t - S.policy.temp_min) / span) * 100}%`;
    ticks.append(tickEl);
  }

  await refresh();
  if (!S.snap) return showEmpty("Không đọc được trạng thái phòng. Tải lại trang để thử lại.");
  $("empty").hidden = true;
  $("app").hidden = false;
  $("pair-btn").hidden = !mayControl();
  render();
  loadLog();
  loadSeries();
  loadVotes();
  loadSuggestion();
  loadNet();
  checkClock();
}

// ------------------------------------------------------------------ mang cua Pi
const NET_MODES = [["auto", "Tự động"], ["standalone", "Độc lập"], ["home", "Chỉ Wi-Fi nhà"]];
const NET_DESC = {
  auto: "Dùng Wi-Fi nhà. Mất Wi-Fi nhà quá 2 phút thì Pi tự phát mạng SmartAC-Backup, và cứ 5 phút thử quay về. Dùng hằng ngày ở nhà.",
  standalone: "Pi luôn phát mạng SmartAC-Backup, không dùng Wi-Fi nhà và không có Internet. Dùng khi đi thử nghiệm hoặc demo, chỉ cần Pi và node.",
  home: "Chỉ dùng Wi-Fi nhà, không bao giờ phát mạng riêng. Router hỏng thì mất kết nối tới khi router chạy lại.",
};
const NET_NAME = Object.fromEntries(NET_MODES);
let NET_LOST = {};   // huong dan khi trang mat ket noi ngay sau khi chuyen che do (dien sau khi biet dia chi)

function netStatusText(n) {
  const st = n.status;
  if (!st || !st.running) return "Dịch vụ pbl5-netwatch không chạy, nên đổi chế độ sẽ chưa có tác dụng (xem SETUP bước 6).";
  const where = st.state === "ap" ? `Pi đang phát Wi-Fi riêng ${n.ap_ssid}.`
    : st.state === "home" ? `Pi đang dùng Wi-Fi nhà “${st.connection}”.` : "Pi đang mất Wi-Fi.";
  const pending = st.mode !== n.mode ? ` Đang chuyển sang chế độ ${NET_NAME[n.mode]}…` : ` Chế độ: ${NET_NAME[n.mode]}.`;
  return where + pending;
}

function renderNet() {
  const n = S.net;
  $("network").hidden = !n;
  if (!n) return;
  $("net-status").textContent = netStatusText(n);
  markSegment($("net-mode"), S.netAsk || n.mode);
  $("net-desc").textContent = NET_DESC[S.netAsk || n.mode];
  const usable = Boolean(n.status && n.status.running) && S.linkOk && isAdmin();
  for (const b of $("net-mode").children) b.disabled = !usable;
  if (!isAdmin()) $("net-desc").textContent += " Chỉ quản trị viên đổi được chế độ mạng.";
}

async function loadNet() {
  try {
    S.net = await api("/system/network");
    NET_LOST = {
      standalone: `Pi đã chuyển sang chế độ độc lập. Trên thiết bị này, vào Wi-Fi ${S.net.ap_ssid}, rồi bấm đường dẫn bên dưới (không phải nhập lại khóa).`,
      auto: `Pi đang quay về Wi-Fi nhà. Vào lại Wi-Fi nhà, rồi bấm đường dẫn bên dưới hoặc mở ${S.net.home_url}`,
      home: `Pi đang quay về Wi-Fi nhà. Vào lại Wi-Fi nhà, rồi bấm đường dẫn bên dưới hoặc mở ${S.net.home_url}`,
    };
  } catch { /* lan sau thu lai */ }
  renderNet();
}

function askNet(mode) {
  const n = S.net;
  if (!n || mode === n.mode) { S.netAsk = null; $("net-confirm").hidden = true; renderNet(); return; }
  const onAp = n.status && n.status.state === "ap";
  let text;
  if (mode === "standalone" && !onAp) {
    text = `Pi sẽ rời Wi-Fi nhà trong khoảng 15 giây và trang này sẽ mất kết nối. Để dùng tiếp: vào Wi-Fi ${n.ap_ssid}, rồi bấm đường dẫn sẽ hiện ở đầu trang (hoặc mở ${n.ap_url}). Về nhà nhớ chuyển lại Tự động.`;
  } else if (mode !== "standalone" && onAp) {
    text = `Pi sẽ tắt mạng ${n.ap_ssid} để vào lại Wi-Fi nhà, và trang này sẽ mất kết nối. Để dùng tiếp: vào lại Wi-Fi nhà, rồi mở ${n.home_url}.` +
      (mode === "auto" ? " Không tìm thấy Wi-Fi nhà thì Pi sẽ phát lại mạng riêng." : " Không tìm thấy Wi-Fi nhà thì Pi sẽ mất mạng cho tới khi có lại.");
  } else if (mode === "home") {
    text = "Từ giờ Pi sẽ không tự phát mạng riêng khi router hỏng, nên khi đó sẽ không điều khiển được. Tiếp tục?";
  } else {
    text = `Chuyển sang chế độ ${NET_NAME[mode]}? Kết nối hiện tại không bị ảnh hưởng.`;
  }
  S.netAsk = mode;
  $("net-confirm-text").textContent = text;
  $("net-confirm").hidden = false;
  renderNet();
}

async function applyNet() {
  const mode = S.netAsk;
  $("net-confirm").hidden = true;
  S.netAsk = null;
  if (!mode) return;
  // Trinh duyet luu khoa theo tung dia chi: dia chi 10.42.0.1 la "trang moi" va se hoi khoa.
  // Tao truoc mot ma ghep (15 phut) de mang sang dia chi moi trong duong dan.
  const n = S.net;
  const leavesNetwork = n && n.status && ((mode === "standalone") !== (n.status.state === "ap"));
  S.netLink = null;
  if (leavesNetwork) {
    try {
      const p = await api("/pairing?ttl_s=900", { method: "POST" });
      S.netLink = `${mode === "standalone" ? n.ap_url : n.home_url}#pair=${p.code}`;
    } catch { /* khong co ma thi van chuyen, nguoi dung nhap khoa */ }
  }
  try {
    S.net = await api("/system/network", { method: "PUT", body: { mode } });
    S.netSwitch = mode;
  } catch (e) {
    $("net-status").textContent = explain(e);
  }
  renderNet();
}

segmented($("net-mode"), NET_MODES, askNet);
$("net-yes").addEventListener("click", applyNet);
$("net-no").addEventListener("click", () => { S.netAsk = null; $("net-confirm").hidden = true; renderNet(); });

async function checkClock() {
  try {
    const t0 = Date.now();
    const h = await (await fetch(`${API}/health`, { cache: "no-store" })).json();
    S.clockSkew = h.time - (t0 + Date.now()) / 2000;
  } catch { /* bo qua */ }
}

// ------------------------------------------------------------------ ghep thiet bi bang QR
// Ma nam sau dau # trong duong dan: trinh duyet khong gui phan nay len may chu, nen ma khong vao log.
let pairTimer = 0;

async function claimPairing() {
  const m = location.hash.match(/^#pair=([A-Za-z0-9_-]{8,64})$/);
  if (!m) return false;
  history.replaceState(null, "", location.pathname + location.search);   // xoa ma khoi thanh dia chi
  try {
    const r = await fetch(`${API}/pairing/claim`, {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: m[1] }),
    });
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      boot(REASON[data && data.error && data.error.code] || REASON.PAIR_INVALID);
      return true;
    }
    if (data.token) useToken(data.token);
    else { useToken(""); S.key = data.api_key; saved.set("pbl5.key", S.key); }
    start();
  } catch {
    boot(REASON.NETWORK);
  }
  return true;
}

async function showPairing() {
  clearInterval(pairTimer);
  const dialog = $("pair-dialog");
  $("pair-left").textContent = "Đang tạo mã…";
  $("pair-qr").removeAttribute("src");
  $("pair-url").textContent = "";
  if (!dialog.open) dialog.showModal();
  try {
    const r = await api("/pairing", { method: "POST" });
    $("pair-qr").src = r.qr;
    $("pair-url").textContent = r.url;
    const until = performance.now() + r.expires_in_s * 1000;
    const tickLeft = () => {
      const left = (until - performance.now()) / 1000;
      if (left <= 0) {
        clearInterval(pairTimer);
        $("pair-qr").removeAttribute("src");
        $("pair-left").textContent = "Mã đã hết hạn. Bấm Tạo mã mới.";
      } else {
        $("pair-left").textContent = `Mã hết hạn sau ${clock(left)}.`;
      }
    };
    tickLeft();
    pairTimer = setInterval(tickLeft, 1000);
  } catch (e) {
    $("pair-left").textContent = explain(e);
  }
}

$("pair-btn").addEventListener("click", showPairing);
$("pair-new").addEventListener("click", showPairing);
$("pair-close").addEventListener("click", () => $("pair-dialog").close());
$("pair-dialog").addEventListener("close", () => clearInterval(pairTimer));

// ------------------------------------------------------------------ tai khoan
// Lan dau: tao quan tri vien bang ma thiet lap tren tem dan Pi. Sau do: dang nhap, hoac tu dang ky roi
// cho quan tri vien cap quyen. Khoa API van dung duoc cho nguoi quan ly Pi.
const ROLE_NAME = { admin: "Quản trị viên", member: "Thành viên", guest: "Khách", pending: "Chờ duyệt", automation: "Tự động" };
const AUTH_TEXT = {
  login: { title: "Đăng nhập", submit: "Đăng nhập", other: "Tạo tài khoản",
           intro: "Đăng nhập bằng tài khoản trên Raspberry Pi này." },
  register: { title: "Tạo tài khoản", submit: "Gửi yêu cầu", other: "Đã có tài khoản? Đăng nhập",
              intro: "Sau khi tạo, quản trị viên cần cấp quyền thì bạn mới đăng nhập được." },
  setup: { title: "Thiết lập lần đầu", submit: "Tạo tài khoản quản trị", other: "",
           intro: "Raspberry Pi này chưa có chủ. Nhập mã thiết lập in trên tem dán ở Pi, rồi tạo tài khoản quản trị viên đầu tiên." },
};
let authMode = "login";

function deviceName() {
  const ua = navigator.userAgent;
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iPhone/iPad" : /Windows/.test(ua) ? "Windows"
    : /Mac/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "Thiết bị";
  return `${os}, trình duyệt`;
}

function useToken(token) {
  S.token = token;
  saved.set("pbl5.token", token || null);
}

function askAuth(mode, message = "") {
  authMode = mode;
  const t = AUTH_TEXT[mode];
  $("auth-title").textContent = t.title;
  $("auth-intro").textContent = t.intro;
  $("auth-submit").textContent = t.submit;
  $("auth-switch").textContent = t.other;
  $("auth-switch").hidden = !t.other;
  $("auth-code-row").hidden = mode !== "setup";
  $("auth-name-row").hidden = mode === "login";
  $("auth-pass2-row").hidden = mode === "login";
  $("auth-pass").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("auth-key").hidden = mode === "setup";
  $("auth-error").textContent = message;
  $("auth-error").dataset.kind = "";
  $("auth-pass").value = "";
  $("auth-pass2").value = "";
  const dialog = $("auth-dialog");
  if (!dialog.open) dialog.showModal();
  (mode === "setup" && !$("auth-code").value ? $("auth-code") : $("auth-user").value ? $("auth-pass") : $("auth-user")).focus();
}

// Khong co phien: hoi Pi da co chu chua de mo dung hop thoai
async function boot(message = "") {
  let status = null;
  try {
    status = await (await fetch(`${API}/setup/status`, { cache: "no-store" })).json();
  } catch { /* xu ly ben duoi */ }
  if (!status) {
    showEmpty("Không kết nối được tới Raspberry Pi. Kiểm tra Pi đang bật và điện thoại đang ở cùng mạng, rồi tải lại trang.");
    return;
  }
  askAuth(status.claimed ? "login" : "setup", message);
}

function signedOut(message = "") {
  useToken("");
  S.me = null;
  S.members = [];
  $("app").hidden = true;
  $("pair-btn").hidden = true;
  $("account-btn").hidden = true;
  boot(message);
}

$("auth-switch").addEventListener("click", () => askAuth(authMode === "login" ? "register" : "login"));
$("auth-key").addEventListener("click", () => { $("auth-dialog").close(); askKey(); });
$("auth-dialog").addEventListener("cancel", (ev) => ev.preventDefault());

$("auth-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("auth-error");
  const username = $("auth-user").value.trim().toLowerCase();
  const password = $("auth-pass").value;
  if (username.length < 3) { err.textContent = REASON.BAD_USERNAME; return; }
  if (password.length < (authMode === "login" ? 1 : 8)) { err.textContent = REASON.BAD_PASSWORD; return; }
  if (authMode !== "login" && password !== $("auth-pass2").value) { err.textContent = "Hai lần nhập mật khẩu chưa giống nhau."; return; }
  const display_name = $("auth-name").value.trim() || undefined;
  const submit = $("auth-submit");
  submit.disabled = true;
  err.textContent = "";
  try {
    if (authMode === "register") {
      await api("/auth/register", { method: "POST", body: { username, password, display_name } });
      askAuth("login");
      err.dataset.kind = "ok";
      err.textContent = `Đã gửi yêu cầu cho tài khoản ${username}. Khi quản trị viên cấp quyền, đăng nhập bằng tên và mật khẩu vừa tạo.`;
      return;
    }
    const r = authMode === "setup"
      ? await api("/setup", { method: "POST", body: { code: $("auth-code").value.trim(), username, password, display_name, device: deviceName() } })
      : await api("/auth/login", { method: "POST", body: { username, password, device: deviceName() } });
    useToken(r.token);
    S.key = "";
    saved.set("pbl5.key", null);
    $("auth-code").value = "";
    $("auth-dialog").close();
    start();
  } catch (e) {
    if (e.code === "ALREADY_CLAIMED") askAuth("login");
    err.dataset.kind = "";
    err.textContent = explain(e);
  } finally {
    submit.disabled = false;
  }
});

// ------------------------------------------------------------------ tai khoan dang dung
function showAccount() {
  const btn = $("account-btn");
  btn.hidden = !S.me;
  if (!S.me) return;
  btn.textContent = S.me.kind === "key" ? "Khóa API" : S.me.display_name;
  btn.title = S.me.kind === "key" ? "Đăng nhập bằng khóa API" : `${S.me.username}, ${ROLE_NAME[S.me.role]}`;
}

$("account-btn").addEventListener("click", () => {
  const me = S.me;
  if (!me) return;
  $("account-who").textContent = me.kind === "key"
    ? "Bạn đang dùng khóa API của Raspberry Pi (quyền quản trị). Đăng xuất sẽ xóa khóa khỏi trình duyệt này."
    : `Tên đăng nhập ${me.username}. Quyền: ${ROLE_NAME[me.role]}. Đang đăng nhập trên ${me.sessions.length} thiết bị.`;
  $("password-form").hidden = me.kind === "key";
  $("pw-status").textContent = "";
  $("account-dialog").showModal();
  $("account-close").focus();   // khong tu bat ban phim tren dien thoai
});
$("account-close").addEventListener("click", () => $("account-dialog").close());
$("sign-out").addEventListener("click", async () => {
  if (S.token) { try { await api("/auth/logout", { method: "POST" }); } catch { /* phien da het thi thoi */ } }
  S.key = "";
  saved.set("pbl5.key", null);
  $("account-dialog").close();
  signedOut("Đã đăng xuất.");
});
$("password-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const status = $("pw-status");
  status.dataset.kind = "";
  try {
    await api("/auth/password", { method: "PUT", body: { old_password: $("pw-old").value, new_password: $("pw-new").value } });
    $("pw-old").value = "";
    $("pw-new").value = "";
    status.dataset.kind = "ok";
    status.textContent = "Đã đổi mật khẩu. Các thiết bị khác đã bị đăng xuất.";
  } catch (e) {
    status.textContent = explain(e);
  }
});

// ------------------------------------------------------------------ quan ly thanh vien (quan tri vien)
async function loadMembers() {
  try {
    S.members = (await api("/users")).items;
  } catch { return; }
  renderMembers();
}

async function memberAction(label, run) {
  $("member-status").textContent = "";
  try {
    await run();
    $("member-status").textContent = label;
  } catch (e) {
    $("member-status").textContent = explain(e);
  }
  loadMembers();
}

const setRole = (u, role) => memberAction(`Đã cấp quyền ${ROLE_NAME[role].toLowerCase()} cho ${u.username}.`,
  () => api(`/users/${encodeURIComponent(u.username)}`, { method: "PUT", body: { role } }));
const removeUser = (u) => memberAction(`Đã xóa tài khoản ${u.username}.`,
  () => api(`/users/${encodeURIComponent(u.username)}`, { method: "DELETE" }));

function renderMembers() {
  $("members").hidden = !isAdmin();
  if (!isAdmin()) return;
  const rows = S.members.map((u) => {
    const mine = S.me.username === u.username;
    const who = el("div", { className: "member-who" },
      el("b", { textContent: u.display_name }),
      el("span", { textContent: u.role === "pending" ? `${u.username}, đang chờ duyệt`
        : `${u.username}, ${ROLE_NAME[u.role].toLowerCase()}${mine ? " (bạn)" : ""}` }));
    const actions = el("div", { className: "member-actions" });
    if (u.role === "pending") {
      actions.append(
        el("button", { type: "button", className: "primary", textContent: "Duyệt thành viên", onclick: () => setRole(u, "member") }),
        el("button", { type: "button", className: "secondary", textContent: "Duyệt khách", onclick: () => setRole(u, "guest") }),
        el("button", { type: "button", className: "secondary danger", textContent: "Từ chối", onclick: () => removeUser(u) }));
    } else if (!mine) {
      const select = el("select", {},
        ...["admin", "member", "guest"].map((r) => el("option", { value: r, textContent: ROLE_NAME[r], selected: r === u.role })));
      select.setAttribute("aria-label", `Quyền của ${u.username}`);
      select.addEventListener("change", () => setRole(u, select.value));
      const del = el("button", { type: "button", className: "secondary danger", textContent: "Xóa" });
      del.addEventListener("click", () => {
        if (del.dataset.armed) return removeUser(u);
        del.dataset.armed = "1";
        del.textContent = "Bấm lần nữa để xóa";
        setTimeout(() => { delete del.dataset.armed; del.textContent = "Xóa"; }, 4000);
      });
      actions.append(select, del);
    }
    const li = el("li", {}, who, actions);
    li.dataset.role = u.role;
    return li;
  });
  $("member-list").replaceChildren(...rows);
}

// ------------------------------------------------------------------ khoa API (nguoi quan ly Pi)
function askKey(message = "") {
  const dialog = $("key-dialog");
  $("key-error").textContent = message;
  $("key-input").value = "";
  if (!dialog.open) dialog.showModal();
}

$("key-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const previous = [S.key, S.token];
  S.key = $("key-input").value.trim();
  S.token = "";
  try {
    await api("/rooms");
  } catch (e) {
    [S.key, S.token] = previous;
    $("key-error").textContent = e.code === "UNAUTHORIZED"
      ? "Khóa không đúng. Kiểm tra lại API_KEY trong gateway/.env." : REASON.NETWORK;
    return;
  }
  saved.set("pbl5.key", S.key);
  useToken("");
  $("key-dialog").close();
  start();
});
$("key-back").addEventListener("click", () => { $("key-dialog").close(); boot(); });
$("key-dialog").addEventListener("cancel", (ev) => { ev.preventDefault(); $("key-dialog").close(); boot(); });

// ------------------------------------------------------------------ su kien dieu khien
segmented($("mode"), MODES, (mode) => change({ mode }, 400));
segmented($("fan"), FANS, (fan) => change({ fan }, 400));
segmented($("range"), RANGES, (hours) => {
  S.hours = hours;
  saved.set("pbl5.hours", String(hours));
  markSegment($("range"), hours);
  loadSeries();
});
markSegment($("range"), S.hours);

$("power").addEventListener("click", () => change({ power: view().power === "on" ? "off" : "on" }, 0));
const nudge = (delta) => {
  const p = S.policy;
  change({ temp: Math.min(p.temp_max, Math.max(p.temp_min, view().temp + delta)) }, 700);
};
$("temp-down").addEventListener("click", () => nudge(-1));
$("temp-up").addEventListener("click", () => nudge(1));
$("temp-range").addEventListener("input", (ev) => change({ temp: Number(ev.target.value) }, 700));
$("room-select").addEventListener("change", (ev) => {
  S.room = ev.target.value;
  saved.set("pbl5.room", S.room);
  S.pending = {};
  S.series = null;
  S.lastVote = null;
  S.suggestion = null;
  voteStatus("");
  feedback("");
  start();
});

document.addEventListener("visibilitychange", () => { if (!document.hidden && S.snap) refresh(); });
let resizeTimer = 0;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawSeries, 150); });
setInterval(() => { if (S.snap && !document.hidden) { render(); renderVotes(); } }, 1000);
for (const b of $("votes").children) b.addEventListener("click", () => castVote(b.dataset.vote));
$("advice-apply").addEventListener("click", applyAdvice);
$("confirm-yes").addEventListener("click", sendConfirmed);
$("confirm-no").addEventListener("click", () => closeConfirm("Đã hủy. Điều hòa giữ nguyên trạng thái."));
$("resend").addEventListener("click", resendState);
$("sync-power").addEventListener("click", syncPower);
$("vote-undo").addEventListener("click", undoVote);   // dem nguoc muot giua hai lan hoi

// Ma thiet lap trong duong dan (#setup=...), vi du tu tem dan khi quet bang camera
const setupHash = location.hash.match(/^#setup=([A-Za-z0-9-]{8,20})$/);
if (setupHash) {
  $("auth-code").value = setupHash[1].toUpperCase();
  history.replaceState(null, "", location.pathname + location.search);
}
claimPairing().then((handled) => {
  if (handled) return;
  if (S.token || S.key) start(); else boot();
});
tick();

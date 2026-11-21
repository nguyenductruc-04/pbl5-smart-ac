/* Dashboard dieu hoa thong minh.
 * Khong dung thu vien ngoai va khong can buoc build: Pi phuc vu thang cac file nay, ke ca khi mat Internet.
 * Moi noi dung dong deu ghi bang textContent (khong innerHTML) vi khoa API nam trong trinh duyet.
 */
"use strict";

const API = "api/v1";
const POLL_MS = 3000;
const MODES = [["cool", "Mát"], ["dry", "Khô"], ["fan", "Quạt"], ["auto", "Tự động"], ["heat", "Sưởi"]];
const FANS = [["auto", "Tự động"], ["low", "Thấp"], ["mid", "Vừa"], ["high", "Cao"]];
const RANGES = [[6, "6 giờ"], [24, "24 giờ"], [168, "7 ngày"]];
const SOURCE = { app: "Ứng dụng", cli: "Dòng lệnh", remote: "Remote", rule: "Luật tự động", ai: "AI" };
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
  UNAUTHORIZED: "Khóa truy cập không đúng.",
  NETWORK: "Không kết nối được tới Raspberry Pi.",
  VOTE_TOO_FAST: "Vừa ghi xong, chờ vài giây rồi bấm lại.",
  UNDO_EXPIRED: "Đã quá 2 phút nên không hoàn tác được nữa.",
  VOTE_NOT_FOUND: "Phiếu này không còn nữa.",
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
  key: saved.get("pbl5.key") || "",
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
};

// ------------------------------------------------------------------ goi API
async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      method,
      cache: "no-store",
      headers: { "X-API-Key": S.key, ...(body ? { "Content-Type": "application/json" } : {}) },
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
  if (!S.linkOk) notices.push({ id: "link", bad: true, text: "Không kết nối được tới Raspberry Pi. Trang đang tự thử lại." });
  else if (!online) notices.push({ id: "offline", bad: true, text: "Node của phòng đang mất kết nối. Điều hòa giữ nguyên trạng thái hiện tại và remote vẫn dùng được." });
  else if (ac && ac.uncertain) notices.push({ id: "uncertain", text: "Trạng thái điều hòa hiển thị ở đây có thể đã lệch với thực tế. Gửi một lệnh bất kỳ để đồng bộ lại." });
  if (online && compressorWait > 0 && v.power === "off") {
    notices.push({ id: "compressor", text: `Máy nén đang nghỉ. Bật lại được sau ${clock(compressorWait)}.` });
  }
  if (safety.automation_enabled && holdLeft > 0) {
    const who = safety.auto_hold_source === "remote" ? "remote" : "ứng dụng";
    notices.push({
      id: "hold",
      text: `Chế độ tự động tạm dừng thêm ${clock(holdLeft)} vì bạn vừa điều chỉnh bằng ${who}.`,
      action: { label: "Cho tự động chạy lại", run: clearHold },
    });
  }
  setNotices(notices);

  // --- dieu khien
  const canControl = S.linkOk && online;
  const on = v.power === "on";
  const power = $("power");
  power.disabled = !canControl;
  power.setAttribute("aria-pressed", String(on));
  $("power-text").textContent = on ? "Tắt điều hòa" : "Bật điều hòa";
  $("tuning").disabled = !canControl || !on;
  $("ac-summary").textContent = !ac ? "Chưa biết trạng thái điều hòa"
    : `${SOURCE[ac.source] || ac.source} đặt lúc ${when(ac.since)}`;

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
  if (!S.snap || !S.linkOk || !nodeOnline()) return false;
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
    if (e.code === "UNAUTHORIZED") askKey(REASON.UNAUTHORIZED);
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
  const canApply = s.target && s.action !== "none" && !s.auto && S.linkOk && nodeOnline();
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
    } else if (e.code === "UNAUTHORIZED") {
      S.pending = {};
      askKey(REASON.UNAUTHORIZED);
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
    if (d.verdict === "allow") {
      const c = results.get(d.cmd_id);
      if (c && c.ok) { why = `Đã phát lệnh (${c.latency_ms} ms).`; }
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
  } catch (e) {
    if (e.code === "UNAUTHORIZED") return askKey(REASON.UNAUTHORIZED);
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
    [S.policy, { rooms }] = await Promise.all([api("/policy"), api("/rooms")]);
  } catch (e) {
    if (e.code === "UNAUTHORIZED") return askKey(REASON.UNAUTHORIZED);
    showEmpty("Không kết nối được tới Raspberry Pi. Kiểm tra Pi đang bật và dịch vụ pbl5-gateway đang chạy, rồi tải lại trang.");
    return;
  }
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
  render();
  loadLog();
  loadSeries();
  loadVotes();
  loadSuggestion();
}

// ------------------------------------------------------------------ khoa truy cap
function askKey(message = "") {
  const dialog = $("key-dialog");
  $("key-error").textContent = message;
  $("key-input").value = "";
  if (!dialog.open) dialog.showModal();
}

$("key-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const previous = S.key;
  S.key = $("key-input").value.trim();
  try {
    await api("/rooms");
  } catch (e) {
    S.key = previous;
    $("key-error").textContent = e.code === "UNAUTHORIZED"
      ? "Khóa không đúng. Kiểm tra lại API_KEY trong gateway/.env." : REASON.NETWORK;
    return;
  }
  saved.set("pbl5.key", S.key);
  $("key-dialog").close();
  start();
});
$("key-forget").addEventListener("click", () => {
  saved.set("pbl5.key", null);
  S.key = "";
  $("key-error").textContent = "Đã xóa khóa khỏi trình duyệt này.";
});
$("key-dialog").addEventListener("cancel", (ev) => { if (!S.key) ev.preventDefault(); });
$("key-btn").addEventListener("click", () => askKey());

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
$("vote-undo").addEventListener("click", undoVote);   // dem nguoc muot giua hai lan hoi

if (S.key) start(); else askKey();
tick();

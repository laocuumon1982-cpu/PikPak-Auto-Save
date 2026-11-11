"use strict";
/* ===================================================================== PikPak Auto Save v3 - giao diện */
window.__errs = [];
window.addEventListener("error", e => window.__errs.push(String(e.message || e)));
window.addEventListener("unhandledrejection", e => window.__errs.push(String(e.reason || e)));

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const norm = s => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d");
const led = (st, cls = "") => `<span class="led ${st} ${cls}"><i></i></span>`;
function api(name, ...args) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) return window.pywebview.api[name](...args);
  return fetch("/api/" + name, {method: "POST", body: JSON.stringify(args)}).then(r => r.json());
}

/* ---------------------------------------------------------------- thông báo nhỏ + hộp thoại */
function toast(t, kind) {
  const d = document.createElement("div");
  d.textContent = t;
  if (kind === "err") d.className = "err";
  $("toast").appendChild(d);
  setTimeout(() => d.remove(), kind === "err" ? 7000 : 3800);
}
window.toast = toast;

const dialogs = [];
function dialog({title, body = "", buttons = [], width = 600, onOpen, left = ""}) {
  return new Promise(resolve => {
    const ov = document.createElement("div");
    ov.className = "overlay";
    ov.innerHTML = `<div class="dlg" style="width:${width}px"><h3>${esc(title)}</h3><div class="body">${body}</div>
      <div class="btns"><div class="left">${left}</div>${buttons.map((b, i) =>
      `<button class="btn ${b.cls || ""}" data-i="${i}">${b.text}</button>`).join("")}</div></div>`;
    document.body.appendChild(ov);
    const dlg = ov.querySelector(".dlg");
    const close = v => { ov.remove(); dialogs.splice(dialogs.indexOf(ctl), 1); resolve(v); };
    const ctl = {el: dlg, close, q: s => dlg.querySelector(s), err: t => { const e = dlg.querySelector(".err"); if (e) e.textContent = t || ""; }};
    dialogs.push(ctl);
    dlg.querySelectorAll(".btns > button").forEach(b => b.onclick = async () => {
      const bt = buttons[+b.dataset.i];
      if (bt.click) { const r = await bt.click(ctl); if (r === false) return; close(r === undefined ? bt.value : r); }
      else close(bt.value);
    });
    ctl.key = e => {
      if (e.key === "Escape") close(null);
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && e.target.tagName !== "BUTTON") {
        const def = buttons.findIndex(b => b.def); if (def >= 0) { e.preventDefault(); dlg.querySelector(`.btns > [data-i="${def}"]`).click(); }
      }
    };
    if (onOpen) onOpen(ctl);
    const f = dlg.querySelector("input,textarea,select"); if (f) setTimeout(() => f.focus(), 30);
  });
}
document.addEventListener("keydown", e => { const top = dialogs[dialogs.length - 1]; if (top) top.key(e); });
const alertBox = (title, msg) => dialog({title, body: `<div class="msg">${esc(msg)}</div>`, buttons: [{text: "OK", cls: "red", def: true, value: true}]});
const confirmBox = (title, msg, ok = "Đồng ý", danger = true) => dialog({title, body: `<div class="msg">${esc(msg)}</div>`,
  buttons: [{text: "Hủy", value: false}, {text: ok, cls: danger ? "red" : "green", def: true, value: true}]});
function promptBox(title, label, val = "", pass = false) {
  return dialog({title, width: 460, body: `<div class="msg">${esc(label)}</div><input id="pv" ${pass ? 'type="password"' : ""} style="width:100%;margin-top:8px" value="${esc(val)}"><div class="err"></div>`,
    buttons: [{text: "Hủy", value: null}, {text: "✓ OK", cls: "red", def: true, click: c => c.q("#pv").value}]});
}
function popMenu(anchor, items) {
  document.querySelectorAll(".menu-pop").forEach(m => m.remove());
  const m = document.createElement("div");
  m.className = "menu-pop";
  m.innerHTML = items.map((it, i) => it === "-" ? "<hr>" : `<div data-i="${i}" class="${it.cls || ""}">${it.text}</div>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.min(r.left, innerWidth - m.offsetWidth - 10) + "px";
  m.style.top = (r.bottom + 6 + m.offsetHeight > innerHeight ? r.top - m.offsetHeight - 6 : r.bottom + 6) + "px";
  m.onclick = e => { const d = e.target.closest("[data-i]"); if (d) { m.remove(); items[+d.dataset.i].do(); } };
  setTimeout(() => document.addEventListener("click", function h() { m.remove(); document.removeEventListener("click", h); }), 0);
}

/* ---------------------------------------------------------------- điều hướng + khóa admin */
const PAGES = {
  scan: ["Quét & Tải", "Tìm tập mới chưa có trong Danh sách đã có → Save vào My PikPak → rclone tải về HDD"],
  folders: ["Thư mục phim", "Các thư mục con trong link chia sẻ PikPak mà tool theo dõi · Đích 1 My PikPak · Đích 2 HDD"],
  history: ["Lịch sử tải", "Các tập đã Save vào My PikPak và tải về HDD"],
  settings: ["Cài đặt", "Tài khoản PikPak, rclone, tự động, COPY_TO_IPHONE, sao lưu"]};
const LOCKED = ["folders", "settings"];
let page = "scan", S = {auto: {on: false, interval: 60}, admin: {unlocked: false, has_pw: false}, leds: {}, issues: []};

async function go(p, noAsk) {
  if (LOCKED.includes(p) && !S.admin.unlocked) {
    if (noAsk || !(await unlock())) { showPage(p, true); return; }
  }
  showPage(p, false);
}
window.go = go;
function showPage(p, locked) {
  if (page === "folders" && p !== "folders" && fpChanges() && !locked) fpAskSave();
  page = p;
  document.querySelectorAll(".nav").forEach(n => n.classList.toggle("on", n.dataset.p === p));
  document.querySelectorAll(".page").forEach(s => s.classList.toggle("on", s.id === "pg-" + (locked ? "locked" : p)));
  $("ptitle").textContent = PAGES[p][0];
  $("psub").textContent = PAGES[p][1];
  if (locked) $("lkTitle").textContent = `Tab "${PAGES[p][0]}" đang khóa`;
  if (p === "settings" && !locked) loadSettings();
  if (p === "folders" && !locked) { foldersVer = -1; }
  api("ui_set", "page", p);
}
document.querySelectorAll(".nav").forEach(n => n.onclick = () => go(n.dataset.p));
$("lkOpen").onclick = () => go(page);
async function unlock() {
  if (S.admin.unlocked) return true;
  const create = !S.admin.has_pw;
  const res = await dialog({title: create ? "Tạo mật khẩu admin" : "Mật khẩu admin", width: 440,
    body: `<div class="msg">🔒 ${create ? "Tab Thư mục phim và Cài đặt được khóa bằng mật khẩu admin để tránh bấm nhầm. Tạo mật khẩu (ít nhất 4 ký tự):"
      : "Nhập mật khẩu admin để mở tab Thư mục phim / Cài đặt:"}</div>
      <input type="password" id="p1" style="width:100%;margin-top:10px">
      ${create ? '<div style="margin-top:8px;color:var(--muted)">Nhập lại mật khẩu</div><input type="password" id="p2" style="width:100%;margin-top:4px">' : ""}
      <div class="err"></div>`,
    buttons: [{text: "Hủy", value: false}, {text: "✓ Mở khóa", cls: "red", def: true, click: async c => {
      const a = c.q("#p1").value;
      if (create && a !== c.q("#p2").value) { c.err("Hai lần nhập không giống nhau."); return false; }
      const m = await api("admin_unlock", a);
      if (m) { c.err(m); c.q("#p1").select(); return false; }
      return true;
    }}]});
  if (res) { S.admin.unlocked = true; S.admin.has_pw = true; paintLock(); }
  return !!res;
}
function paintLock() {
  const u = S.admin.unlocked;
  $("bLock").textContent = u ? "🔓 Khóa lại" : "🔒 Đã khóa";
  $("bLock").classList.toggle("on", u);
  $("lk-folders").hidden = $("lk-settings").hidden = u;
  if (!u && LOCKED.includes(page) && !$("pg-locked").classList.contains("on")) showPage(page, true);
}
$("bLock").onclick = async () => {
  if (S.admin.unlocked) { await api("admin_lock"); S.admin.unlocked = false; paintLock(); toast("🔒 Đã khóa tab Thư mục phim / Cài đặt."); }
  else if (await unlock() && LOCKED.includes(page)) go(page);
};
let lastPing = 0;
["click", "keydown"].forEach(ev => document.addEventListener(ev, () => {
  if (S.admin.unlocked && Date.now() - lastPing > 15000) { lastPing = Date.now(); api("ping"); }
}, true));

$("fold").onclick = () => { $("side").classList.toggle("mini"); $("fold").textContent = $("side").classList.contains("mini") ? "»" : "«";
  api("ui_set", "mini", $("side").classList.contains("mini")); };
$("bTheme").onclick = e => popMenu(e.currentTarget, [
  {text: "☀ Sáng", do: () => setDark(false)}, {text: "☾ Tối", do: () => setDark(true)}, "-",
  {text: "▣ Mở giao diện cũ (bản Tk)", do: async () => {
    if (await confirmBox("Giao diện cũ", "Tool sẽ khởi động lại bằng giao diện cũ (bản Tk).\nMuốn quay lại: trong giao diện cũ vào Cài đặt → Chung → bấm \"🌐 Dùng giao diện web\".", "Khởi động lại"))
      api("classic_ui").then(m => m && toast(m, "err"));
  }}]);
function setDark(on) { document.body.classList.toggle("dark", on); api("ui_set", "dark", on); }

/* ---------------------------------------------------------------- bảng đèn trạng thái */
const TILES = [["pk", "PikPak"], ["rc", "rclone"], ["auto", "Tự quét"], ["dl", "Đang tải"], ["bk", "Sao lưu"], ["err", "Lỗi"]];
const FIX = {pk: ["Đăng nhập", () => openSettings("pikpak", "login")], rc: ["Tải", () => api("get_rclone").then(m => toast(m || "Đang tải rclone.exe..."))],
  err: ["Xem", () => viewReport()], bk: ["Thử lại", () => api("backup_now").then(m => toast(m || "Đang sao lưu lên PikPak..."))]};
$("tiles").innerHTML = TILES.map(([k, t]) => `<div class="raised tile" id="t-${k}">${led("off")}<div class="tx"><b>${t}</b><small class="s-off">...</small></div>` +
  (k === "auto" ? `<span class="auto-pick" onclick="event.stopPropagation()">mỗi <select id="aint">${[15, 30, 45, 60, 90, 120].map(v => `<option>${v}</option>`).join("")}</select> phút</span>`
    : (FIX[k] ? `<button class="fix" hidden>${FIX[k][0]}</button>` : "") + `<span class="chev">›</span>`) + `</div>`).join("");
for (const k in FIX) { const b = $("t-" + k).querySelector(".fix"); b.onclick = e => { e.stopPropagation(); FIX[k][1](); }; }
$("t-pk").onclick = () => openSettings("pikpak");
$("t-rc").onclick = () => openSettings("rclone");
$("t-auto").onclick = () => setAuto(!S.auto.on);
$("t-dl").onclick = () => go("scan");
$("t-bk").onclick = () => openSettings("machine");
$("t-err").onclick = () => viewReport();
$("aint").onchange = () => setAuto(S.auto.on, +$("aint").value);
$("bAuto").onclick = () => setAuto(!S.auto.on);
function setAuto(on, minutes) {
  api("set_auto", on, minutes || +$("aint").value).then(() => toast(on ? `Đã bật tự quét mỗi ${minutes || $("aint").value} phút.` : "Đã tắt tự quét."));
}
async function viewReport() {
  const r = await api("report_latest", true);
  if (r.error) return toast(r.error);
  if (r.copied) toast(`Đã mở và COPY báo cáo ${r.name} - dán (Ctrl+V) vào Claude để sửa.`);
  else { try { await navigator.clipboard.writeText(r.text); toast(`Đã copy báo cáo ${r.name}.`); } catch (e) { toast(`Đã mở báo cáo ${r.name}.`); } }
}
async function openSettings(sub, then) {
  await go("settings");
  if (page !== "settings" || !S.admin.unlocked) return;
  setSeg(sub);
  if (then === "login") setTimeout(pkLogin, 150);
}
const FIXDO = {pk: () => openSettings("pikpak", "login"), rc: () => openSettings("rclone"), bk: () => openSettings("machine"),
  err: () => viewReport(), hdd: () => go("folders"), folders: () => go("folders")};
$("alert").onclick = () => {
  const iss = S.issues || [];
  dialog({title: iss.length ? `Có ${iss.length} mục cần xử lý` : "Mọi thứ hoạt động tốt", width: 640,
    body: iss.length ? iss.map((x, i) => `<div class="raised tile err" style="cursor:default">${led("err")}<div class="tx"><small style="color:var(--text);font-weight:600">${esc(x.t)}</small></div>
        ${FIXDO[x.k] ? `<button class="fix" data-i="${i}">Sửa</button>` : ""}</div>`).join("")
      : `<div class="msg">Tool sẵn sàng tự quét &amp; tải.</div>`,
    buttons: [{text: "Đóng", value: true}],
    onOpen: c => c.el.querySelectorAll(".fix").forEach(b => b.onclick = () => { c.close(); FIXDO[iss[+b.dataset.i].k](); })});
};
function setLed(el, st) { el.classList.remove("ok", "run", "err", "off"); el.classList.add(st); }

/* ---------------------------------------------------------------- QUÉT & TẢI */
let rows = [], rowsVer = -1, logSeq = 0, histVer = -1, foldersVer = -1, fpVer = -1, toastAfter = Date.now() / 1000;
let checked = new Set(), seen = new Set(), sortK = null, sortDir = 1;
function cleanStatus(r) {
  let s = String(r.v[5] || "").replace(/[▰▱]/g, "").replace(/\s+/g, " ").trim();
  if (r.tag === "dl") { const m = s.match(/(\d+)%\s*(.*)$/); if (m) s = `⬇ Đang tải ${m[1]}%` + (m[2] ? " · " + m[2].replace(".", ",") : ""); }
  if (/^●\s*Mới/.test(s)) s = "● Tập mới";
  return s;
}
function visible(r) {
  const q = norm($("q").value.trim());
  if (q && !norm(r.v.join(" ")).includes(q)) return false;
  return {"Tất cả": true, "Mới": r.tag === "new", "Đang tải": r.tag === "dl", "Lỗi": r.tag === "err", "Xong": r.tag === "done",
    "Chưa duyệt": r.tag === "skip", "Đã chọn": checked.has(r.code)}[$("show").value] ?? true;
}
function renderRows() {
  let list = rows.filter(visible);
  if (sortK !== null) list = list.slice().sort((a, b) => String(a.v[sortK]).localeCompare(String(b.v[sortK]), "vi", {numeric: true}) * sortDir);
  $("rows").innerHTML = list.map(r => `<tr class="${checked.has(r.code) ? "sel" : ""}" data-c="${esc(r.code)}">
    <td><span class="chk ${checked.has(r.code) ? "on" : ""}"></span></td><td title="${esc(r.v[0])}">${esc(r.v[0])}</td><td>${esc(r.v[1])}</td>
    <td title="${esc(r.v[2])}">${esc(r.v[2])}</td><td>${esc(r.v[3])}</td><td>${esc(r.v[4])}</td>
    <td><span class="pill t-${r.tag}" title="${esc(r.v[5])}">${esc(cleanStatus(r))}</span></td></tr>`).join("");
  $("selcnt").textContent = "Đã chọn: " + rows.filter(r => checked.has(r.code)).length;
  $("hchk").firstChild.classList.toggle("on", list.length > 0 && list.every(r => checked.has(r.code)));
}
$("rows").onclick = e => { const tr = e.target.closest("tr"); if (!tr) return; const c = tr.dataset.c;
  checked.has(c) ? checked.delete(c) : checked.add(c); renderRows(); };
$("rows").ondblclick = e => { const tr = e.target.closest("tr"); if (tr) api("open_source", tr.dataset.c).then(m => m && toast(m)); };
document.querySelectorAll("#tbl th[data-k]").forEach(th => th.onclick = () => {
  const k = +th.dataset.k; sortDir = sortK === k ? -sortDir : 1; sortK = k;
  document.querySelectorAll("#tbl th").forEach(x => x.classList.remove("sorted", "asc")); th.classList.add("sorted"); if (sortDir > 0) th.classList.add("asc");
  renderRows(); });
$("hchk").onclick = () => { const vis = rows.filter(visible); const all = vis.length && vis.every(r => checked.has(r.code));
  vis.forEach(r => all ? checked.delete(r.code) : checked.add(r.code)); renderRows(); };
$("bAll").onclick = () => { rows.filter(visible).forEach(r => checked.add(r.code)); renderRows(); };
$("bNone").onclick = () => { checked.clear(); renderRows(); };
$("q").oninput = renderRows; $("show").onchange = renderRows;
const sel = () => rows.filter(r => checked.has(r.code)).map(r => r.code);
$("bScan").onclick = () => api("scan", false).then(m => m && toast(m, "err"));
$("bGo").onclick = () => api("scan", true).then(m => m && toast(m, "err"));
$("bStop").onclick = () => api("stop");
$("bDlSel").onclick = () => { const c = sel(); if (!c.length) return toast("Chưa chọn dòng nào."); api("download", c).then(m => m && toast(m, "err")); };
$("bOwn").onclick = () => { const c = sel(); if (!c.length) return toast("Chưa chọn dòng nào.");
  api("mark_owned", c).then(n => { c.forEach(x => checked.delete(x)); toast(`Đã thêm ${n} file vào Danh sách đã có.`); }); };

/* ---------------------------------------------------------------- THƯ MỤC PHIM */
let folders = [], subsOpen = new Set(), FP = null, fpPicked = new Set(), fpCur = null;
function renderFolders() {
  const q = norm($("fq").value.trim());
  const list = folders.filter(f => !q || norm(`${f.name} ${f.note} ${f.url} ${f.src_label}`).includes(q));
  const on = folders.filter(f => f.on).length, rv = folders.filter(f => f.reviewed).length;
  $("fCount").textContent = `${folders.length} thư mục · quét ${on} · đã duyệt ${rv}` + (q ? ` · hiện ${list.length}` : "");
  $("cards").innerHTML = list.length ? list.map(f => `<div class="fcard ${FP && FP.index === f.i ? "act" : ""} ${f.on ? "" : "offc"}" data-i="${f.i}">
    <div class="r1"><span class="chk ${f.on ? "on" : ""}" data-a="toggle" title="Quét thư mục này"></span><div class="nm">${esc(f.name)}</div><span class="idx">#${f.i + 1}</span></div>
    <div class="src">⛓ Nguồn: ${f.src_label ? esc(f.src_label) + " · " : ""}<a data-a="link">${esc(f.link)}</a></div>
    <div class="dests">${f.pk ? `<div><b>1 · MY PIKPAK ›</b> ${esc(f.pk)}</div>` : ""}${f.hdd ? `<div><b>2 · HDD      ›</b> ${esc(f.hdd)}</div>` : ""}
      ${!f.pk && !f.hdd ? `<div style="color:var(--red)">⚠ Chưa có đích đến - bấm Sửa</div>` : ""}</div>
    ${f.note ? `<div class="note">✎ ${esc(f.note)}</div>` : ""}
    ${f.nsubs ? `<div class="subs"><div class="h" data-a="subs">${subsOpen.has(f.id) ? "▾" : "▸"} Thư mục con (${f.nsubs})${subsOpen.has(f.id) ? "" : " — bấm để xem link"}</div>
      ${subsOpen.has(f.id) ? f.subs.map(s => `<div>↳ ${esc(s.path)} <a data-u="${esc(s.url)}">${esc(s.url)}</a></div>`).join("") + (f.nsubs > f.subs.length ? `<div>... và ${f.nsubs - f.subs.length} thư mục con khác</div>` : "") : ""}</div>` : ""}
    <div class="fst ${f.tag}">${esc(f.status)}</div>
    ${f.gaps.length ? `<div class="warnbox">⚠ Có thể thiếu tập:<br>${f.gaps.slice(0, 6).map(g => "• " + esc(g)).join("<br>")}${f.gaps.length > 6 ? `<br>... và ${f.gaps.length - 6} chỗ khác` : ""}
      <div style="margin-top:4px"><a data-a="ack">✓ Đã kiểm tra, bỏ qua cảnh báo này</a></div></div>` : ""}
    ${f.stale ? `<div class="warnbox">${esc(f.stale)}</div>` : ""}
    <div class="acts"><button class="btn sm red" data-a="files">⌕ Quét file</button><button class="btn sm" data-a="dl">⬇ Tải mới</button>
      <button class="btn sm" data-a="edit">✎ Sửa</button><button class="btn sm" data-a="more">⋯</button></div></div>`).join("")
    : `<div class="empty">Chưa có thư mục nào.<br><br>Bấm "＋ Thêm thư mục" hoặc "⧉ Dán nhiều nguồn"<br>để thêm thư mục phim (chọn thư mục con trong link chia sẻ PikPak).</div>`;
}
$("fq").oninput = renderFolders;
$("cards").onclick = async e => {
  const u = e.target.closest("[data-u]"); if (u) return api("open_url", u.dataset.u);
  const a = e.target.closest("[data-a]"); if (!a) return;
  const card = e.target.closest(".fcard"), i = +card.dataset.i, f = folders.find(x => x.i === i);
  const act = a.dataset.a;
  if (act === "toggle") api("folder_toggle", i).then(m => m && toast(m));
  else if (act === "link") api("folder_open_source", i);
  else if (act === "subs") { subsOpen.has(f.id) ? subsOpen.delete(f.id) : subsOpen.add(f.id); renderFolders(); }
  else if (act === "ack") api("folder_ack_gaps", i);
  else if (act === "files") fpScan(i);
  else if (act === "dl") { api("scan", true, [f.id]).then(m => m ? toast(m, "err") : (go("scan"), toast(`Đang quét & tải: ${f.name}`))); }
  else if (act === "edit") folderDialog(i);
  else if (act === "more") popMenu(a, [
    {text: "↗ Mở thư mục nguồn", do: () => api("folder_open_source", i)},
    {text: "⚕ Chẩn đoán (xuất danh sách file + lý do bỏ qua)...", do: () => { api("folder_diagnose", i); toast(`Đang chẩn đoán ${f.name}... xong sẽ tự mở file kết quả.`); }},
    "-", {text: "▲ Đưa lên trên", do: () => api("folder_move", i, -1)}, {text: "▼ Đưa xuống dưới", do: () => api("folder_move", i, 1)},
    "-", {text: "✕ Xóa thư mục", cls: "dang", do: async () => {
      if (await confirmBox("Xóa thư mục phim", `Xóa thư mục "${f.name}" khỏi danh sách?\n(Danh sách file đã có của thư mục vẫn được giữ.)`, "✕ Xóa"))
        api("folder_delete", i).then(m => m && toast(m)); }}]);
};
$("fAdd").onclick = () => folderDialog(-1);
$("fBulk").onclick = () => dialog({title: "Dán nhiều nguồn", width: 720,
  body: `<div class="msg" style="color:var(--muted)">Mỗi dòng 1 nguồn (link chia sẻ PikPak, có thể kèm mã thư mục con). Có thể ghi tên trước:   Tên phim | https://mypikpak.com/s/...</div>
    <textarea id="bt" style="width:100%;height:240px;margin-top:8px;font-family:Consolas,monospace;white-space:pre"></textarea>
    <div class="msg" style="color:var(--muted);margin-top:6px">Thêm xong bấm "✎ Sửa" ở từng thư mục để đặt Đích 1 (My PikPak) và Đích 2 (HDD).</div>`,
  buttons: [{text: "Hủy", value: null}, {text: "＋ Thêm", cls: "red", click: async c => {
    const n = await api("folder_bulk", c.q("#bt").value); toast(n < 0 ? "Tab đang khóa." : `Đã thêm ${n} thư mục.`); }}]});
$("fMore").onclick = e => popMenu(e.currentTarget, [
  {text: "☑ Chọn quét tất cả thư mục", do: () => api("folder_check_all", true)},
  {text: "☐ Bỏ quét tất cả thư mục", do: () => api("folder_check_all", false)}, "-",
  {text: "⇩ Xuất danh sách thư mục...", do: async () => { const r = await api("folder_export"); if (r.path) toast(`Đã xuất ${r.n} thư mục: ${r.path}`); }},
  {text: "⇧ Nhập danh sách thư mục...", do: async () => { const r = await api("folder_import");
    if (r.error) toast(r.error, "err"); else if (r.added !== undefined) toast(`Đã thêm ${r.added} thư mục, bỏ qua ${r.skipped} thư mục đã có.`); }}]);

async function folderDialog(i) {
  const d = await api("folder_get", i);
  const splits = Object.entries(d.splits).map(([k, t]) => `<option value="${k}" ${k === d.split ? "selected" : ""}>${esc(t)}</option>`).join("");
  const adv = !!(d.include || d.exclude || d.split !== "folder");
  dialog({title: d.i >= 0 ? "SỬA THƯ MỤC PHIM" : "THÊM THƯ MỤC PHIM", width: 780,
    body: `<div class="fr"><label><b>Nguồn phim *</b><br><small style="color:var(--muted)">Thư mục con trong link chia sẻ PikPak</small></label>
        <input id="d-url" value="${esc(d.url)}"><button class="btn sm" id="d-share">☁ Chọn trong link chia sẻ...</button></div>
      <div class="hint" id="d-lbl" style="color:var(--green);font-weight:700">${esc(d.src_label)}</div>
      <div class="hint">Bấm "Chọn trong link chia sẻ..." rồi mở tới thư mục phim · hoặc dán link https://mypikpak.com/s/XXXX/&lt;mã thư mục&gt; (có mật khẩu: thêm ?pwd=xxxx)</div>
      <div class="fr"><label><b>Tên phim</b><br><small style="color:var(--muted)">Để trống = tên thư mục</small></label><input id="d-name" value="${esc(d.name)}"></div>
      <div class="fr" style="align-items:flex-start"><label><b>Ghi chú</b></label><textarea id="d-note" class="w" style="height:58px">${esc(d.note)}</textarea></div>
      <div class="sec" style="margin:10px 0 0;padding:10px 14px;box-shadow:none"><h4>Đích đến</h4>
      <div class="fr"><label><b>Đích 1 · My PikPak *</b><br><small style="color:var(--muted)">Save trước tiên (trên máy chủ)</small></label><input id="d-pk" value="${esc(d.pikpak_dir)}"><button class="btn sm" id="d-pkb">Chọn...</button></div>
      <div class="fr"><label><b>Đích 2 · HDD *</b><br><small style="color:var(--muted)">Tải từ My PikPak về PC</small></label><input id="d-hdd" value="${esc(d.local_dir)}"><button class="btn sm" id="d-hddb">Chọn...</button></div>
      <div class="hint">Link chia sẻ → ① Save vào My PikPak → ② rclone tải từ My PikPak về HDD</div>
      <label class="ck" style="margin-left:230px"><input type="checkbox" id="d-sub" ${d.sub_movie ? "checked" : ""}> Tạo thư mục con theo tên phim ở đích (VD ...\\Tiên Nghịch\\ · My Pack/2026/Tiên Nghịch/)</label>
      <div class="preview" id="d-prev" style="margin-left:230px"></div></div>
      <div style="margin-top:10px"><a id="d-advt" style="font-weight:800">${adv ? "▾" : "▸"} NÂNG CAO (tách tên phim · lọc từ khóa)</a></div>
      <div id="d-adv" ${adv ? "" : "hidden"}>
        <div class="fr"><label>Tách tên phim</label><select id="d-split" class="w">${splits}</select></div>
        <div class="fr"><label>Chỉ lấy file có</label><input id="d-inc" value="${esc(d.include)}"></div>
        <div class="fr"><label>Bỏ qua file có</label><input id="d-exc" value="${esc(d.exclude)}"></div>
        <div class="hint">Từ khóa cách nhau dấu phẩy, không phân biệt dấu / hoa thường.</div>
        <label class="ck" style="margin-left:230px"><input type="checkbox" id="d-en" ${d.enabled ? "checked" : ""}> Quét thư mục này</label></div>
      <div class="err"></div>`,
    left: d.link ? `<button class="btn" id="d-open">↗ Mở nguồn</button>` : "",
    buttons: [{text: "Hủy", value: null}, {text: "✓ Lưu", cls: "red", def: true, click: async c => {
      const data = {url: c.q("#d-url").value, name: c.q("#d-name").value, note: c.q("#d-note").value, src_label: c.q("#d-lbl").textContent,
        pikpak_dir: c.q("#d-pk").value, local_dir: c.q("#d-hdd").value, sub_movie: c.q("#d-sub").checked, split: c.q("#d-split").value,
        include: c.q("#d-inc").value, exclude: c.q("#d-exc").value, enabled: c.q("#d-en").checked};
      const m = await api("folder_save", d.i, data);
      if (m) { c.err(m); return false; }
      toast("✔ Đã lưu thư mục phim.");
    }}],
    onOpen: c => {
      const prev = () => {
        const mv = "<Tên phim>", sub = c.q("#d-sub").checked, pk = c.q("#d-pk").value.trim().replace(/\/+$/, ""), hdd = c.q("#d-hdd").value.trim().replace(/[\\/]+$/, "");
        const L = [];
        if (pk) L.push("① PIKPAK › " + pk + "/" + (sub ? mv + "/" : "")); else L.push("⚠ Chưa chọn thư mục My PikPak (Đích 1, bắt buộc)");
        if (hdd) L.push("② HDD    › " + hdd + "\\" + (sub ? mv + "\\" : "")); else L.push("⚠ Chưa chọn thư mục HDD (Đích 2, bắt buộc)");
        c.q("#d-prev").textContent = L.join("\n");
      };
      ["#d-pk", "#d-hdd"].forEach(s => c.q(s).oninput = prev); c.q("#d-sub").onchange = prev; prev();
      c.q("#d-advt").onclick = () => { const a = c.q("#d-adv"); a.hidden = !a.hidden; c.q("#d-advt").textContent = (a.hidden ? "▸" : "▾") + " NÂNG CAO (tách tên phim · lọc từ khóa)"; };
      c.q("#d-share").onclick = async () => {
        const r = await shareBrowser(c.q("#d-url").value);
        if (r) { c.q("#d-url").value = r.url; c.q("#d-lbl").textContent = "☁ " + r.path; if (!c.q("#d-name").value.trim()) c.q("#d-name").value = r.name; }
      };
      c.q("#d-pkb").onclick = async () => { const p = await pikpakBrowser(c.q("#d-pk").value); if (p !== null) { c.q("#d-pk").value = p; prev(); } };
      c.q("#d-hddb").onclick = async () => { const p = await api("pick_folder", c.q("#d-hdd").value); if (p) { c.q("#d-hdd").value = p; prev(); } };
      const o = c.q("#d-open"); if (o) o.onclick = () => api("open_url", d.link);
    }});
}

async function shareBrowser(cur) {
  const s = await api("share_open", cur);
  if (s.error) { await alertBox("Chọn trong link chia sẻ", s.error); return null; }
  const stack = [[s.root, "Link chia sẻ"]];
  let token = "", items = [], selIdx = -1;
  return dialog({title: "Chọn thư mục phim trong link chia sẻ", width: 740,
    body: `<div class="crumb" id="cr"></div><div class="blist" id="bl" style="height:min(62vh,640px)"></div><div class="msg" id="bi" style="color:var(--muted);margin-top:6px"></div>`,
    left: `<button class="btn" id="br">⟳ Tải lại</button>`,
    buttons: [{text: "Hủy", value: null}, {text: "✓ Chọn", cls: "red", def: true, click: c => {
      const it = items[selIdx];
      let id, name, path;
      if (it && it.t === "dir") { id = it.id; name = it.name; path = stack.map(x => x[1]).join(" › ") + " › " + it.name; }
      else { [id, name] = stack[stack.length - 1]; path = stack.map(x => x[1]).join(" › "); }
      if (!id) { c.q("#bi").textContent = "⚠ Hãy mở / chọn 1 thư mục phim (không chọn cả link gốc)."; return false; }
      return {url: `https://mypikpak.com/s/${s.sid}/${id}` + (s.pwd ? `?pwd=${s.pwd}` : ""), name, path};
    }}],
    onOpen: c => {
      const load = async () => {
        c.q("#cr").textContent = stack.map(x => x[1]).join(" › ");
        c.q("#bi").innerHTML = '<span class="spin"></span> Đang đọc link chia sẻ...';
        c.q("#bl").innerHTML = "";
        const r = await api("share_ls", s.sid, s.pwd, stack[stack.length - 1][0], token, s.root);
        if (r.error) { c.q("#bi").textContent = "⚠ " + r.error; return; }
        token = r.token;
        items = (stack.length > 1 ? [{t: "up", name: ".."}] : []).concat(r.dirs.map(d => ({t: "dir", id: d.id, name: d.name})), r.files.map(f => ({t: "file", name: f.name, size: f.size})));
        selIdx = -1;
        c.q("#bl").innerHTML = items.map((it, i) => `<div data-i="${i}" class="${it.t === "file" ? "f" : ""}">${it.t === "up" ? "↰ .." : it.t === "dir" ? "▦ " + esc(it.name) : "&nbsp;&nbsp;&nbsp;&nbsp;" + esc(it.name) + "  (" + esc(it.size) + ")"}</div>`).join("");
        c.q("#bi").textContent = `${r.dirs.length} thư mục · ${r.files.length} file. Nhấp đúp để mở thư mục. Chọn thư mục phim rồi bấm "✓ Chọn".`;
      };
      c.q("#bl").onclick = e => { const d = e.target.closest("[data-i]"); if (!d || d.classList.contains("f")) return;
        c.q("#bl").querySelectorAll(".s").forEach(x => x.classList.remove("s")); d.classList.add("s"); selIdx = +d.dataset.i; };
      c.q("#bl").ondblclick = e => { const d = e.target.closest("[data-i]"); if (!d) return; const it = items[+d.dataset.i];
        if (it.t === "up") { stack.pop(); load(); } else if (it.t === "dir") { stack.push([it.id, it.name]); load(); } };
      c.q("#br").onclick = load;
      load();
    }});
}

async function pikpakBrowser(cur) {
  let path = String(cur || "").replace(/^\/+|\/+$/g, "");
  let dirs = [], selIdx = -1;
  return dialog({title: "Chọn thư mục trên My PikPak", width: 640,
    body: `<div class="crumb" id="cr"></div><div class="blist" id="bl" style="height:min(60vh,600px)"></div><div class="msg" id="bi" style="color:var(--muted);margin-top:6px"></div>`,
    left: `<button class="btn" id="bm">＋ Thư mục mới</button>`,
    buttons: [{text: "Hủy", value: null}, {text: "✓ Chọn thư mục này", cls: "red", def: true, click: () => {
      return selIdx >= 0 && dirs[selIdx] !== ".." ? (path ? path + "/" : "") + dirs[selIdx] : path; }}],
    onOpen: c => {
      const load = async p => {
        c.q("#bi").innerHTML = '<span class="spin"></span> Đang tải danh sách...';
        const r = await api("pk_ls", p);
        if (r.error) { c.q("#bi").textContent = "⚠ " + r.error; return; }
        path = r.path; selIdx = -1;
        c.q("#cr").textContent = "PikPak / " + (path || "(thư mục gốc)");
        dirs = (path ? [".."] : []).concat(r.dirs);
        c.q("#bl").innerHTML = dirs.map((d, i) => `<div data-i="${i}">${d === ".." ? "↰ .." : "▦ " + esc(d)}</div>`).join("");
        c.q("#bi").textContent = r.info || `${r.dirs.length} thư mục. Nhấp đúp để mở.`;
      };
      c.q("#bl").onclick = e => { const d = e.target.closest("[data-i]"); if (!d) return;
        c.q("#bl").querySelectorAll(".s").forEach(x => x.classList.remove("s")); d.classList.add("s"); selIdx = +d.dataset.i; };
      c.q("#bl").ondblclick = e => { const d = e.target.closest("[data-i]"); if (!d) return; const n = dirs[+d.dataset.i];
        load(n === ".." ? path.split("/").slice(0, -1).join("/") : (path ? path + "/" : "") + n); };
      c.q("#bm").onclick = async () => { const n = await promptBox("Thư mục mới", "Tên thư mục mới trong " + (path || "thư mục gốc") + ":");
        if (n && n.trim()) { const m = await api("pk_mkdir", path, n.trim()); if (m) toast(m, "err"); load(path); } };
      load(path);
    }});
}

/* ----- khung file của thư mục */
function fpChanges() { return FP && FP.changes ? FP.changes : 0; }
async function fpAskSave() {
  if (await confirmBox("Chưa lưu", `Thư mục "${FP.fname}" có ${FP.changes} thay đổi chưa lưu.\nLưu ngay?`, "✓ Lưu", false)) {
    const r = await api("fp_save"); if (r.msg) toast(r.msg);
  }
}
async function fpScan(i) {
  if (fpChanges() && FP.index !== i) await fpAskSave();
  fpPicked.clear(); fpCur = null;
  const m = await api("fp_scan", i);
  if (m) toast(m, "err");
}
function fpVisible(r) {
  const q = norm($("fpq").value.trim());
  if (q && !norm(r.name).includes(q)) return false;
  return {"Tất cả": true, "Chưa có": !r.owned, "Đã có": r.owned, "Đang chọn": fpPicked.has(r.code)}[$("fpShow").value] ?? true;
}
function renderFP() {
  const fp = FP;
  $("fpEmpty").hidden = !!(fp && (fp.rows.length || fp.loading));
  if (!fp) { $("fpTitle").textContent = "Danh sách file"; $("fpInfo").textContent = ""; $("fpRows").innerHTML = ""; $("fpCount").textContent = "";
    ["fpMark", "fpUnmark", "fpSave"].forEach(b => $(b).disabled = true); return; }
  $("fpTitle").textContent = fp.fname;
  $("fpInfo").innerHTML = fp.loading ? '<span class="spin"></span> ' + esc(fp.info) : esc(fp.info);
  const list = fp.rows.filter(fpVisible);
  $("fpRows").innerHTML = list.map(r => `<tr class="${fpPicked.has(r.code) ? "sel" : ""} ${fpCur === r.code ? "cur" : ""}" data-c="${esc(r.code)}">
    <td><span class="chk ${fpPicked.has(r.code) ? "on" : ""}"></span></td><td title="${esc(r.name)}">${esc(r.name)}</td><td>${esc(r.date)}</td><td>${esc(r.size)}</td>
    <td><span class="pill t-${r.tag}">${esc(r.status)}</span></td></tr>`).join("");
  const n = fpPicked.size;
  $("fpMark").disabled = $("fpUnmark").disabled = !n;
  $("fpMark").textContent = n ? `☑ Thêm vào Danh sách đã có (${n})` : "☑ Thêm vào Danh sách đã có";
  $("fpSave").disabled = !(fp.changes || (!fp.reviewed && !fp.loading && fp.rows.length));
  $("fpSave").classList.toggle("hot", !!fp.changes);
  $("fpCount").textContent = `Đang chọn ${n} file · Đã có ${fp.own}/${fp.total}` + (fp.changes ? ` · ${fp.changes} thay đổi CHƯA LƯU` : "");
  $("fpH").firstChild.classList.toggle("on", list.length > 0 && list.every(r => fpPicked.has(r.code)));
}
$("fpRows").onclick = e => { const tr = e.target.closest("tr"); if (!tr) return; const c = tr.dataset.c;
  if (e.target.closest(".chk")) { fpPicked.has(c) ? fpPicked.delete(c) : fpPicked.add(c); } else fpCur = c; renderFP(); };
$("fpRows").ondblclick = e => { const tr = e.target.closest("tr"); if (!tr) return; const c = tr.dataset.c; fpPicked.has(c) ? fpPicked.delete(c) : fpPicked.add(c); renderFP(); };
$("fpH").onclick = () => { if (!FP) return; const vis = FP.rows.filter(fpVisible); const all = vis.length && vis.every(r => fpPicked.has(r.code));
  vis.forEach(r => all ? fpPicked.delete(r.code) : fpPicked.add(r.code)); renderFP(); };
$("fpAll").onclick = () => { if (FP) FP.rows.filter(fpVisible).forEach(r => fpPicked.add(r.code)); renderFP(); };
$("fpNone").onclick = () => { fpPicked.clear(); renderFP(); };
$("fpUntil").onclick = () => {
  if (!FP) return;
  if (!fpCur) return alertBox("Chọn từ đầu", "Bấm vào 1 dòng (VD: tập cuối cùng bạn đã có) rồi bấm lại nút này.");
  const vis = FP.rows.filter(fpVisible); const k = vis.findIndex(r => r.code === fpCur);
  vis.slice(0, k + 1).forEach(r => fpPicked.add(r.code)); renderFP();
};
$("fpq").oninput = renderFP; $("fpShow").onchange = renderFP;
$("fpMark").onclick = () => { api("fp_mark", [...fpPicked], true).then(m => { if (m) toast(m, "err"); else fpPicked.clear(); }); };
$("fpUnmark").onclick = () => { api("fp_mark", [...fpPicked], false).then(m => { if (m) toast(m, "err"); else fpPicked.clear(); }); };
$("fpSave").onclick = () => api("fp_save").then(r => r.error ? toast(r.error, "err") : r.msg && toast(r.msg));

/* ---------------------------------------------------------------- LỊCH SỬ */
let hist = [], hPicked = new Set(), hSort = ["ts", -1];
function hVisible(h) {
  const q = norm($("hq").value.trim());
  if (q && !norm(h.folder + " " + h.name).includes(q)) return false;
  const sh = $("hShow").value, today = new Date().toDateString();
  return {"Tất cả": true, "Đang tải": h.tag === "dl", "Xong": h.raw === "Xong", "Lỗi": h.tag === "err", "Lỗi upload": h.up === "error",
    "Hôm nay": new Date(h.ts * 1000).toDateString() === today}[sh] ?? true;
}
function renderHist() {
  const [k, d] = hSort;
  const list = hist.filter(hVisible).sort((a, b) => (k === "ts" ? a.ts - b.ts : String(a[k]).localeCompare(String(b[k]), "vi", {numeric: true})) * d);
  $("hRows").innerHTML = list.slice(0, 1500).map(h => `<tr class="${hPicked.has(h.code) ? "sel" : ""}" data-c="${esc(h.code)}" title="${esc(h.error || h.path)}">
    <td><span class="chk ${hPicked.has(h.code) ? "on" : ""}"></span></td><td>${esc(h.folder)}</td><td title="${esc(h.name)}">${esc(h.name)}</td><td>${esc(h.when)}</td>
    <td><span class="pill t-${h.tag}">${esc(h.status)}</span></td><td>${esc(h.pikpak)}</td></tr>`).join("") ||
    `<tr><td colspan="6" class="empty" style="padding:30px">Chưa có lịch sử.</td></tr>`;
  $("hCount").textContent = `Hiện ${list.length}/${hist.length} tập`;
  $("hSel").textContent = hPicked.size ? `Đã chọn: ${hPicked.size}` : "";
}
$("hRows").onclick = e => { const tr = e.target.closest("tr[data-c]"); if (!tr) return; const c = tr.dataset.c; hPicked.has(c) ? hPicked.delete(c) : hPicked.add(c); renderHist(); };
$("hRows").ondblclick = e => { const tr = e.target.closest("tr[data-c]"); if (tr) api("hist_open", tr.dataset.c).then(m => m && toast(m)); };
$("hH").onclick = () => { const vis = hist.filter(hVisible); const all = vis.length && vis.every(h => hPicked.has(h.code)); vis.forEach(h => all ? hPicked.delete(h.code) : hPicked.add(h.code)); renderHist(); };
document.querySelectorAll("#pg-history th[data-h]").forEach(th => th.onclick = () => {
  const k = th.dataset.h; hSort = [k, hSort[0] === k ? -hSort[1] : (k === "ts" ? -1 : 1)];
  document.querySelectorAll("#pg-history th").forEach(x => x.classList.remove("sorted", "asc")); th.classList.add("sorted"); if (hSort[1] > 0) th.classList.add("asc");
  renderHist(); });
$("hq").oninput = renderHist; $("hShow").onchange = renderHist;
const hSel = () => { const c = [...hPicked]; if (!c.length) toast("Bấm ô tròn để chọn tập trước."); return c; };
$("hDone").onclick = () => { const c = hSel(); if (c.length) api("hist_mark_done", c).then(() => { hPicked.clear(); toast(`Đã đánh dấu Xong ${c.length} tập.`); }); };
$("hUp").onclick = () => { const c = hSel(); if (c.length) api("hist_upload", c).then(m => toast(m)); };
$("hRep").onclick = () => viewReport();
$("hRepDir").onclick = () => api("open_reports");
$("hDel").onclick = async () => { const c = hSel(); if (!c.length) return;
  if (await confirmBox("Xóa khỏi lịch sử", `Xóa ${c.length} tập khỏi lịch sử? Lần quét sau sẽ tải lại.`, "↺ Xóa")) api("hist_delete", c).then(() => hPicked.clear()); };
$("hClear").onclick = async () => { if (await confirmBox("Xóa toàn bộ", "Xóa toàn bộ lịch sử đã tải?", "✕ Xóa toàn bộ")) api("hist_clear").then(() => hPicked.clear()); };

/* ---------------------------------------------------------------- CÀI ĐẶT */
let SET = null, seg = "gen", dirty = false;
const ck = (k, t, extra = "") => `<label class="ck"><input type="checkbox" data-k="${k}" ${SET[k] ? "checked" : ""} ${extra}> ${t}</label>`;
const inp = (k, w = "") => `<input data-k="${k}" value="${esc(SET[k])}" ${w}>`;
const sel2 = (k, vals) => `<select data-k="${k}">${vals.map(v => `<option ${String(v) === String(SET[k]) ? "selected" : ""}>${v}</option>`).join("")}</select>`;
function readoutHTML(id, rows) {
  return `<div class="readout" id="${id}">${led("off", "big")}<div class="rows">${rows.map(([k, t]) => `<b>${t}</b><span data-r="${k}">—</span>`).join("")}</div></div>`;
}
function fillReadout(id, info) {
  const el = $(id); if (!el) return;
  setLed(el.querySelector(".led"), info.ok === true ? "ok" : info.ok === false ? "err" : "run");
  for (const [k, v] of Object.entries(info)) { const s = el.querySelector(`[data-r="${k}"]`); if (s) s.textContent = v; }
}
async function loadSettings() { SET = await api("settings"); dirty = false; $("savebar").classList.remove("isdirty"); renderSettings(); }
function setSeg(s) { seg = s; document.querySelectorAll("#seg div").forEach(d => d.classList.toggle("on", d.dataset.s === s)); if (SET) renderSettings(); }
document.querySelectorAll("#seg div").forEach(d => d.onclick = () => setSeg(d.dataset.s));
function renderSettings() {
  const S2 = SET, el = $("sets");
  if (seg === "gen") el.innerHTML = `
    <div class="sec"><h4>Giao diện</h4><div class="d">Giao diện web (nút nổi 3D, đèn LED). Chọn nền sáng hoặc tối. Máy không chạy được giao diện web sẽ tự dùng giao diện cũ.</div>
      <div class="fr"><button class="btn" id="g-light">☀ Sáng</button><button class="btn" id="g-dark">☾ Tối</button><button class="btn" id="g-classic">▣ Mở giao diện cũ (bản Tk)</button></div></div>
    <div class="sec"><h4>Mật khẩu admin</h4><div class="d">Tab Thư mục phim và Cài đặt cần mật khẩu admin mới mở được (tránh bấm nhầm). Quên mật khẩu: tắt tool, mở Data\\config.json xóa 2 dòng "admin_hash" và "admin_salt" rồi mở lại tool.</div>
      <div class="fr"><button class="btn" id="g-pw">🔑 Đổi mật khẩu admin</button><button class="btn" id="g-lock">🔒 Khóa ngay</button>
        <span style="margin-left:10px">Tự khóa sau</span>${sel2("admin_lock_min", [0, 5, 10, 15, 30, 60])}<span style="color:var(--muted)">phút không thao tác (0 = không tự khóa)</span></div></div>
    <div class="sec"><h4>Tự động</h4>
      <div class="fr">${ck("auto_scan", "Tự quét &amp; tải mỗi")}${sel2("auto_interval", S2.intervals)}<span>phút (tool phải đang mở hoặc chạy dưới khay)</span></div>
      ${ck("start_with_windows", "Khởi động cùng Windows (chạy ẩn dưới khay)")}${ck("startup_scan", "Quét &amp; tải ngay sau khi khởi động (chờ 1 phút cho có mạng)")}
      ${ck("tray_on_close", "Bấm X thì thu nhỏ xuống khay hệ thống (góc đồng hồ)", S2.tray_ok ? "" : "disabled")}${ck("notify", "Thông báo Windows khi có file mới / tải xong / lỗi", S2.tray_ok ? "" : "disabled")}</div>
    <div class="sec"><h4>Cách tải</h4><div class="d">1) Đích 1 - Save: tập mới trong link chia sẻ được lưu vào My PikPak của bạn (sao chép trên máy chủ PikPak, nhanh, không tốn mạng). 2) Đích 2 - HDD: rclone tải tập đó từ My PikPak về thư mục HDD. Đích đặt riêng cho từng thư mục phim ở tab Thư mục phim.</div>
      <div class="fr"><label>Link chia sẻ gốc</label>${inp("share_root")}<button class="btn sm" id="g-share">↗ Mở</button></div>
      <div class="hint">Link thư mục PikPak được chia sẻ cho bạn. Khi thêm thư mục phim, bấm "Chọn trong link chia sẻ..." để chọn thư mục con từ link này. Có mật khẩu: thêm ?pwd=xxxx vào cuối link.</div>
      ${ck("iphone_on", "Copy thêm 1 bản vào thư mục COPY_TO_IPHONE (mọi phim chung 1 thư mục)")}
      <div class="fr"><button class="btn sm" id="g-ipc">📱 Copy các tập đã tải gần đây vào COPY_TO_IPHONE...</button><button class="btn sm" id="g-ipo">↗ Mở thư mục</button></div>
      <div class="fr"><label>Thư mục COPY_TO_IPHONE</label>${inp("iphone_dir")}<button class="btn sm" id="g-ipb">Chọn...</button></div>
      <div class="hint">Mỗi tập tải về HDD xong được copy thêm 1 bản vào đây để chép sang iPhone. File ở đây bạn tự xóa sau khi chép - tool không tải lại.</div>
      <div class="fr"><label>Giới hạn tốc độ</label>${inp("bwlimit", 'style="width:120px;flex:none"')}<span style="color:var(--muted)">VD 20M = 20 MB/s, 500K = 500 KB/s. Để trống = không giới hạn.</span></div>
      <div class="fr"><label>Nghỉ giữa 2 file (giây)</label><input data-k="delay" type="number" min="0" max="60" value="${S2.delay}" style="width:90px"></div>
      <div class="fr"><label>Đuôi file cần tải</label>${inp("extensions")}</div><div class="hint">Cách nhau bằng dấu cách; để trống = mọi loại file</div></div>
    <div class="sec"><h4>Kiểm tra &amp; cảnh báo</h4><div class="d">Chạy im lặng, chỉ báo khi có vấn đề.</div>
      ${ck("health_check", "Kiểm tra trước khi tải: rclone + đăng nhập PikPak, ổ đích HDD đã cắm, còn đủ chỗ trống")}
      <div class="fr"><label>Nhắc khi thư mục không có tập mới sau (ngày, 0 = tắt)</label><input data-k="stale_days" type="number" min="0" max="90" value="${S2.stale_days}" style="width:90px"></div>
      <div class="d">Tự báo "có thể thiếu tập" khi số tập bị nhảy và báo file tải về bị thiếu dung lượng (tự tải lại).</div></div>
    <div class="sec"><h4>Cập nhật phần mềm</h4>
      <div class="fr"><label>Nguồn cập nhật (GitHub)</label>${inp("update_repo")}<button class="btn sm" id="g-upd">⟳ Kiểm tra bản mới</button></div>
      ${ck("update_check", "Tự kiểm tra bản mới mỗi lần mở tool")}<div class="d">Đang dùng: ${esc(S2.version)}</div></div>`;
  else if (seg === "pikpak") el.innerHTML = `
    <div class="sec"><h4>Trạng thái kết nối</h4>${readoutHTML("ro-pk", [["state", "Kết nối"], ["user", "Tài khoản"], ["vip", "Gói"], ["quota", "Dung lượng"], ["rclone", "rclone"], ["checked", "Kiểm tra lúc"]])}
      <div class="fr" style="margin-top:10px"><button class="btn red shine" id="p-chk">⟳ Kiểm tra kết nối</button><button class="btn" id="p-login">⚙ Đổi tài khoản PikPak...</button>
        ${S2.rclone ? "" : '<button class="btn" id="p-rc">⬇ Tải rclone.exe về thư mục tool</button>'}</div></div>
    <div class="sec"><h4>Mặc định cho thư mục mới</h4><div class="d">Thư mục My PikPak điền sẵn khi thêm thư mục phim mới (mỗi thư mục phim vẫn đổi riêng được).</div>
      <div class="fr"><label>Thư mục lưu My PikPak</label>${inp("pikpak_root")}<button class="btn sm" id="p-root">Chọn...</button></div></div>`;
  else if (seg === "rclone") el.innerHTML = `
    <div class="sec"><h4>Trạng thái rclone</h4><div class="d">rclone dùng để lưu phim vào My PikPak và tải từ My PikPak về HDD. Không có rclone.exe thì tool tự tải về.</div>
      ${readoutHTML("ro-rc", [["state", "Trạng thái"], ["ver", "Phiên bản"], ["path", "File"], ["conf", "Cấu hình"], ["checked", "Kiểm tra lúc"]])}
      <div class="fr" style="margin-top:10px"><button class="btn red shine" id="r-chk">⟳ Kiểm tra rclone</button><button class="btn" id="r-up">⬇ Tải lại / cập nhật rclone mới nhất</button><button class="btn" id="r-dir">▸ Mở thư mục tool</button></div></div>`;
  else el.innerHTML = `
    <div class="sec"><h4>Máy này: ${esc(S2.machine)}</h4><div class="d">Tool để trên ổ di động, cắm vào nhiều máy: mỗi máy tự nhớ đường dẫn riêng. Đường dẫn nằm trên chính ổ di động được lưu không phụ thuộc ký tự ổ.</div>
      <div class="tablewrap" style="flex:none;max-height:190px;margin-top:4px"><table class="ptable"><thead><tr><th style="width:40px"></th><th>MÁY</th><th>CẬP NHẬT</th><th>ĐƯỜNG DẪN</th></tr></thead>
        <tbody id="m-rows">${S2.profiles.map(p => `<tr data-n="${esc(p.name)}"><td><span class="chk"></span></td><td>${esc(p.name)}${p.me ? " <b style='color:var(--green)'>(máy này)</b>" : ""}</td><td>${esc(p.when)}</td><td>${esc(p.paths)}</td></tr>`).join("")}</tbody></table></div>
      <div class="fr" style="margin-top:10px"><button class="btn" id="m-copy">⧉ Chép thiết lập từ máy đã chọn</button><button class="btn out" id="m-del">✕ Xóa hồ sơ máy đã chọn</button></div></div>
    <div class="sec"><h4>Sao lưu dữ liệu</h4><div class="d">Phòng khi ổ cứng hỏng: config.json (thư mục, cài đặt), owned.json (Danh sách đã có), history.json (lịch sử) được nén và đưa lên ${esc(S2.backup_remote)}.</div>
      ${ck("backup_on", "Sau mỗi lần tải xong, tự sao lưu dữ liệu lên PikPak")}
      <div class="fr"><button class="btn red shine" id="m-bk">☁ Sao lưu lên PikPak ngay</button><button class="btn" id="m-rpk">⟲ Khôi phục từ PikPak...</button>
        <button class="btn" id="m-bf">⇩ Sao lưu ra file...</button><button class="btn" id="m-rf">⇧ Khôi phục từ file...</button></div>
      <div class="d">${S2.last_backup ? "✔ Lần sao lưu gần nhất: " + esc(S2.last_backup) : "Chưa sao lưu lần nào."}</div></div>
    <div class="sec"><h4>Thư mục Data</h4><div class="d">Mọi dữ liệu (cấu hình, Danh sách đã có, lịch sử, đăng nhập PikPak, nhật ký) nằm trong thư mục Data cạnh tool. Lên bản mới: chép thư mục Data của bản cũ sang là xong.</div>
      <div class="fr"><button class="btn" id="m-data">▸ Mở thư mục Data</button><span style="color:var(--muted)">${esc(S2.data)}</span></div></div>`;
  el.querySelectorAll("[data-k]").forEach(x => x.addEventListener(x.type === "checkbox" || x.tagName === "SELECT" ? "change" : "input", () => {
    SET[x.dataset.k] = x.type === "checkbox" ? x.checked : x.value; dirty = true; $("savebar").classList.add("isdirty"); }));
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  on("g-light", () => setDark(false)); on("g-dark", () => setDark(true)); on("g-classic", () => $("bTheme").click());
  on("g-pw", changePw); on("g-lock", () => $("bLock").click());
  on("g-share", () => api("open_url", SET.share_root));
  on("g-ipo", () => api("open_iphone"));
  on("g-ipb", async () => { const p = await api("pick_folder", SET.iphone_dir); if (p) { SET.iphone_dir = p; dirty = true; $("savebar").classList.add("isdirty"); renderSettings(); } });
  on("g-ipc", async () => { const r = await api("iphone_preview");
    if (!r.n) return alertBox("COPY_TO_IPHONE", `Các tập tải trong ${r.days} ngày gần đây đều đã có trong:\n${r.dir}`);
    if (await confirmBox("COPY_TO_IPHONE", `Copy ${r.n} tập (${r.size}) đã tải trong ${r.days} ngày gần đây vào:\n${r.dir} ?`, "📱 Copy", false)) api("iphone_run").then(m => toast(m || "Đang copy vào COPY_TO_IPHONE...")); });
  on("g-upd", () => updateDialog());
  on("p-chk", pkCheck); on("p-login", pkLogin); on("p-rc", () => api("get_rclone").then(m => toast(m || "Đang tải rclone.exe...")));
  on("p-root", async () => { const p = await pikpakBrowser(SET.pikpak_root); if (p !== null) { SET.pikpak_root = p; dirty = true; $("savebar").classList.add("isdirty"); renderSettings(); } });
  on("r-chk", rcCheck); on("r-up", () => api("get_rclone", true).then(m => toast(m || "Đang tải rclone.exe mới nhất...")));
  on("r-dir", () => api("open_base"));
  let prof = null;
  const mr = $("m-rows"); if (mr) mr.onclick = e => { const tr = e.target.closest("tr"); if (!tr) return; prof = tr.dataset.n;
    mr.querySelectorAll("tr").forEach(t => { t.classList.toggle("sel", t === tr); t.querySelector(".chk").classList.toggle("on", t === tr); }); };
  on("m-copy", async () => { if (!prof) return toast("Chọn 1 máy trong danh sách."); const m = await api("copy_profile", prof);
    if (m) toast(m, "err"); else { toast(`Đã chép thiết lập từ máy "${prof}". Kiểm tra lại các đường dẫn rồi bấm Lưu.`); loadSettings(); } });
  on("m-del", async () => { if (!prof) return toast("Chọn 1 máy trong danh sách.");
    if (await confirmBox("Xóa hồ sơ máy", `Xóa hồ sơ máy "${prof}"?`, "✕ Xóa")) { const m = await api("delete_profile", prof); if (m) toast(m, "err"); else loadSettings(); } });
  on("m-bk", () => api("backup_now").then(m => toast(m || "Đang sao lưu lên PikPak...")));
  on("m-bf", async () => { const r = await api("backup_to_file"); if (r.path) toast("Đã sao lưu ra file: " + r.path); });
  on("m-rf", async () => restoreFlow(await api("restore_pick")));
  on("m-rpk", async () => { toast("Đang tải bản sao lưu từ PikPak..."); restoreFlow(await api("restore_fetch_pikpak")); });
  on("m-data", () => api("open_data"));
  if (seg === "pikpak") pkCheck();
  if (seg === "rclone") rcCheck();
}
async function pkCheck() { fillReadout("ro-pk", {ok: null, state: "đang kiểm tra..."}); fillReadout("ro-pk", await api("pk_detail")); }
async function rcCheck() { fillReadout("ro-rc", {ok: null, state: "đang kiểm tra..."}); fillReadout("ro-rc", await api("rclone_info")); }
async function restoreFlow(r) {
  if (!r || (!r.error && !r.path)) return;
  if (r.error) return alertBox("Khôi phục", r.error);
  if (await confirmBox("Khôi phục dữ liệu", `Khôi phục dữ liệu từ bản sao lưu?\n\n${r.info}\nGồm: ${r.names.join(", ")}\n\nDữ liệu hiện tại sẽ được giữ lại dạng *.bak. Tool sẽ tự khởi động lại.`, "⟲ Khôi phục"))
    api("restore_apply", r.path).then(m => m && toast(m, "err"));
}
async function pkLogin() {
  dialog({title: "Tài khoản PikPak", width: 480,
    body: `<div class="msg" style="color:var(--muted)">Nhập email / mật khẩu PikPak. Tool nhớ tài khoản (mật khẩu được mã hóa) để mỗi lần mở - kể cả trên máy khác khi dùng ổ di động - tự đăng nhập và kiểm tra kết nối.</div>
      <div class="fr"><label style="width:120px">Email / tài khoản</label><input id="lu" value="${esc((SET && SET.user) || "")}"></div>
      <div class="fr"><label style="width:120px">Mật khẩu</label><input id="lp" type="password"></div>
      <label class="ck" style="margin-left:130px"><input type="checkbox" id="lr" checked> Ghi nhớ tài khoản và mật khẩu</label><div class="err"></div>`,
    buttons: [{text: "Hủy", value: null}, {text: "✓ Đăng nhập", cls: "red", def: true, click: async c => {
      c.err(""); c.q(".err").innerHTML = '<span class="spin"></span> Đang đăng nhập...';
      const m = await api("pk_login", c.q("#lu").value, c.q("#lp").value, c.q("#lr").checked);
      if (m) { c.err("⚠ " + m); return false; }
      toast("✔ Đăng nhập PikPak thành công."); if (page === "settings") { loadSettings(); }
    }}]});
}
async function changePw() {
  const r = await dialog({title: "Đổi mật khẩu admin", width: 440,
    body: `${S.admin.has_pw ? '<div>Mật khẩu hiện tại</div><input type="password" id="o" style="width:100%;margin:4px 0 8px">' : ""}
      <div>Mật khẩu mới (ít nhất 4 ký tự)</div><input type="password" id="n1" style="width:100%;margin:4px 0 8px">
      <div>Nhập lại mật khẩu mới</div><input type="password" id="n2" style="width:100%;margin-top:4px"><div class="err"></div>`,
    buttons: [{text: "Hủy", value: null}, {text: "✓ Đổi", cls: "red", def: true, click: async c => {
      if (c.q("#n1").value !== c.q("#n2").value) { c.err("Hai lần nhập không giống nhau."); return false; }
      const m = await api("admin_change", c.q("#o") ? c.q("#o").value : "", c.q("#n1").value);
      if (m) { c.err(m); return false; } return true; }}]});
  if (r) toast("🔑 Đã đổi mật khẩu admin.");
}
$("sSave").onclick = async () => { const m = await api("save_settings", SET); if (m) return toast(m, "err");
  toast("✔ Đã lưu cài đặt cho máy " + SET.machine); dirty = false; $("savebar").classList.remove("isdirty"); };
$("sTest").onclick = () => api("test_notify").then(() => toast("Đã gửi thông báo thử (xem góc phải dưới màn hình Windows)."));

/* ---------------------------------------------------------------- CẬP NHẬT */
async function updateDialog() {
  const s = SET || await api("settings");
  dialog({title: "Cập nhật phần mềm", width: 720,
    body: `<div class="msg">Đang dùng: <b>${esc(S.app || "")}</b></div><div class="msg" id="u-st" style="margin-top:8px"></div>
      <div class="fr" style="margin-top:10px"><label style="width:160px">Nguồn (GitHub)</label><input id="u-repo" value="${esc(s.update_repo || "")}"></div>
      <label class="ck"><input type="checkbox" id="u-auto" ${s.update_check ? "checked" : ""}> Tự kiểm tra bản mới mỗi lần mở tool</label>
      <div class="msg" style="color:var(--muted);margin-top:6px">Có file PikPak-Auto-Save_Portable.zip / PikPak-Auto-Save_vX.Y.zip → bấm "Cập nhật từ file zip". Thư mục Data luôn được giữ nguyên.</div>`,
    left: `<button class="btn" id="u-file">⇧ Cập nhật từ file zip...</button>`,
    buttons: [{text: "Đóng", value: null}, {text: "⟳ Kiểm tra trên GitHub", click: async c => {
      await api("set_update", c.q("#u-repo").value, c.q("#u-auto").checked); await api("check_update"); return false; }},
      {text: "⬇ Cập nhật ngay", cls: "red shine", click: async c => {
        if (!(S.update && S.update.newer)) { toast("Chưa có bản mới - bấm \"Kiểm tra trên GitHub\" trước."); return false; }
        const m = await api("update_apply"); if (m) { toast(m, "err"); return false; } return false; }}],
    onOpen: c => {
      c.q("#u-file").onclick = async () => { await api("set_update", c.q("#u-repo").value, c.q("#u-auto").checked); const m = await api("update_from_file"); if (m) toast(m, "err"); };
      const paint = () => { if (!document.body.contains(c.el)) return; const u = S.update || {};
        c.q("#u-st").innerHTML = u.busy ? '<span class="spin"></span> Đang kiểm tra...' : u.err ? `<span style="color:var(--red)">⚠ ${esc(u.err)}</span>`
          : u.restarting ? "⟳ Đã cập nhật - đang khởi động lại..." : u.progress !== undefined && u.progress !== null ? `<span class="spin"></span> Đang tải bản ${esc(u.tag)}... ${u.progress >= 0 ? u.progress + "%" : ""}`
          : u.tag ? (u.newer ? `<b style="color:var(--red)">Có bản mới ${esc(u.tag)}</b>${u.notes ? `<div style="white-space:pre-line;color:var(--muted);margin-top:6px;max-height:180px;overflow:auto">${esc(u.notes)}</div>` : ""}`
            : `✔ Đang dùng bản mới nhất. Bản trên GitHub: ${esc(u.tag)}`) : "";
        setTimeout(paint, 500); };
      paint();
    }});
}
$("bUpd").onclick = updateDialog;

/* ---------------------------------------------------------------- vòng cập nhật trạng thái */
function setBar(k, e) { $("e-" + k).style.width = e[0] + "%"; $("e-" + k + "-p").textContent = e[0] + "%"; $("e-" + k + "-i").textContent = e[1]; $("e-" + k + "-i").title = e[1]; }
function badge(id, n) { const b = $(id); b.hidden = !n; b.textContent = n; }
let askedMachine = false;
async function tick() {
  try {
    const s = await api("state", rowsVer, logSeq, histVer, foldersVer, fpVer, toastAfter);
    S = Object.assign(S, s);
    $("ver").textContent = s.version + " · giao diện web";
    $("s-folders").textContent = s.stats.folders; $("s-new").textContent = s.stats.new;
    $("s-dl").textContent = s.stats.dl; $("s-owned").textContent = s.stats.owned.toLocaleString("vi-VN");
    setBar("dl", s.energy.dl); setBar("up", s.energy.up); setBar("all", s.energy.all);
    $("fb").style.width = s.energy.all[0] + "%";
    $("status").textContent = s.status;
    ["bScan", "bGo", "bDlSel", "bOwn"].forEach(b => $(b).disabled = s.busy); $("bStop").disabled = !s.busy;
    for (const [k, [st, txt]] of Object.entries(s.leds)) {
      const t = $("t-" + k); if (!t) continue;
      setLed(t.querySelector(".led"), st);
      const sm = t.querySelector("small"); if (sm.textContent !== txt) sm.textContent = txt; sm.className = "s-" + st;
      t.classList.toggle("err", st === "err");
      const fx = t.querySelector(".fix"); if (fx) fx.hidden = st !== "err";
    }
    const n = s.issues.length, overall = n ? "err" : (s.busy ? "run" : "ok");
    setLed($("aled"), n ? "err" : "ok");
    $("alert").classList.toggle("bad", !!n);
    $("a1").textContent = n ? `Có ${n} mục cần xử lý` : "Mọi thứ hoạt động tốt";
    $("a2").textContent = n ? "Tool chưa tự tải được cho tới khi sửa · bấm để xem" : `Thư viện: ${s.lib.toLocaleString("vi-VN")} tập · Máy: ${s.machine}`;
    document.querySelectorAll(".nav .led").forEach(l => setLed(l, overall));
    badge("bd-scan", s.stats.new); badge("bd-history", s.stats.dl); badge("bd-folders", s.folder_err || s.unreviewed);
    $("bd-folders").classList.toggle("o", !s.folder_err);
    if (document.activeElement !== $("aint")) $("aint").value = String(s.auto.interval);
    $("bAuto").textContent = s.auto.on ? `⏱ Tự quét: ${s.auto.interval} phút` + (s.auto.next ? ` · ${s.auto.next}` : "") : "⏱ Tự quét: tắt";
    paintLock();
    const up = s.update || {};
    $("bUpd").textContent = up.newer ? `⟳ Có bản ${up.tag}` : "⟳ Cập nhật";
    $("bUpd").classList.toggle("hot", !!up.newer);
    for (const t of s.toasts) { toast(t.text, t.kind); toastAfter = Math.max(toastAfter, t.t); }
    if (s.rows) {
      rowsVer = s.rows_ver; rows = s.rows;
      const codes = new Set(rows.map(r => r.code));
      for (const r of rows) if (!seen.has(r.code)) { seen.add(r.code); if (r.tag === "new") checked.add(r.code); }
      for (const c of [...checked]) if (!codes.has(c)) checked.delete(c);
      renderRows();
    }
    if (s.history) { histVer = s.hist_ver; hist = s.history; const codes = new Set(hist.map(h => h.code)); for (const c of [...hPicked]) if (!codes.has(c)) hPicked.delete(c); renderHist(); }
    if (s.folders) { foldersVer = s.folders_ver; folders = s.folders; renderFolders(); }
    if (s.fp !== undefined) { fpVer = s.fp_ver; FP = s.fp; if (FP) { const cs = new Set(FP.rows.map(r => r.code)); for (const c of [...fpPicked]) if (!cs.has(c)) fpPicked.delete(c); } renderFP(); renderFolders(); }
    if (s.log.length) {
      const L = $("log"), atEnd = L.scrollTop + L.clientHeight >= L.scrollHeight - 30;
      L.insertAdjacentHTML("beforeend", s.log.map(x => `<div>[${esc(x.slice(0, 8))}] ${esc(x.slice(10))}</div>`).join(""));
      while (L.childElementCount > 400) L.firstChild.remove();
      if (atEnd) L.scrollTop = L.scrollHeight;
    }
    logSeq = s.log_seq;
    if (s.new_machine && !askedMachine) {
      askedMachine = true;
      api("clear_new_machine");
      if (await confirmBox("Máy mới", `Đây là lần đầu tool chạy trên máy "${s.machine}".\n\nTool đã chép thiết lập từ máy dùng gần nhất - kiểm tra lại thư mục COPY_TO_IPHONE, thư mục phim HDD của máy này.\n\nMở Cài đặt để kiểm tra đường dẫn?`, "Mở Cài đặt", false))
        openSettings("machine");
    }
  } catch (e) { $("status").textContent = "Lỗi giao diện: " + e; }
  setTimeout(tick, 500);
}
let started = false;
async function start() {
  if (started) return; started = true;
  try {
    if (await api("ui_get", "dark", false)) document.body.classList.add("dark");
    if (await api("ui_get", "mini", false)) $("fold").click();
  } catch (e) { /* bỏ qua */ }
  tick();
  setTimeout(async () => { const p = (await api("ui_get", "page", "scan")) || "scan"; go(LOCKED.includes(p) ? "scan" : p); }, 300);
}
window.addEventListener("pywebviewready", start);
if (location.protocol.startsWith("http")) start();
else setTimeout(() => { if (window.pywebview && window.pywebview.api) start(); }, 1500);

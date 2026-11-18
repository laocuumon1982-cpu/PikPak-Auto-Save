# -*- coding: utf-8 -*-
"""Điều khiển PikPak Auto Save từ iPhone / iPad (cùng mạng Wi-Fi với PC).

Tool trên PC mở thêm 1 trang web (cổng mặc định 8686) có mã PIN. iPhone / iPad mở bằng Safari, "Thêm vào MH chính"
để dùng như app. Mọi việc vẫn chạy trên PC (quét, Save My PikPak, rclone tải về HDD) - iPhone chỉ điều khiển.
"""
import hashlib
import hmac
import io
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import auto_download_pikpak_share as core

DEFAULT_PORT = 8686
COOKIE = "pk_remote"


# ================================================================ mã QR (tự viết, không cần thư viện)
_ECC_M = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24]
_BLOCKS_M = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9]


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    res = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            res[j] = _gf_mul(res[j], root)
            if j + 1 < degree:
                res[j] ^= res[j + 1]
        root = _gf_mul(root, 0x02)
    return res


def _rs_remainder(data, div):
    res = [0] * len(div)
    for b in data:
        factor = b ^ res.pop(0)
        res.append(0)
        for i, coef in enumerate(div):
            res[i] ^= _gf_mul(coef, factor)
    return res


def _raw_modules(ver):
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        na = ver // 7 + 2
        r -= (25 * na - 10) * na - 55
        if ver >= 7:
            r -= 36
    return r


def qr_matrix(text):
    """Ma trận QR (danh sách hàng, True = ô đen), chế độ byte, mức sửa lỗi M, phiên bản 1-14."""
    data = text.encode("utf-8")
    for ver in range(1, 15):
        cap = (_raw_modules(ver) // 8 - _ECC_M[ver] * _BLOCKS_M[ver]) * 8
        cc = 8 if ver < 10 else 16
        if 4 + cc + len(data) * 8 <= cap:
            break
    else:
        raise ValueError("Chuỗi quá dài cho mã QR")
    bits = []

    def put(val, n):
        bits.extend((val >> i) & 1 for i in reversed(range(n)))
    put(0b0100, 4)
    put(len(data), cc)
    for b in data:
        put(b, 8)
    put(0, min(4, cap - len(bits)))
    put(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    # chia khối + mã sửa lỗi + xen kẽ
    nb, el = _BLOCKS_M[ver], _ECC_M[ver]
    raw = _raw_modules(ver) // 8
    nshort, slen = nb - raw % nb, raw // nb
    div = _rs_divisor(el)
    blocks, k = [], 0
    for i in range(nb):
        dat = words[k:k + slen - el + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < nshort:
            dat.append(0)
        blocks.append(dat + ecc)
    final = [blk[i] for i in range(len(blocks[0])) for j, blk in enumerate(blocks)
             if i != slen - el or j >= nshort]
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fun = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        mod[y][x] = dark
        fun[y][x] = True
    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    setf(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    if ver > 1:
        na = ver // 7 + 2
        step = (ver * 8 + na * 3 + 5) // (na * 4 - 4) * 2
        pos = list(reversed([size - 7 - i * step for i in range(na - 1)] + [6]))
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == na - 1) or (i == na - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format(mask):
        d = (0 << 3) | mask                      # mức M = 00
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        b = (d << 10 | r) ^ 0x5412
        g = lambda i: ((b >> i) & 1) != 0       # noqa: E731
        for i in range(6):
            setf(8, i, g(i))
        setf(8, 7, g(6))
        setf(8, 8, g(7))
        setf(7, 8, g(8))
        for i in range(9, 15):
            setf(14 - i, 8, g(i))
        for i in range(8):
            setf(size - 1 - i, 8, g(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, g(i))
        setf(8, size - 8, True)
    draw_format(0)
    if ver >= 7:
        r = ver
        for _ in range(12):
            r = (r << 1) ^ ((r >> 11) * 0x1F25)
        b = ver << 12 | r
        for i in range(18):
            bit = ((b >> i) & 1) != 0
            a, c = size - 11 + i % 3, i // 3
            setf(a, c, bit)
            setf(c, a, bit)
    i = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fun[y][x] and i < len(final) * 8:
                    mod[y][x] = ((final[i >> 3] >> (7 - (i & 7))) & 1) != 0
                    i += 1
        right -= 2
    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def apply(m):
        for y in range(size):
            for x in range(size):
                if not fun[y][x] and masks[m](x, y):
                    mod[y][x] = not mod[y][x]

    def penalty():
        p = 0
        for rows in (mod, list(map(list, zip(*mod)))):
            for row in rows:
                run, prev = 0, None
                for v in row:
                    run = run + 1 if v == prev else 1
                    prev = v
                    if run == 5:
                        p += 3
                    elif run > 5:
                        p += 1
        for y in range(size - 1):
            for x in range(size - 1):
                if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                    p += 3
        dark = sum(v for row in mod for v in row)
        p += abs(dark * 20 - size * size * 10) // (size * size) * 10
        return p
    best, bestp = 0, None
    for m in range(8):
        apply(m)
        draw_format(m)
        pv = penalty()
        if bestp is None or pv < bestp:
            best, bestp = m, pv
        apply(m)
    apply(best)
    draw_format(best)
    return mod


def qr_svg(text, scale=6, border=4):
    m = qr_matrix(text)
    n = len(m) + border * 2
    path = "".join(f"M{x + border},{y + border}h1v1h-1z" for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * scale}" height="{n * scale}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


# ================================================================ địa chỉ của PC trong mạng nhà
def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))           # không gửi gì, chỉ để biết card mạng đang dùng
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    priv = [ip for ip in ips if ip.startswith(("192.168.", "10.")) or
            (ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)]
    return priv or ips or ["127.0.0.1"]


def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", str(pin).encode(), bytes.fromhex(salt), 60000).hex()


# ================================================================ các hàm iPhone / iPad được / không được gọi
PC_ONLY = {
    "pick_folder": "Chọn thư mục bằng hộp thoại chỉ làm được trên PC - gõ đường dẫn vào ô.",
    "pick_open": "Chọn file chỉ làm được trên PC.", "pick_save": "Lưu file chỉ làm được trên PC.",
    "open_data": "Mở thư mục chỉ làm được trên PC.", "open_base": "Mở thư mục chỉ làm được trên PC.",
    "open_iphone": "Mở thư mục chỉ làm được trên PC.", "open_reports": "Mở thư mục chỉ làm được trên PC.",
    "open_source": "Mở file / thư mục chỉ làm được trên PC.", "hist_open": "Mở file chỉ làm được trên PC.",
    "folder_open_source": "", "open_url": "", "copy_text": "",
    "folder_export": "Xuất danh sách chỉ làm được trên PC.", "folder_import": "Nhập danh sách chỉ làm được trên PC.",
    "backup_to_file": "Sao lưu ra file chỉ làm được trên PC.", "restore_pick": "Khôi phục từ file chỉ làm được trên PC.",
    "update_from_file": "Cập nhật từ file zip chỉ làm được trên PC.", "classic_ui": "Đổi giao diện chỉ làm được trên PC.",
    "quit_app": "Thoát tool chỉ làm được trên PC.", "export_log": "Xuất nhật ký chỉ làm được trên PC.",
    "remote_info": "", "remote_set": "Bật / tắt điều khiển từ xa chỉ làm được trên PC.", "remote_logout_all": "",
    "test_notify": "Thông báo hiện trên PC.", "folder_diagnose": "Chẩn đoán (mở file kết quả) chỉ làm được trên PC.",
}


class RemoteApi:
    """API cho iPhone / iPad: dùng chung Api của PC, nhưng mật khẩu admin mở khóa RIÊNG từng thiết bị."""

    def __init__(self, server, token):
        self.srv = server
        self.api = server.api
        self.eng = server.eng
        self.token = token

    def _sess(self):
        return self.srv.sessions.setdefault(self.token, {"until": 0.0, "last": time.time()})

    def unlocked(self):
        s = self._sess()
        mins = int(self.eng.cfg.get("admin_lock_min", 10) or 0)
        if s["until"] and mins > 0 and time.time() - s["last"] > mins * 60:
            s["until"] = 0.0
        return s["until"] > 0

    def call(self, name, args):
        if name.startswith("_"):
            return {"error": "không có"}
        if name in PC_ONLY:
            if name == "folder_open_source":           # iPhone tự mở link
                f = self.eng.cfg["folders"][int(args[0])]
                return {"url": core.source_link(self.eng.cfg, f)}
            if name in ("open_url", "copy_text"):
                return False
            if name == "remote_info":
                return {"remote": True}
            return PC_ONLY[name]
        s = self._sess()
        if name == "ping":
            s["last"] = time.time()
            return ""
        if name == "admin_unlock":
            pw = args[0] if args else ""
            if not self.eng.cfg.get("admin_hash"):
                return "Chưa có mật khẩu admin - tạo trên PC trước (bấm tab Thư mục phim)."
            if self.eng._pw_hash(pw or "", self.eng.cfg.get("admin_salt", "")) != self.eng.cfg.get("admin_hash"):
                return "Sai mật khẩu admin."
            s["until"] = s["last"] = time.time()
            return ""
        if name == "admin_lock":
            s["until"] = 0.0
            return ""
        if name == "admin_change":
            return "Đổi mật khẩu admin trên PC."
        if name == "report_latest":
            f = self.eng.latest_report()
            if not f:
                return {"error": "Chưa có báo cáo lỗi nào."}
            return {"name": f.name, "copied": False, "text": f.read_text(encoding="utf-8", errors="replace")}
        locked_calls = {"folder_save", "folder_toggle", "folder_check_all", "folder_move", "folder_delete",
                        "folder_ack_gaps", "folder_bulk", "fp_mark", "fp_save", "save_settings", "copy_profile",
                        "delete_profile", "pk_login", "restore_apply", "set_update", "ui_set_shared"}
        if name in locked_calls and not self.unlocked():
            return {"error": "Tab này đang khóa - nhập mật khẩu admin."} if name in ("fp_save", "folder_import") \
                else (-1 if name == "folder_bulk" else "Tab này đang khóa - nhập mật khẩu admin.")
        if name == "ui_get":                 # sáng / tối, trang đang mở: nhớ riêng trên iPhone
            return (s.get("ui") or {}).get(args[0], args[1] if len(args) > 1 else None)
        if name == "ui_set":
            s.setdefault("ui", {})[args[0]] = args[1]
            return ""
        me = self

        class _DevApi(type(self.api)):        # khóa admin theo thiết bị này, không theo PC
            def _locked(self_):
                return "" if me.unlocked() else "Tab này đang khóa - nhập mật khẩu admin."
        fn = getattr(_DevApi(self.eng, self.api._ui), name, None)
        if not callable(fn):
            return {"error": "không có"}
        res = fn(*args)
        if name == "state" and isinstance(res, dict):
            res = dict(res, admin={"unlocked": self.unlocked(), "has_pw": bool(self.eng.cfg.get("admin_hash"))},
                       remote=True, new_machine=False)
        if name == "settings" and isinstance(res, dict):
            res = dict(res, remote_mode=True)
        return res


LOGIN_HTML = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="PikPak"><link rel="apple-touch-icon" href="/icon.png">
<link rel="manifest" href="/manifest.webmanifest"><title>PikPak Auto Save</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(180deg,#e4f1fd,#d2e7fb);
font-family:-apple-system,"Segoe UI",system-ui,sans-serif;color:#0f172a}
.box{box-sizing:border-box;background:linear-gradient(#fff,#eef3f8);border:1px solid #c8d5e2;border-radius:18px;padding:26px 24px;width:min(360px,88vw);
box-shadow:inset 0 1px 0 #fff,0 5px 0 #b4c4d4,0 12px 26px rgba(30,60,100,.18);text-align:center}
.logo{width:56px;height:56px;margin:0 auto 10px;border-radius:14px;background:linear-gradient(150deg,#6b93ff,#2d55c8);color:#fff;
font-weight:900;font-size:28px;display:grid;place-items:center;box-shadow:0 3px 0 #1e3f9c}
h2{margin:6px 0 2px}p{color:#475569;margin:4px 0 16px;font-size:14px}
input{width:100%;box-sizing:border-box;font-size:26px;letter-spacing:10px;text-align:center;padding:10px;border-radius:12px;
border:1px solid #c5cdd8;box-shadow:inset 0 2px 3px rgba(0,0,0,.08)}
button{margin-top:14px;width:100%;padding:12px;font-size:17px;font-weight:800;color:#fff;border:1px solid #9e1417;border-radius:12px;
background:linear-gradient(180deg,#ff7a7d 0%,#ef3337 48%,#d61f23 52%,#b5171b 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.55),0 3px 0 #7d0f12}
button:active{transform:translateY(3px);box-shadow:inset 0 3px 6px rgba(0,0,0,.3)}
.err{color:#dc2626;font-weight:700;min-height:20px;margin-top:10px}</style></head><body>
<form class="box" onsubmit="go(event)"><div class="logo">P</div><h2>PikPak Auto Save</h2>
<p>Điều khiển tool trên máy __MACHINE__<br>Nhập mã PIN (đặt trong Cài đặt của tool trên PC)</p>
<input id="pin" type="password" inputmode="numeric" autocomplete="current-password" autofocus><button>Mở</button>
<div class="err" id="err"></div></form>
<script>async function go(e){e.preventDefault();const r=await fetch("/login",{method:"POST",body:JSON.stringify({pin:document.getElementById("pin").value})});
const j=await r.json();if(j.ok)location.replace("/");else document.getElementById("err").textContent=j.error||"Sai mã PIN";}</script></body></html>"""


class RemoteServer:
    def __init__(self, eng, api, page_fn):
        self.eng, self.api, self.page_fn = eng, api, page_fn
        self.httpd = None
        self.sessions = {}
        self.fails = {}
        self.unlock_lock = threading.Lock()
        self.error = ""

    # ----- cấu hình (Data/config.json -> "remote")
    @property
    def cfg(self):
        return self.eng.cfg.setdefault("remote", {})

    def port(self):
        try:
            return int(self.cfg.get("port") or DEFAULT_PORT)
        except (TypeError, ValueError):
            return DEFAULT_PORT

    def running(self):
        return self.httpd is not None

    def start(self):
        if self.httpd or not self.cfg.get("on") or not self.cfg.get("pin_hash"):
            return
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", self.port()), self._handler())
        except OSError as e:
            self.error = f"Không mở được cổng {self.port()}: {e}"
            self.eng.log("⚠ Điều khiển từ iPhone/iPad: " + self.error)
            return
        srv.daemon_threads = True
        self.httpd = srv
        self.error = ""
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.eng.log(f"📱 Điều khiển từ iPhone/iPad: mở Safari vào http://{lan_ips()[0]}:{self.port()}")

    def stop(self):
        if self.httpd:
            h, self.httpd = self.httpd, None
            threading.Thread(target=lambda: (h.shutdown(), h.server_close()), daemon=True).start()

    def info(self):
        port = self.port()
        urls = [f"http://{ip}:{port}" for ip in lan_ips()]
        return {"on": bool(self.cfg.get("on")), "has_pin": bool(self.cfg.get("pin_hash")), "port": port,
                "running": self.running(), "urls": urls, "qr": qr_svg(urls[0]) if urls else "", "error": self.error,
                "devices": len(self.cfg.get("tokens") or [])}

    def set(self, on, pin, port):
        with self.eng.lock:
            if pin:
                pin = str(pin).strip()
                if not pin.isdigit() or not 4 <= len(pin) <= 8:
                    return "Mã PIN gồm 4-8 chữ số."
                salt = secrets.token_hex(8)
                self.cfg.update(pin_salt=salt, pin_hash=_hash_pin(pin, salt), tokens=[])
                self.sessions.clear()
            if on and not self.cfg.get("pin_hash"):
                return "Đặt mã PIN trước khi bật."
            try:
                p = int(port or DEFAULT_PORT)
                if not 1024 <= p <= 65535:
                    raise ValueError
            except (TypeError, ValueError):
                return "Cổng phải là số từ 1024 đến 65535."
            restart = self.running() and (p != self.port() or not on)
            self.cfg.update(on=bool(on), port=p)
            self.eng.save_config()
        if restart or not on:
            self.stop()
            time.sleep(0.3)
        if on:
            self.start()
        return self.error if on and not self.running() else ""

    def logout_all(self):
        with self.eng.lock:
            self.cfg["tokens"] = []
            self.sessions.clear()
            self.eng.save_config()

    # ----- đăng nhập bằng PIN
    def _token_ok(self, tok):
        if not tok:
            return False
        h = hashlib.sha256(tok.encode()).hexdigest()
        return any(hmac.compare_digest(h, x) for x in (self.cfg.get("tokens") or []))

    def _login(self, ip, pin):
        f = self.fails.get(ip, [0, 0.0])
        if f[0] >= 5 and time.time() - f[1] < 60:
            return None, "Nhập sai nhiều lần - đợi 1 phút rồi thử lại."
        salt = self.cfg.get("pin_salt", "")
        if not salt or not hmac.compare_digest(_hash_pin(pin or "", salt), self.cfg.get("pin_hash", "")):
            self.fails[ip] = [f[0] + 1, time.time()]
            self.eng.log(f"📱 Nhập sai mã PIN từ {ip}")
            return None, "Sai mã PIN."
        self.fails.pop(ip, None)
        tok = secrets.token_urlsafe(24)
        with self.eng.lock:
            toks = (self.cfg.get("tokens") or [])[-19:]
            toks.append(hashlib.sha256(tok.encode()).hexdigest())
            self.cfg["tokens"] = toks
            self.eng.save_config()
        self.eng.log(f"📱 Thiết bị {ip} đã đăng nhập điều khiển từ xa.")
        return tok, ""

    def _icon_png(self, size=180):
        try:
            import base64
            from PIL import Image
            im = Image.open(io.BytesIO(base64.b64decode(core.ICON64))).convert("RGBA").resize((size, size))
            bg = Image.new("RGBA", (size, size), (255, 255, 255, 255))
            bg.alpha_composite(im)
            out = io.BytesIO()
            bg.convert("RGB").save(out, "PNG")
            return out.getvalue()
        except Exception:                   # noqa: BLE001
            return b""

    def _handler(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype, extra=None):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _token(self):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == COOKIE:
                        return v
                return ""

            def do_GET(self):
                path = self.path.split("?")[0]
                if path == "/icon.png":
                    return self._send(200, srv._icon_png(), "image/png")
                if path == "/manifest.webmanifest":
                    return self._send(200, json.dumps({
                        "name": "PikPak Auto Save", "short_name": "PikPak", "start_url": "/", "display": "standalone",
                        "background_color": "#e4f1fd", "theme_color": "#e4f1fd",
                        "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}]}), "application/manifest+json")
                if path != "/":
                    return self._send(404, "not found", "text/plain")
                if not srv._token_ok(self._token()):
                    return self._send(200, LOGIN_HTML.replace("__MACHINE__", core.MACHINE), "text/html; charset=utf-8")
                return self._send(200, srv.page_fn(remote=True), "text/html; charset=utf-8")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 2_000_000:
                    return self._send(413, "{}", "application/json")
                body = self.rfile.read(n) or b"[]"
                if self.path == "/login":
                    try:
                        pin = json.loads(body).get("pin", "")
                    except (ValueError, AttributeError):
                        pin = ""
                    tok, err = srv._login(self.client_address[0], pin)
                    if not tok:
                        return self._send(200, json.dumps({"ok": False, "error": err}, ensure_ascii=False),
                                          "application/json; charset=utf-8")
                    return self._send(200, '{"ok": true}', "application/json", {
                        "Set-Cookie": f"{COOKIE}={tok}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict"})
                tok = self._token()
                if not srv._token_ok(tok):
                    return self._send(401, json.dumps({"error": "Hết phiên - mở lại trang và nhập PIN."},
                                                      ensure_ascii=False), "application/json; charset=utf-8")
                if self.path == "/logout":
                    with srv.eng.lock:
                        h = hashlib.sha256(tok.encode()).hexdigest()
                        srv.cfg["tokens"] = [x for x in (srv.cfg.get("tokens") or []) if x != h]
                        srv.eng.save_config()
                    return self._send(200, "{}", "application/json", {"Set-Cookie": f"{COOKIE}=; Max-Age=0; Path=/"})
                name = self.path.rsplit("/", 1)[-1]
                try:
                    args = json.loads(body)
                    if not isinstance(args, list):
                        args = []
                    res = RemoteApi(srv, tok).call(name, args)
                except Exception as e:      # noqa: BLE001
                    return self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False), "application/json")
                self._send(200, json.dumps(res, ensure_ascii=False), "application/json; charset=utf-8")
        return H

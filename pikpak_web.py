# -*- coding: utf-8 -*-
"""PikPak Auto Save v3 - giao diện web trong cửa sổ app (pywebview / Edge WebView2).

Phần lõi (quét link chia sẻ, Save vào My PikPak, rclone tải về HDD, COPY_TO_IPHONE, báo lỗi, sao lưu, cập nhật)
nằm trong auto_download_pikpak_share.py và được dùng lại nguyên vẹn; file này chỉ thay phần giao diện Tk.
Mở bằng: auto_download_pikpak_share.py (tự gọi run_web) hoặc  python pikpak_web.py [--serve]
"""
import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import auto_download_pikpak_share as core
from auto_download_pikpak_share import (
    APP_NAME, APP_TITLE, APP_VERSION, BASE, CONFIG_FILE, DATA_DIR, HISTORY_FILE, MACHINE, OWNED_FILE,
    STATUS_DONE, STATUS_FAIL, RETRY_STATUSES, WATCH_STATUSES, SPLIT_CHOICES, RCLONE_CONF, RCLONE_EXE, BACKUP_FILES,
    BACKUP_DIR, INTERVAL_CHOICES, find_rclone, human_size, load_json, open_target, pikpak_api, run_rclone, save_json,
    fid, from_portable, to_portable, dec_secret, enc_secret, resolve_src, clean_src, src_key, is_share, share_parts,
    pikpak_join, source_link, folder_link, new_folder_id, one_line, natural_key, sub_label, match_keywords,
    make_source, find_gaps, strip_accents, safe_name, resolve_iphone_dir, copy_with_progress, make_backup_zip,
    download_rclone, github_latest, ver_tuple, download_file, stage_update, clean_env, restart_self, set_startup,
    LocalSource, store, write_log, restore_backup_zip, DB_FILE)

WEB_DIR_NAME = "web"
V_SHORT = APP_VERSION.split(" by")[0]


def web_dir():
    """Thư mục chứa giao diện: cạnh file .py (bản cập nhật dạng Python) hoặc trong exe (_MEIPASS)."""
    for base in (Path(__file__).resolve().parent, Path(getattr(sys, "_MEIPASS", "") or "."), BASE):
        p = base / WEB_DIR_NAME / "index.html"
        if p.is_file():
            return p.parent
    raise FileNotFoundError("Không thấy thư mục giao diện 'web' (web/index.html)")


def page_html():
    """index.html với style.css và app.js nhúng thẳng vào (cửa sổ app nạp trang bằng chuỗi HTML)."""
    d = web_dir()
    html = (d / "index.html").read_text(encoding="utf-8")
    css = (d / "style.css").read_text(encoding="utf-8")
    js = (d / "app.js").read_text(encoding="utf-8")
    html = html.replace('<link rel="stylesheet" href="style.css">', "<style>\n" + css + "\n</style>")
    return html.replace('<script src="app.js"></script>', "<script>\n" + js.replace("</script", "<\\/script") + "\n</script>")


class _Var:
    """Thay StringVar của Tk cho các hàm lõi mượn từ App (status_var.set...)."""

    def __init__(self, setter):
        self._set = setter

    def set(self, v):
        self._set(v)

    def get(self):
        return ""


class EngineQueue(queue.Queue):
    """Tin nhắn từ lõi. Tin "call" (gọi hàm giao diện) chạy ngay - các hàm đó ở đây không dùng Tk."""

    def put(self, item, block=True, timeout=None):
        if item and item[0] == "call":
            _, fn, args, holder, ev = item
            try:
                holder["res"] = fn(*args)
            except Exception as e:          # noqa: BLE001
                holder["err"] = e
            ev.set()
            return
        super().put(item, block, timeout)


class Engine:
    """Trạng thái + mọi thao tác. Hàm quét / tải / báo lỗi / sao lưu... mượn thẳng từ core.App."""
    BORROWED = ("note_listing", "owned_index", "is_owned", "add_owned", "remove_owned", "_scan_job", "_download_job",
                "_download_items", "_fetch_fail", "_remove_broken", "report_error", "_fetch_one", "_copy_to_iphone",
                "_names_preview", "check_pikpak", "_backup_remote", "_do_backup", "diagnose_folder",
                "_diagnose_done", "_apply_profile", "_init_machine_profile", "_fix_missing_paths",
                "_store_machine_profile", "enqueue_upload", "_resume_uploads", "_uploader_loop", "_up_file",
                "_upload_text", "_pw_hash", "_status_text")

    def __init__(self):
        self.lock = threading.RLock()
        self.cfg = load_json(CONFIG_FILE, core.DEFAULT_CONFIG)
        self.cfg.setdefault("folders", [])
        self._no_save = False
        self.new_machine = self._init_machine_profile()
        if not CONFIG_FILE.exists():
            self.cfg["cfg_rev"] = 4
        if int(self.cfg.get("cfg_rev", 1) or 1) < 2:
            self.cfg.update(download_dir=r"D:\DOWNLOAD HH3D", dl_movie_sub=True, organize=False, cfg_rev=2)
        if not self.cfg.get("download_dir"):
            self.cfg["download_dir"] = core.default_download_dir()
        if int(self.cfg.get("cfg_rev", 1) or 1) < 4:
            self.cfg.update(dl_method="copy", cfg_rev=4)
        for f in self.cfg["folders"]:
            fid(f)
            if not f.get("dest_rev"):
                hdd = f.get("local_dir") or to_portable(self.cfg.get("download_dir", "") or "")
                pk = pikpak_join(self.cfg.get("pikpak_root", ""), f.get("pikpak_dir", "")) if \
                    self.cfg.get("pikpak_on", True) else ""
                f.update(local_dir=hdd, pikpak_dir=pk, sub_movie=True, dest_rev=3)
        self.db = store()                   # v3.1: Danh sách đã có + lịch sử + nhật ký trong Data/pikpak.db
        self.history = self.db.load("history")
        for h in self.history.values():
            if h.get("status") in WATCH_STATUSES:
                h["status"] = STATUS_FAIL
        self.owned = self.db.load("owned")
        self.item_meta, self.present_codes, self.sub_of = {}, set(), {}
        self.q = EngineQueue()
        self.worker = None
        self.stop_flag = threading.Event()
        self.log_lines, self.log_seq = [], 0
        self.rows, self.row_order, self.scan_items = {}, [], {}
        self.rows_ver = self.hist_ver = self.folders_ver = self.fp_ver = 1
        self._new_count = 0
        self._batch = (0, 0)
        self._dl_pct = 0
        self.energy = {"dl": [0, "—"], "up": [0, "—"], "all": [0, "—"]}
        self.status = "Sẵn sàng."
        self.status_var = _Var(self._set_status)
        self.pk_ok, self.pk_text = None, "đang kết nối..."
        self._pk_acc, self._rc_ver = {}, None
        self._health_probs, self._in_health = [], False
        self._backup_pending = False
        self.bk_error = ""
        self.next_auto_ts = None
        self.last_summary = self.cfg.get("last_summary", "")
        self.fp = None
        self.update_info = {}
        self.rclone_dl = None             # % đang tải rclone.exe
        self.task_msg = ""                # việc nền đang chạy (sao lưu, copy iPhone...)
        self._admin_until, self._admin_last = 0.0, time.time()
        self.toasts = []                  # thông báo nhỏ đẩy lên giao diện
        self.confirm_fn = None            # hỏi Có / Không (đặt bởi cửa sổ app)
        self.notify_fn = None
        self.quit_fn = None
        self.up_q = queue.Queue()
        self.up_queued = set()
        if self.cfg.get("auto_scan"):
            self.next_auto_ts = time.time() + int(self.cfg.get("auto_interval", 60)) * 60
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._auto_loop, daemon=True).start()
        threading.Thread(target=self._slow_loop, daemon=True).start()
        threading.Thread(target=self._uploader_loop, daemon=True).start()
        self._resume_uploads()
        self.check_pikpak(silent=True)
        self.log(f"{APP_NAME} · giao diện web · dữ liệu: {DATA_DIR}")
        if not find_rclone(self.cfg.get("rclone_path", "")):
            self.log("Chưa có rclone.exe - đang tự tải về thư mục tool...")
            self.get_rclone()

    # ------------------------------------------------------------ thay cho phần giao diện Tk của App
    def log(self, msg):
        self.q.put(("log", msg))

    def _set_status(self, text):
        self.status = str(text)

    def toast(self, text, kind="info"):
        with self.lock:
            self.toasts.append({"t": time.time(), "text": str(text), "kind": kind})
            del self.toasts[:-20]

    def save_config(self):
        with self.lock:
            if self._no_save:
                return
            self._store_machine_profile()
            save_json(CONFIG_FILE, self.cfg)

    def save_history(self):
        with self.lock:
            if self._no_save:               # vừa khôi phục / cập nhật: không ghi đè dữ liệu
                return
            self.db.save("history", self.history)
            self.hist_ver += 1

    def save_owned(self):
        with self.lock:
            if self._no_save:
                return
            self.db.save("owned", self.owned)

    def refresh_history(self):
        self.hist_ver += 1

    def refresh_folders(self):
        self.folders_ver += 1

    def update_stats(self):
        pass

    def call_ui(self, fn, *args, timeout=20):
        if self._in_health:
            return self.confirm("Phát hiện vấn đề:\n\n• " + "\n• ".join(self._health_probs) + "\n\nVẫn tiếp tục tải?")
        return fn(*args)

    def confirm(self, text):
        try:
            return bool(self.confirm_fn(text)) if self.confirm_fn else True
        except Exception:                   # noqa: BLE001
            return True

    def _health_check(self, cfg, auto, items=None):
        self._in_health = True
        try:
            return core.App._health_check(self, cfg, auto, items)
        finally:
            self._in_health = False

    def _show_health(self, probs):
        self._health_probs = list(probs)

    def _show_err_badge(self):
        pass

    def _set_pk_status(self, text, ok):
        self.pk_ok = ok
        self.pk_text = text.replace("☁ PikPak:", "").strip()
        if ok and not self._pk_acc:
            threading.Thread(target=self._read_account, daemon=True).start()

    def schedule_backup(self):
        if not self.cfg.get("backup_on", True) or self._backup_pending or not find_rclone(self.cfg.get("rclone_path", "")):
            return
        self._backup_pending = True
        t = threading.Timer(20, lambda: self.up_q.put("__backup__"))
        t.daemon = True
        t.start()

    def notify(self, title, msg):
        self.log(f"» {title}: {msg}")
        if self.cfg.get("notify", True) and self.notify_fn:
            try:
                self.notify_fn(title, msg)
            except Exception:               # noqa: BLE001
                pass

    # ------------------------------------------------------------ bơm tin nhắn từ lõi -> trạng thái
    def _pump(self):
        while True:
            batch = [self.q.get()]
            try:
                while True:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            hist_changed = owned_changed = False
            with self.lock:
                for m in batch:
                    try:
                        h, o = self._handle(m)
                        hist_changed |= h
                        owned_changed |= o
                    except Exception as e:   # noqa: BLE001
                        self._add_log(f"LỖI giao diện: {e}")
                if hist_changed:
                    self.save_history()
                if owned_changed:
                    self.save_owned()

    def _add_log(self, text):
        line = f"{dt.datetime.now():%H:%M:%S}  {text}"
        self.log_seq += 1
        self.log_lines.append(line)
        del self.log_lines[:-400]
        write_log(text)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "log":
            self._add_log(msg[1])
        elif kind == "status":
            self.status = msg[1]
        elif kind == "progress":
            self._batch = (msg[1], msg[2])
            self._dl_pct = 0
            self._energy_total()
        elif kind == "energy":
            key = msg[1]
            try:
                pct = max(0, min(100, int(round(float(msg[2] or 0)))))
            except (TypeError, ValueError):
                pct = 0
            self.energy[key][0] = pct
            if len(msg) > 3 and msg[3] is not None:
                self.energy[key][1] = str(msg[3])
            if key == "dl":
                self._dl_pct = pct
                self._energy_total()
        elif kind == "row":
            _, code, values, tag = msg[:4]
            self.scan_items[code] = msg[4]
            if code not in self.rows:
                self.row_order.append(code)
            self.rows[code] = {"code": code, "v": list(values), "tag": tag}
            self.rows_ver += 1
        elif kind == "rowstatus":
            r = self.rows.get(msg[1])
            if r:
                r["v"][5], r["tag"] = msg[2], msg[3]
                self.rows_ver += 1
        elif kind == "newcount":
            self._new_count = msg[1]
        elif kind == "hist":
            self.history[msg[1]] = msg[2]
            return True, False
        elif kind == "histmerge":
            self.history.setdefault(msg[1], {}).update(msg[2])
            return True, False
        elif kind == "owned_add":
            _, fcode, folder_code, fname, name, size, src = msg
            self.add_owned(fcode, folder_code, fname, name, size, src)
            return False, True
        elif kind == "owned_remove":
            self.remove_owned(msg[1], msg[2], msg[3])
            return False, True
        elif kind == "folderstat":
            i, data = msg[1], msg[2]
            if i < len(self.cfg["folders"]):
                self.cfg["folders"][i].update(data)
                save_json(CONFIG_FILE, self.cfg)
                self.folders_ver += 1
        elif kind == "foldername":
            i, name = msg[1], msg[2]
            if i < len(self.cfg["folders"]) and not self.cfg["folders"][i].get("name"):
                self.cfg["folders"][i]["name"] = name
                save_json(CONFIG_FILE, self.cfg)
                self.folders_ver += 1
        elif kind == "summary":
            self.last_summary = self.cfg["last_summary"] = msg[1]
        elif kind == "retry_soon":
            if self.cfg.get("auto_scan"):
                self.next_auto_ts = min(self.next_auto_ts or 1e18, time.time() + msg[1])
        elif kind == "pkstatus":
            self._set_pk_status(msg[1], msg[2])
        elif kind == "backup":
            self._backup_pending = False
            if msg[1]:
                self.cfg["last_backup"], self.bk_error = msg[2], ""
                save_json(CONFIG_FILE, self.cfg)
                self._add_log(f"⟲ Đã sao lưu dữ liệu lên PikPak ({msg[2]}).")
            else:
                self.bk_error = msg[2]
                self._add_log("⚠ Sao lưu lên PikPak lỗi: " + msg[2])
        elif kind == "upload":
            return self._on_upload(msg[1], msg[2], msg[3]), False
        elif kind == "fetched":
            self.enqueue_upload(msg[1])
            return True, False
        elif kind == "notify":
            self.notify(msg[1], msg[2])
        elif kind == "done":
            self.status = msg[1]
            if self.energy["dl"][1] not in ("—",):
                self.energy["dl"][1] = "✔ " + str(msg[1]).strip()
            self.folders_ver += 1
        return False, False

    def _on_upload(self, code, state, info):
        if state in ("done", "error"):
            self.up_queued.discard(code)
            nm = (self.history.get(code) or {}).get("name", "")
            self.energy["up"] = [100, f"✔ Đã lưu: {nm}"] if state == "done" else [0, f"⚠ Lỗi lưu: {nm}"]
        h = self.history.get(code)
        if not h:
            return False
        h["upload"], h["upload_msg"] = state, info
        r = self.rows.get(code)
        if r and state in ("done", "error"):
            r["v"][5] = "✔  Xong · HDD · My PikPak" if state == "done" else "✔  HDD  ·  ⚠ lỗi lưu PikPak"
            r["tag"] = "done" if state == "done" else "err"
            self.rows_ver += 1
        if state == "done":
            h["upload_ts"] = time.time()
            self._add_log(f"☁ Đã lưu vào My PikPak: {h.get('name', '')}  →  {info}")
        elif state == "error":
            self._add_log(f"⚠ Lưu My PikPak lỗi: {h.get('name', '')} — {info}")
            self.report_error(f"Lưu My PikPak lỗi: {h.get('name', '')}", info)
        return state in ("done", "error")

    def _energy_total(self):
        done, n = self._batch
        if not n:
            return
        cur = self._dl_pct if done < n else 0
        tot = min(100, (done + cur / 100) / n * 100)
        self.energy["all"] = [int(tot), f"{min(done + (1 if done < n else 0), n)} / {n}"]

    # ------------------------------------------------------------ quét / tải
    def busy(self):
        return bool(self.worker and self.worker.is_alive())

    def _run_worker(self, target, *args):
        self.stop_flag.clear()
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def start_scan(self, download, auto=False, only=None):
        if self.busy():
            return "Đang chạy - chờ xong hoặc bấm Dừng."
        if core.requests is None:
            return "Thiếu thư viện 'requests'."
        if not self.cfg["folders"]:
            return "Chưa có thư mục phim nào - thêm ở tab Thư mục phim."
        if not only and not any(f.get("enabled", True) for f in self.cfg["folders"]):
            return "Chưa chọn thư mục nào để quét (tab Thư mục phim)."
        with self.lock:
            self.rows, self.row_order, self.scan_items = {}, [], {}
            self._new_count = 0
            self.rows_ver += 1
            n = len(only) if only else sum(1 for f in self.cfg["folders"] if f.get("enabled", True))
            self._batch = (0, n)
            for k in self.energy:
                self.energy[k] = [0, "—"]
        self._run_worker(self._scan_job, download, auto, set(only) if only else None)
        return ""

    def download_codes(self, codes):
        if self.busy():
            return "Đang chạy - chờ xong hoặc bấm Dừng."
        idx = self.owned_index()
        items = [self.scan_items[c] for c in codes if c in self.scan_items]
        items = [it for it in items if not self.is_owned(idx, it[0], it[4], it[2])]
        if not items:
            return "Không có file nào cần tải trong các dòng đã chọn."
        self._run_worker(self._download_job, items)
        return ""

    def mark_owned(self, codes):
        n = 0
        with self.lock:
            for c in codes:
                it = self.scan_items.get(c)
                if not it:
                    continue
                fcode, fname, name, size, folder_code = it
                self.add_owned(fcode, folder_code, fname, name, size, "manual")
                self.rows.pop(c, None)
                n += 1
            self.row_order = [c for c in self.row_order if c in self.rows]
            self._new_count = max(0, self._new_count - n)
            self.rows_ver += 1
            self.save_owned()
        self.log(f"Đã thêm {n} file vào Danh sách đã có (sẽ không tải).")
        return n

    def stop(self):
        self.stop_flag.set()
        self.log("■ Đang dừng...")

    def set_auto(self, on, minutes=None):
        with self.lock:
            self.cfg["auto_scan"] = bool(on)
            if minutes:
                try:
                    self.cfg["auto_interval"] = max(5, int(minutes))
                except (TypeError, ValueError):
                    pass
            self.save_config()
        if on:
            self.next_auto_ts = time.time() + int(self.cfg.get("auto_interval", 60)) * 60
            self.log(f"Bật tự quét mỗi {self.cfg['auto_interval']} phút.")
        else:
            self.next_auto_ts = None
            self.log("Tắt tự quét.")
        if getattr(self, "on_auto_changed", None):
            self.on_auto_changed()

    def _auto_loop(self):
        while True:
            time.sleep(10)
            try:
                now = time.time()
                if self.cfg.get("auto_scan") and not self.next_auto_ts:
                    self.next_auto_ts = now + int(self.cfg.get("auto_interval", 60)) * 60
                if self.next_auto_ts and now >= self.next_auto_ts:
                    if self.busy():
                        self.next_auto_ts = now + 120
                    else:
                        self.log("⏱ Tự quét theo lịch...")
                        self.start_scan(True, auto=True)
                        self.next_auto_ts = (now + int(self.cfg.get("auto_interval", 60)) * 60
                                             if self.cfg.get("auto_scan") else None)
                mins = int(self.cfg.get("admin_lock_min", 10) or 0)
                if self._admin_until and mins > 0 and now - self._admin_last > mins * 60:
                    self._admin_until = 0
                    self.toast(f"🔒 Tự khóa sau {mins} phút không thao tác.")
            except Exception:               # noqa: BLE001
                pass

    def _slow_loop(self):
        while True:
            try:
                r = find_rclone(self.cfg.get("rclone_path", ""))
                if r and not self._rc_ver:
                    c, o, _e = run_rclone(r, ["version"], 30)
                    m = re.search(r"v\d+\.\d+", o or "") if c == 0 else None
                    self._rc_ver = m.group(0) if m else "?"
                elif not r:
                    self._rc_ver = None
                if self.pk_ok and time.time() - self._pk_acc.get("ts", 0) > 1800:
                    self._read_account()
            except Exception:               # noqa: BLE001
                pass
            time.sleep(30)

    def _read_account(self):
        """Email, VIP (hạn dùng), dung lượng My PikPak - cho thẻ PikPak ở bảng đèn."""
        cfg = json.loads(json.dumps(self.cfg))
        acc = {"ts": time.time()}
        if cfg.get("pikpak_user") and cfg.get("pikpak_pass"):
            try:
                api = pikpak_api(cfg)
                try:
                    v = (api.call("GET", "/drive/v1/privilege/vip") or {}).get("data") or {}
                    ty = str(v.get("type") or "").lower()
                    if ty:
                        acc["vip"] = ty != "novip" and str(v.get("status") or "ok").lower() in (
                            "ok", "valid", "active", "normal")
                        acc["expire"] = str(v.get("expire") or "")[:10]
                except Exception:           # noqa: BLE001
                    pass
                try:
                    q = (api.call("GET", "/drive/v1/about") or {}).get("quota") or {}
                    acc["total"], acc["used"] = int(q.get("limit") or 0), int(q.get("usage") or 0)
                except Exception:           # noqa: BLE001
                    pass
            except Exception:               # noqa: BLE001
                pass
        r = find_rclone(cfg.get("rclone_path", ""))
        if not acc.get("total") and r:
            _c, o3, _e = run_rclone(r, ["about", f"{cfg.get('pikpak_remote', 'pikpak') or 'pikpak'}:", "--json"], 60)
            try:
                j = json.loads(o3)
                acc["total"], acc["used"] = int(j.get("total") or 0), int(j.get("used") or 0)
            except (ValueError, TypeError):
                pass
        self._pk_acc = acc

    # ------------------------------------------------------------ bảng đèn trạng thái
    def _err_reports(self):
        d = DATA_DIR / "BaoLoi"
        return sorted(d.glob("BaoLoi_*.txt")) if d.is_dir() else []

    def leds(self):
        L, issues = {}, []
        if self.busy():
            done, n = self._batch
            sp = re.search(r"[\d.,]+\s*[KMG]i?B/s", self.energy["dl"][1] or "")
            txt = (f"{min(done + 1, n)}/{n} · " if n else "") + f"{self._dl_pct}%" + (
                f" · {sp.group(0).replace('.', ',')}" if sp else "")
            L["dl"] = ("run", txt if self._dl_pct or sp else self.status[:70])
        elif self.task_msg:
            L["dl"] = ("run", self.task_msg)
        else:
            L["dl"] = ("off", "Rảnh")
        user = self.cfg.get("pikpak_user") or ""
        if self.rclone_dl is not None:
            L["pk"] = ("run", f"Đang tải rclone.exe... {self.rclone_dl}%")
        elif self.pk_ok is True:
            head = "Đã kết nối"
            acc = self._pk_acc
            if "vip" in acc:
                ex = acc.get("expire", "")
                try:
                    ex = dt.datetime.strptime(ex, "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    pass
                head += (" · VIP" + (f" (hạn {ex})" if ex else "")) if acc["vip"] else " · không VIP"
            rest = [x for x in (user, (f"Đã dùng {human_size(acc['used'])} / {human_size(acc['total'])}"
                                       if acc.get("total") else "")) if x]
            L["pk"] = ("ok", "\n".join([head] + rest))
        elif self.pk_ok is False or "chưa" in self.pk_text:
            L["pk"] = ("err", "Chưa kết nối" + (f" · {user}" if user else ""))
            issues.append(("pk", "PikPak chưa kết nối: " + self.pk_text))
        else:
            L["pk"] = ("run", "Đang kết nối..." + (f"\n{user}" if user else ""))
        if not find_rclone(self.cfg.get("rclone_path", "")):
            L["rc"] = ("err", "Chưa có rclone.exe" if self.rclone_dl is None else f"Đang tải... {self.rclone_dl}%")
            issues.append(("rc", "Chưa có rclone.exe - bấm Tải ở thẻ rclone"))
        else:
            L["rc"] = ("ok", f"{self._rc_ver} sẵn sàng" if self._rc_ver else "sẵn sàng")
        if self.cfg.get("auto_scan") and self.next_auto_ts:
            L["auto"] = ("ok", f"Bật · lần tới {dt.datetime.fromtimestamp(self.next_auto_ts):%H:%M}")
        else:
            L["auto"] = ("off", "Đang tắt")
        bk = self.cfg.get("last_backup") or ""
        if not self.cfg.get("backup_on", True):
            L["bk"] = ("off", "Đã tắt")
        elif self._backup_pending:
            L["bk"] = ("run", "Đang sao lưu...")
        elif self.bk_error:
            L["bk"] = ("err", "Sao lưu lỗi")
            issues.append(("bk", "Sao lưu lên PikPak lỗi: " + self.bk_error[:120]))
        elif not bk:
            L["bk"] = ("run", "Chưa đồng bộ")
        else:
            try:
                h = int((dt.datetime.now() - dt.datetime.strptime(bk, "%H:%M %d/%m/%Y")).total_seconds() // 3600)
            except ValueError:
                h = 0
            today = bk[6:11] == f"{dt.date.today():%d/%m}"
            L["bk"] = ("run", f"Chưa đồng bộ ({h} giờ)") if h >= 24 else \
                ("ok", f"Đã đồng bộ {bk[:5] if today else bk[:11]}")
        n = len(self._err_reports())
        if n:
            L["err"] = ("err", f"{n} lỗi · bấm Xem")
            issues.append(("err", f"{n} báo cáo lỗi - bấm Xem ở thẻ Lỗi"))
        else:
            L["err"] = ("off", "Không có lỗi")
        for p_ in self._health_probs:
            if not any(k in p_ for k in ("rclone", "PikPak")):
                issues.append(("hdd", p_))
        bad = [f.get("name") or f.get("url", "") for f in self.cfg["folders"]
               if f.get("enabled", True) and f.get("last_error")]
        if bad:
            issues.append(("folders", f"{len(bad)} thư mục phim quét lỗi: " + ", ".join(bad[:3])))
        return L, issues

    # ------------------------------------------------------------ trạng thái gửi cho giao diện
    def state(self, rows_ver=-1, log_after=0, hist_ver=-1, folders_ver=-1, fp_ver=-1, toast_after=0):
        with self.lock:
            on = [f for f in self.cfg["folders"] if f.get("enabled", True)]
            dl = sum(1 for h in self.history.values() if h.get("status") in WATCH_STATUSES)
            L, issues = self.leds()
            log_after = int(log_after or 0)
            st = {
                "version": V_SHORT, "app": APP_NAME, "machine": MACHINE, "busy": self.busy(), "status": self.status,
                "stats": {"folders": f"{len(on)}/{len(self.cfg['folders'])}", "new": self._new_count, "dl": dl,
                          "owned": len(self.owned)},
                "energy": self.energy, "leds": {k: list(v) for k, v in L.items()},
                "issues": [{"k": k, "t": t} for k, t in issues],
                "auto": {"on": bool(self.cfg.get("auto_scan")), "interval": int(self.cfg.get("auto_interval", 60)),
                         "next": (f"{dt.datetime.fromtimestamp(self.next_auto_ts):%H:%M}"
                                  if self.next_auto_ts else "")},
                "summary": self.last_summary, "lib": len(self.owned),
                "rows_ver": self.rows_ver, "hist_ver": self.hist_ver, "folders_ver": self.folders_ver,
                "fp_ver": self.fp_ver,
                "log": self.log_lines[max(0, len(self.log_lines) - (self.log_seq - log_after)):]
                if self.log_seq > log_after else [],
                "log_seq": self.log_seq,
                "unreviewed": sum(1 for f in on if not f.get("reviewed")),
                "folder_err": sum(1 for f in on if f.get("last_error")),
                "admin": {"unlocked": self.admin_unlocked(), "has_pw": bool(self.cfg.get("admin_hash"))},
                "update": {k: v for k, v in self.update_info.items() if k != "url"},
                "toasts": [t for t in self.toasts if t["t"] > float(toast_after or 0)],
                "new_machine": self.new_machine,
            }
            if rows_ver != self.rows_ver:
                st["rows"] = [self.rows[c] for c in self.row_order if c in self.rows]
            if hist_ver != self.hist_ver:
                st["history"] = self._history_rows()
            if folders_ver != self.folders_ver:
                st["folders"] = self.folder_cards()
            if fp_ver != self.fp_ver:
                st["fp"] = self.fp_view()
            return st

    def _history_rows(self):
        recs = sorted(self.history.items(), key=lambda kv: -float(kv[1].get("ts", 0) or 0))
        out = []
        for c, h in recs:
            st = h.get("status", "")
            tag = "done" if st == STATUS_DONE else "err" if (st in RETRY_STATUSES or st.startswith("Lỗi")) else \
                "dl" if st in WATCH_STATUSES else "skip"
            out.append({"code": c, "name": h.get("name", ""), "folder": h.get("folder") or h.get("movie", ""),
                        "status": self._status_text(st), "raw": st, "tag": tag, "when": h.get("sent_at", ""),
                        "ts": float(h.get("ts", 0) or 0), "size": human_size(h.get("size")),
                        "pikpak": self._upload_text(h), "up": h.get("upload", ""),
                        "error": (h.get("error") or "")[:300], "path": h.get("path") or ""})
        return out

    # ------------------------------------------------------------ THƯ MỤC PHIM
    def _folder_status(self, f):
        if not f.get("enabled", True):
            return "Tạm bỏ qua khi quét", "skip"
        if f.get("last_error"):
            return "⚠ Lỗi lần quét trước: " + str(f["last_error"])[:90], "err"
        if not f.get("reviewed"):
            return "◔ Chưa duyệt — bấm \"Quét file\" để chọn những file đã có", "dl"
        when = ""
        if f.get("last_scan"):
            when = " · quét " + dt.datetime.fromtimestamp(float(f["last_scan"])).strftime("%H:%M %d/%m")
        total, owned = int(f.get("total", 0) or 0), int(f.get("owned", 0) or 0)
        new = max(0, total - owned)
        if new:
            return f"● {new} file mới chưa có · đã có {owned}/{total}{when}", "new"
        return f"✔ Đã có đủ {owned}/{total} file{when}", "done"

    def folder_cards(self):
        out = []
        sd = int(self.cfg.get("stale_days", 7) or 0)
        for i, f in enumerate(self.cfg["folders"]):
            st, tag = self._folder_status(f)
            gaps = f.get("gaps") or []
            show_gaps = bool(gaps and f.get("enabled", True) and "|".join(gaps) != f.get("gap_ack"))
            stale = ""
            if sd and f.get("latest_up") and f.get("enabled", True) and f.get("reviewed"):
                try:
                    lu = dt.date.fromisoformat(f["latest_up"])
                    days = (dt.date.today() - lu).days
                    if days >= sd:
                        stale = (f"⏳ {days} ngày chưa có tập mới (mới nhất up {lu:%d/%m/%Y}) - bên up có chuyển "
                                 "sang thư mục khác không?")
                except ValueError:
                    pass
            sm = f.get("sub_movie", True)
            out.append({"i": i, "id": fid(f), "name": f.get("name") or "(chưa có tên)", "on": f.get("enabled", True),
                        "url": f.get("url", ""), "link": source_link(self.cfg, f) or f.get("url", ""),
                        "src_label": f.get("src_label", ""), "note": one_line(f.get("note", "")),
                        "pk": (f["pikpak_dir"] + ("/<Tên phim>" if sm else "")) if f.get("pikpak_dir") else "",
                        "hdd": (from_portable(f["local_dir"]) + ("\\<Tên phim>" if sm else "")) if f.get("local_dir") else "",
                        "subs": [{"path": d.get("path"), "url": folder_link(d.get("code"))}
                                 for d in (f.get("subs") or [])[:80]], "nsubs": len(f.get("subs") or []),
                        "status": st, "tag": tag, "gaps": gaps if show_gaps else [], "stale": stale,
                        "reviewed": bool(f.get("reviewed"))})
        return out

    def folder_get(self, i):
        """Dữ liệu cho hộp Thêm / Sửa thư mục phim (i = -1: thêm mới)."""
        old = dict(self.cfg["folders"][i]) if i is not None and 0 <= i < len(self.cfg["folders"]) else {}
        return {"i": i if old else -1, "name": old.get("name", ""),
                "url": resolve_src(self.cfg, old.get("url", "")) or old.get("url", "") if old else "",
                "note": old.get("note", ""), "src_label": old.get("src_label", ""),
                "local_dir": from_portable(old.get("local_dir", "")) if old else
                from_portable(self.cfg.get("library_root", "") or r"D:\DOWNLOAD HH3D"),
                "pikpak_dir": old.get("pikpak_dir", "") if old else (self.cfg.get("pikpak_root", "") or "My Pack/2026"),
                "sub_movie": old.get("sub_movie", False), "split": old.get("split", "folder"),
                "include": old.get("include", ""), "exclude": old.get("exclude", ""),
                "enabled": old.get("enabled", True), "link": source_link(self.cfg, old) if old else "",
                "splits": SPLIT_CHOICES}

    def folder_save(self, i, d):
        """Lưu hộp Thêm / Sửa. Trả về chuỗi lỗi (rỗng = OK)."""
        with self.lock:
            src = clean_src(self.cfg, d.get("url", ""))
            if not src or not is_share(src):
                return ("Nguồn phải là thư mục trong link chia sẻ PikPak - bấm \"Chọn trong link chia sẻ...\" "
                        "(hoặc dán link https://mypikpak.com/s/...).")
            hdd = (d.get("local_dir") or "").strip()
            pk = pikpak_join(d.get("pikpak_dir") or "")
            if not pk:
                return "Chọn thư mục My PikPak để Save vào (Đích 1, bắt buộc)."
            if not hdd:
                return "Chọn thư mục lưu trên HDD (Đích 2, bắt buộc)."
            i = int(i) if i is not None and int(i) >= 0 else None
            key = src_key(self.cfg, src)
            for j, f in enumerate(self.cfg["folders"]):
                if j != i and src_key(self.cfg, f.get("url", "")) == key:
                    return f"Thư mục này đã có trong danh sách (dòng {j + 1})."
            old = self.cfg["folders"][i] if i is not None else {}
            same = old and src_key(self.cfg, old.get("url", "")) == key
            rec = dict(old) if same else {"id": old.get("id") or new_folder_id()}
            split = d.get("split") if d.get("split") in SPLIT_CHOICES else "folder"
            rec.update({"name": (d.get("name") or "").strip(), "url": src, "note": (d.get("note") or "").strip(),
                        "include": (d.get("include") or "").strip(), "exclude": (d.get("exclude") or "").strip(),
                        "local_dir": to_portable(hdd), "pikpak_dir": pk, "sub_movie": bool(d.get("sub_movie")),
                        "split": split, "enabled": bool(d.get("enabled", True)), "dest_rev": 3,
                        "src_label": (d.get("src_label") or "").strip()})
            self.cfg["library_root"] = to_portable(hdd)
            self.cfg["pikpak_root"] = pk
            if i is None:
                self.cfg["folders"].append(rec)
            else:
                self.cfg["folders"][i] = rec
            self.save_config()
            self.folders_ver += 1
        self.log(f"✎ Đã lưu thư mục phim: {rec['name'] or src}")
        return ""

    def folder_toggle(self, i, on=None):
        with self.lock:
            f = self.cfg["folders"][i]
            f["enabled"] = (not f.get("enabled", True)) if on is None else bool(on)
            self.save_config()
            self.folders_ver += 1

    def folder_check_all(self, on):
        with self.lock:
            for f in self.cfg["folders"]:
                f["enabled"] = bool(on)
            self.save_config()
            self.folders_ver += 1

    def folder_move(self, i, step):
        with self.lock:
            fl = self.cfg["folders"]
            j = i + step
            if 0 <= j < len(fl):
                fl[i], fl[j] = fl[j], fl[i]
                if self.fp and self.fp["index"] in (i, j):
                    self.fp["index"] = j if self.fp["index"] == i else i
                self.save_config()
                self.folders_ver += 1

    def folder_delete(self, i):
        with self.lock:
            f = self.cfg["folders"].pop(i)
            if self.fp:
                if self.fp["index"] == i:
                    self.fp = None
                elif self.fp["index"] > i:
                    self.fp["index"] -= 1
                self.fp_ver += 1
            self.save_config()
            self.folders_ver += 1
        self.log(f"✕ Đã xóa thư mục phim: {f.get('name') or f.get('url')}")

    def folder_ack_gaps(self, i):
        with self.lock:
            f = self.cfg["folders"][i]
            f["gap_ack"] = "|".join(f.get("gaps") or [])
            self.save_config()
            self.folders_ver += 1

    def folder_bulk(self, text):
        added = 0
        with self.lock:
            for line in (text or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                name, url = ("", line)
                if "|" in line:
                    name, url = [x.strip() for x in line.split("|", 1)]
                src = clean_src(self.cfg, url)
                if not src:
                    continue
                key = src_key(self.cfg, src)
                if any(src_key(self.cfg, f.get("url", "")) == key for f in self.cfg["folders"]):
                    continue
                self.cfg["folders"].append({"id": new_folder_id(), "name": name.strip(), "url": src, "enabled": True,
                                            "include": "", "exclude": "", "note": "", "local_dir": ""})
                added += 1
            self.save_config()
            self.folders_ver += 1
        return added

    def folder_export(self, path):
        save_json(path, {"app": APP_NAME, "exported": dt.datetime.now().isoformat(timespec="seconds"),
                         "folders": self.cfg["folders"]})
        return len(self.cfg["folders"])

    def folder_import(self, path):
        data = load_json(path, {})
        items = data.get("folders") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return None
        added = 0
        with self.lock:
            have = {src_key(self.cfg, f.get("url", "")) for f in self.cfg["folders"]}
            for f in items:
                if not isinstance(f, dict) or not f.get("url"):
                    continue
                code = src_key(self.cfg, f["url"])
                if code not in have:
                    f = dict(f)
                    fid(f)
                    self.cfg["folders"].append(f)
                    have.add(code)
                    added += 1
            self.save_config()
            self.folders_ver += 1
        return [added, len(items) - added]

    # ----- khung file của 1 thư mục
    def fp_scan(self, i):
        if core.requests is None:
            return "Thiếu thư viện 'requests'."
        f = self.cfg["folders"][i]
        code = fid(f)
        if not resolve_src(self.cfg, f.get("url", "")):
            return "Nguồn không hợp lệ - bấm Sửa để chọn lại thư mục trong link chia sẻ."
        token = object()
        with self.lock:
            self.fp = {"index": i, "code": code, "fname": f.get("name") or code, "rows": {}, "order": [],
                       "loading": True, "token": token, "info": "Đang quét tất cả file (cả thư mục con)...",
                       "error": ""}
            self.fp_ver += 1
        cfg = json.loads(json.dumps(self.cfg))

        def job():
            try:
                fs = make_source(cfg, f, self.log)
                files = list(fs.walk())
                real = getattr(fs, "title", None) or (os.path.basename(os.path.normpath(fs.path))
                                                      if isinstance(fs, LocalSource) else "")
                self.note_listing(files)
                exts = {e.lower() if e.startswith(".") else "." + e.lower()
                        for e in cfg.get("extensions", "").split() if e.strip()}
                inc, exc = f.get("include", ""), f.get("exclude", "")
                out, skipped = [], {}
                for it in files:
                    name, fc = it.get("name") or "", it.get("linkcode")
                    if not fc or not name:
                        continue
                    if exts and os.path.splitext(name)[1].lower() not in exts:
                        e = os.path.splitext(name)[1].lower() or "(không đuôi)"
                        skipped[e] = skipped.get(e, 0) + 1
                        continue
                    if (inc or exc) and not match_keywords(name, inc, exc):
                        skipped["(lọc từ khóa)"] = skipped.get("(lọc từ khóa)", 0) + 1
                        continue
                    out.append((fc, name, it.get("size"), fs.item_date(it)))
                okc = {o[0] for o in out}
                gaps = find_gaps([(it.get("_sub", ""), it.get("name") or "") for it in files
                                  if it.get("linkcode") in okc])
                dates = [o[3] for o in out if o[3]]
                for g_ in gaps:
                    self.log(f"[{f.get('name') or code}] ⚠ Có thể thiếu tập: {g_}")
                subs = ", ".join(f"{k or '(gốc)'}: {v}" for k, v in fs.subs.items())
                self.log(f"[{f.get('name') or code}] Quét file: {len(files)} file · " + subs)
                for sub, err in fs.errors:
                    self.log(f"[{f.get('name') or code}] ⚠ Thư mục con \"{sub}\" đọc lỗi: {err}")
                with self.lock:
                    fc_ = next((x for x in self.cfg["folders"] if fid(x) == code), None)
                    if fc_ is not None:
                        fc_["gaps"] = gaps
                        if dates:
                            fc_["latest_up"] = max(dates).isoformat()
                        fc_["subs"] = list(fs.subdirs)
                        if not fc_.get("name") and real:
                            fc_["name"] = real
                    self._fp_loaded(token, code, real, out, skipped, list(fs.errors))
            except Exception as e:          # noqa: BLE001
                with self.lock:
                    if self.fp and self.fp.get("token") is token:
                        self.fp.update(loading=False, error=str(e)[:300], info="⚠ Lỗi đọc thư mục: " + str(e)[:200])
                        self.fp_ver += 1
                        idx = self._folder_index(code)
                        if idx is not None:
                            self.cfg["folders"][idx]["last_error"] = str(e)[:120]
                            save_json(CONFIG_FILE, self.cfg)
                            self.folders_ver += 1
        threading.Thread(target=job, daemon=True).start()
        return ""

    def _folder_index(self, code):
        return next((j for j, x in enumerate(self.cfg["folders"]) if fid(x) == code), None)

    def _fp_loaded(self, token, code, real, files, skipped, errors):
        if not self.fp or self.fp.get("token") is not token:
            return
        if real and self.fp["fname"] == code:
            self.fp["fname"] = real
        idx = self.owned_index()
        rows, seen = {}, set()
        for fc, name, size, d in files:
            if fc in seen:
                continue
            seen.add(fc)
            own = self.is_owned(idx, fc, code, name)
            h = self.history.get(fc, {})
            rows[fc] = {"name": name, "size": size, "date": d.strftime("%d/%m/%Y") if d else "", "owned": own,
                        "orig": own, "hist": h.get("status", ""), "sub": self.sub_of.get(fc, "")}
        order = sorted(rows, key=lambda c: (natural_key(rows[c]["sub"]), natural_key(rows[c]["name"])))
        n_own = sum(1 for r in rows.values() if r["owned"])
        n_sub = len({r["sub"] for r in rows.values() if r["sub"]})
        info = (f"{len(order)} file" + (f" (trong {n_sub} thư mục con)" if n_sub else "")
                + f" · {n_own} đã có · {len(order) - n_own} chưa có."
                + (f"   Bỏ qua {sum(skipped.values())} file: " + ", ".join(f"{k} ×{v}" for k, v in skipped.items())
                   if skipped else "   Tích chọn file → \"Thêm vào Danh sách đã có\" → \"Lưu\".")
                + (f"   ⚠ {len(errors)} thư mục con đọc lỗi (xem nhật ký)" if errors else ""))
        self.fp.update(rows=rows, order=order, loading=False, info=info)
        i = self._folder_index(code)
        if i is not None:
            f = self.cfg["folders"][i]
            f.update(total=len(order), owned=n_own, last_scan=time.time(), last_error="")
            save_json(CONFIG_FILE, self.cfg)
            self.folders_ver += 1
        self.fp_ver += 1

    def _fp_label(self, r):
        if r["owned"] and not r["orig"]:
            return "✔ Đã có (chưa lưu)", "done"
        if not r["owned"] and r["orig"]:
            return "↺ Sẽ bỏ khỏi DS (chưa lưu)", "err"
        if r["owned"]:
            return "✔ Đã có", "done"
        if r["hist"] in WATCH_STATUSES:
            return "⬇ Đang tải", "dl"
        return "● Chưa có", "new"

    def fp_changes(self):
        return sum(1 for r in self.fp["rows"].values() if r["owned"] != r["orig"]) if self.fp else 0

    def fp_view(self):
        fp = self.fp
        if not fp:
            return None
        rows = []
        for c in fp["order"]:
            r = fp["rows"][c]
            t, tag = self._fp_label(r)
            rows.append({"code": c, "name": sub_label(r["sub"], r["name"]), "date": r["date"],
                         "size": human_size(r["size"]), "status": t, "tag": tag, "owned": r["owned"]})
        i = fp["index"]
        reviewed = bool(self.cfg["folders"][i].get("reviewed")) if i < len(self.cfg["folders"]) else True
        return {"index": i, "code": fp["code"], "fname": fp["fname"], "loading": fp["loading"], "info": fp["info"],
                "error": fp["error"], "rows": rows, "changes": self.fp_changes(), "reviewed": reviewed,
                "own": sum(1 for r in fp["rows"].values() if r["owned"]), "total": len(fp["rows"])}

    def fp_mark(self, codes, on):
        with self.lock:
            if not self.fp:
                return
            for c in codes:
                if c in self.fp["rows"]:
                    self.fp["rows"][c]["owned"] = bool(on)
            self.fp_ver += 1

    def fp_save(self):
        with self.lock:
            fp = self.fp
            if not fp or fp.get("loading"):
                return ""
            add = rem = 0
            for c, r in fp["rows"].items():
                if r["owned"] and not r["orig"]:
                    self.add_owned(c, fp["code"], fp["fname"], r["name"], r["size"], "manual")
                    add += 1
                elif not r["owned"] and r["orig"]:
                    self.remove_owned(c, fp["code"], r["name"])
                    rem += 1
                r["orig"] = r["owned"]
            self.save_owned()
            own = sum(1 for r in fp["rows"].values() if r["owned"])
            i = fp["index"]
            if i < len(self.cfg["folders"]):
                self.cfg["folders"][i].update(total=len(fp["rows"]), owned=own, last_scan=time.time(), reviewed=True)
                self.save_config()
            fp["info"] = f"{len(fp['rows'])} file · {own} đã có · {len(fp['rows']) - own} chưa có.   ✔ Đã lưu."
            self.fp_ver += 1
            self.folders_ver += 1
        msg = (f"[{fp['fname']}] Đã lưu: +{add} file vào Danh sách đã có" + (f", bỏ {rem} file" if rem else "")
               + f". Thư mục đã duyệt: {own}/{len(fp['rows'])} file đã có.")
        self.log(msg)
        return msg

    def fp_close(self):
        with self.lock:
            self.fp = None
            self.fp_ver += 1

    # ----- chọn thư mục trong link chia sẻ / My PikPak
    def share_open(self, cur=""):
        root = (self.cfg.get("share_root") or "").strip()
        if not is_share(root):
            root = cur if is_share(cur) else ""
        if not is_share(root):
            return {"error": "Chưa có link chia sẻ gốc - nhập ở Cài đặt → Chung → Link chia sẻ gốc."}
        if not (self.cfg.get("pikpak_user") and self.cfg.get("pikpak_pass")):
            return {"error": "Cần đăng nhập tài khoản PikPak để đọc link chia sẻ (Cài đặt → My PikPak → "
                             "Đổi tài khoản PikPak)."}
        sid, parent, pwd = share_parts(root)
        return {"sid": sid, "root": parent or "", "pwd": pwd or ""}

    def share_ls(self, sid, pwd, folder, token, root):
        try:
            api = pikpak_api(self.cfg, self.log)
            if not token:
                files, token = api.share_list(sid, pwd, root or None)
                if (folder or "") != (root or ""):
                    files, _t = api.share_list(sid, pwd, folder or None, token)
            else:
                files, _t = api.share_list(sid, pwd, folder or None, token)
        except Exception as e:              # noqa: BLE001
            return {"error": str(e)[:300]}
        dirs = sorted(({"id": f.get("id"), "name": f.get("name") or "?"} for f in files
                       if "folder" in str(f.get("kind"))), key=lambda f: natural_key(f["name"]))
        fl = []
        for f in files:
            if "folder" in str(f.get("kind")):
                continue
            try:
                sz = human_size(int(f.get("size") or 0))
            except (TypeError, ValueError):
                sz = ""
            fl.append({"name": f.get("name") or "?", "size": sz})
        fl.sort(key=lambda f: natural_key(f["name"]))
        return {"token": token, "dirs": dirs, "files": fl}

    def pk_ls(self, path):
        r = find_rclone(self.cfg.get("rclone_path", ""))
        if not r:
            return {"error": "Chưa có rclone.exe."}
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"
        path = pikpak_join(path or "")
        code, out, err = run_rclone(r, ["lsjson", f"{remote}:{path}", "--dirs-only"], 60)
        if code != 0:
            if path:
                return {"path": path, "dirs": [], "info": "Thư mục chưa có trên PikPak, sẽ được tạo khi lưu."}
            return {"error": (err or out).strip()[-200:]}
        try:
            dirs = sorted((d.get("Name", "") for d in json.loads(out or "[]")), key=natural_key)
        except ValueError:
            dirs = []
        return {"path": path, "dirs": dirs}

    def pk_mkdir(self, path, name):
        r = find_rclone(self.cfg.get("rclone_path", ""))
        if not r or not (name or "").strip():
            return "Chưa có rclone.exe." if not r else ""
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"
        code, out, err = run_rclone(r, ["mkdir", f"{remote}:{pikpak_join(path or '', name)}"], 60)
        return "" if code == 0 else (err or out).strip()[-200:]

    # ------------------------------------------------------------ LỊCH SỬ
    def hist_mark_done(self, codes):
        with self.lock:
            for c in codes:
                h = self.history.get(c)
                if h:
                    h["status"], h["done_ts"] = STATUS_DONE, time.time()
                    self.add_owned(c, h.get("folder_code", ""), h.get("folder", ""), h.get("name", ""),
                                   h.get("size"), "manual")
            self.save_owned()
            self.save_history()

    def hist_delete(self, codes):
        with self.lock:
            for c in codes:
                self.history.pop(c, None)
            self.save_history()

    def hist_clear(self):
        with self.lock:
            self.history = {}
            self.save_history()

    def hist_upload(self, codes):
        if not find_rclone(self.cfg.get("rclone_path", "")):
            return "Chưa có rclone.exe."
        n = 0
        with self.lock:
            for c in codes:
                n += bool(self.enqueue_upload(c, force=True))
            self.save_history()
        return (f"Đã thêm {n} file vào hàng chờ lưu My PikPak." if n else
                "Không có file nào lưu được (chỉ lưu file đã tải xong và còn trên máy).")

    def open_path(self, path):
        if path and os.path.exists(path):
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                open_target(os.path.dirname(path))
            return ""
        return "Chưa có đường dẫn file (tập chưa tải xong hoặc đã bị chuyển/xóa)."

    def open_source(self, code):
        m = self.item_meta.get(code) or (self.history.get(code) or {}).get("src") or {}
        p = (self.history.get(code) or {}).get("path")
        if p and os.path.exists(p):
            return self.open_path(p)
        if m.get("path") and os.path.exists(m["path"]):
            return self.open_path(m["path"])
        if m.get("share"):
            open_target(f"https://mypikpak.com/s/{m['share']}")
        return ""

    def latest_report(self):
        files = self._err_reports()
        return files[-1] if files else None

    def clear_reports(self):
        for f_ in self._err_reports():
            try:
                f_.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------ CÀI ĐẶT
    SETTING_KEYS = {"share_root": str, "iphone_on": bool, "iphone_dir": str, "bwlimit": str, "delay": int,
                    "extensions": str, "health_check": bool, "stale_days": int, "auto_scan": bool, "auto_interval": int,
                    "start_with_windows": bool, "startup_scan": bool, "tray_on_close": bool, "notify": bool,
                    "admin_lock_min": int, "update_check": bool, "update_repo": str, "backup_on": bool,
                    "pikpak_root": str}

    def get_settings(self):
        c = self.cfg
        out = {k: c.get(k, core.DEFAULT_CONFIG.get(k, "")) for k in self.SETTING_KEYS}
        out.update(iphone_dir=resolve_iphone_dir(c.get("iphone_dir")), delay=int(c.get("delay", 2) or 0),
                   stale_days=int(c.get("stale_days", 7) or 0), auto_interval=int(c.get("auto_interval", 60) or 60),
                   admin_lock_min=int(c.get("admin_lock_min", 10) or 0), tray_on_close=c.get("tray_on_close", True),
                   notify=c.get("notify", True), iphone_on=c.get("iphone_on", True), health_check=c.get("health_check", True),
                   startup_scan=c.get("startup_scan", True), backup_on=c.get("backup_on", True),
                   update_check=c.get("update_check", True), bwlimit=str(c.get("bwlimit", "") or ""))
        profs = []
        for name, p in sorted(c.get("profiles", {}).items(), key=lambda kv: -kv[1].get("updated", 0)):
            profs.append({"name": name, "me": name == MACHINE, "paths": f"COPY_TO_IPHONE: {p.get('iphone_dir') or '-'}",
                          "when": dt.datetime.fromtimestamp(p.get("updated", 0)).strftime("%H:%M %d/%m/%Y")
                          if p.get("updated") else ""})
        out.update(user=c.get("pikpak_user", ""), machine=MACHINE, profiles=profs, data=str(DATA_DIR), base=str(BASE),
                   last_backup=c.get("last_backup", ""), backup_remote=self._backup_remote(), intervals=INTERVAL_CHOICES,
                   version=APP_NAME, tray_ok=bool(core.TRAY_OK), rclone=find_rclone(c.get("rclone_path", "")) or "",
                   db=self.db_info())
        return out

    def save_settings(self, d):
        with self.lock:
            for k, typ in self.SETTING_KEYS.items():
                if k not in d:
                    continue
                v = d[k]
                try:
                    if typ is bool:
                        v = bool(v)
                    elif typ is int:
                        v = max(0, int(v))
                    else:
                        v = str(v or "").strip()
                except (TypeError, ValueError):
                    continue
                if k == "iphone_dir":
                    v = resolve_iphone_dir(v)
                elif k == "bwlimit":
                    v = re.sub(r"\s+", "", v)
                elif k == "pikpak_root":
                    v = pikpak_join(v)
                elif k == "auto_interval":
                    v = max(5, v or 60)
                elif k == "start_with_windows":
                    try:
                        set_startup(v)
                    except OSError as e:
                        self.log(f"Không đặt được khởi động cùng Windows: {e}")
                        continue
                self.cfg[k] = v
            if self.cfg.get("auto_scan") and not self.next_auto_ts:
                self.next_auto_ts = time.time() + int(self.cfg.get("auto_interval", 60)) * 60
            elif not self.cfg.get("auto_scan"):
                self.next_auto_ts = None
            self.save_config()
            self.folders_ver += 1
        self.log("✔ Đã lưu cài đặt cho máy " + MACHINE)
        if getattr(self, "on_auto_changed", None):
            self.on_auto_changed()
        return ""

    def copy_profile(self, name):
        with self.lock:
            if name == MACHINE or name not in self.cfg.get("profiles", {}):
                return "Chọn 1 máy KHÁC trong danh sách để chép thiết lập."
            self._apply_profile(self.cfg["profiles"][name])
            self._fix_missing_paths()
            self.save_config()
        return ""

    def delete_profile(self, name):
        with self.lock:
            if name == MACHINE:
                return "Không xóa được hồ sơ của máy đang dùng."
            self.cfg.get("profiles", {}).pop(name, None)
            self.save_config()
        return ""

    # ----- PikPak / rclone
    def pk_login(self, user, pw, remember=True):
        r = find_rclone(self.cfg.get("rclone_path", ""))
        if not r:
            return "Chưa có rclone.exe - tải ở thẻ rclone trước."
        user = (user or "").strip()
        if not user or not pw:
            return "Nhập đủ email và mật khẩu."
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"
        run_rclone(r, ["config", "delete", remote], 20)
        code, out, err = run_rclone(r, ["config", "create", remote, "pikpak", "user", user, "pass", pw, "--obscure",
                                        "--non-interactive"], 60)
        if code != 0:
            return "Không tạo được cấu hình: " + (err or out).strip()[-300:]
        code, out, err = run_rclone(r, ["lsd", f"{remote}:"], 60)
        if code != 0:
            return "Đăng nhập lỗi: " + (err or out).strip()[-300:]
        with self.lock:
            self.cfg["pikpak_user"] = user if remember else ""
            self.cfg["pikpak_pass"] = enc_secret(pw) if remember else ""
            self.save_config()
        PK = core.PK_SESSION_FILE
        try:
            if PK.is_file():
                PK.unlink()                 # phiên API cũ của tài khoản khác
        except OSError:
            pass
        self._pk_acc = {}
        self._set_pk_status("☁ PikPak: ✔ đã kết nối (" + user + ")", True)
        self.log(f"☁ Đăng nhập PikPak thành công: {user}")
        return ""

    def pk_detail(self):
        cfg = json.loads(json.dumps(self.cfg))
        r = find_rclone(cfg.get("rclone_path", ""))
        info = {"checked": f"{dt.datetime.now():%H:%M:%S %d/%m}",
                "user": cfg.get("pikpak_user") or rclone_conf_user_safe(cfg) or "(chưa lưu tài khoản)"}
        if not r:
            info.update(ok=False, state="✘ Chưa có rclone.exe", rclone="chưa có - bấm \"Tải rclone.exe\"", quota="—")
            return info
        remote = cfg.get("pikpak_remote", "pikpak") or "pikpak"
        t0 = time.time()
        code, out, err = run_rclone(r, ["lsd", f"{remote}:"], 60)
        ms = int((time.time() - t0) * 1000)
        info["ok"] = code == 0
        info["state"] = f"✔ Đã kết nối · {ms} ms" if code == 0 else "✘ Lỗi: " + (err or out).strip()[-160:]
        c2, o2, _e = run_rclone(r, ["version"], 30)
        info["rclone"] = (o2.splitlines()[0].strip() if c2 == 0 and o2.strip() else "?") + f"  ·  {r}"
        info["quota"] = "—"
        if code == 0:
            self._set_pk_status("☁ PikPak: ✔ đã kết nối", True)
            self._read_account()
            acc = self._pk_acc
            if acc.get("total"):
                pct = acc["used"] * 100 // acc["total"]
                info["quota"] = (f"{pct}% · đã dùng {human_size(acc['used'])} / {human_size(acc['total'])} · trống "
                                 f"{human_size(acc['total'] - acc['used'])}")
                info["quota_pct"] = pct
            if "vip" in acc:
                info["vip"] = ("VIP" + (f" · hạn {acc['expire']}" if acc.get("expire") else "")) if acc["vip"] \
                    else "Tài khoản thường (không VIP)"
        else:
            self._set_pk_status("☁ PikPak: ⚠ lỗi kết nối - " + (err or out).strip()[-120:], False)
        return info

    def rclone_info(self):
        r = find_rclone(self.cfg.get("rclone_path", ""))
        info = {"checked": f"{dt.datetime.now():%H:%M:%S %d/%m}", "path": r or str(RCLONE_EXE) + "  (chưa có)"}
        if not r:
            info.update(ok=False, state="✘ Chưa có rclone.exe", ver="—", conf="—")
            return info
        t0 = time.time()
        c, o, e = run_rclone(r, ["version"], 30)
        ok = c == 0
        info["ver"] = (o.splitlines()[0].strip() if o.strip() else "?") if ok else ("lỗi: " + (e or o).strip()[:120])
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"
        has = RCLONE_CONF.is_file() and f"[{remote}]" in RCLONE_CONF.read_text(encoding="utf-8", errors="ignore")
        info["conf"] = f"{RCLONE_CONF}  ·  " + (f"✔ có kết nối [{remote}]" if has else
                                               "✘ chưa có kết nối PikPak - đăng nhập ở tab My PikPak")
        info["ok"] = ok and has
        info["state"] = (f"✔ Sẵn sàng · {int((time.time() - t0) * 1000)} ms" if ok and has else
                         "⚠ rclone chạy được nhưng chưa có kết nối PikPak" if ok else "✘ rclone không chạy được")
        return info

    def get_rclone(self, update=False):
        if self.rclone_dl is not None:
            return "Đang tải rclone.exe..."
        if core.requests is None:
            return "Thiếu thư viện 'requests'."
        if update and find_rclone():
            try:
                os.replace(str(RCLONE_EXE), str(RCLONE_EXE) + ".old")
            except OSError:
                pass
        self.rclone_dl = 0

        def job():
            try:
                download_rclone(lambda pct: setattr(self, "rclone_dl", pct))
                self._rc_ver = None
                self.log("✔ Đã tải rclone.exe vào thư mục tool.")
                self.toast("Đã tải rclone.exe.")
                try:
                    Path(str(RCLONE_EXE) + ".old").unlink()
                except OSError:
                    pass
                self.check_pikpak(silent=True)
            except Exception as e:          # noqa: BLE001
                old = Path(str(RCLONE_EXE) + ".old")
                if old.is_file() and not RCLONE_EXE.is_file():
                    try:
                        os.replace(str(old), str(RCLONE_EXE))
                    except OSError:
                        pass
                msg = (f"Không tải được rclone.exe: {e}. Tải tay ở https://rclone.org/downloads/ (Windows 64-bit), "
                       f"giải nén, chép rclone.exe vào {RCLONE_EXE.parent}")
                self.log("⚠ " + msg)
                self.toast(msg, "err")
            finally:
                self.rclone_dl = None
        threading.Thread(target=job, daemon=True).start()
        return ""

    # ----- sao lưu / khôi phục
    def backup_now(self):
        if not find_rclone(self.cfg.get("rclone_path", "")):
            return "Chưa có rclone.exe."
        self.save_config()
        self._backup_pending = True
        self.up_q.put("__backup__")
        return ""

    def backup_to_file(self, path):
        self.save_config()
        make_backup_zip(path)
        return ""

    def restore_preview(self, path):
        import zipfile
        try:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n in BACKUP_FILES]
                info = z.comment.decode("utf-8", "ignore")
        except Exception as e:              # noqa: BLE001
            return {"error": f"Không đọc được file: {e}"}
        if not names:
            return {"error": "File không phải bản sao lưu của tool."}
        if "pikpak.db" in names:
            names = [n for n in names if n not in ("owned.json", "history.json")]
        return {"info": info, "names": names, "path": path}

    def restore_fetch_pikpak(self):
        import tempfile
        r = find_rclone(self.cfg.get("rclone_path", ""))
        if not r:
            return {"error": "Chưa có rclone.exe."}
        tmp = Path(tempfile.gettempdir()) / "PikPakShare_restore.zip"
        code, out, err = run_rclone(r, ["copyto", f"{self._backup_remote()}/PikPakShare_backup_latest.zip", str(tmp)], 300)
        if code != 0 or not tmp.is_file():
            return {"error": "Không tải được bản sao lưu: " + (err or out).strip()[-150:]}
        return self.restore_preview(str(tmp))

    def restore_apply(self, path):
        with self.lock:
            try:
                restore_backup_zip(path)
            except Exception as e:          # noqa: BLE001
                return f"Không khôi phục được: {e}"
            self._no_save = True
        self.restart(["--after-update"])
        return ""

    def export_log(self):
        dest = DATA_DIR / "NhatKy_xuat.txt"
        n = self.db.export_log(str(dest))
        open_target(str(dest))
        return f"Đã xuất {n} dòng nhật ký gần nhất ra {dest.name}."

    def db_info(self):
        try:
            size = human_size(DB_FILE.stat().st_size)
        except OSError:
            size = "?"
        return {"path": str(DB_FILE), "size": size, "owned": self.db.count("owned"),
                "history": self.db.count("history"), "log": self.db.count("log")}

    # ----- COPY_TO_IPHONE bù
    def iphone_preview(self, days=7):
        self.save_config()
        d = resolve_iphone_dir(self.cfg.get("iphone_dir"))
        cut = time.time() - days * 86400
        todo = []
        for h in self.history.values():
            src = h.get("hdd") or h.get("path") or ""
            if h.get("status") != STATUS_DONE or (h.get("done_ts") or 0) < cut or not src or not os.path.isfile(src):
                continue
            dst = os.path.join(d, safe_name(h.get("name") or os.path.basename(src)))
            if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
                continue
            todo.append((src, dst))
        self._iphone_todo = todo
        return {"n": len(todo), "size": human_size(sum(os.path.getsize(a) for a, _b in todo)), "dir": d, "days": days}

    def iphone_run(self):
        todo = list(getattr(self, "_iphone_todo", []) or [])
        if not todo:
            return "Không có tập nào cần copy."
        d = resolve_iphone_dir(self.cfg.get("iphone_dir"))

        def job():
            os.makedirs(d, exist_ok=True)
            ok_n = 0
            for i, (a, b) in enumerate(todo, 1):
                self.task_msg = f"📱 Copy iPhone {i}/{len(todo)}"
                self.q.put(("status", f"📱 Copy vào COPY_TO_IPHONE {i}/{len(todo)}: {os.path.basename(a)}"))
                try:
                    ok, msg = copy_with_progress(a, b, lambda p, sp="", n=os.path.basename(a): self.q.put(
                        ("energy", "dl", p, f"📱 {n}   {sp}")), None, chunk=16 << 20)
                    if ok:
                        ok_n += 1
                        self.log(f"📱 Đã copy vào COPY_TO_IPHONE: {b}")
                    else:
                        self.log(f"⚠ Copy vào COPY_TO_IPHONE lỗi: {os.path.basename(a)}: {msg}")
                except Exception as e:      # noqa: BLE001
                    self.log(f"⚠ Copy vào COPY_TO_IPHONE lỗi: {os.path.basename(a)}: {e}")
            self.task_msg = ""
            self.q.put(("status", f"📱 Xong: đã copy {ok_n}/{len(todo)} tập vào COPY_TO_IPHONE."))
        threading.Thread(target=job, daemon=True).start()
        return ""

    # ----- mật khẩu admin
    def admin_unlocked(self):
        return self._admin_until > 0

    def admin_activity(self):
        self._admin_last = time.time()

    def admin_unlock(self, pw):
        if not self.cfg.get("admin_hash"):
            if len(pw or "") < 4:
                return "Mật khẩu ít nhất 4 ký tự."
            self._admin_set(pw)
            self.log("🔑 Đã tạo mật khẩu admin.")
        elif self._pw_hash(pw or "", self.cfg.get("admin_salt", "")) != self.cfg.get("admin_hash"):
            return "Sai mật khẩu admin."
        self._admin_until = self._admin_last = time.time()
        return ""

    def _admin_set(self, pw):
        with self.lock:
            salt = os.urandom(8).hex()
            self.cfg["admin_salt"], self.cfg["admin_hash"] = salt, self._pw_hash(pw, salt)
            self.save_config()

    def admin_lock(self):
        self._admin_until = 0

    def admin_change(self, old, new):
        if self.cfg.get("admin_hash") and self._pw_hash(old or "", self.cfg.get("admin_salt", "")) != self.cfg["admin_hash"]:
            return "Sai mật khẩu admin hiện tại."
        if len(new or "") < 4:
            return "Mật khẩu mới ít nhất 4 ký tự."
        self._admin_set(new)
        self.log("🔑 Đã đổi mật khẩu admin.")
        return ""

    # ----- cập nhật phần mềm
    def check_update(self, silent=True):
        repo = (self.cfg.get("update_repo") or "").strip()
        if self.update_info.get("busy"):
            return ""
        if not repo:
            self.update_info = {"err": "Chưa đặt nguồn cập nhật (GitHub: tên-tài-khoản/tên-repo)."}
            return self.update_info["err"]
        self.update_info = dict(self.update_info, busy=True, err="")

        def job():
            try:
                tag, notes, url = github_latest(repo)
                newer = ver_tuple(tag) > ver_tuple(APP_VERSION)
                self.update_info = {"tag": tag, "notes": (notes or "").strip()[:1500], "url": url, "newer": newer,
                                    "checked": f"{dt.datetime.now():%H:%M %d/%m}"}
                if newer:
                    self.log(f"⟳ Có bản mới {tag} (đang dùng {V_SHORT}).")
                    if silent:
                        self.notify("Có bản mới " + tag, "Bấm nút Cập nhật trên tool để cài.")
            except Exception as e:          # noqa: BLE001
                self.update_info = {"err": str(e)[:300]}
                self.log(f"Kiểm tra cập nhật: {e}")
        threading.Thread(target=job, daemon=True).start()
        return ""

    def update_apply(self, zip_path=None):
        if self.busy():
            return "Tool đang quét / tải. Đợi xong rồi cập nhật."
        url, tag = self.update_info.get("url"), self.update_info.get("tag", "")
        if not zip_path and not url:
            return "Chưa có bản mới để tải."

        def job():
            try:
                path = zip_path
                if not path:
                    import tempfile
                    path = str(Path(tempfile.gettempdir()) / f"PikPak-Auto-Save_{tag}.zip")
                    self.update_info = dict(self.update_info, progress=0)
                    download_file(url, path, lambda pct, done: self.update_info.__setitem__("progress", pct))
                self.save_config()
                new_ver, pending_exe = stage_update(path)
                self.log(f"⟳ Đã cập nhật lên {new_ver or tag or 'bản mới'} - khởi động lại...")
                with self.lock:
                    self.db.save("history", self.history)
                    self._no_save = True
                self.update_info = dict(self.update_info, restarting=True)
                self._restart_after_update(pending_exe)
            except Exception as e:          # noqa: BLE001
                self.update_info = dict(self.update_info, progress=None, err=f"Cập nhật không thành công: {e}")
                self.toast(f"Cập nhật không thành công: {e}", "err")
        threading.Thread(target=job, daemon=True).start()
        return ""

    def _restart_after_update(self, pending_exe):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if pending_exe:       # bản exe: thay file exe sau khi tool thoát hẳn
            exe = Path(sys.executable)
            bat = BASE / "_capnhat.bat"
            waits = "".join(
                f':w{n}\r\ntasklist /FI "PID eq {pid}" | find " {pid} " >nul && (ping -n 2 127.0.0.1 >nul & goto w{n})\r\n'
                for n, pid in enumerate({os.getpid(), os.getppid()}))
            bat.write_text(
                "@echo off\r\n" + waits + "ping -n 2 127.0.0.1 >nul\r\nset _r=0\r\n"
                f':mv\r\nmove /y "{pending_exe}" "{exe}" >nul 2>nul || (set /a _r+=1 & ping -n 2 127.0.0.1 >nul & '
                'if %_r% lss 15 goto mv)\r\n'
                f'start "" "{exe}" --after-update\r\n'
                'del "%~f0"\r\n', encoding="utf-8")
            subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, cwd=str(BASE), env=clean_env())
            self.quit(force=True)
        else:
            self.restart(["--after-update"])

    def restart(self, extra=()):
        self.save_config()
        restart_self(list(extra))
        self.quit(force=True)

    def quit(self, force=False):
        self.stop_flag.set()
        if self.quit_fn:
            self.quit_fn()
        else:
            os._exit(0)


for _n in Engine.BORROWED:                   # dùng lại nguyên hàm của bản Tk (không đụng tới giao diện)
    setattr(Engine, _n, core.App.__dict__[_n])
del _n


def rclone_conf_user_safe(cfg):
    try:
        return core.rclone_conf_user(cfg.get("pikpak_remote", "pikpak") or "pikpak")
    except Exception:                       # noqa: BLE001
        return ""


def set_clipboard(text):
    """Copy chữ vào clipboard Windows (không cần Tk)."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = (str(text) + "\0").encode("utf-16-le")
    for _ in range(10):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(0x0002, len(data))
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(13, h)
        return True
    finally:
        u32.CloseClipboard()


# ================================================================ cầu nối JS <-> Python (mọi hàm trả về JSON)
class Api:
    def __init__(self, eng, ui):
        self._eng = eng
        self._ui = ui                       # cửa sổ: hộp chọn file / thư mục

    def _locked(self):
        return "Tab này đang khóa - nhập mật khẩu admin." if not self._eng.admin_unlocked() else ""

    # ----- chung
    def state(self, rows_ver=-1, log_after=0, hist_ver=-1, folders_ver=-1, fp_ver=-1, toast_after=0):
        return self._eng.state(rows_ver, log_after, hist_ver, folders_ver, fp_ver, toast_after)

    def ping(self):
        self._eng.admin_activity()
        return ""

    def ui_get(self, key, default=None):
        return (self._eng.cfg.get("web_ui") or {}).get(key, default)

    def ui_set(self, key, value):
        with self._eng.lock:
            self._eng.cfg.setdefault("web_ui", {})[key] = value
            save_json(CONFIG_FILE, self._eng.cfg)
        return ""

    def pick_folder(self, initial=""):
        return self._ui.pick_folder(initial)

    def pick_open(self, kind="json"):
        return self._ui.pick_open(kind)

    def pick_save(self, name, kind="json"):
        return self._ui.pick_save(name, kind)

    def open_url(self, url):
        if url:
            open_target(url)
        return ""

    def copy_text(self, text):
        return set_clipboard(text)

    def clear_new_machine(self):
        self._eng.new_machine = False
        self._eng.save_config()
        return ""

    # ----- quét & tải
    def scan(self, download, only=None):
        return self._eng.start_scan(bool(download), only=set(only) if only else None)

    def download(self, codes):
        return self._eng.download_codes(list(codes or []))

    def mark_owned(self, codes):
        return self._eng.mark_owned(list(codes or []))

    def stop(self):
        self._eng.stop()
        return ""

    def set_auto(self, on, minutes=None):
        self._eng.set_auto(on, minutes)
        return ""

    def open_source(self, code):
        return self._eng.open_source(code)

    # ----- đèn trạng thái
    def check_pikpak(self):
        self._eng._pk_acc = {}
        self._eng.check_pikpak(silent=False)
        return ""

    def backup_now(self):
        return self._eng.backup_now()

    def report_latest(self, open_it=True):
        f = self._eng.latest_report()
        if not f:
            return {"error": "Chưa có báo cáo lỗi nào."}
        txt = f.read_text(encoding="utf-8", errors="replace")
        copied = set_clipboard(txt)
        if open_it:
            open_target(str(f))
        return {"name": f.name, "copied": copied, "text": txt if not copied else ""}

    def open_reports(self):
        d = DATA_DIR / "BaoLoi"
        d.mkdir(parents=True, exist_ok=True)
        open_target(str(d))
        return ""

    def clear_reports(self):
        self._eng.clear_reports()
        return ""

    def get_rclone(self, update=False):
        return self._eng.get_rclone(bool(update))

    # ----- mật khẩu admin
    def admin_unlock(self, pw):
        return self._eng.admin_unlock(pw)

    def admin_lock(self):
        self._eng.admin_lock()
        return ""

    def admin_change(self, old, new):
        return self._eng.admin_change(old, new)

    # ----- thư mục phim (cần mở khóa)
    def folder_get(self, i):
        return self._eng.folder_get(i)

    def folder_save(self, i, data):
        return self._locked() or self._eng.folder_save(i, data)

    def folder_toggle(self, i):
        return self._locked() or self._eng.folder_toggle(i) or ""

    def folder_check_all(self, on):
        return self._locked() or self._eng.folder_check_all(on) or ""

    def folder_move(self, i, step):
        return self._locked() or self._eng.folder_move(i, step) or ""

    def folder_delete(self, i):
        return self._locked() or self._eng.folder_delete(i) or ""

    def folder_ack_gaps(self, i):
        return self._locked() or self._eng.folder_ack_gaps(i) or ""

    def folder_bulk(self, text):
        if self._locked():
            return -1
        return self._eng.folder_bulk(text)

    def folder_export(self):
        p = self._ui.pick_save(f"PikPakFolders_{dt.date.today():%Y%m%d}.json", "json")
        return {"n": self._eng.folder_export(p), "path": p} if p else {}

    def folder_import(self):
        if self._locked():
            return {"error": self._locked()}
        p = self._ui.pick_open("json")
        if not p:
            return {}
        r = self._eng.folder_import(p)
        return {"error": "File không đúng định dạng."} if r is None else {"added": r[0], "skipped": r[1]}

    def folder_diagnose(self, i):
        self._eng.diagnose_folder(i)
        return ""

    def folder_open_source(self, i):
        f = self._eng.cfg["folders"][i]
        open_target(source_link(self._eng.cfg, f))
        return ""

    def fp_scan(self, i):
        return self._eng.fp_scan(i)

    def fp_mark(self, codes, on):
        return self._locked() or self._eng.fp_mark(list(codes or []), on) or ""

    def fp_save(self):
        if self._locked():
            return {"error": self._locked()}
        return {"msg": self._eng.fp_save()}

    def fp_close(self):
        self._eng.fp_close()
        return ""

    def share_open(self, cur=""):
        return self._eng.share_open(cur)

    def share_ls(self, sid, pwd, folder, token, root):
        return self._eng.share_ls(sid, pwd, folder, token, root)

    def pk_ls(self, path):
        return self._eng.pk_ls(path)

    def pk_mkdir(self, path, name):
        return self._eng.pk_mkdir(path, name)

    # ----- lịch sử
    def hist_mark_done(self, codes):
        self._eng.hist_mark_done(list(codes or []))
        return ""

    def hist_delete(self, codes):
        self._eng.hist_delete(list(codes or []))
        return ""

    def hist_clear(self):
        self._eng.hist_clear()
        return ""

    def hist_upload(self, codes):
        return self._eng.hist_upload(list(codes or []))

    def hist_open(self, code):
        return self._eng.open_path((self._eng.history.get(code) or {}).get("path"))

    # ----- cài đặt (cần mở khóa)
    def settings(self):
        return self._eng.get_settings()

    def save_settings(self, data):
        return self._locked() or self._eng.save_settings(dict(data or {}))

    def copy_profile(self, name):
        return self._locked() or self._eng.copy_profile(name)

    def delete_profile(self, name):
        return self._locked() or self._eng.delete_profile(name)

    def pk_login(self, user, pw, remember=True):
        return self._locked() or self._eng.pk_login(user, pw, remember)

    def pk_detail(self):
        return self._eng.pk_detail()

    def rclone_info(self):
        return self._eng.rclone_info()

    def open_data(self):
        DATA_DIR.mkdir(exist_ok=True)
        open_target(str(DATA_DIR))
        return ""

    def open_base(self):
        open_target(str(BASE))
        return ""

    def open_iphone(self):
        d = resolve_iphone_dir(self._eng.cfg.get("iphone_dir"))
        os.makedirs(d, exist_ok=True)
        open_target(d)
        return ""

    def iphone_preview(self):
        return self._eng.iphone_preview()

    def iphone_run(self):
        return self._eng.iphone_run()

    def backup_to_file(self):
        p = self._ui.pick_save(f"PikPakShare_backup_{dt.date.today():%Y-%m-%d}.zip", "zip")
        if not p:
            return {}
        self._eng.backup_to_file(p)
        return {"path": p}

    def restore_pick(self):
        p = self._ui.pick_open("zip")
        return self._eng.restore_preview(p) if p else {}

    def restore_fetch_pikpak(self):
        return self._eng.restore_fetch_pikpak()

    def restore_apply(self, path):
        return self._locked() or self._eng.restore_apply(path)

    def export_log(self):
        return self._eng.export_log()

    def db_info(self):
        return self._eng.db_info()

    def test_notify(self):
        self._eng.save_config()
        self._eng.notify(APP_TITLE, "Thông báo hoạt động bình thường.")
        return ""

    # ----- cập nhật
    def check_update(self):
        return self._eng.check_update(silent=False)

    def set_update(self, repo, auto):
        with self._eng.lock:
            self._eng.cfg["update_repo"] = (repo or "").strip()
            self._eng.cfg["update_check"] = bool(auto)
            save_json(CONFIG_FILE, self._eng.cfg)
        return ""

    def update_apply(self):
        return self._eng.update_apply()

    def update_from_file(self):
        p = self._ui.pick_open("zip")
        if not p:
            return ""
        return self._eng.update_apply(p)

    def classic_ui(self):
        """Mở giao diện cũ (Tk) - dự phòng. Nhớ lựa chọn (mở lại vẫn là giao diện cũ cho tới khi chọn lại web)."""
        if self._eng.busy():
            return "Tool đang quét / tải - đợi xong rồi đổi giao diện."
        with self._eng.lock:
            self._eng.cfg["ui_mode"] = "classic"
        self._eng.restart([])
        return ""

    def quit_app(self):
        self._eng.quit(force=True)
        return ""


# ================================================================ cửa sổ app (pywebview) + khay hệ thống
class AppWindow:
    def __init__(self, eng, startup=False):
        self.eng = eng
        self.win = None
        self.tray = None
        self.quitting = False
        self.startup = startup

    # ----- hộp chọn file / thư mục (cửa sổ Windows)
    @staticmethod
    def _kind(name):
        import webview
        fd = getattr(webview, "FileDialog", None)
        if fd is not None:
            return getattr(fd, name)
        return getattr(webview, {"OPEN": "OPEN_DIALOG", "FOLDER": "FOLDER_DIALOG", "SAVE": "SAVE_DIALOG"}[name])

    def _dlg(self, kind, **kw):
        try:
            res = self.win.create_file_dialog(self._kind(kind), **kw)
        except Exception as e:              # noqa: BLE001
            self.eng.toast(f"Không mở được hộp chọn: {e}", "err")
            return ""
        if not res:
            return ""
        return os.path.normpath(res if isinstance(res, str) else res[0])

    def pick_folder(self, initial=""):
        return self._dlg("FOLDER", directory=initial if initial and os.path.isdir(initial) else "")

    def pick_open(self, kind="json"):
        ft = ("File zip (*.zip)",) if kind == "zip" else ("File JSON (*.json)",)
        return self._dlg("OPEN", file_types=ft)

    def pick_save(self, name, kind="json"):
        return self._dlg("SAVE", save_filename=name)

    # ----- khay hệ thống
    def start_tray(self):
        if not core.TRAY_OK:
            return
        try:
            import base64
            import io
            img = core.PILImage.open(io.BytesIO(base64.b64decode(core.ICON64)))
            pystray = core.pystray
            menu = pystray.Menu(
                pystray.MenuItem("Mở PikPak Auto Save", lambda: self.show(), default=True),
                pystray.MenuItem("Quét & Tải ngay", lambda: self.eng.start_scan(True, auto=True)),
                pystray.MenuItem(lambda item: "Tắt tự quét" if self.eng.cfg.get("auto_scan") else "Bật tự quét",
                                 lambda: self.eng.set_auto(not self.eng.cfg.get("auto_scan"))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Thoát", lambda: self.quit()))
            self.tray = pystray.Icon("PikPakShare", img, APP_NAME, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
            self.eng.notify_fn = lambda t, m: self.tray.notify(m, t)
            self.eng.on_auto_changed = lambda: self.tray.update_menu()
        except Exception as e:              # noqa: BLE001
            self.tray = None
            self.eng.log(f"Không tạo được biểu tượng khay: {e}")

    def show(self):
        try:
            self.win.show()
            self.win.restore()
        except Exception:                   # noqa: BLE001
            pass

    def quit(self):
        self.quitting = True
        self.eng.stop_flag.set()
        self._remember()
        try:
            self.eng.save_config()
            self.eng.save_history()
        except Exception:                   # noqa: BLE001
            pass
        if self.tray:
            try:
                self.tray.stop()
            except Exception:               # noqa: BLE001
                pass
        try:
            self.win.destroy()
        except Exception:                   # noqa: BLE001
            os._exit(0)

    # ----- nhớ kích thước / vị trí cửa sổ
    def _remember(self):
        w = self.eng.cfg.setdefault("web_window", {})
        g = getattr(self, "_geom", None)
        if g:
            w.update(g)

    def _on_resized(self, width, height):
        if not getattr(self, "_maxed", False):
            self._geom = dict(getattr(self, "_geom", {}) or {}, width=width, height=height)

    def _on_moved(self, x, y):
        if not getattr(self, "_maxed", False):
            self._geom = dict(getattr(self, "_geom", {}) or {}, x=x, y=y)

    def _on_closing(self):
        if self.quitting:
            return True
        if self.tray and self.eng.cfg.get("tray_on_close", True):
            self._remember()
            self.eng.save_config()
            self.win.hide()
            if not getattr(self, "_hint", False):
                self._hint = True
                self.eng.notify(APP_TITLE, "Tool vẫn chạy dưới khay hệ thống. Nhấp đúp biểu tượng để mở lại.")
            return False
        if self.eng.busy():                # hỏi trong luồng khác (không chặn cửa sổ)
            threading.Thread(target=lambda: self.eng.confirm("Tool đang quét / tải. Vẫn thoát?") and self.quit(),
                             daemon=True).start()
            return False
        self.quitting = True
        self.eng.stop_flag.set()
        self._remember()
        self.eng.save_config()
        self.eng.save_history()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:               # noqa: BLE001
                pass
        return True

    def run(self, debug=False, selftest=False):
        import webview
        html = page_html()
        g = self.eng.cfg.get("web_window") or {}
        hidden = bool(self.startup and core.TRAY_OK and self.eng.cfg.get("tray_on_close", True))
        sw, sh = 1920, 1080                 # cỡ màn hình -> cửa sổ không bao giờ to hơn màn hình
        try:
            sc = webview.screens[0]
            sw, sh = int(sc.width), int(sc.height)
        except Exception:                   # noqa: BLE001
            pass
        w_, h_ = int(g.get("width", min(1480, sw - 40))), int(g.get("height", min(920, sh - 60)))
        kw = dict(width=max(800, min(w_, sw)), height=max(560, min(h_, sh - 30)),
                  min_size=(min(1000, sw - 40), min(620, sh - 80)), background_color="#eef1f5", hidden=hidden)
        if "x" in g and "y" in g and -50 < int(g["x"]) < sw - 100 and -50 < int(g["y"]) < sh - 100:
            kw.update(x=int(g["x"]), y=int(g["y"]))
        if sw < 1200 or sh < 760:
            g = dict(g, max=True)
        try:
            self.win = webview.create_window(APP_NAME, html=html, js_api=Api(self.eng, self), maximized=bool(g.get("max")), **kw)
        except TypeError:                   # pywebview cũ
            kw.pop("hidden", None)
            self.win = webview.create_window(APP_NAME, html=html, js_api=Api(self.eng, self), **kw)
        ev = self.win.events
        ev.closing += self._on_closing
        ev.resized += self._on_resized
        ev.moved += self._on_moved
        try:
            ev.maximized += lambda: (setattr(self, "_maxed", True), self.eng.cfg.setdefault("web_window", {}).update(max=True))
            ev.restored += lambda: (setattr(self, "_maxed", False), self.eng.cfg.setdefault("web_window", {}).update(max=False))
        except AttributeError:
            pass
        self.eng.confirm_fn = lambda text: self.win.evaluate_js("window.confirm(%s)" % json.dumps(text))
        self.eng.quit_fn = self.quit
        self.start_tray()
        if self.startup and self.eng.cfg.get("startup_scan", True):
            self.eng.next_auto_ts = time.time() + 60
            self.eng.log("Khởi động cùng Windows: sẽ quét sau 1 phút.")
        if self.eng.cfg.get("update_check", True):
            threading.Timer(15, lambda: self.eng.check_update(silent=True)).start()
        if selftest:
            threading.Thread(target=self._selftest, daemon=True).start()
        icon = Path(getattr(sys, "_MEIPASS", BASE)) / "icon.ico"
        try:
            webview.start(debug=debug, icon=str(icon) if icon.exists() else None)
        except TypeError:
            webview.start(debug=debug)
        self.quitting = True
        if self.tray:
            try:
                self.tray.stop()
            except Exception:               # noqa: BLE001
                pass

    def _selftest(self):
        """Kiểm tra bản exe trên máy build: mở cửa sổ, đọc giao diện, chụp màn hình từng tab."""
        time.sleep(10)
        res = {}
        try:
            res["alert"] = self.win.evaluate_js("document.getElementById('a1').textContent")
            res["version"] = self.win.evaluate_js("document.getElementById('ver').textContent")
            res["tiles"] = self.win.evaluate_js("document.querySelectorAll('.tile').length")
            res["js_errors"] = self.win.evaluate_js("JSON.stringify(window.__errs||[])")
        except Exception as e:              # noqa: BLE001
            res["js_error"] = str(e)
        try:
            from PIL import ImageGrab
            for name, js in (("selftest", ""), ("selftest_history", "go('history',true)")):
                if js:
                    self.win.evaluate_js(js)
                    time.sleep(2)
                im = ImageGrab.grab()
                im.save(str(BASE / f"{name}.png"))
                im = im.convert("RGB")
                im.thumbnail((1280, 1280))
                im.save(str(BASE / f"{name}.jpg"), quality=72)
        except Exception as e:              # noqa: BLE001
            res["shot_error"] = str(e)
        (BASE / "selftest.txt").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        self.quit()


class BrowserUI:
    """Chế độ trình duyệt (--serve): không có hộp chọn file của Windows -> dùng đường dẫn đặt sẵn để thử."""

    def __init__(self, eng):
        self.eng = eng

    def pick_folder(self, initial=""):
        return os.environ.get("PK_PICK_FOLDER", "")

    def pick_open(self, kind="json"):
        return os.environ.get("PK_PICK_OPEN", "")

    def pick_save(self, name, kind="json"):
        d = os.environ.get("PK_PICK_SAVE_DIR", "")
        return os.path.join(d, name) if d else ""


def serve(eng, port=0, open_browser=True):
    """Mở giao diện bằng trình duyệt (dự phòng khi máy không có WebView2, và để thử)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    api = Api(eng, BrowserUI(eng))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, page_html(), "text/html; charset=utf-8")
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._send(403, "forbidden", "text/plain")
            name = self.path.rsplit("/", 1)[-1]
            n = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(n) or b"[]")
            fn = getattr(api, name, None)
            if name.startswith("_") or not callable(fn):
                return self._send(404, "{}", "application/json")
            try:
                res = fn(*args)
            except Exception as e:          # noqa: BLE001
                return self._send(500, json.dumps({"error": str(e)}), "application/json")
            self._send(200, json.dumps(res, ensure_ascii=False), "application/json; charset=utf-8")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print("Giao diện:", url, flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    eng.quit_fn = lambda: os._exit(0)
    srv.serve_forever()


def run_web(argv=None):
    """Mở giao diện web. Trả về False nếu máy không chạy được (thiếu pywebview / WebView2) -> dùng giao diện Tk."""
    argv = list(sys.argv if argv is None else argv)
    if "--serve" in argv:
        serve(Engine(), int(os.environ.get("PK_PORT", "0") or 0), open_browser="--no-browser" not in argv)
        return True
    try:
        import webview  # noqa: F401
    except Exception:                       # noqa: BLE001
        core.WEB_FAIL = "Chưa có thư viện pywebview (bản Python: chạy CaiDat.bat) - đang dùng giao diện cũ."
        return False
    try:
        web_dir()
    except FileNotFoundError:
        core.WEB_FAIL = "Thiếu thư mục giao diện 'web' cạnh tool - đang dùng giao diện cũ."
        return False
    eng = Engine()
    w = AppWindow(eng, startup="--startup" in argv)
    if "--auto" in argv:
        threading.Timer(1.5, lambda: eng.start_scan(True)).start()
    try:
        w.run(debug="--debug" in argv, selftest="--selftest" in argv)
    except Exception as e:                  # noqa: BLE001  (VD máy thiếu Edge WebView2)
        eng.report_error("Không mở được giao diện web (WebView2)", str(e), exc=e)
        core.WEB_FAIL = (f"Không mở được giao diện web: {e} - máy thiếu Edge WebView2? Tải \"Evergreen Bootstrapper\" "
                         "ở developer.microsoft.com/microsoft-edge/webview2 - đang dùng giao diện cũ.")
        if w.win is None:
            return False
        raise
    with eng.lock:
        if not eng._no_save:
            eng.save_config()
            eng.save_history()
    os._exit(0)


if __name__ == "__main__":
    if not run_web():
        print("Không mở được giao diện web - chạy: pip install pywebview  (hoặc dùng --serve)")

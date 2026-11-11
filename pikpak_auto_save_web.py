# -*- coding: utf-8 -*-
"""PikPak Auto Save v3.0 (thử nghiệm) - giao diện web trong cửa sổ app (pywebview / Edge WebView2).

Phần lõi (quét link chia sẻ, Save vào My PikPak, rclone tải về HDD, copy COPY_TO_IPHONE, báo lỗi, sao lưu)
dùng lại NGUYÊN các hàm của bản v2.x trong auto_download_pikpak_share.py - file này chỉ thay phần giao diện.
Dùng chung thư mục Data với bản v2.x (đặt file exe này cùng thư mục với "PikPak Auto Save.exe").

Chạy:  python pikpak_auto_save_web.py            -> cửa sổ app (cần: pip install pywebview)
       python pikpak_auto_save_web.py --serve    -> mở bằng trình duyệt (dự phòng / để thử)
"""
import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import auto_download_pikpak_share as core
from auto_download_pikpak_share import (
    APP_TITLE, CONFIG_FILE, DATA_DIR, HISTORY_FILE, MACHINE, OWNED_FILE, STATUS_DONE, STATUS_FAIL,
    WATCH_STATUSES, find_rclone, human_size, load_json, open_target, pikpak_api, run_rclone, save_json, fid,
    from_portable, dec_secret)

WEB_VERSION = "v3.0 thử nghiệm"
APP_NAME = f"{APP_TITLE} {WEB_VERSION}"
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
V2_EXE = core.EXE_NAME


class EngineQueue(queue.Queue):
    """Hàng đợi tin nhắn từ lõi v2.x. Tin "call" chạy ngay (không có Tk) - còn lại để bộ bơm xử lý."""

    def __init__(self, eng):
        super().__init__()
        self.eng = eng

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
    """Trạng thái + luồng làm việc. Các hàm quét / tải mượn thẳng từ core.App (không đụng tới Tk)."""
    _B = core.App.__dict__
    note_listing = _B["note_listing"]
    owned_index = _B["owned_index"]
    is_owned = _B["is_owned"]
    add_owned = _B["add_owned"]
    remove_owned = _B["remove_owned"]
    _scan_job = _B["_scan_job"]
    _download_job = _B["_download_job"]
    _download_items = _B["_download_items"]
    _fetch_fail = _B["_fetch_fail"]
    _remove_broken = _B["_remove_broken"]
    report_error = _B["report_error"]
    _fetch_one = _B["_fetch_one"]
    _copy_to_iphone = _B["_copy_to_iphone"]
    _names_preview = _B["_names_preview"]
    check_pikpak = _B["check_pikpak"]
    _backup_remote = _B["_backup_remote"]
    _do_backup = _B["_do_backup"]

    def __init__(self):
        self.cfg = load_json(CONFIG_FILE, core.DEFAULT_CONFIG)
        self.cfg.setdefault("folders", [])
        for f in self.cfg["folders"]:
            fid(f)
        self._no_save = False
        self.history = load_json(HISTORY_FILE, {})
        for h in self.history.values():
            if h.get("status") in WATCH_STATUSES:
                h["status"] = STATUS_FAIL
        self.owned = load_json(OWNED_FILE, None)
        if not isinstance(self.owned, dict):
            self.owned = {}
        self.item_meta, self.present_codes, self.sub_of = {}, set(), {}
        self.q = EngineQueue(self)
        self.lock = threading.RLock()
        self.worker = None
        self.stop_flag = threading.Event()
        self.log_lines = []                 # dòng nhật ký (giữ 400 dòng cuối)
        self.log_seq = 0                    # tổng số dòng đã ghi (để giao diện chỉ lấy dòng mới)
        self.rows, self.row_order, self.scan_items = {}, [], {}
        self.rows_ver = self.hist_ver = 0
        self._new_count = 0
        self._batch = (0, 0)
        self._dl_pct = 0
        self.energy = {"dl": [0, "—"], "up": [0, "—"], "all": [0, "—"]}
        self.status = "Sẵn sàng."
        self.pk_ok, self.pk_text = None, "đang kết nối..."
        self._pk_acc, self._rc_ver = {}, None
        self._health_probs, self._in_health = [], False
        self._backup_pending = False
        self.bk_error = ""
        self.next_auto_ts = None
        self.confirm_fn = None              # hỏi Có/Không trên giao diện (đặt bởi cửa sổ app)
        self.notify_fn = None
        self.v2_running = False
        self.last_summary = self.cfg.get("last_summary", "")
        if self.cfg.get("auto_scan"):
            self.next_auto_ts = time.time() + int(self.cfg.get("auto_interval", 60)) * 60
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._auto_loop, daemon=True).start()
        threading.Thread(target=self._slow_loop, daemon=True).start()
        self.check_pikpak(silent=True)
        self.log(f"{APP_NAME} - dùng chung dữ liệu: {DATA_DIR}")

    # ------------------------------------------------------------ phần thay cho giao diện Tk
    def log(self, msg):
        self.q.put(("log", msg))

    def save_config(self):
        save_json(CONFIG_FILE, self.cfg)

    def save_history(self):
        save_json(HISTORY_FILE, self.history)

    def save_owned(self):
        save_json(OWNED_FILE, self.owned)

    def call_ui(self, fn, *args, timeout=20):
        if self._in_health:                 # câu hỏi "Phát hiện vấn đề... Vẫn tiếp tục tải?"
            txt = ("Phát hiện vấn đề:\n\n• " + "\n• ".join(self._health_probs) + "\n\nVẫn tiếp tục tải?")
            return self.confirm(txt)
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
        t = threading.Timer(20, self._do_backup)
        t.daemon = True
        t.start()

    def notify(self, title, msg):
        self.log(f"🔔 {title}: {msg}")
        if self.notify_fn:
            try:
                self.notify_fn(title, msg)
            except Exception:               # noqa: BLE001
                pass

    # ------------------------------------------------------------ bơm tin nhắn từ lõi -> trạng thái
    def _pump(self):
        while True:
            msg = self.q.get()
            hist_changed = owned_changed = False
            batch = [msg]
            try:
                while True:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
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
                    self.hist_ver += 1
                if owned_changed:
                    self.save_owned()

    def _add_log(self, text):
        line = f"{dt.datetime.now():%H:%M:%S}  {text}"
        self.log_seq += 1
        self.log_lines.append(line)
        del self.log_lines[:-400]
        try:
            with open(core.LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(f"{dt.datetime.now():%Y-%m-%d} {line}\n")
        except OSError:
            pass

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
            key, pct = msg[1], max(0, min(100, int(round(float(msg[2] or 0)))))
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
                self.save_config()
        elif kind == "foldername":
            i, name = msg[1], msg[2]
            if i < len(self.cfg["folders"]) and not self.cfg["folders"][i].get("name"):
                self.cfg["folders"][i]["name"] = name
                self.save_config()
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
                self.save_config()
                self._add_log(f"⟲ Đã sao lưu dữ liệu lên PikPak ({msg[2]}).")
            else:
                self.bk_error = msg[2]
                self._add_log("⚠ Sao lưu lên PikPak lỗi: " + msg[2])
        elif kind == "notify":
            self.notify(msg[1], msg[2])
        elif kind == "done":
            self.status = msg[1]
            if self.energy["dl"][1] not in ("—",):
                self.energy["dl"][1] = "✔ " + str(msg[1]).strip()
        return False, False

    def _energy_total(self):
        done, n = self._batch
        if not n:
            return
        cur = self._dl_pct if done < n else 0
        tot = min(100, (done + cur / 100) / n * 100)
        self.energy["all"] = [int(tot), f"{min(done + (1 if done < n else 0), n)} / {n}"]

    # ------------------------------------------------------------ việc nền
    def busy(self):
        return bool(self.worker and self.worker.is_alive())

    def _run_worker(self, target, *args):
        self.stop_flag.clear()
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def start_scan(self, download, auto=False):
        if self.busy():
            return "Đang chạy - chờ xong hoặc bấm Dừng."
        if core.requests is None:
            return "Thiếu thư viện 'requests'."
        if not self.cfg["folders"]:
            return "Chưa có thư mục phim nào (thêm trong tab Thư mục phim của bản v2.5)."
        if not any(f.get("enabled", True) for f in self.cfg["folders"]):
            return "Chưa chọn thư mục nào để quét."
        with self.lock:
            self.rows, self.row_order, self.scan_items = {}, [], {}
            self._new_count = 0
            self.rows_ver += 1
            self._batch = (0, sum(1 for f in self.cfg["folders"] if f.get("enabled", True)))
            for k in self.energy:
                self.energy[k] = [0, "—"]
        self._run_worker(self._scan_job, download, auto, None)
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

    def stop(self):
        self.stop_flag.set()
        self.log("■ Đang dừng...")

    def set_auto(self, on, minutes):
        self.cfg["auto_scan"] = bool(on)
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

    def _auto_loop(self):
        while True:
            time.sleep(10)
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
                self.v2_running = self._v2_running()
                if self.pk_ok and time.time() - self._pk_acc.get("ts", 0) > 1800:
                    self._read_account()
            except Exception:               # noqa: BLE001
                pass
            time.sleep(30)

    @staticmethod
    def _v2_running():
        if os.name != "nt":
            return False
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {V2_EXE}", "/NH"], capture_output=True,
                                 text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return V2_EXE.lower() in out.lower()
        except Exception:                   # noqa: BLE001
            return False

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

    # ------------------------------------------------------------ trạng thái cho giao diện
    def _err_reports(self):
        d = DATA_DIR / "BaoLoi"
        return sorted(d.glob("BaoLoi_*.txt")) if d.is_dir() else []

    def leds(self):
        """Đèn trạng thái: (trạng thái ok/run/err/off, chữ) + danh sách việc cần xử lý."""
        L, issues = {}, []
        busy = self.busy()
        if busy:
            done, n = self._batch
            sp = re.search(r"[\d.,]+\s*[KMG]i?B/s", self.energy["dl"][1] or "")
            txt = (f"{min(done + 1, n)}/{n} · " if n else "") + f"{self._dl_pct}%" + (
                f" · {sp.group(0).replace('.', ',')}" if sp else "")
            L["dl"] = ("run", txt if self._dl_pct or sp else self.status[:60])
        else:
            L["dl"] = ("off", "Rảnh")
        user = self.cfg.get("pikpak_user") or ""
        if self.pk_ok is True:
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
            issues.append("PikPak chưa kết nối: " + self.pk_text)
        else:
            L["pk"] = ("run", "Đang kết nối..." + (f"\n{user}" if user else ""))
        if not find_rclone(self.cfg.get("rclone_path", "")):
            L["rc"] = ("err", "Chưa có rclone.exe")
            issues.append("Chưa có rclone.exe (tải trong Cài đặt của bản v2.5)")
        else:
            L["rc"] = ("ok", f"{self._rc_ver} sẵn sàng" if self._rc_ver else "sẵn sàng")
        if self.cfg.get("auto_scan") and self.next_auto_ts:
            L["auto"] = ("ok", f"Bật · lần tới {dt.datetime.fromtimestamp(self.next_auto_ts):%H:%M}")
        else:
            L["auto"] = ("off", "Đang tắt")
        bk = self.cfg.get("last_backup") or ""
        if not self.cfg.get("backup_on", True):
            L["bk"] = ("off", "Đã tắt")
        elif self.bk_error:
            L["bk"] = ("err", "Sao lưu lỗi")
            issues.append("Sao lưu lên PikPak lỗi: " + self.bk_error[:120])
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
            L["err"] = ("err", f"{n} lỗi · bấm để xem")
            issues.append(f"{n} báo cáo lỗi (bấm thẻ Lỗi để xem)")
        else:
            L["err"] = ("off", "Không có lỗi")
        for p_ in self._health_probs:
            if not any(k in p_ for k in ("rclone", "PikPak")):
                issues.append(p_)
        if self.v2_running:
            issues.insert(0, f"Bản v2.5 ({V2_EXE}) đang mở - tắt bản v2.5 trước khi dùng bản thử v3.0 "
                             "(2 bản dùng chung dữ liệu)")
        return L, issues

    def state(self, rows_ver=-1, log_after=0, hist_ver=-1):
        with self.lock:
            on = [f for f in self.cfg["folders"] if f.get("enabled", True)]
            dl = sum(1 for h in self.history.values() if h.get("status") in WATCH_STATUSES)
            L, issues = self.leds()
            st = {
                "version": WEB_VERSION, "machine": MACHINE, "busy": self.busy(), "status": self.status,
                "stats": {"folders": f"{len(on)}/{len(self.cfg['folders'])}", "new": self._new_count, "dl": dl,
                          "owned": len(self.owned)},
                "energy": self.energy, "leds": {k: list(v) for k, v in L.items()}, "issues": issues,
                "auto": {"on": bool(self.cfg.get("auto_scan")), "interval": int(self.cfg.get("auto_interval", 60)),
                         "next": (f"{dt.datetime.fromtimestamp(self.next_auto_ts):%H:%M}"
                                  if self.next_auto_ts else "")},
                "summary": self.last_summary, "rows_ver": self.rows_ver, "hist_ver": self.hist_ver,
                "log": self.log_lines[max(0, len(self.log_lines) - (self.log_seq - int(log_after or 0))):]
                if self.log_seq > int(log_after or 0) else [],
                "log_seq": self.log_seq, "lib": len(self.owned),
                "unreviewed": sum(1 for f in on if not f.get("reviewed")),
                "folder_err": sum(1 for f in on if f.get("last_error")),
            }
            if rows_ver != self.rows_ver:
                st["rows"] = [self.rows[c] for c in self.row_order if c in self.rows]
            if hist_ver != self.hist_ver:
                st["history"] = self._history_rows()
            return st

    def _history_rows(self, limit=500):
        recs = sorted(self.history.items(), key=lambda kv: -float(kv[1].get("ts", 0) or 0))[:limit]
        return [{"code": c, "name": h.get("name", ""), "movie": h.get("movie") or h.get("folder", ""),
                 "status": h.get("status", ""), "when": h.get("sent_at", ""), "size": human_size(h.get("size")),
                 "error": (h.get("error") or "")[:200], "path": h.get("path") or ""} for c, h in recs]

    def folders(self):
        out = []
        for f in self.cfg["folders"]:
            ls = f.get("last_scan")
            out.append({"name": f.get("name") or f.get("url", ""), "on": f.get("enabled", True),
                        "reviewed": bool(f.get("reviewed")), "note": f.get("note", ""),
                        "last": dt.datetime.fromtimestamp(ls).strftime("%H:%M %d/%m") if ls else "",
                        "total": f.get("total", ""), "owned": f.get("owned", ""), "err": f.get("last_error", ""),
                        "hdd": from_portable(f.get("local_dir", "")) if f.get("local_dir") else "",
                        "pk": f.get("pikpak_dir", "")})
        return out

    def settings(self):
        c = self.cfg
        return {"user": c.get("pikpak_user", ""), "rclone": find_rclone(c.get("rclone_path", "")) or "(chưa có)",
                "iphone_on": c.get("iphone_on", True), "iphone_dir": core.resolve_iphone_dir(c.get("iphone_dir")),
                "backup_on": c.get("backup_on", True), "last_backup": c.get("last_backup", ""),
                "share_root": c.get("share_root", ""), "data": str(DATA_DIR), "bwlimit": c.get("bwlimit", ""),
                "extensions": c.get("extensions", "")}

    def open_source(self, code):
        m = self.item_meta.get(code) or (self.history.get(code) or {}).get("src") or {}
        h = self.history.get(code) or {}
        p = h.get("path")
        if p and os.path.exists(p):
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
            else:
                open_target(os.path.dirname(p))
        elif m.get("share"):
            open_target(f"https://mypikpak.com/s/{m['share']}")

    def open_report(self):
        files = self._err_reports()
        if not files:
            return ""
        open_target(str(files[-1]))
        return files[-1].read_text(encoding="utf-8", errors="replace")


# ================================================================ cầu nối JS <-> Python
class Api:
    def __init__(self, eng):
        self._eng = eng

    def state(self, rows_ver=-1, log_after=0, hist_ver=-1):
        return self._eng.state(rows_ver, log_after, hist_ver)

    def scan(self, download):
        return self._eng.start_scan(bool(download))

    def download(self, codes):
        return self._eng.download_codes(list(codes or []))

    def mark_owned(self, codes):
        self._eng.mark_owned(list(codes or []))
        return ""

    def stop(self):
        self._eng.stop()
        return ""

    def set_auto(self, on, minutes):
        self._eng.set_auto(on, minutes)
        return ""

    def folders(self):
        return self._eng.folders()

    def settings(self):
        return self._eng.settings()

    def open_source(self, code):
        self._eng.open_source(code)
        return ""

    def open_report(self):
        return self._eng.open_report()

    def open_data(self):
        open_target(str(DATA_DIR))
        return ""

    def check_pikpak(self):
        self._eng._pk_acc = {}
        self._eng.check_pikpak(silent=False)
        return ""

    def backup_now(self):
        if not find_rclone(self._eng.cfg.get("rclone_path", "")):
            return "Chưa có rclone.exe."
        self._eng._backup_pending = True
        threading.Thread(target=self._eng._do_backup, daemon=True).start()
        return ""

    def ui_get(self, key, default=None):
        return (self._eng.cfg.get("web_ui") or {}).get(key, default)

    def ui_set(self, key, value):
        self._eng.cfg.setdefault("web_ui", {})[key] = value
        self._eng.save_config()
        return ""


def load_html():
    return (HERE / "web" / "index.html").read_text(encoding="utf-8")


# ================================================================ chế độ trình duyệt (dự phòng + thử nghiệm)
def serve(api, port=0, open_browser=True, block=True):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
                self._send(200, load_html(), "text/html; charset=utf-8")
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
    if block:
        srv.serve_forever()
    else:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, url


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DuyAnh.PikPakShare.Web")
        except Exception:                   # noqa: BLE001
            pass
    eng = Engine()
    api = Api(eng)
    if "--serve" in sys.argv:
        return serve(api, int(os.environ.get("PK_PORT", "0") or 0), open_browser="--no-browser" not in sys.argv)
    try:
        import webview
    except ImportError:
        print("Chưa có pywebview (pip install pywebview) - mở bằng trình duyệt.")
        return serve(api)
    win = webview.create_window(APP_NAME, html=load_html(), js_api=api, width=1480, height=900,
                                min_size=(1100, 680), background_color="#eef1f5")

    def confirm(text):
        return win.evaluate_js("window.confirm(%s)" % json.dumps(text))
    eng.confirm_fn = confirm
    if "--selftest" in sys.argv:            # kiểm tra bản exe trên máy build: mở cửa sổ, đọc giao diện, chụp màn hình
        def selftest():
            time.sleep(10)
            res = {}
            try:
                res["alert"] = win.evaluate_js("document.getElementById('a1').textContent")
                res["version"] = win.evaluate_js("document.getElementById('ver').textContent")
                res["tiles"] = win.evaluate_js("document.querySelectorAll('.tile').length")
            except Exception as e:          # noqa: BLE001
                res["js_error"] = str(e)
            try:
                from PIL import ImageGrab
                ImageGrab.grab().save(str(core.BASE / "selftest.png"))
            except Exception as e:          # noqa: BLE001
                res["shot_error"] = str(e)
            (core.BASE / "selftest.txt").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            win.destroy()
        threading.Thread(target=selftest, daemon=True).start()
    eng.notify_fn = lambda t, m: win.evaluate_js("window.toast && toast(%s)" % json.dumps(f"{t}: {m}"))
    icon = HERE / "icon.ico"
    try:
        webview.start(debug="--debug" in sys.argv, icon=str(icon) if icon.exists() else None)
    except TypeError:                        # pywebview cũ không có tham số icon
        webview.start(debug="--debug" in sys.argv)
    eng.stop_flag.set()
    with eng.lock:
        eng.save_config()
        eng.save_history()


if __name__ == "__main__":
    main()

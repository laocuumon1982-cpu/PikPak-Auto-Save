# -*- coding: utf-8 -*-
"""
PikPak Auto Save v2.5 by Duy Anh
 - Nguồn phim: thư mục con trong link chia sẻ PikPak (mypikpak.com/s/...).
 - Đích 1 (chạy trước): Save (lưu) tập mới vào My PikPak của bạn - sao chép trên máy chủ PikPak, không tốn mạng.
 - Đích 2: rclone (tài khoản của bạn) tải tập đó từ My PikPak về HDD của PC (đa luồng, nhanh).
 - Tập đã xong được đưa vào "Danh sách đã có" để lần sau không tải lại.
Chạy:  python auto_download_pikpak_share.py          (mở giao diện)
       python auto_download_pikpak_share.py --auto   (mở giao diện và tự Quét & Tải ngay)
"""
import datetime as dt
import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
from collections import deque
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

try:
    import requests
except ImportError:
    requests = None

try:  # khay hệ thống + thông báo Windows (pip install pystray pillow)
    import pystray
    from PIL import Image as PILImage
    TRAY_OK = os.name == "nt"
except Exception:
    pystray = PILImage = None
    TRAY_OK = False

APP_TITLE = "PikPak Auto Save"
APP_VERSION = "v2.5 by Duy Anh"
APP_NAME = f"{APP_TITLE} {APP_VERSION}"
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = BASE / "Data"                # v5.9: mọi dữ liệu nằm trong Data\ -> lên bản mới chỉ cần chép thư mục Data
DATA_FILES = ("config.json", "owned.json", "history.json", "rclone.conf", "log.txt", "pikpak_session.json")


def _migrate_data_dir():
    """Chuyển dữ liệu kiểu cũ (nằm cạnh tool) vào thư mục Data. Không ghi đè file đã có trong Data."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
    except OSError:
        return
    for name in DATA_FILES:
        old, new = BASE / name, DATA_DIR / name
        if old.is_file() and not new.exists():
            try:
                shutil.move(str(old), str(new))
            except OSError:
                try:
                    shutil.copy2(str(old), str(new))
                except OSError:
                    pass


_migrate_data_dir()
PK_SESSION_FILE = DATA_DIR / "pikpak_session.json"
CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.json"
OWNED_FILE = DATA_DIR / "owned.json"        # Danh sách đã có (không tải)
RCLONE_CONF = DATA_DIR / "rclone.conf"      # cấu hình rclone (đăng nhập PikPak) -> đi theo thư mục Data
BACKUP_FILES = ("config.json", "owned.json", "history.json")
BACKUP_DIR = "_Backup PikPakShare"
EXE_NAME = "PikPak Auto Save.exe"
OLD_EXE_NAMES = ("PikPak Auto Download.exe", "Auto Download - PikPak Share.exe")     # tên exe v1.1 / v1.0
MACHINE = (os.environ.get("COMPUTERNAME") or "").strip() or __import__("socket").gethostname()
PATH_KEYS = ("raidrive_root", "iphone_dir")
MACHINE_KEYS = PATH_KEYS + ("rd_remote_base", "start_with_windows")
LOG_FILE = DATA_DIR / "log.txt"

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"

INTERVAL_CHOICES = ("15", "30", "45", "60", "90", "120")
DL_METHODS = {"auto": "rclone tải từ My PikPak"}
STATUS_NEW = "Tập mới"
STATUS_OPENED = "Đang chờ tải"
STATUS_DL = "Đang tải"
STATUS_DONE = "Xong"
STATUS_SKIP_DONE = "Đã tải xong trước đó"
STATUS_HAVE = "Đã có trong thư mục phim"
STATUS_FAIL = "Lỗi tải"
STATUS_BAD = "Lỗi - file thiếu dung lượng"     # tải xong nhưng file nhỏ hơn bản gốc -> tải lại
RETRY_STATUSES = (STATUS_FAIL, STATUS_BAD)
MARKED = "Đánh dấu thủ công"   # sent_at của tập bạn tự đánh dấu là đã có
MAX_TRIES = 5                 # số lần quét tự tải lại 1 tập lỗi trước khi báo "hãy kiểm tra"
RETRY_NOW = 2                 # số lượt tải lại ngay trong cùng lần tải (sau 20s, 40s)
STALE_HOURS = 12              # "Đang tải" quá 12 giờ mà chưa có file -> cho tải lại
STALE_FOLDER_DAYS = 14        # thư mục 14 ngày không có tập mới -> cảnh báo
CATCHUP_MAX_DAYS = 14         # quét bù tối đa 14 ngày khi tool không chạy
WATCH_STATUSES = (STATUS_OPENED, STATUS_DL)

# ----- màu giao diện (v3.2: dịu mắt - nền xám nhạt, xanh dương trầm, thanh bên xám than)
C_BG = "#eef1f4"             # nền cửa sổ
C_CARD = "#fbfcfd"           # khung nội dung
C_PANEL = "#f4f6f8"          # ô / bảng điều khiển bên trong
C_FIELD = "#ffffff"          # ô nhập
C_ACCENT = "#2f6fb5"         # xanh dương trầm
C_ACCENT_HOVER = "#255d99"
C_ACCENT_DIS = "#b9cde3"
C_ON_ACCENT = "#ffffff"      # chữ trên nút xanh
C_SOFT = "#eaf1f8"           # nền thanh công cụ
C_SOFT_BORDER = "#cfdeee"
C_SEL = "#dbe8f5"            # dòng đang chọn
C_HEAD = "#eef2f6"           # tiêu đề bảng
C_ODD = "#f7f9fb"            # dòng lẻ
C_TEXT = "#24303d"
C_MUTED = "#687585"
C_BORDER = "#d9e0e7"
C_GREEN = "#2e9e6a"
C_ORANGE = "#d98b1f"
C_RED = "#d64545"
C_BLUE = "#2f86c9"           # "mới" - xanh cyan
C_WARN_BG = "#fdf4e3"
C_SIDE = "#263240"
C_SIDE_CARD = "#2f3c4b"
C_SIDE_HOVER = "#38475a"
C_SIDE_ACTIVE = "#5fb3e8"
SIDE_W = 430          # thanh bên trái (mở rộng)
SIDE_W_MINI = 64      # thanh bên trái (thu gọn)
SIDE_MIN, SIDE_MAX = 240, 700   # giới hạn khi kéo đổi độ rộng
C_SIDE_TEXT = "#e3e9ef"
C_SIDE_MUTED = "#9aa8b6"
# màu phụ (đổi theo giao diện)
C_BTN_HOVER = "#e6eef6"
C_DIS_TEXT = "#a7b1bc"
C_DANGER_BG, C_DANGER_BORDER, C_DANGER_HOVER, C_DANGER_DIS = "#fbeeee", "#f0c9c9", "#f6dcdc", "#e2a9a9"
C_TROUGH = "#dde4ec"
C_SCROLL_ACT = "#c4cfdb"
C_SKIP = "#9aa5b1"
C_SIDE_OK, C_SIDE_BAD = "#8fd9b0", "#f2a7a7"
C_ERR_BG, C_ERR_FG = "#5a2a2f", "#ffdcdc"
C_FOOT = "#7f8e9e"
C_LOG_BG, C_LOG_FG = "#1f2933", "#c9e8d6"
C_CHECK_BORDER = "#b5c0cc"
C_GLYPH = "#c3ccd6"
ENERGY_EMPTY = "#e3e9ef"
ENERGY_SETS = {}              # màu riêng cho từng thanh (dl / up / all); trống = dùng ENERGY_COLORS
C_STAT1 = "#14b8a6"           # màu ô "Thư mục sẽ quét"

# ----- giao diện: "classic" = giao diện GỐC (v1.3, không xóa được) · "fresh" = giao diện MỚI (nền trắng, nút đỏ,
#       thanh bên cam nhạt, mục đang chọn vạch xanh lá) - chọn bằng nút "◐ Giao diện", xóa được ở Cài đặt > Chung.
C_SIDE_SEL_TEXT = "#ffffff"   # chữ mục đang chọn ở thanh bên
SIDE_FONT_ADD = 0             # cộng thêm cỡ chữ ở thanh bên
BAR_STYLE = "segment"         # thanh %: "segment" (ô vuông) / "smooth" (dải liền, chuyển màu)
LAYOUT = "classic"            # bố cục: "classic" (thanh bên + tab) / "workspace" / "movie"
AVATARS = False               # ảnh chữ cái tên phim trong bảng (cần Pillow)
C_CTA, C_CTA_HOVER = "", ""   # nút hành động phụ (Tải mục đã chọn); trống = theo C_ACCENT
STAT_COLORS = ()              # màu 4 ô thống kê; trống = mặc định
ROW_H_ADD = 0                 # tăng chiều cao dòng bảng
PILL_STATUS = False           # cột Trạng thái hiện thành nhãn có viền màu
LED_PANEL = False             # thanh bên: bảng ĐÈN TRẠNG THÁI + thông tin tài khoản PikPak (giao diện 4)
LED_LIST = False              # bảng đèn dạng danh sách thẻ nổi (giao diện 5, 6, 7)
BTN_3D = False                # nút nổi 3D
BAR_STRIPES = False           # thanh tải có sọc chéo
ANIM = False                  # hiệu ứng động: đèn nhịp thở, sọc chạy (giao diện 7)
STAT_ICONS = False            # ô thống kê có biểu tượng vuông màu
C_LED_PANEL, C_LED_CARD, C_LED_BD, C_LED_SHADOW = "#d3e7fa", "#ffffff", "#d5dee8", "#b4c8dc"
C_LED_TITLE, C_LED_OFF_TXT, C_LED_ERR_BG, C_LED_ERR_BD = "#000000", "#334155", "#fdeaea", "#f3b4b4"
LED_TXT_COLORS = {"ok": "#16a34a", "run": "#ea580c", "err": "#dc2626", "off": "#475569"}
SIDE_BOLD = False             # chữ thanh bên in đậm hết
C_SIDE_BRAND = "#ffffff"      # tên tool ở thanh bên
THEMES = {
    "classic": {},
    "fresh": {
        "C_BG": "#f4f4f5", "C_CARD": "#ffffff", "C_PANEL": "#fafafa", "C_FIELD": "#ffffff",
        "C_ACCENT": "#dc2626", "C_ACCENT_HOVER": "#b91c1c", "C_ACCENT_DIS": "#f5b5b5", "C_ON_ACCENT": "#ffffff",
        "C_SOFT": "#fef2f2", "C_SOFT_BORDER": "#fecaca", "C_SEL": "#fee2e2", "C_HEAD": "#f7f7f8",
        "C_ODD": "#fbfbfb", "C_TEXT": "#262626", "C_MUTED": "#71717a", "C_BORDER": "#e4e4e7",
        "C_GREEN": "#16a34a", "C_ORANGE": "#ea580c", "C_RED": "#dc2626", "C_BLUE": "#2563eb",
        "C_WARN_BG": "#fff7ed",
        "C_SIDE": "#dcefff", "C_SIDE_CARD": "#c7e4fc", "C_SIDE_HOVER": "#b2d8f8", "C_SIDE_ACTIVE": "#16a34a",
        "C_SIDE_TEXT": "#000000", "C_SIDE_MUTED": "#1e293b", "C_SIDE_SEL_TEXT": "#000000", "C_SIDE_BRAND": "#000000",
        "SIDE_FONT_ADD": 2, "SIDE_BOLD": True,
        "C_BTN_HOVER": "#fef2f2", "C_DIS_TEXT": "#b4b4bb",
        "C_DANGER_BG": "#fdecec", "C_DANGER_BORDER": "#f5c2c2", "C_DANGER_HOVER": "#fadada", "C_DANGER_DIS": "#e8a9a9",
        "C_TROUGH": "#ececee", "C_SCROLL_ACT": "#d4d4d8", "C_SKIP": "#a1a1aa",
        "C_SIDE_OK": "#166534", "C_SIDE_BAD": "#b91c1c", "C_ERR_BG": "#dc2626", "C_ERR_FG": "#ffffff",
        "C_FOOT": "#334155", "C_LOG_BG": "#1f1d1d", "C_LOG_FG": "#d9f99d", "C_CHECK_BORDER": "#c8c8ce",
        "C_GLYPH": "#e4e4e7", "ENERGY_EMPTY": "#ececee",
        "ENERGY_COLORS": ("#f87171", "#ef4444", "#dc2626", "#ea580c", "#f59e0b", "#16a34a"),
        "C_STAT1": "#ea580c",
    },
}
# ----- Giao diện 3: y như giao diện 2 (thanh bên xanh da trời nhạt) nhưng thanh tải là dải liền,
#       trạng thái trong bảng hiện thành nhãn có viền màu
THEMES["fresh2"] = dict(THEMES["fresh"], BAR_STYLE="smooth", PILL_STATUS=True,
                        ENERGY_SETS={"dl": ("#fca5a5", "#ef4444", "#dc2626"), "up": ("#93c5fd", "#2563eb"),
                                     "all": ("#86efac", "#16a34a")})
# ----- Giao diện 4: như giao diện 3 + thanh bên có thẻ cảnh báo, bảng đèn LED trạng thái, thông tin tài khoản PikPak
THEMES["fresh3"] = dict(THEMES["fresh2"], LED_PANEL=True)
# ----- Giao diện 5, 6, 7: nút nổi 3D, thanh tải sọc, ô thống kê có biểu tượng, bảng đèn dạng danh sách
THEMES["pro"] = dict(THEMES["fresh2"], LED_PANEL=True, LED_LIST=True, BTN_3D=True, BAR_STRIPES=True, STAT_ICONS=True,
                     C_SIDE="#e3f0fc", C_SIDE_CARD="#d3e7fa", C_SIDE_HOVER="#d0e5f8", C_BG="#eef1f5",
                     C_SIDE_MUTED="#1e293b")
THEMES["prodark"] = dict(THEMES["pro"], **{
    "C_BG": "#10172a", "C_CARD": "#151d31", "C_PANEL": "#1a2338", "C_FIELD": "#0f172a",
    "C_SOFT": "#2a1620", "C_SOFT_BORDER": "#5b2330", "C_SEL": "#3a1d29", "C_HEAD": "#1a2338", "C_ODD": "#172036",
    "C_TEXT": "#e5e7eb", "C_MUTED": "#94a3b8", "C_BORDER": "#2a3552",
    "C_GREEN": "#22c55e", "C_ORANGE": "#f97316", "C_RED": "#ef4444", "C_BLUE": "#3b82f6", "C_WARN_BG": "#2a2116",
    "C_SIDE": "#131b2f", "C_SIDE_CARD": "#182136", "C_SIDE_HOVER": "#1f2a44", "C_SIDE_TEXT": "#f1f5f9",
    "C_SIDE_MUTED": "#cbd5e1", "C_SIDE_SEL_TEXT": "#ffffff", "C_SIDE_BRAND": "#ffffff",
    "C_BTN_HOVER": "#26304a", "C_DIS_TEXT": "#64748b",
    "C_DANGER_BG": "#2a1a22", "C_DANGER_BORDER": "#5b2330", "C_DANGER_HOVER": "#3a2029", "C_DANGER_DIS": "#7f4b55",
    "C_TROUGH": "#0b1120", "C_SCROLL_ACT": "#334155", "C_SKIP": "#64748b",
    "C_SIDE_OK": "#4ade80", "C_SIDE_BAD": "#f87171", "C_ERR_BG": "#7f1d1d", "C_ERR_FG": "#ffffff",
    "C_FOOT": "#94a3b8", "C_LOG_BG": "#0a120d", "C_LOG_FG": "#d9f99d", "C_CHECK_BORDER": "#475569",
    "C_GLYPH": "#334155", "ENERGY_EMPTY": "#0b1120",
    "C_LED_PANEL": "#182136", "C_LED_CARD": "#1d2740", "C_LED_BD": "#2c3856", "C_LED_SHADOW": "#0b1020",
    "C_LED_TITLE": "#f8fafc", "C_LED_OFF_TXT": "#94a3b8", "C_LED_ERR_BG": "#3a1a22", "C_LED_ERR_BD": "#7f2a36",
    "LED_TXT_COLORS": {"ok": "#4ade80", "run": "#fb923c", "err": "#f87171", "off": "#94a3b8"}})
THEMES["proanim"] = dict(THEMES["pro"], ANIM=True, C_BLUE="#2f7fa3",
                         ENERGY_SETS={"dl": ("#fca5a5", "#ef4444", "#dc2626"), "up": ("#7cc0dd", "#2f7fa3"),
                                      "all": ("#86efac", "#16a34a")})
THEME_NAMES = {"classic": "Giao diện 1  (gốc v1.3)",
               "fresh": "Giao diện 2  (thanh bên xanh da trời nhạt)",
               "fresh2": "Giao diện 3  (thanh bên xanh da trời nhạt · thanh tải dải liền · nhãn trạng thái có viền)",
               "fresh3": "Giao diện 4  (như 3 · bảng đèn trạng thái · tài khoản PikPak)",
               "pro": "Giao diện 5  (sáng · nút nổi 3D · bảng đèn dạng danh sách)",
               "prodark": "Giao diện 6  (tối · như 5)",
               "proanim": "Giao diện 7  (nút nổi 3D · bảng đèn trạng thái · đèn nhịp thở, thanh tải sọc chạy)"}
THEME_SHORT = {"classic": "giao diện 1", "fresh": "giao diện 2", "fresh2": "giao diện 3", "fresh3": "giao diện 4", "pro": "giao diện 5",
               "prodark": "giao diện 6", "proanim": "giao diện 7"}


# v2.5: chỉ giữ giao diện 1, 3, 7 - giao diện đã bỏ tự chuyển sang giao diện gần giống
THEME_ALIAS = {"fresh": "fresh2", "fresh3": "fresh2", "pro": "proanim", "prodark": "proanim"}
for _k in THEME_ALIAS:
    THEMES.pop(_k, None)
    THEME_NAMES.pop(_k, None)
    THEME_SHORT.pop(_k, None)


def apply_theme(name):
    """Đổi bảng màu toàn cục (gọi trước khi dựng giao diện). Giao diện cũ đã bỏ (động, Dashboard) -> giao diện gốc."""
    name = THEME_ALIAS.get(name, name)
    name = name if name in THEMES else "classic"
    globals().update(THEMES[name])
    return name


def theme_label(cfg, key, short=False):
    """Tên giao diện (người dùng đổi được ở Cài đặt > Chung > Giao diện)."""
    custom = str((cfg.get("theme_names") or {}).get(key) or "").strip()
    if custom:
        return custom
    return (THEME_SHORT if short else THEME_NAMES).get(key, key)


def removed_themes(cfg):
    r = set(cfg.get("removed_themes") or []) & set(THEMES)
    r.discard("classic")
    return r


FONT = "Segoe UI"
MONO = "Consolas"             # số liệu kiểu màn hình máy

ICON64 = "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAMe0lEQVR42t2be4xd1XXGf2vvfe65d+6dhyemNJC4do0x75AGWxg7tqoSkN2Yxg7jYKuRmopIIVUraBLVSaFjo6K4qFJpo7ZSq0RVHynUDiCUOoAg9IEDxYlEGxzMKwmG8hB0PJ6ZO/dxzt6rf5x7Z8bjedw748fYW9r/3HPPOftbe+211vftfYRpWt+/qN27TTzA2j26RAObVNiiniUQVqIiLKQmqmBeEssRUR4Sw/4DO+XIZCwn3HbCL6rZbyK69u7a5cHmbge2GkuvKhAgeGUhNmMFDIhA8AwADxpfv+/AH8WHJuI67p7jntCvBhFFRNfs9ruCcc+7iFvF0+urPoS6D5p4FVUWYtfEa6j74Ks+iKfXRdwajHt+zW6/q4mLfjVTe0C/GnZLuPaOwV6zqPPbNjY3ppWABk1F1CIi6LR+szDaxPGpqqp4MeJcweBr4bFwdHjHs3/WM9DEOg6l4R6rvjrUm8sXv2cLdlU6kiYILnOos7mpoqSu5CJf8Qfr1fLGg1/vGmguBwPQtw2DCFFUuN/FdlUynCRAhCKocnZ3BIiS4SRxsV0VRYX7EckwA7KhX92/75Z0zVdru3KlXH8yWk9EJOIcbKqaRB25qD5S3/3M1+NdG/rVCais66+tQN0h9WrQIMjZ7vbTWwAxKlYCkl7+9O74FQeiWq/ujArWJUktFRGHKudoEw3euzh2SSXdCfLbct1XyhcY6w6LsSUNaSMwniYHaLxJ5MRQO3EZZ+H9ZIwpe5gYhwY/Enx6ibMu2mxd1JlWq0GMmOPzySksWhpvqiVQTxXvJ2QxAWcgjoScy34PQU+eFyRJcPl8pxfZ7PDpzWoiRNDT4fpGMkDD5QzokvOEZecbLvmwwdnM9iNVOPxm4LW3lXcHFWehlIcw5hHztICgGgCf3uwIuhQfkBDMqU751grlSgboE1dbfn2142MXCR3x1O9975jyzIuB7z6X8qNXAoUYIifz9wZVgw8QdKms/3JV0XDqln1j+VoDR4eVjyy3/O5NER9bMV6RTjWzZlJc2P+c5xuP1Pm/Y1DqAO/nGRYUEIOT4LMHhVMX6AwwOKT0rY+4Y2uOQgy+YXMxGdipwKhmxjECm1ZbPvLLefr/vsbzrwa6Sw0jzGNcBI+hwfDQU9MtMDSibP/ViK9tHwdvTRYIZea1im2wu9TDhYuF+26L+ehyQ3lUsTKPsTUwm1PBygxZd0YZKQc2XGX5yrYcIWSzamTqqnWm5mxmuFJB+NMvxJzfI9Tr2XvmOdaTU3MbshkRVdJE8akyOqp8oFO48zfjDKCM5/yp+qxB1GRG6C4Kd302JklCpoPMozvRk5PWyqNK6pViHnpKBmNgZFT5wm/kWNQpY26vCqMVPaHSEKCjILMaommEa1Zabrgm4rH/SugsCmGOMWxuZe+EyF6uZPevvdJx7WWOK5dbLjxvPMJ3dsiY2wOMVpXb+gcZGlacy35LU+jqFP767h6Khez/MxmieenTGyKePFiHeQRDJ2FuEVSAoWHloxdbbr0p5ppL3fS2kvE1rprdd2ySAZrXWq0iVeGKZZYVF1p+9pYnzsmcssKcPMAIjJSVbb+W445bCmMDCo2Zk0mR/ISXuvE+8bd2WghgLay5wnLwUMLiHpmTEZy0aQBrYeCY8sW+Ap/bHBNCNhhjyNJSaxrNcZFf51DiNo2+/YaYCxYbHvx+jZ/8zNNVlPa8qa2cLpn7fnJdjs9tjvE+m2FjzgCvbWSOrqKw+eM5/vbOTm77dJ5qVQk+k4FawdSyB4hAUofze4TbtxfGZuFMSyfaXA4Gfmtznl9YZNjzrTL5XKseEBqLd5ZuUEYrgZs/EdPdKWOzf8YVjkZqBEhS2LQux+e3FhgaCVhpAZcozNYNkNZhcZewaV1W1JwJt5/NQ5vV4o6NeS5bZqmMakaqZsTWQrUkKPV6YOkHLT2dMm10XwhGQLNAve3GPEmimNkrQW1hnUCaKFdd7DAmY2HWLkzRr+mZq6+M+ECXUK0p1k6fFVrOAuqVUmHhi8XNoqun07DsQku9psiMWaAFdUUaJEc5O9TiZozqyGcTJ8B0FW9rlaCCoJTL7RlgjKA0ZkUa6s+0/9dxdUgmvHvOAbf5sDC9ztsaGwyQs8ILh+uEUGx5QMf9r4GoIy9TiiDSuHaCOiTtz74IVOvK2+94clYgZBF/zh6gAWIHr7+RMjgUWNRtpmVsTQnryWdqfOfRalYzTHA/72G0pmOlbNNQozXlD+4dGg+umvGDgcHAlhsK3PjxeKzkbsUAR95M+d+3U3I5QcOMXKC1cityysDRwKNPVdixpThtJpDGINZcneP+71Z4/Ok6XSUZY3wikI+P5/0iGSM8+D/1MaNYm2kMV6yMWH1VNCtFnrz+9z9ZoV5TCjnwKjNxgdaUk5BCRyw89K9ljg2FaVNLc5AdBeHP7+zm8hWZk3V3CqWiUOyYWvQQgWJH9p/uTsFZYemHLH9xVzeLuk1LtUeTIf709ZRHvz9KqSAEz8xKlgSllU5QYqe8957nL781dHyQmwJMCJkR7vqdTro7DdU6M97TvKYK1RpEDu75/a4xtWc28E0PGR4J3PuNQZK6jpXCM+FqSxP0qdJVEvY/Pso/f2cEa8fFjKkCoPewYqlj9+91UqtpS0Cyml750q0lLl7m8C2u+4yWK7v+5CgvvlSnmJfsLNNsWmYrXGBiD6myqEv45j8M8d8v1HEuM8JUy8HazAhXXxbxtS92UqnOHHCcy/YPPv+ZItdfF5P6caIzk9c049EDD5V57odVFnUJIVVa4zlzVFMjC3987wA/OZwZoVmBNQWSZhfJWNrG9THbNxc4eixMCcpaeO/9wMYNMTs2F0iSLJtMft7E3vQ052D/42X+7h+P0dMlpEnrOOzKy760q5l6W+2EjHlVKoEn/62C98oHf9FRKpop5e4m4FVX5hgcgR+/lBDnZDwNSrbur/2VHHff3oW1mUFkFhnde3j9SMLffPMY//TAMPnYjJW9LeP55NY3269vG6xLTDYTo6OBnm7L0l+KKORlygKmGaQqFeXHb4KNzZgBRBpk60NQzDe2zWSWgAccHfQceSOlUg2UiuPO3BxfS1A2b3ljfgW+gDFCmir1mjIbtTAC+Q5DrRSPoVQgLteoj3jS0DrVdhZyOcGYue8Yu3nzG82ir5Us7bUkiKaB3EidemdmhKhcQ+qefF7a0xmaws48Tq62rQrPNBhtYwWZJCUaFYI1uEoz4rXPN+dL0N0ZYbgKKoKtJNgxEn9mqHNLekBrcWAO0zaR87Zrw3ByjsvM+0icSDaYTCvQueJpOwPFeYN1zMj02ogBzbwhbYNPk4zarromjzFychZmCzX/a6/WGDzqiWODartjH8c8yQO07bUswJd3nse69cXTunbfOJJw1853GHg/xUXSMEK7WyqKE5U5+awxMDIcWLOuyLr1xey0xmnYKxAg9cqHl0Tc9Kku/uq+91nUa/FzimWCUw2vWpO7yPuaihhpJwhFDt55K6FSCRQKp2+nxLpsmD99pUZkQYO2NYeqQa2NxYf6q06C/Nwad1EI9SCiban9+Zzw+ms19vS/y9Zbesb0vFMpnoeG4vPsf5Z56rEhih0GTbW9d6oEa50NIfm5g7CPwPUQBG1v6MFDR4fhR8+W+eEPyqf1SxIN0FGUbPbbv1uyY4Fhn9x0/YsXRBodFrEl1ZS5bHqdqX3CuZ0LUs0OxPuRRJJLzCNPXPoW3u+LTElQ9XPRBoI/M32OWoaPTEnwft8jT1z6lgPEp26PN+XPSjAmE9E4Rz+YyLZZfFpOfer2AGI2bHjKPvz08pe9r9yTc91GVdOxk5TnUldQ1TTnuo33lXsefnr5yxs2PJWd6unrU7t3r4Sb17/8eD5adH21/n4iYs6p74ZUQ5LPLY6qydEn9v3HxTf09anZu1e8jEVFhU+tfrE3zue+F0Vdq6rJQCI0P5tb6B8MTlXljW/TKKT5qDdKkqGDtWp948PPXTqQQZGJeU8NSOi79ge9Nnf+t50p3lhPB0E1RbBn3/eDqigeEZdzPaSh/Jivv7tj77PXDTSxnjCl/ajZ3bjwmbWv7BLkD53tcIkfIWjavGHhflWmqs2a0IgzkS2R+tFU0XseOLBi12SM0/h00ytEb1l76HKIbxd0q5GoF5SgnhDq7SmPp4UhKMbkMGIBIWgyoMiDULvv/gOXH5qIqyVFqREYPUDf2heWWM1tEpUtqmEJElaq6oLyAhFR1LwkYo6o6ENe6vv3HrjiyGQsk9v/Ax7DJYt4zTQbAAAAAElFTkSuQmCC"
ICON28 = "iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAYAAAByDd+UAAAFbklEQVR42pWW+4ucZxXHP+e8l5md2dlEWVq00BRjQ1NErD8YElutiUIsJIEtK9SiSL1A9gcNaERQXFbFC80PFewu7T+gNCYiipdSCaQlodVCqYSK9Ubxlq5pNjvZmX3feZ5z/OGdmZ29JGEfeN4fXs5zvuec77kJuMzOInNzYge+5Q95aifc2IfTwgERYTvH3RFAaIvyogR94sI35Vezs65zc7hMT3ty+rTE/bO9+aSWHncHCw7msD2oEVBABU0FEYhFWLg4l81MT3siAPu/UczXWvnxst2zvrDeSqcMP+B+AyFzQyBvZVq0y4WL36nNyP1f7x7WrP7rWPYCeMIt/BIREoUQnWiVcJoKApg5vqW/EpM8S623+vGUKCdFcIlR5CZ8uUOiUPacdgE7mzBRF8zhyrJhDuNjlZyvt1rcTSRkTpSTqUTb51aIuic38yxR6HScyR3CZw+lHHpfwttbgplz6Q3n9POBi69Farmg0udxGH5PvCwQt33y4S93Hbetw6eVparQ7sB736V877Eakzu2DsTPLwS+/5OSWj6SPBsUphKCIyLDOPSFkgS6XacXqoS9Y1I59YUaO5qyKdSDMB47kLLUduZ/VtBqCjGO6BTAg6diLhtNUYXla86eOxOO3Z+x6x0Jd0wKO5rCsy8U/PLcKgBHD9b56AdruINKZdgjB1POniu42jZqGcSwjlBJJfomrtrLztSDOV/8RJ1GXdZ586/LxvN/KAG47958+F8V3CDPhCP7M5462yVtCokKNsKYSjQGN3Gju2Lcd7fytU+P0agLIYIZhAAikGfQagqtppBnbIqMO3zuWI0nT44znkMojMTWMFTNGd7oeDAeO1oHIEZIk0qRjBS5WXW3KniR6t0H3pPylU81CIUhoxhDZDNCYdw2AXvuSocWD060SpH5aCOp/kXb7Gk0eOD9GffsUoqOod7HkegMLtFJcJItGlueVZk7VpNhZo7VhCRhU2hF1vLk9p1CLA3tY6QyYnIusPSW8Z/Lkd27UswqkOXrztlnu6SJ8OqfeuRZ1cp+/2rJauGE4Dx8eIyJ8cqY0X61uBjJcCSC+BZJU3aNn/5iBZHKixih2RA6XefbT7Z5+VJV2HkOL18q+cFTbRavGs1GlY0DDlXhhZcK/vx6SSOrcqMf0jVA6xkTY/Db51b4zXMd0rTqNgAzjzaZ+WST7mqlVAVWV+HIoTpf/fz4Gtexisq1ZeNHTy+RizOKsakOMWe8Bqd+eBWLzuGPNYecfukzTf79P+OlV0pUnHv3ZMydmBjW7+C8uRj57qmrXFkMNBtCDGucypGpf/rG2Sn9wV2WsHt3xtt2Km6Vt92u88f/Ki7CXROBd04mhOhD3szgr3/rsXTNaIxV7W2UUzl67A2/4YRIhNXCiaGa/oMRlY+nuAp2vUfZbwjD7ihVt0lStpwJqUTbkFdrD1euR1RhXZUYrL5VVmNVIdnw0gw0FQiC+OapmqqJuNu6iakC3Y4zNTXBAw+OY+ao3nzBcXNEhX/8veTp+SvIRjQHEZWUGFYUbVagMpyD3jN23Zlzz97atgBrOaQ4NjL1cEdEccKKTB16/Xdp2vhIL3RMRJJRi0KE1oRua2HrrBhuVBz6cHOMWdrQEDrn0iTwuKocTFzcbY1PEcgVOkthW4CaVKuhD0vBXUVdTSQJPC4AD3/otflGfvvxbvmm9ZuhymBUi2zaim64i1b1hA/eepWnY/lt2ikvL5w5v3dGp6efSc6c3ztTFIsLuTQ0o64aQWKsmnq/JUm4xR3IREdjRCNk1DWXhhbF4sKZ83tnpqefSWR01X/kwF8eAk4YYZ9Aq2/gdvdvrxKEtpK+CDzx4wvvHq76/wcfdelN5/BKZQAAAABJRU5ErkJggg=="

def resolve_iphone_dir(value):
    """Thư mục COPY_TO_IPHONE thật trên máy này. Đường dẫn nằm trong thư mục người dùng KHÁC
    (VD C:\\Users\\Duy Anh\\... chép Data từ máy khác sang máy dùng tài khoản Admin) -> đổi sang thư mục
    người dùng hiện tại (C:\\Users\\Admin\\...)."""
    d = os.path.normpath(from_portable(str(value or "").strip())) if str(value or "").strip() else ""
    if not d:
        return default_iphone_dir()
    home = os.path.normpath(os.path.expanduser("~"))
    users = os.path.dirname(home)                            # C:\\Users
    if os.path.normcase(d).startswith(os.path.normcase(users) + os.sep):
        rest = d[len(users) + 1:]
        owner, _, sub = rest.partition(os.sep)
        if owner and os.path.normcase(os.path.join(users, owner)) != os.path.normcase(home) and \
                owner.lower() not in ("public", "default", "all users"):
            return os.path.join(home, sub) if sub else home
    return d


def default_iphone_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads", "Video", "COPY_TO_IPHONE")


def default_download_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads", "PikPak Auto Save")


DEFAULT_CONFIG = {
    "window": {},
    "auto_scan": False,
    "auto_interval": 60,
    "notify": True,
    "tray_on_close": True,
    "start_with_windows": False,
    "startup_scan": True,
    "share_root": "https://mypikpak.com/s/VOyELoBfemkzMwlEob9EwA-Ho2",   # link chia sẻ gốc để chọn thư mục phim
    "raidrive_root": "",          # (không dùng)
    "rd_remote_base": "",         # thư mục trên PikPak tương ứng gốc ổ RaiDrive (thường để trống)
    "download_dir": r"D:\DOWNLOAD HH3D",   # thư mục tải về: <thư mục>\<Tên phim>\
    "dl_movie_sub": True,         # tạo thư mục con theo tên phim trong thư mục tải về
    "dl_method": "copy",          # copy: copy từ ổ RaiDrive (đa luồng); auto: rclone tải thẳng
    "copy_threads": 4,            # số luồng copy song song từ ổ RaiDrive
    "delay": 2,
    "organize": False,            # copy thêm 1 bản sang HDD rời (tắt mặc định)
    "library_root": r"O:\3 - DOWNLOAD HH3D",   # ổ HDD rời: <thư mục>\<Tên phim>\
    "update_repo": "laocuumon1982-cpu/PikPak-Auto-Save",
    "update_check": True,
    "side_collapsed": False,
    "backup_on": True,
    "pikpak_user": "",
    "pikpak_pass": "",
    "profiles": {},
    "pikpak_on": True,            # lưu 1 bản vào My PikPak
    "pikpak_remote": "pikpak",
    "pikpak_root": "My Pack/2026",
    "pk_movie_sub": True,         # My PikPak: tạo thư mục con theo tên phim
    "rclone_path": "",
    "health_check": True,
    "stale_days": 7,
    "extensions": ".mkv .mp4 .avi .ts .m4v .mov",
    "bwlimit": "",                # giới hạn tốc độ rclone, VD 20M (trống = không giới hạn)
    "rd_check_min": 0,
    "rd_autostart": False,
    "raidrive_exe": "",           # đường dẫn RaiDrive.exe (trống = tự tìm)
    "rd_to_tray": False,
    "admin_lock_min": 10,         # tự khóa tab Thư mục phim / Cài đặt sau N phút không thao tác (0 = không)
    "iphone_on": True,            # copy thêm 1 bản vào thư mục chung COPY_TO_IPHONE
    "iphone_dir": default_iphone_dir(),
    "folders": [],
}


# ----------------------------------------------------------------- tiện ích
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(default, dict) and isinstance(data, dict):
            merged = dict(default)
            merged.update(data)
            return merged
        return data
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


def save_json(path, data):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def to_date(value):
    if value in (None, "", 0, "0"):
        return None
    try:
        v = float(value)
        if v > 1e12:
            v /= 1000
        return dt.datetime.fromtimestamp(v).date()
    except (TypeError, ValueError, OSError):
        pass
    s = str(value)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def name_key(name):
    """Chuẩn hóa tên file để so khớp (IDM có thể thay ký tự đặc biệt)."""
    return re.sub(r"[^0-9a-z]+", "", strip_accents(str(name)))


def folder_link(code):
    return code or ""


def sub_label(sub, name):
    """Tên hiển thị kèm thư mục con: 'Season 2 › Tap 01.mp4'."""
    return f"{sub}  ›  {name}" if sub else name


def strip_accents(text):
    """Bỏ dấu tiếng Việt + chữ thường, để lọc từ khóa không phân biệt dấu/hoa thường."""
    text = unicodedata.normalize("NFD", str(text).replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def one_line(text):
    """Ghi chú nhiều dòng -> 1 dòng để hiện trong bảng."""
    return " · ".join(x.strip() for x in str(text or "").splitlines() if x.strip())


def clean_paste(text):
    """Bỏ ký tự Tk không hiển thị được (emoji ngoài BMP) để dán không bị lỗi."""
    return "".join(ch for ch in str(text) if ord(ch) <= 0xFFFF).replace("\r\n", "\n").replace("\r", "\n")


def read_clipboard_windows():
    """Đọc clipboard bằng Windows API (ổn định hơn Tk khi có tiếng Việt / emoji)."""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetClipboardData.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not u32.OpenClipboard(None):
        return None
    try:
        h = u32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return None
        ptr = k32.GlobalLock(h)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def natural_key(text):
    """Sắp xếp 'Tap 2' trước 'Tap 10'."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", strip_accents(text))]


def split_keywords(text):
    return [strip_accents(k).strip() for k in re.split(r"[,;]", text or "") if k.strip()]


def match_keywords(name, include, exclude):
    n = strip_accents(name)
    inc, exc = split_keywords(include), split_keywords(exclude)
    if inc and not any(k in n for k in inc):
        return False
    return not any(k in n for k in exc)


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip().rstrip(".")
    return name or "_"


def local_dir_for(cfg, folder_cfg, movie):
    """Đích đến trên HDD của 1 phim: <Đích HDD của thư mục>[\\<Tên phim>] ('' nếu không copy về HDD)."""
    d = from_portable(str((folder_cfg or {}).get("local_dir", "") or "").strip())
    if not d:
        return ""
    return os.path.join(d, safe_name(movie)) if (folder_cfg or {}).get("sub_movie", True) and movie else d


_TAG_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】")


def series_title(name):
    """Tên phim từ tên file: '[HH3D] Tiên Nghịch - Tập 98 [4K].mp4' -> 'Tiên Nghịch'."""
    stem = os.path.splitext(str(name))[0]
    t = re.sub(r"[._]+", " ", _TAG_RE.sub(" ", stem))
    m = re.search(r"(?i)(?:\bS\d{1,2}\s*E\d{1,4}\b|\b(?:t[aậ]p|tap|ep(?:isode)?|e)\s*\d{1,4}\b)", t)
    if m:
        t = t[:m.start()]
    else:
        nums = [x for x in re.finditer(r"(?<![\d.])(\d{1,4})(?![\d.])", _NOISE_RE.sub(lambda z: " " * len(z.group(0)), t))
                if not 1900 <= int(x.group(1)) <= 2099]
        if nums:
            t = t[:nums[-1].start()]
    t = _NOISE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—_|:+#")
    return t or stem


SPLIT_CHOICES = {"auto": "Tự động: thư mục con cấp 1, không có thì theo tên file",
                 "sub": "Theo thư mục con cấp 1", "file": "Theo tên file (bỏ số tập)",
                 "folder": "Cả nguồn là 1 phim"}


def movie_of(folder_cfg, sub, name):
    """Tên phim của 1 file trong nguồn (nguồn có thể chứa nhiều phim)."""
    mode = (folder_cfg or {}).get("split", "auto")
    fname = (folder_cfg or {}).get("name") or "Khác"
    first = str(sub or "").split(" › ")[0].strip()
    if mode == "folder":
        return fname
    if mode == "sub":
        return first or fname
    if mode == "file":
        return series_title(name)
    return first or series_title(name)


def index_local_files(dirs, depth=3):
    """{khóa tên: [(đường dẫn, dung lượng, đuôi)]} của các file trong các thư mục (tối đa 3 cấp)."""
    idx = {}
    for root in dirs:
        if not root or not os.path.isdir(root):
            continue
        base = root.rstrip("\\/").count(os.sep)
        for cur, sub, files in os.walk(root):
            if cur.count(os.sep) - base >= depth:
                sub[:] = []
            for fn in files:
                stem, ext = os.path.splitext(fn)
                try:
                    size = os.path.getsize(os.path.join(cur, fn))
                except OSError:
                    continue
                rec = (os.path.join(cur, fn), size, ext.lower())
                keys = {name_key(stem), name_key(re.sub(r"(_\d+|\s*\(\d+\))$", "", stem))}
                for k in keys:
                    if k:
                        idx.setdefault(k, []).append(rec)
    return idx


def find_local(idx, name, size):
    """Trả về đường dẫn nếu tập đã có trên máy (cùng tên, cùng đuôi, đủ dung lượng)."""
    stem, ext = os.path.splitext(name)
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        size = 0
    for path, fsize, fext in idx.get(name_key(stem), []):
        if fext == ext.lower() and (not size or fsize >= size * 0.995):
            return path
    return None


def copy_to_library(path, dest_dir):
    """Copy file đã tải xong vào thư mục phim (file gốc vẫn nằm trong thư mục IDM). Trả về đường dẫn bản copy."""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(dest)):
        return path
    size = os.path.getsize(path)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return dest          # đã copy trước đó rồi
    stem, ext = os.path.splitext(dest)
    n = 2
    while os.path.exists(dest):
        cand = f"{stem} ({n}){ext}"
        if os.path.exists(cand) and os.path.getsize(cand) == size:
            return cand
        dest = cand
        n += 1
    last = None
    for _ in range(5):  # IDM có thể còn giữ file vài giây
        try:
            tmp = dest + ".part"
            shutil.copy2(path, tmp)
            os.replace(tmp, dest)
            return dest
        except OSError as e:
            last = e
            try:
                os.remove(dest + ".part")
            except OSError:
                pass
            time.sleep(2)
    raise last


move_to_library = copy_to_library   # tên cũ


# ----------------------------------------------------------------- Ổ di động / hồ sơ máy / bảo mật nhẹ
def tool_drive():
    return os.path.splitdrive(str(BASE))[0]          # VD "E:" (ổ đang chứa tool)


def to_portable(value):
    """Đường dẫn nằm cùng ổ với tool -> lưu dạng @TOOL@\\... (đổi ký tự ổ vẫn đúng)."""
    out = []
    for part in str(value or "").split(";"):
        part = part.strip()
        drv, rest = os.path.splitdrive(part)
        td = tool_drive()
        out.append("@TOOL@" + rest if (drv and td and drv.upper() == td.upper()) else part)
    return "; ".join(x for x in out if x)


def from_portable(value):
    return str(value or "").replace("@TOOL@", tool_drive())


_SECRET_KEY = b"PikPakShare-DuyAnh"


def enc_secret(text):
    """Mã hóa nhẹ (không để mật khẩu dạng chữ thường trong file cấu hình)."""
    import base64
    if not text:
        return ""
    data = text.encode("utf-8")
    return "x1:" + base64.urlsafe_b64encode(bytes(b ^ _SECRET_KEY[i % len(_SECRET_KEY)]
                                                  for i, b in enumerate(data))).decode()


def dec_secret(text):
    import base64
    if not text or not str(text).startswith("x1:"):
        return text or ""
    try:
        data = base64.urlsafe_b64decode(str(text)[3:].encode())
        return bytes(b ^ _SECRET_KEY[i % len(_SECRET_KEY)] for i, b in enumerate(data)).decode("utf-8")
    except Exception:
        return ""


def make_backup_zip(dest):
    """Nén các file dữ liệu quan trọng vào 1 file zip."""
    import zipfile
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in BACKUP_FILES:
            fp = DATA_DIR / name
            if fp.is_file():
                z.write(fp, name)
        z.comment = f"{APP_NAME} | {MACHINE} | {dt.datetime.now():%Y-%m-%d %H:%M}".encode("utf-8")
    return dest


# ----------------------------------------------------------------- PikPak (qua rclone)
RCLONE_EXE = BASE / ("rclone.exe" if os.name == "nt" else "rclone")
RCLONE_ZIP_URL = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"


def find_rclone(pref=""):
    """v5.8: rclone.exe LUÔN nằm cùng thư mục tool (đi theo ổ di động), không chọn đường dẫn nữa."""
    for c in (RCLONE_EXE, DATA_DIR / RCLONE_EXE.name):
        if c.is_file():
            return str(c)
    return ""


def download_rclone(progress=None):
    """Tải rclone.exe (bản Windows 64-bit) từ rclone.org về thư mục tool."""
    import tempfile
    import zipfile
    tmp = Path(tempfile.gettempdir()) / "rclone_fad.zip"
    with requests.get(RCLONE_ZIP_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done * 100 // total)
    with zipfile.ZipFile(tmp) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("/rclone.exe") or n.lower() == "rclone.exe"), None)
        if not name:
            raise RuntimeError("Không thấy rclone.exe trong file tải về")
        part = Path(str(RCLONE_EXE) + ".part")
        with z.open(name) as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(part, RCLONE_EXE)
    try:
        tmp.unlink()
    except OSError:
        pass
    return str(RCLONE_EXE)


def rclone_conf_user(remote="pikpak"):
    """Tài khoản PikPak đang lưu trong rclone.conf (mục [remote], dòng user = ...)."""
    try:
        txt = RCLONE_CONF.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(r"^\[" + re.escape(remote) + r"\]\s*$(.*?)(?=^\[|\Z)", txt, re.M | re.S)
    if not m:
        return ""
    u = re.search(r"^\s*user\s*=\s*(.+?)\s*$", m.group(1), re.M)
    return u.group(1) if u else ""


def run_rclone(rclone, args, timeout=60):
    """Chạy rclone ẩn cửa sổ. Trả về (mã thoát, stdout, stderr)."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        p = subprocess.run([rclone, "--config", str(RCLONE_CONF)] + list(args), capture_output=True, text=True,
                           encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=flags)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Quá thời gian chờ"
    except OSError as e:
        return -1, "", str(e)


def pikpak_join(*parts):
    return "/".join(str(x).strip().strip("/\\") for x in parts if str(x).strip().strip("/\\"))


def pikpak_folder(cfg, folder_cfg, movie):
    """Đích đến trên My PikPak: <Đích PikPak của thư mục>[/<Tên phim>] ('' nếu không lưu)."""
    base = pikpak_join(str((folder_cfg or {}).get("pikpak_dir", "") or ""))
    if not base:
        return ""
    return pikpak_join(base, safe_name(movie or "Khác")) if (folder_cfg or {}).get("sub_movie", True) else base


def pikpak_dest(cfg, folder_cfg, movie):
    """remote:<Thư mục lưu>/<Tên phim>"""
    return f"{cfg.get('pikpak_remote', 'pikpak') or 'pikpak'}:{pikpak_folder(cfg, folder_cfg, movie)}"


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{os.path.abspath(__file__)}" --startup'


def set_startup(enabled):
    """Bật/tắt khởi động cùng Windows (HKCU\\...\\Run)."""
    if os.name != "nt":
        return
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, "PikPakShare", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, "PikPakShare")
            except FileNotFoundError:
                pass


# ----------------------------------------------------------------- Nguồn phim: thư mục RaiDrive / link chia sẻ PikPak
class SourceError(Exception):
    pass


FshareError = SourceError          # tên cũ dùng ở vài chỗ
SHARE_RE = re.compile(r"mypikpak\.com/s/([A-Za-z0-9_-]+)(?:/([A-Za-z0-9_-]+))?")
RD_TOKEN = "@RD@"                  # đường dẫn tương đối theo ổ RaiDrive của từng máy


def is_share(src):
    return bool(SHARE_RE.search(str(src or "")))


def share_parts(src):
    """(share_id, parent_id, pass_code) của link chia sẻ PikPak."""
    s = str(src or "").strip()
    m = SHARE_RE.search(s)
    if not m:
        return None, None, ""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(s).query)
    pwd = (q.get("pwd") or q.get("pass_code") or q.get("password") or [""])[0]
    if not pwd and "|" in s:
        pwd = s.split("|", 1)[1].strip()
    return m.group(1), m.group(2), pwd


def rd_root(cfg):
    r = from_portable(str(cfg.get("raidrive_root", "") or "").strip())
    if r and len(r) == 2 and r[1] == ":":
        r += os.sep
    return r


def raidrive_running():
    """RaiDrive.exe (ứng dụng, không tính dịch vụ RaiDrive.Service) có đang chạy không. None = không biết."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq RaiDrive*", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15).stdout
        return any(_is_rd_ui(line.split('","')[0].strip('"')) for line in out.splitlines() if line.strip())
    except Exception:
        return None


def _is_rd_ui(name):
    """Tên tiến trình là ứng dụng RaiDrive (không tính dịch vụ / trình cập nhật)."""
    n = (name or "").lower()
    return n.startswith("raidrive") and n.endswith(".exe") and not any(
        x in n for x in ("service", "svc", "update", "helper", "uninst", "setup"))


def raidrive_windows(log=None):
    """Danh sách cửa sổ chính của RaiDrive: [(hwnd, tiêu đề, tên tiến trình, đang hiện)]."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    user32, k32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")    # bản riêng, không đụng argtypes chung
    enum_proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proto, wintypes.LPARAM]
    for fn in ("IsWindowVisible", "GetWindowTextLengthW", "IsIconic"):
        getattr(user32, fn).argtypes = [wintypes.HWND]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    names = {}

    def proc_name(pid):
        if pid not in names:
            n = ""
            h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        n = os.path.basename(buf.value)
                finally:
                    k32.CloseHandle(h)
            names[pid] = n
        return names[pid]

    res = []

    def _cb(hwnd, _l):
        try:
            ln = user32.GetWindowTextLengthW(hwnd)
            if ln <= 0 or user32.GetWindow(hwnd, 4):       # bỏ cửa sổ không tên / cửa sổ con (GW_OWNER)
                return True
            buf = ctypes.create_unicode_buffer(ln + 1)
            user32.GetWindowTextW(hwnd, buf, ln + 1)
            title = buf.value
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pn = proc_name(pid.value)
            if _is_rd_ui(pn) or (not pn and title.lower().startswith("raidrive")):
                res.append((hwnd, title, pn, bool(user32.IsWindowVisible(hwnd))))
        except Exception:
            pass
        return True
    cb = enum_proto(_cb)
    user32.EnumWindows(cb, 0)
    return res


def hide_raidrive_windows(timeout=120, settle=25, log=None):
    """Thu cửa sổ RaiDrive xuống khay (ẩn cửa sổ, biểu tượng RaiDrive vẫn ở góc đồng hồ).
    Canh tối đa `timeout` giây: RaiDrive hay hiện màn hình chờ, rồi cửa sổ chính, có khi hiện lại sau khi
    kết nối ổ -> lần nào hiện là ẩn, dừng khi đã yên `settle` giây kể từ lần ẩn cuối. Trả về số lần ẩn."""
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    hidden, t0, last, seen = 0, time.time(), None, set()
    while time.time() - t0 < timeout:
        for hwnd, title, pn, vis in raidrive_windows():
            if not vis:
                continue
            user32.ShowWindow(hwnd, 0)                         # SW_HIDE
            time.sleep(0.2)
            if user32.IsWindowVisible(hwnd):                   # bị chặn (VD RaiDrive chạy quyền Admin)
                user32.PostMessageW(hwnd, 0x0112, 0xF020, 0)    # WM_SYSCOMMAND / SC_MINIMIZE
                time.sleep(0.3)
                if user32.IsWindowVisible(hwnd) and hwnd not in seen and log:
                    log(f"⚠ Windows không cho ẩn cửa sổ \"{title}\" ({pn or '?'}) - có thể RaiDrive đang chạy "
                        "bằng quyền Administrator: bỏ \"Run as administrator\" của RaiDrive hoặc chạy tool bằng "
                        "quyền Admin.")
            seen.add(hwnd)
            hidden += 1
            last = time.time()
        if last and time.time() - last > settle:
            break
        time.sleep(0.5)
    if not hidden and log:
        if raidrive_windows():
            log("▣ RaiDrive đang nằm dưới khay hệ thống.")
        else:
            log("⚠ Không thấy cửa sổ RaiDrive để thu nhỏ.")
    return hidden


def find_raidrive_exe(custom=""):
    """Tìm RaiDrive.exe: đường dẫn tự chọn -> thư mục cài đặt thường gặp -> registry."""
    custom = from_portable(str(custom or "").strip())
    if custom and os.path.isfile(custom):
        return custom
    if os.name != "nt":
        return ""
    env = os.environ.get
    bases = [env("ProgramFiles", r"C:\Program Files"), env("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             env("ProgramW6432", ""), os.path.join(env("LOCALAPPDATA", ""), "Programs")]
    for b in bases:
        if not b:
            continue
        for sub in (r"OpenBoxLab\RaiDrive Mount\RaiDrive.Mount.exe", r"RaiDrive\RaiDrive.exe",
                    r"OpenBoxLab\RaiDrive\RaiDrive.exe", r"RaiDrive Mount\RaiDrive.Mount.exe"):
            c = os.path.join(b, sub)
            if os.path.isfile(c):
                return c
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\RaiDrive.exe") as k:
                    v = winreg.QueryValue(k, None)
                    if v and os.path.isfile(v.strip('"')):
                        return v.strip('"')
            except OSError:
                pass
            for path in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    with winreg.OpenKey(hive, path) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            try:
                                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                                    name = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                                    if "raidrive" not in name.lower():
                                        continue
                                    for val in ("InstallLocation", "DisplayIcon"):
                                        try:
                                            v = str(winreg.QueryValueEx(sk, val)[0]).strip('"').split(",")[0]
                                        except OSError:
                                            continue
                                        c = v if v.lower().endswith(".exe") else os.path.join(v, "RaiDrive.exe")
                                        if os.path.isfile(c) and "uninst" not in os.path.basename(c).lower():
                                            return c
                            except OSError:
                                continue
                except OSError:
                    pass
    except Exception:
        pass
    return ""


def to_rd(cfg, path):
    """Đường dẫn nằm trong ổ RaiDrive -> '@RD@\\...' (không phụ thuộc ký tự ổ của từng máy)."""
    root = rd_root(cfg)
    p = os.path.normpath(str(path or "").strip())
    if root and os.path.normcase(p + os.sep).startswith(os.path.normcase(os.path.normpath(root).rstrip("\\/") + os.sep)):
        rel = os.path.relpath(p, root)
        return RD_TOKEN + ("" if rel == "." else os.sep + rel)
    return to_portable(p)


def resolve_src(cfg, src):
    """Nguồn của thư mục -> đường dẫn thật trên máy này (link chia sẻ giữ nguyên)."""
    s = str(src or "").strip()
    if is_share(s):
        return s
    if s.startswith(RD_TOKEN):
        root = rd_root(cfg)
        rest = s[len(RD_TOKEN):].lstrip("\\/")
        return os.path.join(root, rest) if root else ""
    return from_portable(s)


def src_key(cfg, src):
    """Khóa so trùng nguồn."""
    s = str(src or "").strip()
    sid, parent, _ = share_parts(s)
    if sid:
        return f"S:{sid}:{parent or ''}"
    return "L:" + os.path.normcase(os.path.normpath(resolve_src(cfg, s) or s)).rstrip("\\/")


def clean_src(cfg, text):
    """Chuẩn hóa nguồn người dùng nhập: link chia sẻ PikPak hoặc đường dẫn thư mục. None nếu không hợp lệ."""
    t = str(text or "").strip().strip('"').strip()
    if not t:
        return None
    sid, parent, pwd = share_parts(t)
    if sid:
        return f"https://mypikpak.com/s/{sid}" + (f"/{parent}" if parent else "") + (f"?pwd={pwd}" if pwd else "")
    if t.startswith(RD_TOKEN):
        return t
    if re.match(r"^[A-Za-z]:[\\/]?", t) or t.startswith(("\\\\", "/")):
        return to_rd(cfg, t)
    return None


def remote_of(cfg, path):
    """File / thư mục trên ổ RaiDrive -> đường dẫn rclone 'pikpak:...' (None nếu không nằm trong ổ RaiDrive)."""
    root = rd_root(cfg)
    if not root or not path:
        return None
    p = os.path.normpath(path)
    r = os.path.normpath(root).rstrip("\\/")
    if not os.path.normcase(p + os.sep).startswith(os.path.normcase(r + os.sep)):
        return None
    rel = os.path.relpath(p, root)
    rel = "" if rel == "." else rel.replace("\\", "/")
    remote = cfg.get("pikpak_remote", "pikpak") or "pikpak"
    return f"{remote}:{pikpak_join(cfg.get('rd_remote_base', ''), rel)}"


def new_folder_id():
    import uuid
    return uuid.uuid4().hex[:10]


def fid(f):
    """Mã cố định của 1 thư mục nguồn (không đổi khi đổi ký tự ổ / máy khác)."""
    if not f.get("id"):
        f["id"] = new_folder_id()
    return f["id"]


def get_code(src):
    """Giữ tương thích: mã từ link chia sẻ (thư mục cục bộ dùng fid)."""
    sid, parent, _ = share_parts(src)
    return (sid + (":" + parent if parent else "")) if sid else None


class LocalSource:
    """Thư mục trên máy / ổ RaiDrive (mount PikPak WebDAV)."""

    def __init__(self, path, folder_id, log=None):
        self.path, self.fid, self.log = path, folder_id, log or (lambda m: None)
        self.errors, self.subs, self.subdirs = [], {}, []
        self._warned_date = True

    def list_folder(self, code=None, info=None):
        if not self.path or not os.path.isdir(self.path):
            raise SourceError(f"Không thấy thư mục {self.path or '(chưa có ổ RaiDrive?)'} - ổ RaiDrive đã kết nối chưa?")
        try:
            names = os.listdir(self.path)
        except OSError as e:
            raise SourceError(f"Không đọc được {self.path}: {e}")
        if info is not None:
            info.append((1, len(names), len(names), [], None, None))
        return os.path.basename(os.path.normpath(self.path)), names

    def walk(self, code=None, sub="", _seen=None, _depth=0):
        self.errors, self.subs, self.subdirs = [], {}, []
        self.list_folder()
        base = os.path.normpath(self.path)
        for cur, dirs, files in os.walk(base, onerror=lambda e: self.errors.append(
                (os.path.relpath(getattr(e, "filename", "") or base, base), str(e)))):
            rel_dir = os.path.relpath(cur, base)
            rel_dir = "" if rel_dir == "." else rel_dir
            depth = 0 if not rel_dir else rel_dir.count(os.sep) + 1
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$")) and d.lower() != "system volume information")
            if depth >= 12:
                dirs[:] = []
            sub_label_ = rel_dir.replace(os.sep, " › ")
            for d in dirs:
                self.subdirs.append({"path": ((sub_label_ + " › ") if sub_label_ else "") + d,
                                     "code": os.path.join(cur, d)})
            n = 0
            for fn in files:
                if fn.startswith((".", "~$")) or fn.lower().endswith((".part", ".partial", ".tmp", ".crdownload")):
                    continue
                p = os.path.join(cur, fn)
                try:
                    st = os.stat(p)
                except OSError as e:
                    self.errors.append((sub_label_ or fn, str(e)))
                    continue
                rel = (rel_dir + os.sep + fn) if rel_dir else fn
                n += 1
                yield {"linkcode": f"{self.fid}:{rel.replace(os.sep, '/')}", "name": fn, "size": st.st_size,
                       "created": st.st_mtime, "_sub": sub_label_, "_path": p, "_rel": rel.replace(os.sep, "/")}
            self.subs[sub_label_] = n

    @staticmethod
    def code_of(it):
        return it.get("linkcode", "")

    @staticmethod
    def is_dir(it):
        return False

    def item_date(self, it):
        return to_date(it.get("created"))


# ---- PikPak API (tự viết, tối thiểu): đăng nhập + đọc link chia sẻ + lưu (restore) về My PikPak
PK_USER = "https://user.mypikpak.com"
PK_API = "https://api-drive.mypikpak.com"
PK_CLIENT_ID = "YNxT9w7GMdWvEOKa"
PK_CLIENT_SECRET = "dbw2OtmVEeuUvIptb1Coyg"
PK_SESSION = PK_SESSION_FILE


class PikPakAPI:
    def __init__(self, user, password, log=None):
        import hashlib
        self.user, self.password, self.log = user, password, log or (lambda m: None)
        self.web = requests.Session()
        self.web.headers.update({"User-Agent": BROWSER_UA, "Content-Type": "application/json; charset=utf-8"})
        self.s = load_json(PK_SESSION, {}) if PK_SESSION else {}
        if self.s.get("user") != user:
            self.s = {"user": user}
        self.s.setdefault("device_id", hashlib.md5(f"fad-{user}".encode()).hexdigest())
        self.lock = threading.Lock()

    def _save(self):
        try:
            save_json(PK_SESSION, self.s)
        except OSError:
            pass

    def _post(self, url, data, headers=None):
        r = self.web.post(url, json=data, headers=headers or {}, timeout=30)
        try:
            return r.json()
        except ValueError:
            raise SourceError(f"PikPak trả dữ liệu lỗi (HTTP {r.status_code})")

    def login(self):
        if not self.user or not self.password:
            raise SourceError("Chưa có tài khoản PikPak (Cài đặt → Lưu trữ & PikPak → Tài khoản PikPak).")
        url = f"{PK_USER}/v1/auth/signin"
        meta = {"email": self.user} if "@" in self.user else (
            {"phone_number": self.user} if re.fullmatch(r"\+?\d{9,18}", self.user) else {"username": self.user})
        cap = self._post(f"{PK_USER}/v1/shield/captcha/init",
                         {"client_id": PK_CLIENT_ID, "action": f"POST:{url}", "device_id": self.s["device_id"],
                          "meta": meta})
        token = cap.get("captcha_token")
        if not token:
            raise SourceError("PikPak từ chối đăng nhập (captcha): " + str(cap.get("error_description") or cap)[:150])
        j = self._post(url, {"client_id": PK_CLIENT_ID, "client_secret": PK_CLIENT_SECRET, "username": self.user,
                             "password": self.password, "captcha_token": token},
                       {"X-Device-Id": self.s["device_id"]})
        if not j.get("access_token"):
            raise SourceError("Đăng nhập PikPak lỗi: " + str(j.get("error_description") or j.get("error") or j)[:150])
        self.s.update(access=j["access_token"], refresh=j.get("refresh_token", ""), user_id=j.get("sub", ""))
        self._save()

    def refresh(self):
        if not self.s.get("refresh"):
            return self.login()
        j = self._post(f"{PK_USER}/v1/auth/token", {"client_id": PK_CLIENT_ID, "refresh_token": self.s["refresh"],
                                                    "grant_type": "refresh_token"})
        if not j.get("access_token"):
            return self.login()
        self.s.update(access=j["access_token"], refresh=j.get("refresh_token", self.s["refresh"]),
                      user_id=j.get("sub", self.s.get("user_id", "")))
        self._save()

    def call(self, method, path, params=None, data=None):
        with self.lock:
            if not self.s.get("access"):
                self.login()
            for attempt in range(4):
                hdr = {"Authorization": f"Bearer {self.s['access']}", "X-Device-Id": self.s["device_id"]}
                try:
                    r = self.web.request(method, PK_API + path, params=params, json=data, headers=hdr, timeout=30)
                except requests.RequestException as e:
                    if attempt == 3:
                        raise SourceError(f"Lỗi mạng PikPak: {e}")
                    time.sleep(2 + attempt * 2)
                    continue
                try:
                    j = r.json()
                except ValueError:
                    j = {}
                if r.status_code == 401 or j.get("error_code") in (16, 4122, 4121) or j.get("error") == "unauthenticated":
                    self.refresh()
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(3 + attempt * 3)
                    continue
                if j.get("error"):
                    raise SourceError("PikPak: " + str(j.get("error_description") or j.get("error"))[:200])
                return j
            raise SourceError("PikPak không phản hồi, thử lại sau.")

    # ----- link chia sẻ
    def share_list(self, share_id, pass_code="", parent_id=None, pass_code_token=""):
        """Đọc 1 thư mục trong link chia sẻ. Trả về (files, pass_code_token)."""
        files, page = [], ""
        while True:
            if parent_id and pass_code_token:
                params = {"share_id": share_id, "parent_id": parent_id, "pass_code_token": pass_code_token,
                          "limit": "100", "thumbnail_size": "SIZE_SMALL", "page_token": page}
                j = self.call("GET", "/drive/v1/share/detail", params=params)
            else:
                params = {"share_id": share_id, "pass_code": pass_code or "", "limit": "100",
                          "thumbnail_size": "SIZE_SMALL", "page_token": page}
                if parent_id:
                    params["parent_id"] = parent_id
                j = self.call("GET", "/drive/v1/share", params=params)
                pass_code_token = j.get("pass_code_token", pass_code_token)
                st = j.get("share_status")
                if st and st not in ("OK", "SHARE_STATUS_OK"):
                    raise SourceError(f"Link chia sẻ không dùng được ({st}) - hết hạn / bị xóa / sai mật khẩu?")
            files += j.get("files") or []
            page = j.get("next_page_token") or ""
            if not page:
                break
        return files, pass_code_token

    def restore(self, share_id, pass_code_token, file_ids, parent_id=""):
        data = {"share_id": share_id, "pass_code_token": pass_code_token, "file_ids": list(file_ids)}
        if parent_id:
            data.update(parent_id=parent_id, specify_parent_id=True)
        return self.call("POST", "/drive/v1/share/restore", data=data)

    # ----- My PikPak
    def folder_id(self, path, create=True):
        """Mã thư mục theo đường dẫn 'A/B/C' trong My PikPak (tạo nếu chưa có)."""
        parent = ""
        for name in [x for x in str(path).replace("\\", "/").split("/") if x.strip()]:
            found, page = None, ""
            while not found:
                j = self.call("GET", "/drive/v1/files", params={
                    "parent_id": parent, "limit": "200", "page_token": page,
                    "filters": json.dumps({"trashed": {"eq": False}, "kind": {"eq": "drive#folder"}})})
                found = next((f["id"] for f in j.get("files") or [] if f.get("name") == name), None)
                page = j.get("next_page_token") or ""
                if not page:
                    break
            if not found:
                if not create:
                    return None
                j = self.call("POST", "/drive/v1/files", data={"kind": "drive#folder", "name": name,
                                                                "parent_id": parent})
                found = (j.get("file") or {}).get("id")
                if not found:
                    raise SourceError(f"Không tạo được thư mục {name} trên PikPak")
            parent = found
        return parent


_API = {}


def pikpak_api(cfg, log=None):
    user = cfg.get("pikpak_user", "")
    key = user
    if key not in _API:
        _API[key] = PikPakAPI(user, dec_secret(cfg.get("pikpak_pass", "")), log)
    return _API[key]


class ShareSource:
    """Link chia sẻ PikPak (mypikpak.com/s/...)."""

    def __init__(self, link, folder_id, cfg, log=None):
        self.link, self.fid, self.cfg, self.log = link, folder_id, cfg, log or (lambda m: None)
        self.share_id, self.parent, self.pwd = share_parts(link)
        self.errors, self.subs, self.subdirs = [], {}, []
        self.token, self.title = "", None
        self._warned_date = True

    def list_folder(self, code=None, info=None):
        api = pikpak_api(self.cfg, self.log)
        files, self.token = api.share_list(self.share_id, self.pwd, None)      # lấy pass_code_token ở gốc
        if self.parent:                                                         # thư mục con đã chọn
            files, _t = api.share_list(self.share_id, self.pwd, self.parent, self.token)
        if info is not None:
            info.append((1, len(files), len(files), [], None, None))
        if self.title is None:
            self.title = files[0].get("name") if len(files) == 1 and "folder" in str(files[0].get("kind")) else ""
        return self.title, files

    def walk(self, code=None, sub="", _seen=None, _depth=0):
        self.errors, self.subs, self.subdirs = [], {}, []
        api = pikpak_api(self.cfg, self.log)
        _, top = self.list_folder()
        stack = [("", top)]
        seen = set()
        while stack:
            sub_, files = stack.pop(0)
            n = 0
            for it in files:
                if "folder" in str(it.get("kind")):
                    if it.get("id") in seen or sub_.count("›") >= 12:
                        continue
                    seen.add(it.get("id"))
                    child = (sub_ + " › " if sub_ else "") + (it.get("name") or "?")
                    self.subdirs.append({"path": child, "code": f"https://mypikpak.com/s/{self.share_id}/{it['id']}"})
                    try:
                        kids, _t = api.share_list(self.share_id, self.pwd, it["id"], self.token)
                        stack.append((child, kids))
                    except Exception as e:
                        self.errors.append((child, str(e)))
                    continue
                try:
                    size = int(it.get("size") or 0)
                except (TypeError, ValueError):
                    size = 0
                n += 1
                yield {"linkcode": f"{self.fid}:{it.get('id')}", "name": it.get("name") or "", "size": size,
                       "created": it.get("created_time") or it.get("modified_time"), "_sub": sub_,
                       "_id": it.get("id"), "_share": self.share_id, "_pct": self.token}
            self.subs[sub_] = n

    @staticmethod
    def code_of(it):
        return it.get("linkcode", "")

    @staticmethod
    def is_dir(it):
        return False

    def item_date(self, it):
        return to_date(it.get("created"))


def make_source(cfg, f, log=None):
    src = resolve_src(cfg, f.get("url", ""))
    if is_share(src):
        return ShareSource(src, fid(f), cfg, log)
    return LocalSource(src, fid(f), log)


def source_link(cfg, f):
    """Mở nguồn: đường dẫn thư mục (Explorer) hoặc link chia sẻ."""
    return resolve_src(cfg, f.get("url", ""))


def open_target(target):
    """Mở thư mục trong Explorer / link trên trình duyệt."""
    if not target:
        return
    if re.match(r"https?://", target):
        import webbrowser
        webbrowser.open(target)
    elif os.name == "nt":
        os.startfile(target)
    else:
        subprocess.Popen(["xdg-open", target])


def rclone_copy(rclone, src, dst, progress=None, stop=None, extra=()):
    """rclone copyto SRC DST (local<->remote hoặc remote->remote: PikPak tự sao chép trên máy chủ).
    progress(pct, speed). Trả về (ok, thông báo)."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    cmd = [rclone, "--config", str(RCLONE_CONF), "copyto", src, dst, "--retries", "3", "--low-level-retries", "10",
           "--stats", "1s", "--stats-one-line", "--stats-log-level", "NOTICE", "--no-traverse",
           "--multi-thread-streams", "8", "--multi-thread-cutoff", "64M", "--buffer-size", "32M"] + list(extra)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=flags, env=clean_env())
    tail = []
    for line in p.stdout:
        tail = (tail + [line.strip()])[-6:]
        m = re.search(r"(\d{1,3})%", line)
        sp = re.search(r"([\d.]+\s*[KMGT]?i?B/s)", line)
        if m and progress:
            progress(int(m.group(1)), sp.group(1) if sp else "")
        if stop is not None and stop.is_set():
            p.terminate()
            return False, "Đã dừng"
    rc = p.wait()
    return rc == 0, (" | ".join(x for x in tail if x)[-240:] if rc else "")


FAST_COPY_STATE = {}          # "broken": ổ RaiDrive không cho đọc song song (tự chuyển 1 luồng tới khi mở lại tool)


def fast_copy(src, dst, progress=None, stop=None, threads=4, block=8 << 20):
    """Copy nhanh từ ổ RaiDrive: chia file thành nhiều đoạn, mỗi đoạn 1 luồng đọc song song
    (ổ mạng WebDAV đọc 1 luồng thường chậm). File nhỏ / 1 luồng -> copy thường có tải tiếp."""
    total = os.path.getsize(src)
    if threads <= 1 or total < 64 << 20 or FAST_COPY_STATE.get("broken"):
        return copy_with_progress(src, dst, progress, stop, chunk=16 << 20)
    part = dst + ".part"
    with open(part, "wb") as fo:
        fo.truncate(total)
    seg = -(-total // threads)
    done = [0] * threads
    errs = []

    def work(i):
        a, b = i * seg, min(total, (i + 1) * seg)
        try:
            with open(src, "rb", buffering=0) as fi, open(part, "r+b", buffering=0) as fo:
                fi.seek(a)
                fo.seek(a)
                pos = a
                while pos < b:
                    if (stop is not None and stop.is_set()) or errs:
                        return
                    d = fi.read(min(block, b - pos))
                    if not d:
                        raise OSError(f"đọc thiếu dữ liệu ở byte {pos}")
                    fo.write(d)
                    pos += len(d)
                    done[i] = pos - a
        except Exception as e:
            errs.append(f"luồng {i + 1} (byte {a:,}-{b:,}): {type(e).__name__}: {e}")
    ths = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(threads)]
    t0 = time.time()
    for t in ths:
        t.start()
    while any(t.is_alive() for t in ths):
        time.sleep(0.5)
        if progress:
            got = sum(done)
            progress(got * 100 // total, human_size(got / max(0.5, time.time() - t0)) + "/s")
    if stop is not None and stop.is_set():
        return False, "Đã dừng"
    if errs:
        try:
            os.remove(part)
        except OSError:
            pass
        FAST_COPY_STATE["broken"] = True       # ổ không đọc song song được -> các file sau copy 1 luồng
        if progress:
            progress(0, "copy 1 luồng...")
        ok, msg = copy_with_progress(src, dst, progress, stop, chunk=16 << 20)
        return ok, (msg if ok else f"Copy đa luồng lỗi ({errs[0]}); copy 1 luồng cũng lỗi: {msg}")
    os.replace(part, dst)
    try:
        st = os.stat(src)
        os.utime(dst, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    return True, ""


def copy_with_progress(src, dst, progress=None, stop=None, chunk=4 << 20):
    """Copy file từ ổ RaiDrive về máy, tải tiếp được (file .part), báo % tiến độ."""
    try:
        return _copy_with_progress(src, dst, progress, stop, chunk)
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


class _WriteError(OSError):
    """Lỗi ghi ra ổ đích (đầy ổ, rút ổ...) - không thử lại."""


COPY_READ_RETRIES = 12        # ổ RaiDrive (WebDAV) đọc lỗi giữa chừng -> mở lại file, đọc tiếp từ chỗ dừng


def _copy_with_progress(src, dst, progress=None, stop=None, chunk=4 << 20):
    """Copy 1 luồng. Ổ RaiDrive hay báo lỗi đọc giữa chừng (VD FileNotFoundError khi WebDAV chập chờn):
    không bỏ cả file mà chờ vài giây, mở lại file nguồn và ĐỌC TIẾP từ đúng chỗ đã copy (tối đa
    COPY_READ_RETRIES lần liên tiếp không tiến thêm được byte nào)."""
    total = os.path.getsize(src)
    part = dst + ".part"
    done, fails, last_err = 0, 0, ""
    t0, d0 = time.time(), 0
    with open(part, "wb") as fo:
        while True:
            if stop is not None and stop.is_set():
                return False, "Đã dừng"
            try:
                with open(src, "rb") as fi:
                    if done:
                        fi.seek(done)
                    while True:
                        if stop is not None and stop.is_set():
                            return False, "Đã dừng"
                        b = fi.read(chunk)
                        if not b:
                            break
                        try:
                            fo.write(b)
                        except OSError as we:
                            raise _WriteError(we.errno, f"Lỗi ghi file đích: {we}") from we
                        done += len(b)
                        fails = 0
                        if progress and total:
                            el = max(0.5, time.time() - t0)
                            progress(done * 100 // total, human_size((done - d0) / el) + "/s")
                if total and done < total:
                    raise OSError(5, f"đọc thiếu dữ liệu ({human_size(done)} / {human_size(total)})")
                break
            except _WriteError:
                raise
            except OSError as e:
                fails += 1
                last_err = f"{type(e).__name__}: {e}"
                if fails > COPY_READ_RETRIES:
                    raise OSError(getattr(e, "errno", None) or 5,
                                  f"{last_err} (đã thử đọc tiếp {COPY_READ_RETRIES} lần)") from e
                wait = min(30, 3 * fails)
                if progress and total:
                    progress(done * 100 // total, f"⟳ ổ RaiDrive lỗi đọc - đọc tiếp sau {wait}s "
                                                  f"({fails}/{COPY_READ_RETRIES})")
                if stop is not None:
                    if stop.wait(wait):
                        return False, "Đã dừng"
                else:
                    time.sleep(wait)
                try:
                    fo.flush()
                except OSError as we:
                    raise _WriteError(we.errno, f"Lỗi ghi file đích: {we}") from we
                t0, d0 = time.time(), done
    os.replace(part, dst)
    try:
        st = os.stat(src)
        os.utime(dst, (st.st_atime, st.st_mtime))
    except OSError:
        pass
    return True, ""


# ----------------------------------------------------------------- v6.4: số tập / thiếu tập
_NOISE_RE = re.compile(r"(?i)\b(?:\d{3,4}p|[248]k|\d{1,2}\s*bit|[xh]\.?26[45]|hevc|avc|aac\d*|ddp?\d(?:\.\d)?|"
                       r"\d(?:\.\d)?ch|web-?dl|bluray|vie|eng|v\d)\b")


def episode_of(name):
    """Đọc số tập trong tên file -> (khóa nhóm, mùa, tập) hoặc None.
    VD 'Jade Dynasty 4K 10Bit HQ S4E090 TMPĐ_Giacobe Ngọc.mkv' -> ('jadedynasty...', 4, 90)."""
    stem = os.path.splitext(str(name))[0]
    m = re.search(r"(?i)\bS(\d{1,2})\s*[ ._-]?\s*E[Pp]?(\d{1,4})\b", stem)
    if m:
        season, ep, span = int(m.group(1)), int(m.group(2)), m.span()
    else:
        m = re.search(r"(?i)(?:\b(?:t[aậ]p|tap|ep(?:isode)?|e)\s*[ ._-]?\s*)(\d{1,4})\b", strip_accents(stem))
        if m:
            stem = strip_accents(stem)          # vị trí khớp tính trên chuỗi đã bỏ dấu
            season, ep, span = 0, int(m.group(1)), m.span()
        else:
            clean = _NOISE_RE.sub(" ", stem)
            nums = [x for x in re.finditer(r"(?<![\d.])(\d{1,4})(?![\d.])", clean)]
            if not nums:
                return None
            x = nums[-1]
            season, ep = 0, int(x.group(1))
            if 1900 <= ep <= 2099:          # năm, không phải số tập
                return None
            key = name_key(_NOISE_RE.sub(" ", clean[:x.start()] + " " + clean[x.end():]))
            return key, season, ep
    rest = stem[:span[0]] + " " + stem[span[1]:]
    return name_key(_NOISE_RE.sub(" ", rest)), season, ep


def _ranges(nums):
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append((start, prev))
            start = prev = n
    if start is not None:
        out.append((start, prev))
    return out


def find_gaps(items, max_report=40):
    """items: [(thư mục con, tên file)]. Trả về danh sách dòng 'có thể thiếu' (rỗng nếu đủ)."""
    groups = {}
    for sub, name in items:
        e = episode_of(name)
        if e:
            groups.setdefault((sub, e[0], e[1]), set()).add(e[2])
    lines = []
    for (sub, _key, season), eps in sorted(groups.items(), key=lambda kv: (natural_key(kv[0][0]), kv[0][2])):
        if len(eps) < 3:
            continue
        eps = sorted(eps)
        missing = sorted(set(range(eps[0], eps[-1] + 1)) - set(eps))
        if not missing or len(missing) > max(50, len(eps)):    # khoảng trống quá lớn -> không phải bộ liền
            continue
        w = max(2, len(str(eps[-1])))
        txt = ", ".join((f"{a:0{w}d}" if a == b else f"{a:0{w}d}–{b:0{w}d}") for a, b in _ranges(missing)[:15])
        where = (sub + " · " if sub else "") + (f"Mùa {season} · " if season else "")
        lines.append(f"{where}tập {eps[0]}–{eps[-1]}: thiếu {txt}" + (" ..." if len(_ranges(missing)) > 15 else ""))
        if len(lines) >= max_report:
            break
    return lines


# ----------------------------------------------------------------- CẬP NHẬT
def ver_tuple(v):
    """'v5.9 by Duy Anh' / 'v6.0' -> (5, 9) để so sánh phiên bản."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v).split(" by")[0])[:4]) or (0,)


def file_version(py_path):
    try:
        m = re.search(r'^APP_VERSION = "([^"]+)"', Path(py_path).read_text(encoding="utf-8", errors="ignore"), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def github_latest(repo):
    """Thông tin bản phát hành mới nhất trên GitHub: (tag, ghi chú, url file zip phù hợp)."""
    r = requests.get(f"https://api.github.com/repos/{repo.strip().strip('/')}/releases/latest", timeout=20,
                     headers={"Accept": "application/vnd.github+json", "User-Agent": "PikPakShare"})
    if r.status_code == 404:
        raise RuntimeError(f"Chưa có bản phát hành nào ở github.com/{repo} (hoặc repo không tồn tại / riêng tư).")
    r.raise_for_status()
    j = r.json()
    zips = [a for a in j.get("assets") or [] if str(a.get("name", "")).lower().endswith(".zip")]
    frozen = getattr(sys, "frozen", False)
    pick = None
    for a in zips:
        n = a["name"].lower()
        if frozen and "portable" in n:
            pick = a
        elif not frozen and "portable" not in n:
            pick = pick or a
    url = (pick or {}).get("browser_download_url") or (None if frozen and zips else j.get("zipball_url"))
    if not url and zips:
        url = zips[0]["browser_download_url"]
    return j.get("tag_name") or j.get("name") or "", j.get("body") or "", url


def download_file(url, dest, progress=None):
    with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "PikPakShare"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done * 100 // total if total else -1, done)
    return dest


UPDATE_SKIP = {"data", "__pycache__", ".git", "_bancu"}


def stage_update(zip_path):
    """Giải nén bản cập nhật, chép đè vào thư mục tool - GIỮ NGUYÊN thư mục Data.
    Trả về (phiên bản mới, đường dẫn exe mới cần thay sau khi thoát hoặc None)."""
    import tempfile
    import zipfile
    tmp = Path(tempfile.mkdtemp(prefix="fad_upd_"))
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                raise RuntimeError("File cập nhật không hợp lệ")
        z.extractall(tmp)
    exe_name = Path(sys.executable).name if getattr(sys, "frozen", False) else EXE_NAME
    exe_names = {exe_name, EXE_NAME, *OLD_EXE_NAMES}
    root = None
    for cur, dirs, files in os.walk(tmp):
        dirs[:] = [d for d in dirs if d.lower() not in UPDATE_SKIP]
        if "auto_download_pikpak_share.py" in files or exe_names & set(files):
            root = Path(cur)
            break
    if root is None:
        raise RuntimeError("File zip không phải bản PikPak Auto Save (không thấy auto_download_pikpak_share.py / .exe).")
    frozen = getattr(sys, "frozen", False)
    new_ver = file_version(root / "auto_download_pikpak_share.py") if (root / "auto_download_pikpak_share.py").is_file() else ""
    new_exe = next((root / n for n in (exe_name, EXE_NAME, *OLD_EXE_NAMES) if (root / n).is_file()), None)
    has_exe = new_exe is not None
    if frozen and not has_exe and not new_ver:
        raise RuntimeError("Bản cập nhật không có file exe hay auto_download_pikpak_share.py.")
    old_dir = BASE / "_BanCu"
    old_dir.mkdir(exist_ok=True)
    cur_py = BASE / "auto_download_pikpak_share.py"
    if cur_py.is_file():
        shutil.copy2(cur_py, old_dir / f"auto_download_pikpak_share_{file_version(cur_py).split(' by')[0] or 'cu'}.py")
    pending_exe = None
    for item in root.iterdir():
        if item.name.lower() in UPDATE_SKIP or item.name in DATA_FILES:
            continue
        dest = BASE / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        elif frozen and item.name == exe_name:   # exe đang chạy -> thay sau khi tool thoát
            pending_exe = BASE / (exe_name + ".new")
            shutil.copy2(item, pending_exe)
        else:
            shutil.copy2(item, dest)
    shutil.rmtree(tmp, ignore_errors=True)
    return new_ver, pending_exe


def migrate_exe_name():
    """Đổi tên exe cũ ("PikPak Auto Download.exe" v1.1, "Auto Download - PikPak Share.exe" v1.0) -> "PikPak Auto Save.exe".
    Exe cũ (tên cũ) chạy code mới (auto_download_pikpak_share.py cạnh exe) -> nếu cạnh đó đã có exe tên mới
    thì mở exe tên mới rồi thoát. Exe tên mới khi chạy sẽ cất exe cũ vào _BanCu."""
    if not getattr(sys, "frozen", False):
        return
    me = Path(sys.executable)
    new = BASE / EXE_NAME
    if me.name in OLD_EXE_NAMES and new.is_file() and me.resolve() != new.resolve():
        args = [a for a in sys.argv[1:] if a != "--embedded"]
        subprocess.Popen([str(new)] + args, cwd=str(BASE), env=clean_env(), close_fds=True)
        os._exit(0)
    if me.name == EXE_NAME:
        olds = [BASE / n for n in OLD_EXE_NAMES if (BASE / n).is_file()]
        if not olds:
            return

        def _stash():
            dest_dir = BASE / "_BanCu"
            for _ in range(30):           # chờ exe cũ thoát hẳn
                left = []
                for o in olds:
                    try:
                        dest_dir.mkdir(exist_ok=True)
                        d = dest_dir / o.name
                        if d.exists():
                            d.unlink()
                        shutil.move(str(o), str(d))
                    except OSError:
                        left.append(o)
                olds[:] = left
                if not olds:
                    return
                time.sleep(2)
        threading.Thread(target=_stash, daemon=True).start()


def clean_env():
    """Môi trường sạch để mở lại chính tool (bản exe PyInstaller onefile).
    Nếu để nguyên, bản mới dùng chung thư mục tạm _MEI... của bản cũ -> bản cũ thoát thì thư mục bị xóa
    -> lỗi 'No such file or directory: ...\\Temp\\_MEIxxxx\\base_library.zip'."""
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("_MEIPASS") or k.startswith("_PYI_") or k == "_PYIBoot_SPLASH")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if getattr(sys, "frozen", False):          # bỏ thư mục _MEI cũ khỏi PATH / TCL / TK
        mei = str(getattr(sys, "_MEIPASS", "") or "")
        if mei:
            env["PATH"] = os.pathsep.join(x for x in env.get("PATH", "").split(os.pathsep)
                                          if x and not x.startswith(mei))
            for k in ("TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
                if env.get(k, "").startswith(mei):
                    env.pop(k, None)
    return env


def restart_self(extra=()):
    """Mở lại tool (đúng kiểu đang chạy: exe hoặc .py) với môi trường sạch."""
    if getattr(sys, "frozen", False):
        cmd = [sys.executable] + list(extra)
    else:
        cmd = [sys.executable, str(BASE / "auto_download_pikpak_share.py")] + list(extra)
    subprocess.Popen(cmd, cwd=str(BASE), env=clean_env(), close_fds=True)


def run_newer_script():
    """Bản exe: nếu cạnh exe có auto_download_pikpak_share.py MỚI HƠN (do bấm Cập nhật) thì chạy code mới đó
    bằng Python có sẵn trong exe -> cập nhật được cả bản exe mà không cần đóng gói lại."""
    if not getattr(sys, "frozen", False) or "--embedded" in sys.argv:
        return False
    py = BASE / "auto_download_pikpak_share.py"
    if not py.is_file() or ver_tuple(file_version(py)) <= ver_tuple(APP_VERSION):
        return False
    src = py.read_text(encoding="utf-8")
    g = {"__name__": "__main__", "__file__": str(py), "__builtins__": __builtins__}
    exec(compile(src, str(py), "exec"), g)
    return True


# ----------------------------------------------------------------- GUI
def ebar(pct, n=10):
    """Thanh năng lượng dạng chữ cho cột Trạng thái: ▰▰▰▱▱▱▱▱▱▱"""
    try:
        pct = max(0, min(100, int(pct)))
    except (TypeError, ValueError):
        pct = 0
    k = (pct * n + 50) // 100
    return "▰" * k + "▱" * (n - k)


def _mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


ENERGY_COLORS = ("#5fb3e8", "#3d9ad6", "#2f86c9", "#2aa198", "#2e9e6a", "#3fb27f")


class EnergyBar(tk.Canvas):
    """Thanh năng lượng chia ô, tô màu chuyển tím -> xanh dương -> xanh lá theo %."""
    def __init__(self, parent, bg, height=18, seg=36, empty=None, colors=None):
        super().__init__(parent, bg=bg, height=height, highlightthickness=0, bd=0)
        self.seg, self.empty, self.colors, self.pct = seg, empty or ENERGY_EMPTY, colors or ENERGY_COLORS, 0
        self.off = 0                                 # độ lệch sọc (giao diện động)
        self.bind("<Configure>", lambda e: self._draw())

    def _color(self, t):
        cs = self.colors
        x = t * (len(cs) - 1)
        i = min(int(x), len(cs) - 2)
        return _mix(cs[i], cs[i + 1], x - i)

    def set(self, pct):
        try:
            pct = max(0.0, min(100.0, float(pct)))
        except (TypeError, ValueError):
            pct = 0.0
        if abs(pct - self.pct) >= 0.5 or pct in (0.0, 100.0):
            self.pct = pct
            self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        if BAR_STYLE == "smooth":                   # dải liền bo tròn, chuyển màu theo chiều ngang
            th = max(6, min(12, h - 4))
            y0 = (h - th) / 2
            y1 = y0 + th
            r = th / 2
            self.create_oval(0, y0, th, y1, fill=self.empty, outline="")
            self.create_oval(w - 1 - th, y0, w - 1, y1, fill=self.empty, outline="")
            self.create_rectangle(r, y0, w - 1 - r, y1, fill=self.empty, outline="")
            fw = (w - 1) * self.pct / 100
            if fw > 0:
                fw = max(fw, th)
                n = max(1, int((fw - th) // (6 if BAR_STRIPES else 3)))
                for k in range(n):
                    xa = r + (fw - th) * k / n
                    xb = r + (fw - th) * (k + 1) / n
                    self.create_rectangle(xa, y0, xb + 1, y1, fill=self._color(k / max(1, n - 1)), outline="")
                self.create_oval(0, y0, th, y1, fill=self._color(0), outline="")
                self.create_oval(fw - th, y0, fw, y1, fill=self._color(1), outline="")
                if BAR_STRIPES:                         # sọc chéo sáng + vệt bóng phía trên
                    lo, hi = r * 0.6, fw - r * 0.6
                    x = lo - 16 + self.off
                    while x < hi:
                        pts = [(x, y1), (x + 6, y1), (x + 6 + th, y0), (x + th, y0)]
                        pts = [(min(max(px, lo), hi), py) for px, py in pts]
                        col = _mix(self._color(min(1, max(0, (x - lo) / max(1, hi - lo)))), "#ffffff", 0.4)
                        self.create_polygon(*[v for p in pts for v in p], fill=col, outline="")
                        x += 16
                    self.create_line(r, y0 + 2, max(r, fw - r), y0 + 2, fill=_mix(self._color(0.5), "#ffffff", 0.55))
            return
        gap = 3
        n = max(8, min(self.seg, int(w // 14)))      # cửa sổ hẹp -> ít ô hơn, ô không bị mảnh như mã vạch
        sw = (w - gap * (n - 1)) / n
        full = self.pct / 100 * n
        for i in range(n):
            x0 = i * (sw + gap)
            fill = self._color(i / max(1, n - 1)) if i < full else self.empty
            if i < full < i + 1:                       # ô đang nạp dở -> nhạt hơn
                fill = _mix(self.empty, self._color(i / max(1, n - 1)), full - i)
            self.create_rectangle(x0, 1, x0 + sw, h - 1, fill=fill, outline="")
            if i < full:                               # vệt sáng phía trên cho có "năng lượng"
                self.create_rectangle(x0, 1, x0 + sw, 1 + max(2, h // 4), fill=_mix(fill, "#ffffff", 0.45),
                                      outline="")


class App(tk.Tk):
    def __init__(self, auto=False, startup=False):
        super().__init__()
        try:
            _disk = load_json(CONFIG_FILE, {})
        except Exception:
            _disk = {}
        _disk = _disk if isinstance(_disk, dict) else {}
        _want = _disk.get("ui_theme", "classic")
        self.layout = apply_theme("classic" if _want in removed_themes(_disk) else _want)
        self.title(APP_NAME)
        self.geometry(f"{min(1480, max(1100, self.winfo_screenwidth() - 60))}x"
                      f"{max(800, min(900, self.winfo_screenheight() - 80)) if LED_LIST else 800}")
        self._normal_geom = None
        self._was_zoomed = False
        self.minsize(1040, 640)
        self.configure(bg=C_BG)
        self._set_icon()

        self.cfg = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        self._no_save = False
        self._new_machine = self._init_machine_profile()
        if not CONFIG_FILE.exists():
            self.cfg["cfg_rev"] = 4
        if int(self.cfg.get("cfg_rev", 1) or 1) < 2:      # v1.1: tải về D:\DOWNLOAD HH3D\<Tên phim>, bỏ copy HDD
            self.cfg.update(download_dir=r"D:\DOWNLOAD HH3D", dl_movie_sub=True, organize=False, cfg_rev=2)
            for prof in (self.cfg.get("profiles") or {}).values():
                prof.update(download_dir=r"D:\DOWNLOAD HH3D", organize=False)
        if not self.cfg.get("download_dir"):
            self.cfg["download_dir"] = default_download_dir()
        if int(self.cfg.get("cfg_rev", 1) or 1) < 4:     # v2.1: copy về HDD từ ổ RaiDrive (đa luồng)
            self.cfg.update(dl_method="copy", cfg_rev=4)
        for f in self.cfg["folders"]:
            fid(f)
            if not f.get("dest_rev"):        # v2.0: đích đến (HDD / My PikPak) nằm trong từng thư mục phim
                hdd = f.get("local_dir") or to_portable(self.cfg.get("download_dir", "") or "")
                pk = pikpak_join(self.cfg.get("pikpak_root", ""), f.get("pikpak_dir", "")) if \
                    self.cfg.get("pikpak_on", True) else ""
                f.update(local_dir=hdd, pikpak_dir=pk, sub_movie=True, dest_rev=3)
        self.tray = None
        self.next_auto_ts = None
        self._tray_hint_shown = False
        self.history = load_json(HISTORY_FILE, {})
        for h in self.history.values():          # lần trước tắt giữa chừng -> cho tải lại
            if h.get("status") in WATCH_STATUSES:
                h["status"] = STATUS_FAIL
        self.item_meta = {}                      # mã file -> thông tin nguồn (đường dẫn / id chia sẻ)
        self.present_codes, self.sub_of = set(), {}
        self._subs_open = set()
        self.owned = load_json(OWNED_FILE, None)
        if not isinstance(self.owned, dict):
            self.owned = self._migrate_owned()
        self.auto_var = tk.BooleanVar(value=bool(self.cfg.get("auto_scan", False)))
        self.interval_var = tk.StringVar(value=str(self.cfg.get("auto_interval", 60)))
        self.last_summary = ""
        self.q = queue.Queue()
        self.worker = None
        self.monitor_busy = False
        self.stop_flag = threading.Event()
        self.fp = None            # trạng thái khung "file của thư mục" bên tab Thư mục
        self.log_lines = deque(maxlen=300)
        self.rows_ver = self.hist_ver = self.folders_ver = 0

        self._style()
        self._install_edit_bindings()
        self._make_check_images()
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill="both", expand=True)
        if LAYOUT == "workspace":
            self._build_ws_layout(body)
        elif LAYOUT == "movie":
            self._build_movie_layout(body)
        else:
            main = tk.Frame(body, bg=C_BG)
            self._build_header(main)
            self._build_statusbar(main)
            nb = self._make_notebook(main)
            self._build_sidebar(body)
            main.pack(side="left", fill="both", expand=True)
            nb.pack(fill="both", expand=True, padx=18, pady=(16, 0))

        self._build_scan()
        self._build_folders()
        self._build_settings()
        self._build_history()
        self.page = None
        self._admin_until, self._admin_last = 0.0, time.time()
        self.select_page("folders" if not any(f.get("reviewed") for f in self.cfg["folders"]) else "scan", ask=False)
        for seq in ("<Any-KeyPress>", "<Any-ButtonPress>"):
            self.bind_all(seq, self._admin_activity, add="+")
        self.after(20000, self._admin_tick)
        if LAYOUT != "classic":
            self.after(800, self._layout_tick)
        if PILL_STATUS:
            self.after(500, self._pill_tick)
        if self.cfg.get("last_summary"):
            self._set_last(self.cfg["last_summary"])
        self.update_stats()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._restore_window()
        self.bind("<Configure>", self._track_geom, add="+")
        self._start_tray()
        self.after(100, self._poll)
        if self.cfg.get("update_check", True):
            self.after(15000, lambda: self.check_update(silent=True))
        self.after(500, self._init_col_memory)
        if requests is None:
            messagebox.showerror(APP_NAME, "Thiếu thư viện 'requests'.\nChạy: pip install requests")
        if startup:
            if self.tray and self.cfg.get("tray_on_close", True):
                self._was_zoomed = bool((self.cfg.get("window") or {}).get("zoomed"))
                self.withdraw()
            if self.cfg.get("startup_scan", True):
                self.next_auto_ts = time.time() + 60
                self.log("Khởi động cùng Windows: sẽ quét sau 1 phút.")
        if auto:
            self.after(800, lambda: self.start_scan(download=True))
        self.after(1000, self._auto_tick)
        self.up_q = queue.Queue()
        self.up_queued = set()          # file đang nằm trong hàng chờ / đang upload (tránh upload 2 lần)
        threading.Thread(target=self._uploader_loop, daemon=True).start()
        self._resume_uploads()
        self._backup_pending = False
        self.after(1500, lambda: self.check_pikpak(silent=True))
        self.after(2500, self._ask_rclone_first_run)
        self.after(1200, self._rd_tick)
        self.report_callback_exception = self._tk_exception
        self.after(1600, self._show_err_badge)
        if self._new_machine:
            self.after(900, self._new_machine_dialog)

    # ================================================================ DANH SÁCH ĐÃ CÓ
    def _migrate_owned(self):
        """Lần đầu dùng v4: chuyển các tập 'Xong' trong lịch sử cũ sang Danh sách đã có."""
        owned = {}
        save_json(OWNED_FILE, owned)
        return owned

    def note_listing(self, files):
        """Ghi nhớ mã file + thư mục con của danh sách vừa quét (dùng cho so khớp Danh sách đã có)."""
        for it in files:
            c = it.get("linkcode")
            if c:
                self.present_codes.add(c)
                self.sub_of[c] = it.get("_sub", "")
                self.item_meta[c] = {k: it.get("_" + k) for k in ("path", "rel", "id", "share", "pct", "sub")
                                     if it.get("_" + k) is not None}

    def owned_index(self):
        """(tập mã file, tập (mã thư mục, thư mục con, tên chuẩn hóa)) để tra nhanh.
        So theo TÊN chỉ dùng cho file đã có mà mã cũ không còn ở nguồn (bị up lại) - tránh việc
        2 tập trùng tên ở 2 thư mục con (Season 1 / Season 2) bị coi là một -> quét thiếu."""
        codes = set(self.owned)
        present = self.present_codes
        names = set()
        for c, v in list(self.owned.items()):
            if c in present:
                continue
            names.add((v.get("folder", ""), v.get("sub"), name_key(v.get("name", ""))))
        return codes, names

    def is_owned(self, idx, fcode, folder_code, name):
        codes, names = idx
        if fcode in codes:
            return True
        k = name_key(name)
        sub = self.sub_of.get(fcode)
        return ((folder_code, sub, k) in names if sub is not None else False) \
            or (folder_code, None, k) in names or ("", None, k) in names

    def add_owned(self, fcode, folder_code, fname, name, size, src):
        rec = {"folder": folder_code or "", "fname": fname, "name": name, "size": size,
               "ts": time.time(), "src": src}
        if fcode in self.sub_of:
            rec["sub"] = self.sub_of[fcode]
        self.owned[fcode] = rec

    def remove_owned(self, fcode, folder_code, name):
        k = name_key(name)
        sub = self.sub_of.get(fcode)
        for c in [c for c, v in self.owned.items()
                  if c == fcode or (c not in self.present_codes and v.get("folder", "") in (folder_code, "")
                                    and name_key(v.get("name", "")) == k
                                    and (v.get("sub") is None or v.get("sub") == sub))]:
            self.owned.pop(c, None)

    def save_owned(self):
        save_json(OWNED_FILE, self.owned)
        self.update_stats()

    # ================================================================ GIAO DIỆN CHUNG
    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        base = tkfont.Font(family=FONT, size=10)
        self.row_h = max(30, base.metrics("linespace") + 14) + ROW_H_ADD     # dòng bảng đủ cao, không cắt chữ
        self.option_add("*TCombobox*Listbox.background", C_PANEL)
        self.option_add("*TCombobox*Listbox.foreground", C_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", C_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", C_ON_ACCENT)
        self.option_add("*Menu.background", C_PANEL)
        self.option_add("*Menu.foreground", C_TEXT)
        self.option_add("*Menu.activeBackground", C_ACCENT)
        self.option_add("*Menu.activeForeground", C_ON_ACCENT)
        self.option_add("*Menu.relief", "flat")
        st.configure(".", background=C_BG, foreground=C_TEXT, font=(FONT, 10), bordercolor=C_BORDER,
                     troughcolor=C_PANEL, focuscolor=C_ACCENT, insertcolor=C_TEXT)
        st.configure("Card.TFrame", background=C_CARD)
        st.configure("Panel.TFrame", background=C_PANEL)
        st.configure("Bg.TFrame", background=C_BG)
        st.configure("TLabel", background=C_CARD, foreground=C_TEXT)
        st.configure("Muted.TLabel", background=C_CARD, foreground=C_MUTED, font=(FONT, 9))
        st.configure("Section.TLabel", background=C_CARD, foreground=C_ACCENT, font=(FONT, 10, "bold"))
        st.configure("Status.TLabel", background=C_BG, foreground=C_MUTED, font=(MONO, 9))
        st.configure("TCheckbutton", background=C_CARD, foreground=C_TEXT, indicatorbackground=C_FIELD,
                     indicatorforeground=C_ACCENT, indicatorrelief="flat")
        st.map("TCheckbutton", background=[("active", C_CARD)], foreground=[("disabled", C_MUTED)],
               indicatorbackground=[("selected", C_FIELD)])
        st.configure("Side.TNotebook", background=C_BG, borderwidth=0, tabmargins=(0, 0, 0, 0), bordercolor=C_BG,
                     lightcolor=C_BG, darkcolor=C_BG)
        st.layout("Side.TNotebook.Tab", [])
        st.configure("TButton", padding=(12, 6), background=C_PANEL, foreground=C_TEXT, bordercolor=C_BORDER,
                     lightcolor=C_PANEL, darkcolor=C_PANEL, borderwidth=1, focusthickness=0, font=(FONT, 10))
        st.map("TButton", background=[("active", C_BTN_HOVER), ("disabled", C_CARD)],
               foreground=[("disabled", C_DIS_TEXT)], bordercolor=[("active", C_ACCENT)])
        st.configure("Small.TButton", padding=(8, 4), font=(FONT, 9))
        for name, pad, fs in (("Accent.TButton", (14, 7), 10), ("AccentSmall.TButton", (10, 4), 9)):
            st.configure(name, background=C_ACCENT, foreground=C_ON_ACCENT, bordercolor=C_ACCENT,
                         lightcolor=C_ACCENT, darkcolor=C_ACCENT, font=(FONT, fs, "bold"), padding=pad)
            st.map(name, background=[("active", C_ACCENT_HOVER), ("disabled", C_ACCENT_DIS)],
                   foreground=[("disabled", "#ffffff")], bordercolor=[("active", C_ACCENT_HOVER)])
        cta, cta_h = C_CTA or C_ACCENT, C_CTA_HOVER or C_ACCENT_HOVER
        st.configure("Cta.TButton", background=cta, foreground="#ffffff", bordercolor=cta, lightcolor=cta,
                     darkcolor=cta, font=(FONT, 10, "bold"), padding=(14, 7))
        st.map("Cta.TButton", background=[("active", cta_h), ("disabled", _mix(cta, C_CARD, 0.55))],
               foreground=[("disabled", "#ffffff")], bordercolor=[("active", cta_h)])
        st.configure("Success.TButton", background=C_ACCENT, foreground=C_ON_ACCENT, bordercolor=C_ACCENT,
                     lightcolor=C_ACCENT, darkcolor=C_ACCENT, font=(FONT, 10, "bold"), padding=(16, 7))
        st.map("Success.TButton", background=[("active", C_ACCENT_HOVER), ("disabled", C_ACCENT_DIS)])
        for name, pad, fs in (("Danger.TButton", (12, 6), 10), ("DangerSmall.TButton", (8, 4), 9)):
            st.configure(name, background=C_DANGER_BG, foreground=C_RED, bordercolor=C_DANGER_BORDER,
                         lightcolor=C_DANGER_BG, darkcolor=C_DANGER_BG, padding=pad, font=(FONT, fs))
            st.map(name, background=[("active", C_DANGER_HOVER)], foreground=[("disabled", C_DANGER_DIS)])
        if BTN_3D:                                    # nút nổi: cạnh trên sáng, cạnh dưới tối
            st.configure("TButton", lightcolor=_mix(C_PANEL, "#ffffff", 0.7), darkcolor=_mix(C_PANEL, "#000000", 0.2),
                         bordercolor=_mix(C_BORDER, "#000000", 0.18), borderwidth=2)
            for name in ("Accent.TButton", "AccentSmall.TButton", "Cta.TButton", "Success.TButton"):
                st.configure(name, lightcolor=_mix(C_ACCENT, "#ffffff", 0.35), darkcolor=_mix(C_ACCENT, "#000000", 0.3),
                             bordercolor=_mix(C_ACCENT, "#000000", 0.4), borderwidth=2)
            for name in ("Danger.TButton", "DangerSmall.TButton"):
                st.configure(name, lightcolor=_mix(C_DANGER_BG, "#ffffff", 0.7),
                             darkcolor=_mix(C_DANGER_BORDER, "#000000", 0.1),
                             bordercolor=_mix(C_DANGER_BORDER, "#000000", 0.2), borderwidth=2)
        for name, pad in (("TEntry", 6), ("TCombobox", 5), ("TSpinbox", 4)):
            st.configure(name, fieldbackground=C_FIELD, foreground=C_TEXT, bordercolor=C_BORDER,
                         lightcolor=C_FIELD, darkcolor=C_FIELD, padding=pad, arrowsize=12, insertcolor=C_ACCENT,
                         arrowcolor=C_MUTED, background=C_PANEL, selectbackground=C_ACCENT,
                         selectforeground=C_ON_ACCENT)
            st.map(name, bordercolor=[("focus", C_ACCENT)], lightcolor=[("focus", C_FIELD)],
                   fieldbackground=[("readonly", C_FIELD), ("disabled", C_CARD)],
                   foreground=[("readonly", C_TEXT), ("disabled", C_MUTED)])
        st.configure("Pro.Treeview", background=C_CARD, fieldbackground=C_CARD, foreground=C_TEXT,
                     rowheight=self.row_h, borderwidth=0, font=(FONT, 10))
        st.configure("Pro.Treeview.Heading", background=C_HEAD, foreground=C_MUTED, bordercolor=C_BORDER,
                     lightcolor=C_HEAD, darkcolor=C_HEAD, font=(FONT, 8, "bold"), borderwidth=0, padding=(8, 8),
                     relief="flat")
        st.map("Pro.Treeview.Heading", background=[("active", C_PANEL)], foreground=[("active", C_ACCENT)])
        st.map("Pro.Treeview", background=[("selected", C_SEL)], foreground=[("selected", C_TEXT)])
        st.layout("Pro.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Pro.Horizontal.TProgressbar", troughcolor=C_TROUGH, background=C_ACCENT,
                     bordercolor=C_TROUGH, lightcolor=C_ACCENT, darkcolor=C_ACCENT, thickness=10)
        st.configure("Vertical.TScrollbar", background=C_PANEL, troughcolor=C_CARD, borderwidth=0, arrowsize=12,
                     bordercolor=C_CARD, lightcolor=C_PANEL, darkcolor=C_PANEL, arrowcolor=C_MUTED)
        st.map("Vertical.TScrollbar", background=[("active", C_SCROLL_ACT)])
        st.configure("TPanedwindow", background=C_CARD)
        st.configure("Sash", sashthickness=8, gripcount=0, background=C_BORDER)
        st.configure("TMenubutton", background=C_PANEL, foreground=C_TEXT, bordercolor=C_BORDER,
                     lightcolor=C_PANEL, darkcolor=C_PANEL, arrowcolor=C_MUTED, padding=(10, 5))
        st.map("TMenubutton", background=[("active", C_BTN_HOVER)])

    def _tree(self, parent, cols, heads, widths, anchors=None, height=12, check=False, stretch=None):
        wrap = ttk.Frame(parent, style="Card.TFrame")
        border = tk.Frame(wrap, bg=C_BORDER, padx=1, pady=1)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg=C_CARD)
        inner.pack(fill="both", expand=True)
        tree = ttk.Treeview(inner, columns=cols, show=("tree headings" if check else "headings"),
                            style="Pro.Treeview", height=height)
        if check:
            tree.column("#0", width=46, minwidth=46, stretch=False, anchor="center")
        for i, (c, t, w) in enumerate(zip(cols, heads, widths)):
            tree.heading(c, text=t, anchor="w")
            st_ = (c in stretch) if stretch else (w >= 300)
            tree.column(c, width=w, minwidth=min(w, 60), anchor=(anchors[i] if anchors else "w"), stretch=st_)
        sb = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.tag_configure("odd", background=C_ODD)
        tree.tag_configure("new", foreground=C_BLUE)
        tree.tag_configure("dl", foreground=C_ORANGE)
        tree.tag_configure("done", foreground=C_GREEN)
        tree.tag_configure("err", foreground=C_RED)
        tree.tag_configure("skip", foreground=C_SKIP)
        return wrap, tree

    def _make_notebook(self, parent):
        nb = ttk.Notebook(parent, style="Side.TNotebook")
        self.nb = nb
        self.tab_scan = ttk.Frame(nb, style="Card.TFrame", padding=14)
        self.tab_folders = ttk.Frame(nb, style="Card.TFrame", padding=14)
        self.tab_settings = ttk.Frame(nb, style="Card.TFrame", padding=14)
        self.tab_history = ttk.Frame(nb, style="Card.TFrame", padding=14)
        for fr in (self.tab_scan, self.tab_folders, self.tab_history, self.tab_settings):
            nb.add(fr)
        return nb

    def _set_last(self, summary):
        try:
            self.side_last.config(text="Quét lần cuối:\n" + summary)
        except (AttributeError, tk.TclError):
            pass

    def _build_sidebar(self, parent):
        def SF(n, bold=False):          # cỡ chữ thanh bên (giao diện mới: to hơn, in đậm)
            return (FONT, n + SIDE_FONT_ADD, "bold" if (bold or SIDE_BOLD) else "normal")
        self.side_w = max(SIDE_MIN, min(SIDE_MAX, int(self.cfg.get("side_w", SIDE_W) or SIDE_W)))
        side = tk.Frame(parent, bg=C_SIDE, width=self.side_w)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.side = side
        W = self.side_w - 64          # độ rộng chữ trong các thẻ

        # ----- logo + tên app + nút thu gọn
        top = tk.Frame(side, bg=C_SIDE)
        top.pack(fill="x", padx=(18, 10), pady=(16, 10))
        self.side_brand = tk.Frame(top, bg=C_SIDE)
        self.side_brand.pack(side="left")
        if self.icon_small:
            tk.Label(self.side_brand, image=self.icon_small, bg=C_SIDE).pack(side="left", padx=(0, 10))
        bt = tk.Frame(self.side_brand, bg=C_SIDE)
        bt.pack(side="left")
        tk.Label(bt, text=APP_TITLE.upper(), bg=C_SIDE, fg=C_SIDE_BRAND, font=SF(11, True)).pack(anchor="w")
        tk.Label(bt, text=APP_VERSION, bg=C_SIDE,
                 fg=C_SIDE_MUTED, font=SF(8)).pack(anchor="w")
        self.side_toggle = tk.Label(top, text="«", bg=C_SIDE, fg=C_SIDE_TEXT, font=SF(15, True),
                                    cursor="hand2", padx=8)
        self.side_toggle.pack(side="right")
        self.side_toggle.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.side_toggle.bind("<Enter>", lambda e: self.side_toggle.config(bg=C_SIDE_HOVER))
        self.side_toggle.bind("<Leave>", lambda e: self.side_toggle.config(bg=C_SIDE))
        self.bind_all("<Control-b>", lambda e: self.toggle_sidebar())
        tk.Frame(side, bg=C_SIDE_HOVER, height=1).pack(fill="x", padx=14, pady=(0, 8))

        self.side_menu_lbl = tk.Label(side, text="MENU", bg=C_SIDE, fg=C_SIDE_MUTED, font=SF(8, True))
        self.side_menu_lbl.pack(anchor="w", padx=24, pady=(4, 4))
        self.nav = {}
        items = (("folders", "▦", "Thư mục phim", self.tab_folders),
                 ("scan", "⬇", "Quét & Tải", self.tab_scan),
                 ("history", "☰", "Lịch sử tải", self.tab_history),
                 ("settings", "⚙", "Cài đặt", self.tab_settings))
        for n, (key, icon, text, frame) in enumerate(items, 1):
            row = tk.Frame(side, bg=C_SIDE, cursor="hand2")
            row.pack(fill="x", padx=12, pady=2)
            bar = tk.Frame(row, bg=C_SIDE, width=3)
            bar.pack(side="left", fill="y")
            ic = tk.Label(row, text=icon, bg=C_SIDE, fg=C_SIDE_MUTED, font=SF(13), width=2)
            ic.pack(side="left", padx=(10, 8), pady=10)
            lb = tk.Label(row, text=text, bg=C_SIDE, fg=C_SIDE_TEXT, font=SF(11, True))
            lb.pack(side="left")
            badge = tk.Label(row, text="", bg=C_ACCENT, fg=C_ON_ACCENT, font=(MONO, 9, "bold"), padx=7)
            self.nav[key] = {"row": row, "bar": bar, "icon": ic, "label": lb, "badge": badge, "frame": frame}
            for w in (row, ic, lb, badge):
                w.bind("<Button-1>", lambda e, k=key: self.select_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
            self.bind_all(f"<Control-Key-{n}>", lambda e, k=key: self.select_page(k))

        def card(parent_, title, **pack):
            outer = tk.Frame(parent_, bg=C_SIDE_CARD, padx=14, pady=10)
            outer.pack(fill="x", **pack)
            tk.Label(outer, text=title, bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=SF(8, True)).pack(anchor="w")
            return outer

        self.side_lib = card(side, "THƯ VIỆN", padx=14, pady=(16, 0))
        self.side_owned = tk.Label(self.side_lib, text="", bg=C_SIDE_CARD, fg=C_SIDE_OK, font=SF(10),
                                   anchor="w", justify="left", wraplength=W)
        self.side_owned.pack(fill="x", pady=(4, 0))

        bottom = tk.Frame(side, bg=C_SIDE)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        self.side_bottom = bottom
        ca = card(bottom, "TỰ ĐỘNG", pady=(0, 10))
        r = tk.Frame(ca, bg=C_SIDE_CARD)
        r.pack(fill="x", pady=(6, 2))
        tk.Checkbutton(r, text="Tự quét mỗi", variable=self.auto_var, command=self._auto_changed,
                       bg=C_SIDE_CARD, fg=C_SIDE_TEXT, selectcolor=C_SIDE_HOVER, activebackground=C_SIDE_CARD,
                       activeforeground=C_TEXT, font=SF(10), bd=0, highlightthickness=0).pack(side="left")
        cb = ttk.Combobox(r, textvariable=self.interval_var, values=INTERVAL_CHOICES, width=4, state="readonly")
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._auto_changed())
        tk.Label(r, text="phút", bg=C_SIDE_CARD, fg=C_SIDE_TEXT, font=SF(10)).pack(side="left")
        self.side_auto = tk.Label(ca, text="", bg=C_SIDE_CARD, fg=C_SIDE_ACTIVE, font=SF(10), anchor="w")
        self.side_auto.pack(fill="x", pady=(4, 0))
        self.side_last = tk.Label(ca, text="Chưa quét lần nào", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=SF(9),
                                  anchor="w", justify="left", wraplength=W)
        self.side_last.pack(fill="x", pady=(2, 0))

        ck = card(bottom, "KẾT NỐI", pady=(0, 10))
        self.side_rd = tk.Label(ck, text="▣ RaiDrive: đang kiểm tra...", bg=C_SIDE_CARD, fg=C_SIDE_MUTED,
                                font=SF(10), anchor="w", justify="left", wraplength=W, cursor="hand2")
        self.side_rd.bind("<Button-1>", lambda e: (self.select_page("settings"), self._settings_page("raidrive")))
        self.side_pk = tk.Label(ck, text="☁ PikPak: đang kiểm tra...", bg=C_SIDE_CARD, fg=C_SIDE_MUTED,
                                font=SF(10), anchor="w", justify="left", wraplength=W, cursor="hand2")
        self.side_pk.pack(fill="x")
        self.side_pk.bind("<Button-1>", lambda e: self.get_rclone() if not find_rclone() else (
            self.select_page("settings"), self._settings_page("pikpak")))
        self.side_bk = tk.Label(ck, text="", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=SF(9), anchor="w",
                                justify="left", wraplength=W)
        self.side_bk.pack(fill="x")
        self.side_err = tk.Label(ck, text="", bg=C_ERR_BG, fg=C_ERR_FG, font=SF(9, True), anchor="w",
                                 justify="left", wraplength=W, cursor="hand2", padx=6, pady=4)
        self.side_err.bind("<Button-1>", self.copy_last_report)
        self.side_health = tk.Label(ck, text="", bg=C_SIDE_CARD, fg=C_SIDE_BAD, font=SF(9, True), anchor="w",
                                    justify="left", wraplength=W)
        if self.cfg.get("last_backup"):
            self.side_bk.config(text="⟲ Sao lưu: " + self.cfg["last_backup"])
        tk.Label(ck, text=f"⌂ Máy: {MACHINE}", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=SF(9),
                 anchor="w").pack(fill="x", pady=(2, 0))
        self.side_foot = tk.Label(bottom, text="",
                                  bg=C_SIDE, fg=C_FOOT, font=SF(8), anchor="w", justify="left", wraplength=W)
        self._side_wraps = [self.side_rd, self.side_owned, self.side_last, self.side_pk, self.side_bk, self.side_foot, self.side_health, self.side_err]
        # vạch kéo đổi độ rộng thanh bên
        grip = tk.Frame(parent, bg=C_BORDER, width=5, cursor="sb_h_double_arrow")
        grip.pack(side="left", fill="y")
        grip.bind("<Enter>", lambda e: grip.config(bg=C_ACCENT))
        grip.bind("<Leave>", lambda e: grip.config(bg=C_BORDER))
        grip.bind("<B1-Motion>", self._side_drag)
        grip.bind("<ButtonRelease-1>", self._side_drag_end)
        grip.bind("<Double-Button-1>", lambda e: self.toggle_sidebar())
        self.side_grip = grip
        if LED_PANEL:
            self._build_led_side(side, SF, W)
        if self.cfg.get("side_collapsed"):
            self.after(10, lambda: self.toggle_sidebar(True))

    # ================================================================ GIAO DIỆN 4: bảng ĐÈN TRẠNG THÁI ở thanh bên
    LED_COL = {"ok": ("#86efac", "#16a34a"), "run": ("#fde68a", "#f59e0b"),
               "err": ("#fca5a5", "#dc2626"), "off": ("#f1f5f9", "#9ca3af")}
    LED_DOT = {"ok": "#22c55e", "run": "#f59e0b", "err": "#ef4444", "off": "#9ca3af"}
    LED_TXT = {"ok": "#16a34a", "run": "#ea580c", "err": "#dc2626", "off": "#334155"}
    LED_BG = {"ok": "#ffffff", "run": "#ffffff", "err": "#fdeaea", "off": "#ffffff"}
    LED_BD = {"ok": "#d5dee8", "run": "#d5dee8", "err": "#f3b4b4", "off": "#d5dee8"}

    def _draw_led(self, cv, state, dim=False):
        """Đèn LED tròn bóng: viền sáng, lõi chuyển màu, đốm sáng phía trên."""
        try:
            s = int(cv.cget("width"))
            cv.delete("all")
        except tk.TclError:
            return
        hi, lo = self.LED_COL.get(state, self.LED_COL["off"])
        if dim:
            hi = _mix(hi, lo, 0.7 if dim is True else float(dim))
        cv.create_oval(0, 0, s - 1, s - 1, fill=_mix(lo, "#ffffff", 0.55), outline="")       # quầng
        cv.create_oval(1.5, 1.5, s - 2.5, s - 2.5, fill=_mix(lo, "#000000", 0.18), outline="")
        for i in range(6):
            k = 2.5 + i * s * 0.055
            cv.create_oval(k, k + i * 0.35, s - k - 1, s - k - 1, fill=_mix(lo, hi, i / 6), outline="")
        cv.create_oval(s * 0.26, s * 0.13, s * 0.62, s * 0.40, fill=_mix(hi, "#ffffff", 0.8), outline="")

    def _build_led_side(self, side, SF, W):
        """Giao diện 4: thẻ cảnh báo dưới menu + bảng ĐÈN TRẠNG THÁI ở đáy thanh bên.
        Các nhãn cũ (side_pk, side_bk, side_health, side_err...) vẫn còn (ẩn) để phần lõi dùng chung."""
        self.side_lib.pack_forget()
        self.side_bottom.pack_forget()
        self.led_cards = {}
        self._led_blink = False
        self._pk_acc = {}
        self._rc_ver = None
        self._led_issues = []
        if LED_LIST:
            return self._build_led_list(side, SF, W)
        WHITE = "#ffffff"

        # ----- thẻ cảnh báo (nền trắng, đèn to)
        al = tk.Frame(side, bg=WHITE, highlightthickness=1, highlightbackground="#c9d6e3",
                      padx=8, pady=8, cursor="hand2")
        al.pack(fill="x", padx=14, pady=(14, 0))
        self.led_alert = al
        self.led_alert_cv = tk.Canvas(al, width=32, height=32, bg=WHITE, highlightthickness=0)
        self.led_alert_cv.pack(side="left", padx=(0, 6))
        tx = tk.Frame(al, bg=WHITE)
        tx.pack(side="left", fill="x", expand=True)
        self.led_alert_t1 = tk.Label(tx, text="Đang kiểm tra...", bg=WHITE, fg="#000000",
                                     font=(FONT, 11 + SIDE_FONT_ADD // 2, "bold"), anchor="w")
        self.led_alert_t1.pack(fill="x")
        self.led_alert_t2 = tk.Label(tx, text="", bg=WHITE, fg="#111827", font=(FONT, 9), anchor="w",
                                     justify="left", wraplength=W)
        self.led_alert_t2.pack(fill="x")
        for w in (al, self.led_alert_cv, tx, self.led_alert_t1, self.led_alert_t2):
            w.bind("<Button-1>", lambda e: self._led_show_issues())
        self.side_lib = al

        # ----- đáy: bảng ĐÈN TRẠNG THÁI
        bottom = tk.Frame(side, bg=C_SIDE_CARD, padx=12, pady=10)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        self.side_bottom = bottom
        tk.Label(bottom, text="ĐÈN TRẠNG THÁI", bg=C_SIDE_CARD, fg="#1e293b",
                 font=(FONT, 9, "bold")).pack(anchor="w")
        lg = tk.Frame(bottom, bg=C_SIDE_CARD)
        lg.pack(anchor="w", pady=(2, 6))
        for st, nm in (("ok", "Tốt"), ("run", "Đang chạy"), ("err", "Lỗi"), ("off", "Tắt")):
            dot = tk.Canvas(lg, width=9, height=9, bg=C_SIDE_CARD, highlightthickness=0)
            dot.create_oval(0, 0, 8, 8, fill=self.LED_DOT[st], outline="")
            dot.pack(side="left")
            tk.Label(lg, text=nm, bg=C_SIDE_CARD, fg="#334155", font=(FONT, 8)).pack(side="left", padx=(2, 12))
        grid = tk.Frame(bottom, bg=C_SIDE_CARD)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="led")
        grid.columnconfigure(1, weight=1, uniform="led")

        def open_err():
            self.copy_last_report()
            d = DATA_DIR / "BaoLoi"
            files = sorted(d.glob("BaoLoi_*.txt")) if d.is_dir() else []
            if files:
                open_target(str(files[-1]))

        layout = (("dl", "Đang tải", 0, 0, 2, None),
                  ("pk", "PikPak", 1, 0, 1, lambda: self.get_rclone() if not find_rclone() else (
                      self.select_page("settings"), self._settings_page("pikpak"))),
                  ("rd", "RaiDrive", 1, 1, 1, None),
                  ("rc", "rclone", 2, 0, 1, lambda: self.get_rclone() if not find_rclone() else None),
                  ("auto", "Tự quét", 2, 1, 1, None),
                  ("bk", "Sao lưu", 3, 0, 1, lambda: self.select_page("settings")),
                  ("err", "Lỗi", 3, 1, 1, open_err))
        for key, title, r, c, span, cmd in layout:
            f = tk.Frame(grid, bg=WHITE, highlightthickness=1, highlightbackground=self.LED_BD["off"],
                         padx=10, pady=9, cursor="hand2" if cmd else "")
            f.grid(row=r, column=c, columnspan=span, sticky="nsew",
                   padx=(0, 4) if (c == 0 and span == 1) else ((4, 0) if c == 1 else 0), pady=(0, 8))
            cv = tk.Canvas(f, width=20, height=20, bg=WHITE, highlightthickness=0)
            cv.pack(side="left", anchor="n", padx=(0, 6))
            tx = tk.Frame(f, bg=WHITE)
            tx.pack(side="left", fill="x", expand=True, anchor="n")
            t1 = tk.Label(tx, text=title, bg=WHITE, fg="#000000", font=(FONT, 10 + SIDE_FONT_ADD // 2, "bold"),
                          anchor="w")
            t1.pack(fill="x")
            t2 = tk.Label(tx, text="...", bg=WHITE, fg=self.LED_TXT["off"], font=(FONT, 8 if key == "pk" else 9),
                          anchor="w",
                          justify="left")
            t2.pack(fill="x")
            self.led_cards[key] = {"f": f, "cv": cv, "tx": tx, "t1": t1, "t2": t2, "span": span, "state": None}
            self._draw_led(cv, "off")
            if cmd:
                for w in (f, cv, tx, t1, t2):
                    w.bind("<Button-1>", lambda e, fn=cmd: fn())

        ar = tk.Frame(bottom, bg=WHITE, highlightthickness=1, highlightbackground=self.LED_BD["off"],
                      padx=10, pady=6)
        ar.pack(fill="x")
        tk.Checkbutton(ar, text="Tự quét mỗi", variable=self.auto_var, command=self._auto_changed,
                       bg=WHITE, fg="#000000", selectcolor=WHITE, activebackground=WHITE,
                       activeforeground="#000000", font=(FONT, 10, "bold"), bd=0, highlightthickness=0).pack(side="left")
        cb = ttk.Combobox(ar, textvariable=self.interval_var, values=INTERVAL_CHOICES, width=4, state="readonly")
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self._auto_changed())
        tk.Label(ar, text="phút", bg=WHITE, fg="#000000", font=(FONT, 10, "bold")).pack(side="left")
        self.side_auto = tk.Label(ar, text="", bg=WHITE, fg="#475569", font=(FONT, 10, "bold"), anchor="e")
        self.side_auto.pack(side="right")

        # chấm đỏ ở mục Cài đặt khi có vấn đề
        row = self.nav["settings"]["row"]
        self.led_nav_dot = tk.Canvas(row, width=16, height=16, bg=row["bg"], highlightthickness=0, cursor="hand2")
        self._draw_led(self.led_nav_dot, "err")
        self.led_nav_dot.bind("<Button-1>", lambda e: self.select_page("settings"))
        self.after(600, self._led_tick)
        self.after(3000, self._led_slow)

    # ----- giao diện 5 / 6 / 7: bảng đèn dạng danh sách (thẻ nổi, mũi tên ›)
    def _build_led_list(self, side, SF, W):
        CARD = C_LED_CARD
        self.LED_BG = {"ok": CARD, "run": CARD, "off": CARD, "err": C_LED_ERR_BG}
        self.LED_BD = {"ok": C_LED_BD, "run": C_LED_BD, "off": C_LED_BD, "err": C_LED_ERR_BD}
        self.LED_TXT = dict(LED_TXT_COLORS)
        if ANIM:
            self.LED_COL = dict(self.LED_COL, run=("#fca5a5", "#dc2626"))
            self.LED_TXT["run"] = self.LED_TXT["err"]

        def raised(parent_, **pack):
            """Thẻ nổi: khung bóng đổ (đậm hơn ở cạnh dưới) bọc thẻ trắng."""
            sh = tk.Frame(parent_, bg=C_LED_SHADOW)
            sh.pack(fill="x", **pack)
            inner = tk.Frame(sh, bg=CARD, highlightthickness=1, highlightbackground=C_LED_BD)
            inner.pack(fill="x", padx=(0, 1), pady=(0, 2))
            return sh, inner

        # ----- thẻ "Mọi thứ hoạt động tốt"
        _sh, al = raised(side, padx=14, pady=(14, 0))
        self.led_alert = al
        self.led_alert_cv = tk.Canvas(al, width=32, height=32, bg=CARD, highlightthickness=0)
        self.led_alert_cv.pack(side="left", padx=(10, 6), pady=8)
        tx = tk.Frame(al, bg=CARD)
        tx.pack(side="left", fill="x", expand=True)
        self.led_alert_t1 = tk.Label(tx, text="Đang kiểm tra...", bg=CARD, fg=C_LED_TITLE,
                                     font=(FONT, 11 + SIDE_FONT_ADD // 2, "bold"), anchor="w")
        self.led_alert_t1.pack(fill="x")
        self.led_alert_t2 = tk.Label(tx, text="", bg=CARD, fg=C_LED_OFF_TXT, font=(FONT, 9), anchor="w",
                                     justify="left", wraplength=W)
        self.led_alert_t2.pack(fill="x")
        for w in (al, self.led_alert_cv, tx, self.led_alert_t1, self.led_alert_t2):
            w.bind("<Button-1>", lambda e: self._led_show_issues())
        self.side_lib = _sh

        # ----- đáy: BẢNG ĐÈN TRẠNG THÁI
        bottom = tk.Frame(side, bg=C_LED_PANEL, padx=12, pady=10, highlightthickness=1,
                          highlightbackground=_mix(C_LED_PANEL, C_LED_SHADOW, 0.6))
        bottom.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
        self.side_bottom = bottom
        tk.Label(bottom, text="BẢNG ĐÈN TRẠNG THÁI", bg=C_LED_PANEL, fg=C_LED_TITLE,
                 font=(FONT, 9, "bold")).pack(anchor="w")
        lg = tk.Frame(bottom, bg=C_LED_PANEL)
        lg.pack(anchor="w", pady=(2, 6))
        for st, nm in (("ok", "Tốt"), ("run", "Đang chạy"), ("err", "Lỗi"), ("off", "Tắt")):
            dot = tk.Canvas(lg, width=9, height=9, bg=C_LED_PANEL, highlightthickness=0)
            dot.create_oval(0, 0, 8, 8, fill=self.LED_DOT[st], outline="")
            dot.pack(side="left")
            tk.Label(lg, text=nm, bg=C_LED_PANEL, fg=C_LED_OFF_TXT, font=(FONT, 8)).pack(side="left", padx=(3, 12))

        def open_err():
            d = DATA_DIR / "BaoLoi"
            files = sorted(d.glob("BaoLoi_*.txt")) if d.is_dir() else []
            if not files:
                messagebox.showinfo(APP_NAME, "Chưa có báo cáo lỗi nào.")
                return
            self.copy_last_report()
            open_target(str(files[-1]))

        def toggle_auto():
            self.auto_var.set(not self.auto_var.get())
            self._auto_changed()

        layout = (("pk", "PikPak", lambda: self.get_rclone() if not find_rclone() else (
                      self.select_page("settings"), self._settings_page("pikpak"))),
                  ("rc", "rclone", lambda: self.get_rclone() if not find_rclone() else (
                      self.select_page("settings"), self._settings_page("pikpak"))),
                  ("auto", "Tự quét", toggle_auto),
                  ("dl", "Đang tải", lambda: self.select_page("scan")),
                  ("bk", "Sao lưu", lambda: self.select_page("settings")),
                  ("err", "Lỗi", open_err))
        for key, title, cmd in layout:
            sh, f = raised(bottom, pady=(0, 6))
            f.config(cursor="hand2")
            cv = tk.Canvas(f, width=22, height=22, bg=CARD, highlightthickness=0)
            cv.pack(side="left", padx=(10, 8), pady=7)
            tx = tk.Frame(f, bg=CARD)
            tx.pack(side="left", fill="x", expand=True)
            t1 = tk.Label(tx, text=title, bg=CARD, fg=C_LED_TITLE, font=(FONT, 10 + SIDE_FONT_ADD // 2, "bold"),
                          anchor="w")
            t1.pack(fill="x")
            t2 = tk.Label(tx, text="...", bg=CARD, fg=self.LED_TXT["off"], font=(FONT, 9), anchor="w",
                          justify="left")
            t2.pack(fill="x")
            extra = []
            if key == "auto":
                ar = tk.Frame(f, bg=CARD)
                ar.pack(side="right", padx=(0, 10))
                l1 = tk.Label(ar, text="mỗi", bg=CARD, fg=C_LED_TITLE, font=(FONT, 9, "bold"))
                l1.pack(side="left")
                cb = ttk.Combobox(ar, textvariable=self.interval_var, values=INTERVAL_CHOICES, width=3,
                                  state="readonly")
                cb.pack(side="left", padx=5)
                cb.bind("<<ComboboxSelected>>", lambda e: self._auto_changed())
                l2 = tk.Label(ar, text="phút", bg=CARD, fg=C_LED_TITLE, font=(FONT, 9, "bold"))
                l2.pack(side="left")
                extra = [ar, l1, l2]
            else:
                ch = tk.Label(f, text="›", bg=CARD, fg=C_LED_OFF_TXT, font=(FONT, 13, "bold"))
                ch.pack(side="right", padx=(0, 12))
                extra = [ch]
            self.led_cards[key] = {"f": f, "cv": cv, "tx": tx, "t1": t1, "t2": t2, "span": 2, "state": None,
                                   "extra": extra, "narrow": key == "auto"}
            self._draw_led(cv, "off")
            for w in (f, cv, tx, t1, t2) + ((extra[0],) if key != "auto" else ()):
                w.bind("<Button-1>", lambda e, fn=cmd: fn())
        # thẻ Tự quét không còn ô tích: bấm vào thẻ để bật / tắt
        self.side_auto = tk.Label(side)        # (nhãn ẩn - phần lõi vẫn ghi vào)

        # đèn trạng thái trên mục menu đang chọn
        for k, n in self.nav.items():
            n["dot"] = tk.Canvas(n["row"], width=18, height=18, bg=C_SIDE, highlightthickness=0)
        self.led_nav_dot = None
        self.after(600, self._led_tick)
        self.after(3000, self._led_slow)
        if ANIM:
            self.after(200, self._led_anim)

    def _led_nav_style(self, key):
        """Mục menu đang chọn: thẻ trắng nổi, biểu tượng ô xanh lá, đèn trạng thái bên phải."""
        for k, n in self.nav.items():
            on = k == key
            bg = C_LED_CARD if on else C_SIDE
            n["row"].config(bg=bg, highlightthickness=1 if on else 0, highlightbackground=C_LED_SHADOW)
            n["bar"].config(bg=bg)
            n["label"].config(bg=bg)
            n["icon"].config(bg=C_GREEN if on else bg, fg="#ffffff" if on else C_SIDE_TEXT)
            d = n.get("dot")
            if d is not None:
                d.config(bg=bg)
                if on and not getattr(self, "side_collapsed", False):
                    d.pack(side="right", padx=(0, 12))
                else:
                    d.pack_forget()

    def _led_anim(self):
        """Giao diện 7: đèn nhịp thở + thanh tải sọc chạy."""
        if not getattr(self, "led_cards", None):
            return
        self.after(120, self._led_anim)
        self._led_phase = (getattr(self, "_led_phase", 0) + 1) % 24
        t = (1 + math.cos(self._led_phase / 24 * 2 * math.pi)) / 2 * 0.8
        for c in self.led_cards.values():
            if c["state"] in ("run", "err"):
                self._draw_led(c["cv"], c["state"], dim=t)
        st = getattr(self, "_led_overall", "ok")
        if getattr(self, "_led_issues", None):
            self._draw_led(self.led_alert_cv, "err", dim=t)
        if st != "ok":
            n = self.nav.get(getattr(self, "page", ""), {})
            if n.get("dot") is not None and n["dot"].winfo_ismapped():
                self._draw_led(n["dot"], st, dim=t)
        try:
            for bar, _iv, _pv in self.energy.values():
                if isinstance(bar, EnergyBar) and 0 < bar.pct:
                    bar.off = (bar.off + 2) % 16
                    bar._draw()
        except (AttributeError, tk.TclError):
            pass

    def _led_set(self, key, state, text):
        c = self.led_cards.get(key)
        if not c:
            return
        wrap = max(110, (self.side_w - 56) // (1 if c["span"] == 2 else 2) - (200 if c.get("narrow") else 46))
        changed = c["state"] != state
        if changed:
            c["state"] = state
            bg = self.LED_BG[state]
            c["f"].config(bg=bg, highlightbackground=self.LED_BD[state])
            for w in (c["cv"], c["tx"], c["t1"], c["t2"]) + tuple(c.get("extra", ())):
                w.config(bg=bg)
            c["t2"].config(fg=self.LED_TXT[state])
        if c["t2"].cget("text") != text or c["t2"].cget("wraplength") != wrap:
            c["t2"].config(text=text, wraplength=wrap)
        if not (ANIM and state in ("run", "err") and not changed):     # giao diện 7: _led_anim tự vẽ nhịp thở
            self._draw_led(c["cv"], state, dim=(state == "run" and self._led_blink))

    def _led_slow(self):
        """Việc chậm chạy nền (30s/lần): phiên bản rclone, ổ RaiDrive, thông tin tài khoản PikPak."""
        self.after(30000, self._led_slow)
        cfg = json.loads(json.dumps(self.cfg))
        pk_ok = getattr(self, "pk_ok", None)

        def job():
            r = find_rclone()
            if r and not self._rc_ver:
                c, o, _e = run_rclone(r, ["version"], 30)
                m = re.search(r"v\d+\.\d+", o or "") if c == 0 else None
                self._rc_ver = m.group(0) if m else "?"
            elif not r:
                self._rc_ver = None
            root = rd_root(cfg) if cfg.get("raidrive_root") else ""
            self._led_rd = None if not root else (root, os.path.isdir(root))
            acc = dict(self._pk_acc)
            if pk_ok and time.time() - acc.get("ts", 0) > 1800:
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
                        except Exception:
                            pass
                        try:
                            q = (api.call("GET", "/drive/v1/about") or {}).get("quota") or {}
                            acc["total"], acc["used"] = int(q.get("limit") or 0), int(q.get("usage") or 0)
                        except Exception:
                            pass
                    except Exception:
                        pass
                if not acc.get("total") and r:
                    c3, o3, _e = run_rclone(r, ["about", f"{cfg.get('pikpak_remote', 'pikpak') or 'pikpak'}:",
                                                "--json"], 60)
                    try:
                        j = json.loads(o3)
                        acc["total"], acc["used"] = int(j.get("total") or 0), int(j.get("used") or 0)
                    except (ValueError, TypeError):
                        pass
            elif not pk_ok:
                acc = {}
            self._pk_acc = acc
        threading.Thread(target=job, daemon=True).start()

    def _led_tick(self):
        if not getattr(self, "led_cards", None):
            return
        self.after(700, self._led_tick)
        self._led_blink = not self._led_blink
        issues = []
        try:
            # Đang tải
            if self.worker and self.worker.is_alive():
                info = ""
                try:
                    info = self.energy["dl"][1].get()
                except (AttributeError, KeyError, tk.TclError):
                    pass
                done, n = getattr(self, "_batch", (0, 0))
                txt = (f"{done}/{n} · " if n else "") + f"{getattr(self, '_dl_pct', 0)}%"
                if LED_LIST:
                    sp = re.search(r"[\d.,]+\s*[KMG]i?B/s", info or "")
                    self._led_set("dl", "run", txt + (f" · {sp.group(0).replace('.', ',')}" if sp else ""))
                else:
                    self._led_set("dl", "run", txt + (f" · {info}" if info and info != "—" else ""))
            else:
                self._led_set("dl", "off", "Rảnh")
            # PikPak + thông tin tài khoản
            ok = getattr(self, "pk_ok", None)
            user = self.cfg.get("pikpak_user") or ""
            t = self.side_pk.cget("text").replace("☁ PikPak:", "").strip()
            if ok is True:
                st, lines = "ok", ["Đã kết nối"]
            elif ok is False or "chưa" in t:
                st, lines = "err", ["Chưa kết nối"]
                issues.append("PikPak chưa kết nối" + (f": {t}" if t else "") + " (bấm thẻ PikPak để thiết lập)")
            else:
                st, lines = "run", ["Đang kết nối..."]
            if user:
                lines.append(user)
            acc = self._pk_acc
            if ok and acc:
                if "vip" in acc:
                    ex = acc.get("expire", "")
                    try:
                        ex = dt.datetime.strptime(ex, "%Y-%m-%d").strftime("%d/%m/%Y")
                    except ValueError:
                        pass
                    lines.append(("★ VIP" + (f" · hạn {ex}" if ex else "")) if acc["vip"] else "Không VIP")
                if acc.get("total"):
                    lines.append(f"{human_size(acc['used'])} / {human_size(acc['total'])}")
                elif acc.get("used"):
                    lines.append(f"Đã dùng {human_size(acc['used'])}")
            if LED_LIST:                         # thẻ rộng: "Đã kết nối · VIP (hạn ...)" / email · dung lượng
                head = lines[0]
                rest = [x for x in lines[1:] if not x.startswith(("★", "Không VIP"))]
                vip = [x for x in lines[1:] if x.startswith(("★", "Không VIP"))]
                if vip:
                    head += " · " + vip[0].replace("★ ", "").replace(" · hạn", " (hạn") + (")" if "hạn" in vip[0] else "")
                lines = [head] + ([" · ".join(rest)] if rest else [])
            self._led_set("pk", st, "\n".join(lines))
            # RaiDrive (tool này không bắt buộc: chưa đặt ổ = "Không dùng")
            rd = getattr(self, "_led_rd", None)
            if "rd" not in self.led_cards:       # giao diện 7: không có thẻ RaiDrive
                pass
            elif not rd:
                self._led_set("rd", "off", "Không dùng")
            elif rd[1]:
                self._led_set("rd", "ok", (f"Ổ {rd[0].rstrip(os.sep)} đã gắn" if LED_LIST
                                           else f"Đã gắn ổ {rd[0].rstrip(os.sep)}"))
            else:
                self._led_set("rd", "err", f"Chưa gắn ổ {rd[0].rstrip(os.sep)}")
                issues.append(f"RaiDrive chưa gắn ổ {rd[0].rstrip(os.sep)}")
            # rclone
            if not find_rclone():
                self._led_set("rc", "err", "Chưa có · bấm để tải")
                issues.append("Chưa có rclone.exe (bấm thẻ rclone để tải)")
            else:
                self._led_set("rc", "ok", f"{self._rc_ver} sẵn sàng" if self._rc_ver else "sẵn sàng")
            # Tự quét
            on = bool(self.cfg.get("auto_scan"))
            if on and self.next_auto_ts:
                self._led_set("auto", "ok", ("Bật · lần tới " if LED_LIST else "Lần tới ")
                              + f"{dt.datetime.fromtimestamp(self.next_auto_ts):%H:%M}")
            else:
                self._led_set("auto", "off", "Đang tắt")
            self.side_auto.config(text="Bật" if on else "Tắt", fg="#16a34a" if on else "#475569")
            # Sao lưu
            bk = self.cfg.get("last_backup") or ""
            if not self.cfg.get("backup_on", True):
                self._led_set("bk", "off", "Đã tắt")
            elif "lỗi" in self.side_bk.cget("text"):
                self._led_set("bk", "err", "Sao lưu lỗi")
                issues.append("Sao lưu lên PikPak bị lỗi")
            elif not bk:
                self._led_set("bk", "run", "Chưa đồng bộ")
            else:
                try:
                    h = int((dt.datetime.now() - dt.datetime.strptime(bk, "%H:%M %d/%m/%Y")).total_seconds() // 3600)
                except ValueError:
                    h = 0
                if h >= 24:
                    self._led_set("bk", "run", f"Chưa đồng bộ ({h} giờ)")
                else:
                    today = bk[6:11] == f"{dt.date.today():%d/%m}"
                    self._led_set("bk", "ok", f"Đã đồng bộ {bk[:5] if today else bk[:11]}")
            # Lỗi
            d = DATA_DIR / "BaoLoi"
            n = len(list(d.glob("BaoLoi_*.txt"))) if d.is_dir() else 0
            if n:
                self._led_set("err", "err", f"{n} lỗi · bấm để xem")
                issues.append(f"{n} báo cáo lỗi (bấm thẻ Lỗi để xem)")
            else:
                self._led_set("err", "off" if LED_LIST else "ok", "Không có lỗi")
            for p_ in getattr(self, "_health_probs", []) or []:
                if not any(k in p_ for k in ("rclone", "PikPak")):
                    issues.append(p_)
        except (tk.TclError, AttributeError):
            return
        self._led_issues = issues
        n = len(issues)
        busy = bool(self.worker and self.worker.is_alive())
        self._led_overall = "err" if n else ("run" if busy else "ok")
        if LED_LIST:
            self.led_alert_t1.config(text=f"Có {n} mục cần xử lý" if n else "Mọi thứ hoạt động tốt")
            self.led_alert_t2.config(text="Tool chưa tự tải được cho tới khi sửa · bấm để xem" if n else
                                     f"Thư viện: {len(self.owned):,} tập · Máy: {MACHINE}".replace(",", "."),
                                     wraplength=self.side_w - 110)
            if not ANIM:
                self._draw_led(self.led_alert_cv, "err" if n else "ok")
            nv = self.nav.get(getattr(self, "page", ""), {})
            if nv.get("dot") is not None and (not ANIM or self._led_overall == "ok"):
                self._draw_led(nv["dot"], self._led_overall, dim=(self._led_overall != "ok" and self._led_blink))
            if ANIM and not n:
                self._draw_led(self.led_alert_cv, "ok")
            return
        self.led_alert_t1.config(text=f"Có {n} mục cần xử lý" if n else "Mọi thứ đều ổn")
        self.led_alert_t2.config(text="Tool chưa tự tải được cho tới khi sửa" if n else "Sẵn sàng tự quét & tải",
                                 wraplength=self.side_w - 100)
        self._draw_led(self.led_alert_cv, "err" if n else "ok")
        if n and not getattr(self, "side_collapsed", False):
            if not self.led_nav_dot.winfo_ismapped():
                self.led_nav_dot.pack(side="right", padx=(0, 12))
            self.led_nav_dot.config(bg=self.nav["settings"]["row"].cget("bg"))
        elif self.led_nav_dot.winfo_ismapped():
            self.led_nav_dot.pack_forget()

    def _led_show_issues(self):
        iss = getattr(self, "_led_issues", [])
        if iss:
            messagebox.showwarning(APP_NAME, "Các mục cần xử lý:\n\n• " + "\n• ".join(iss))
        else:
            messagebox.showinfo(APP_NAME, "Mọi thứ đều ổn - tool sẵn sàng tự quét & tải.")

    def _side_drag(self, e):
        if LAYOUT != "classic":
            return
        w = e.x_root - self.side.winfo_rootx()
        if getattr(self, "side_collapsed", False):
            if w < SIDE_MIN:
                return
            self.toggle_sidebar(False)
        w = max(SIDE_MIN, min(SIDE_MAX, w))
        if w == self.side_w:
            return
        self.side_w = w
        self.side.config(width=w)
        for lb in self._side_wraps:
            lb.config(wraplength=w - 64)

    def _side_drag_end(self, e):
        self.cfg["side_w"] = self.side_w
        try:
            disk = load_json(CONFIG_FILE, {})
            if isinstance(disk, dict) and disk:
                disk["side_w"] = self.side_w
                save_json(CONFIG_FILE, disk)
        except Exception:
            pass

    def toggle_sidebar(self, collapse=None):
        """Thu gọn / mở rộng thanh bên trái (Ctrl+B)."""
        if LAYOUT != "classic":
            return
        if collapse is None:
            collapse = not getattr(self, "side_collapsed", False)
        self.side_collapsed = collapse
        self.side.config(width=SIDE_W_MINI if collapse else self.side_w)
        if collapse:
            self.side_brand.pack_forget()
            self.side_menu_lbl.pack_forget()
            self.side_toggle.config(text="»")
            self.side_toggle.master.pack_configure(padx=(6, 6))
            for n in self.nav.values():
                n["label"].pack_forget()
                n["badge"].pack_forget()
            self.side_lib.pack_forget()
            self.side_bottom.pack_forget()
        else:
            self.side_toggle.config(text="«")
            self.side_toggle.master.pack_configure(padx=(18, 10))
            self.side_brand.pack(side="left")
            self.side_menu_lbl.pack(anchor="w", padx=24, pady=(4, 4), before=self.nav["folders"]["row"])
            for n in self.nav.values():
                n["label"].pack(side="left")
                if n["badge"].cget("text"):
                    n["badge"].pack(side="right", padx=10)
            self.side_bottom.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
            self.side_lib.pack(fill="x", padx=14, pady=(16, 0))
        if self.cfg.get("side_collapsed") != collapse:
            self.cfg["side_collapsed"] = collapse
            try:   # chỉ ghi cờ này, không đụng các ô Cài đặt đang sửa dở
                disk = load_json(CONFIG_FILE, {})
                if isinstance(disk, dict) and disk:
                    disk["side_collapsed"] = collapse
                    save_json(CONFIG_FILE, disk)
            except Exception:
                pass

    def update_stats(self):
        dl = sum(1 for h in self.history.values() if h.get("status") in WATCH_STATUSES)
        on = [f for f in self.cfg["folders"] if f.get("enabled", True)]
        unreviewed = sum(1 for f in on if not f.get("reviewed"))
        if hasattr(self, "stat_vars"):
            self.stat_vars["folders"].set(f"{len(on)}/{len(self.cfg['folders'])}")
            self.stat_vars["new"].set(str(getattr(self, "_new_count", 0)))
            self.stat_vars["dl"].set(str(dl))
            self.stat_vars["owned"].set(str(len(self.owned)))
        if hasattr(self, "nav"):
            self.set_badge("scan", getattr(self, "_new_count", 0))
            self.set_badge("history", dl, C_ORANGE)
            bad = sum(1 for f in on if f.get("last_error"))
            self.set_badge("folders", bad or unreviewed, C_RED if bad else C_ORANGE)
            self.side_owned.config(text=f"✔ Danh sách đã có: {len(self.owned)} file"
                                   + (f"\n◔ {unreviewed} thư mục chưa duyệt" if unreviewed else ""))

    # ================================================================ TAB THƯ MỤC FSHARE
    def _build_folders(self):
        t = self.tab_folders
        pw = ttk.Panedwindow(t, orient="horizontal")
        pw.pack(fill="both", expand=True)
        left = ttk.Frame(pw, style="Card.TFrame")
        right = ttk.Frame(pw, style="Card.TFrame")
        pw.add(left, weight=0)
        pw.add(right, weight=1)
        self._sash_set = False

        def place_sash(e):
            if not self._sash_set and e.width > 700:
                self._sash_set = True
                self.after(50, lambda: pw.sashpos(0, max(440, int(e.width * 0.43))))
        pw.bind("<Configure>", place_sash, add="+")

        # ----- cột trái: danh sách thư mục
        top = ttk.Frame(left, style="Card.TFrame")
        top.pack(fill="x", padx=(0, 12))
        ttk.Label(top, text="Thư mục phim nguồn", style="Section.TLabel").pack(side="left")
        self.folder_count = tk.StringVar()
        ttk.Label(top, textvariable=self.folder_count, style="Muted.TLabel").pack(side="left", padx=10)
        b = ttk.Frame(left, style="Card.TFrame")
        b.pack(fill="x", pady=(10, 6), padx=(0, 12))
        ttk.Button(b, text="＋  Thêm thư mục", style="Accent.TButton",
                   command=lambda: self.open_folder_dialog()).pack(side="left")
        ttk.Button(b, text="⧉  Dán nhiều nguồn", command=self.folder_bulk).pack(side="left", padx=8)
        mb = ttk.Menubutton(b, text="⋯  Khác")
        menu = tk.Menu(mb, tearoff=0, font=(FONT, 10))
        menu.add_command(label="Chọn quét tất cả thư mục", command=lambda: self.folder_check_all(True))
        menu.add_command(label="Bỏ quét tất cả thư mục", command=lambda: self.folder_check_all(False))
        menu.add_separator()
        menu.add_command(label="Xuất danh sách thư mục...", command=self.folder_export)
        menu.add_command(label="Nhập danh sách thư mục...", command=self.folder_import)
        mb["menu"] = menu
        mb.pack(side="left")
        sr = ttk.Frame(left, style="Card.TFrame")
        sr.pack(fill="x", pady=(0, 8), padx=(0, 12))
        ttk.Label(sr, text="⌕ Tìm", style="Muted.TLabel").pack(side="left")
        self.folder_search_var = tk.StringVar()
        ttk.Entry(sr, textvariable=self.folder_search_var).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.folder_search_var.trace_add("write", lambda *a: self.refresh_folders())

        holder = tk.Frame(left, bg=C_BG, highlightbackground=C_BORDER, highlightthickness=1)
        holder.pack(fill="both", expand=True, padx=(0, 12))
        self.card_canvas = tk.Canvas(holder, bg=C_BG, highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.card_canvas.pack(side="left", fill="both", expand=True)
        self.card_inner = tk.Frame(self.card_canvas, bg=C_BG)
        self._card_win = self.card_canvas.create_window((0, 0), window=self.card_inner, anchor="nw")
        self.card_inner.bind("<Configure>", lambda e: self.card_canvas.configure(
            scrollregion=self.card_canvas.bbox("all")))
        self.card_canvas.bind("<Configure>", self._on_cards_resize)
        for w in (self.card_canvas, self.card_inner):
            w.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._cards_wheel))
            w.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))
        self._wrap_labels = []
        self.active_folder = None

        # ----- cột phải: file của thư mục đang chọn
        self._build_file_panel(right)
        self.refresh_folders()

    def _cards_wheel(self, e):
        self.card_canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")

    def _on_cards_resize(self, e):
        self.card_canvas.itemconfigure(self._card_win, width=e.width)
        for lb in self._wrap_labels:
            try:
                lb.configure(wraplength=max(200, e.width - 56))
            except tk.TclError:
                pass

    def _folder_status(self, f):
        """(chữ, màu) trạng thái của 1 thư mục."""
        if not f.get("enabled", True):
            return "Tạm bỏ qua khi quét", C_MUTED
        if f.get("last_error"):
            return "⚠  Lỗi lần quét trước: " + str(f["last_error"])[:70], C_RED
        if not f.get("reviewed"):
            return "◔  Chưa duyệt — bấm \"Quét file\" để chọn những file đã có", C_ORANGE
        when = ""
        if f.get("last_scan"):
            when = " · quét " + dt.datetime.fromtimestamp(float(f["last_scan"])).strftime("%H:%M %d/%m")
        total, owned = int(f.get("total", 0) or 0), int(f.get("owned", 0) or 0)
        new = max(0, total - owned)
        if new:
            return f"●  {new} file mới chưa có  ·  đã có {owned}/{total}{when}", C_BLUE
        return f"✔  Đã có đủ {owned}/{total} file{when}", C_GREEN

    def refresh_folders(self):
        for w in self.card_inner.winfo_children():
            w.destroy()
        self._wrap_labels = []
        q = strip_accents(self.folder_search_var.get().strip()) if hasattr(self, "folder_search_var") else ""
        width = max(300, self.card_canvas.winfo_width() - 56)
        shown = 0
        for i, f in enumerate(self.cfg["folders"]):
            text = f"{f.get('name', '')} {f.get('note', '')} {f.get('url', '')}"
            if q and q not in strip_accents(text):
                continue
            shown += 1
            active = self.active_folder == i
            card = tk.Frame(self.card_inner, bg=C_CARD, highlightthickness=2 if active else 1,
                            highlightbackground=C_ACCENT if active else C_BORDER, padx=12, pady=10)
            card.pack(fill="x", padx=8, pady=(8, 0))
            r1 = tk.Frame(card, bg=C_CARD)
            r1.pack(fill="x")
            on = f.get("enabled", True)
            chk = tk.Label(r1, image=self.img_on if on else self.img_off, bg=C_CARD, cursor="hand2")
            chk.pack(side="left", anchor="n", pady=2)
            chk.bind("<Button-1>", lambda e, i=i: self._toggle_folder(i))
            tk.Label(r1, text=f"#{i + 1}", bg=C_CARD, fg=C_MUTED, font=(FONT, 9)).pack(side="right", anchor="n")
            name = tk.Label(r1, text=f.get("name") or "(chưa có tên)", bg=C_CARD,
                            fg=C_TEXT if on else C_MUTED, font=(FONT, 11, "bold"), anchor="w", justify="left",
                            wraplength=width - 40)
            name.pack(side="left", fill="x", expand=True, padx=(8, 0))
            self._wrap_labels.append(name)
            real = source_link(self.cfg, f)
            kind = "⛓ Nguồn:  " + ((f.get("src_label") + "   ·   ") if f.get("src_label") else "")
            link = tk.Label(card, text=kind + (real or f.get("url", "")),
                            bg=C_CARD, fg=C_MUTED, font=(FONT, 9), anchor="w",
                            justify="left", wraplength=width, cursor="hand2")
            link.pack(fill="x", pady=(4, 0))
            self._link_label(link, real, C_MUTED)
            dests = []
            if f.get("pikpak_dir"):
                dests.append(("1 · MY PIKPAK", f["pikpak_dir"] + ("/<Tên phim>" if f.get("sub_movie", True) else "")))
            if f.get("local_dir"):
                dests.append(("2 · HDD", from_portable(f["local_dir"]) + ("\\<Tên phim>" if f.get("sub_movie", True) else "")))
            dbox = tk.Frame(card, bg=C_PANEL, padx=8, pady=4)
            dbox.pack(fill="x", pady=(6, 0))
            for k_, v_ in dests or [("⚠", "Chưa có đích đến - bấm Sửa")]:
                ln_ = tk.Frame(dbox, bg=C_PANEL)
                ln_.pack(fill="x")
                tk.Label(ln_, text=f"{k_:<7}›", bg=C_PANEL, fg=C_ACCENT, font=(MONO, 9, "bold")).pack(side="left")
                dl_ = tk.Label(ln_, text=" " + v_, bg=C_PANEL, fg=C_TEXT if dests else C_RED, font=(MONO, 9),
                               anchor="w", justify="left", wraplength=width - 110)
                dl_.pack(side="left", fill="x")
                self._wrap_labels.append(dl_)
            self._wrap_labels.append(link)
            if f.get("note"):
                nt = tk.Label(card, text="✎  " + one_line(f["note"]), bg=C_CARD, fg=C_MUTED, font=(FONT, 9),
                              anchor="w", justify="left", wraplength=width)
                nt.pack(fill="x", pady=(2, 0))
                self._wrap_labels.append(nt)
            subs = f.get("subs") or []
            if subs:
                code_f = fid(f)
                expanded = code_f in self._subs_open
                box = tk.Frame(card, bg=C_SOFT, padx=8, pady=5)
                box.pack(fill="x", pady=(6, 0))
                hd = tk.Label(box, text=("▾" if expanded else "▸") + f"  Thư mục con ({len(subs)})"
                              + ("" if expanded else "  —  bấm để xem link"),
                              bg=C_SOFT, fg=C_ACCENT_HOVER, font=(FONT, 9, "bold"), anchor="w", cursor="hand2")
                hd.pack(fill="x")
                hd.bind("<Button-1>", lambda e, c=code_f: self._toggle_subs(c))
                if expanded:
                    for d in subs[:60]:
                        u = folder_link(d.get("code"))
                        ln = tk.Label(box, text=f"↳ {d.get('path')}   {u}", bg=C_SOFT, fg=C_BLUE, font=(FONT, 9),
                                      anchor="w", justify="left", wraplength=width - 20, cursor="hand2")
                        ln.pack(fill="x", pady=(2, 0))
                        self._link_label(ln, u, C_BLUE)
                    if len(subs) > 60:
                        tk.Label(box, text=f"... và {len(subs) - 60} thư mục con khác", bg=C_SOFT, fg=C_MUTED,
                                 font=(FONT, 9), anchor="w").pack(fill="x")
                    tk.Label(box, text="Bấm: mở  ·  Chuột phải: copy đường dẫn / link", bg=C_SOFT, fg=C_MUTED,
                             font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))
            stext, scol = self._folder_status(f)
            stl = tk.Label(card, text=stext, bg=C_CARD, fg=scol, font=(FONT, 9, "bold"), anchor="w",
                           justify="left", wraplength=width)
            stl.pack(fill="x", pady=(6, 0))
            self._wrap_labels.append(stl)
            gaps = f.get("gaps") or []
            if gaps and f.get("enabled", True) and "|".join(gaps) != f.get("gap_ack"):
                gb = tk.Frame(card, bg=C_WARN_BG, padx=8, pady=5)
                gb.pack(fill="x", pady=(6, 0))
                gl = tk.Label(gb, text="⚠  Có thể thiếu tập:\n" + "\n".join("   • " + x for x in gaps[:6])
                              + (f"\n   ... và {len(gaps) - 6} chỗ khác" if len(gaps) > 6 else ""),
                              bg=C_WARN_BG, fg=C_ORANGE, font=(FONT, 9, "bold"), anchor="w", justify="left",
                              wraplength=width - 20)
                gl.pack(fill="x")
                self._wrap_labels.append(gl)
                ack = tk.Label(gb, text="✓ Đã kiểm tra, bỏ qua cảnh báo này", bg=C_WARN_BG, fg=C_MUTED,
                               font=(FONT, 8, "underline"), anchor="w", cursor="hand2")
                ack.pack(fill="x", pady=(3, 0))
                ack.bind("<Button-1>", lambda e, i=i: self._ack_gaps(i))
            sd = int(self.cfg.get("stale_days", 7) or 0)
            if sd and f.get("latest_up") and f.get("enabled", True) and f.get("reviewed"):
                try:
                    lu = dt.date.fromisoformat(f["latest_up"])
                    days = (dt.date.today() - lu).days
                except ValueError:
                    days, lu = 0, None
                if days >= sd:
                    sl = tk.Label(card, text=f"⏳  {days} ngày chưa có tập mới (mới nhất up {lu:%d/%m/%Y}) - bên up có "
                                             "chuyển sang thư mục khác không?", bg=C_CARD, fg=C_ORANGE, font=(FONT, 9),
                                  anchor="w", justify="left", wraplength=width)
                    sl.pack(fill="x", pady=(4, 0))
                    self._wrap_labels.append(sl)
            r3 = tk.Frame(card, bg=C_CARD)
            r3.pack(fill="x", pady=(8, 0))
            ttk.Button(r3, text="⌕  Quét file", style="AccentSmall.TButton",
                       command=lambda i=i: self.scan_folder_files(i)).pack(side="left")
            ttk.Button(r3, text="⬇  Tải mới", style="Small.TButton",
                       command=lambda f=f: self.start_scan(True, only={fid(f)})).pack(side="left", padx=(6, 0))
            ttk.Button(r3, text="✎  Sửa", style="Small.TButton",
                       command=lambda i=i: self.open_folder_dialog(i)).pack(side="left", padx=(6, 0))
            more = ttk.Menubutton(r3, text="⋯", style="Small.TButton", width=3)
            mm = tk.Menu(more, tearoff=0, font=(FONT, 10))
            mm.add_command(label="↗  Mở thư mục nguồn", command=lambda f=f: open_target(source_link(self.cfg, f)))
            mm.add_command(label="⚕  Chẩn đoán (xuất danh sách file + lý do bỏ qua)...",
                           command=lambda i=i: self.diagnose_folder(i))
            mm.add_separator()
            mm.add_command(label="▲  Đưa lên trên", command=lambda i=i: self.folder_move(i, -1))
            mm.add_command(label="▼  Đưa xuống dưới", command=lambda i=i: self.folder_move(i, 1))
            mm.add_separator()
            mm.add_command(label="✕  Xóa thư mục", command=lambda i=i: self.folder_delete(i))
            more["menu"] = mm
            more.pack(side="left", padx=(6, 0))
        if not self.cfg["folders"]:
            tk.Label(self.card_inner, text="Chưa có thư mục nào.\n\nBấm \"＋ Thêm thư mục\" hoặc \"⧉ Dán nhiều link\"\n"
                                           "để thêm thư mục phim (chọn thư mục con trong link chia sẻ PikPak).",
                     bg=C_BG, fg=C_MUTED, font=(FONT, 10), justify="center").pack(pady=40)
        tk.Frame(self.card_inner, bg=C_BG, height=8).pack()
        on = sum(1 for f in self.cfg["folders"] if f.get("enabled", True))
        rv = sum(1 for f in self.cfg["folders"] if f.get("reviewed"))
        self.folders_ver = getattr(self, "folders_ver", 0) + 1
        self.folder_count.set(f"{len(self.cfg['folders'])} thư mục · quét {on} · đã duyệt {rv}"
                              + (f" · hiện {shown}" if q else ""))
        self.update_stats()

    def _toggle_folder(self, i):
        self.cfg["folders"][i]["enabled"] = not self.cfg["folders"][i].get("enabled", True)
        self.save_config(); self.refresh_folders()

    def folder_check_all(self, on):
        for f in self.cfg["folders"]:
            f["enabled"] = bool(on)
        self.save_config(); self.refresh_folders()

    def _add_folder(self, name, url, include="", exclude="", note="", local_dir=""):
        src = clean_src(self.cfg, url)
        if not src:
            return False
        key = src_key(self.cfg, src)
        if any(src_key(self.cfg, f.get("url", "")) == key for f in self.cfg["folders"]):
            return False
        if not name.strip() and not is_share(src):
            name = os.path.basename(os.path.normpath(resolve_src(self.cfg, src)))
        self.cfg["folders"].append({"id": new_folder_id(), "name": name.strip(), "url": src,
                                    "enabled": True, "include": include.strip(), "exclude": exclude.strip(),
                                    "note": note.strip(), "local_dir": local_dir.strip()})
        return True

    def folder_move(self, i, step):
        j = i + step
        fl = self.cfg["folders"]
        if 0 <= j < len(fl):
            fl[i], fl[j] = fl[j], fl[i]
            if self.active_folder in (i, j):
                self.active_folder = j if self.active_folder == i else i
                if self.fp:
                    self.fp["index"] = self.active_folder
            self.save_config(); self.refresh_folders()

    def folder_delete(self, i):
        f = self.cfg["folders"][i]
        if not messagebox.askyesno(APP_NAME, f"Xóa thư mục \"{f.get('name') or f.get('url')}\" khỏi danh sách?\n"
                                             "(Danh sách file đã có của thư mục vẫn được giữ.)"):
            return
        del self.cfg["folders"][i]
        if self.active_folder == i:
            self.active_folder, self.fp = None, None
            self._fp_clear()
        elif self.active_folder is not None and self.active_folder > i:
            self.active_folder -= 1
            if self.fp:
                self.fp["index"] = self.active_folder
        self.save_config(); self.refresh_folders()

    # ----- khung bên phải: file của 1 thư mục
    def _build_file_panel(self, p):
        self.fp_title = tk.StringVar(value="Danh sách file")
        self.fp_info = tk.StringVar(value="")
        hdr = ttk.Frame(p, style="Card.TFrame")
        hdr.pack(fill="x", padx=(12, 0))
        ttk.Label(hdr, textvariable=self.fp_title, style="Section.TLabel").pack(anchor="w")
        ttk.Label(hdr, textvariable=self.fp_info, style="Muted.TLabel", wraplength=640, justify="left").pack(
            anchor="w", pady=(2, 0))

        bar = tk.Frame(p, bg=C_SOFT, highlightbackground=C_SOFT_BORDER, highlightthickness=1)
        bar.pack(fill="x", pady=(10, 8), padx=(12, 0))
        b1 = tk.Frame(bar, bg=C_SOFT, padx=10, pady=6)
        b1.pack(fill="x")
        self.fp_btns = []
        for text, img, cmd in (("Chọn tất cả", self.img_on, lambda: self._fp_pick_visible(True)),
                               ("Bỏ chọn", self.img_off, lambda: self._fp_pick_visible(False))):
            bt = ttk.Button(b1, text=text, image=img, compound="left", command=cmd)
            bt.pack(side="left", padx=(0, 6))
            self.fp_btns.append(bt)
        bt = ttk.Button(b1, text="↧  Chọn từ đầu đến dòng đang bấm", command=self._fp_pick_until)
        bt.pack(side="left")
        self.fp_btns.append(bt)
        b2 = tk.Frame(bar, bg=C_SOFT, padx=10)
        b2.pack(fill="x", pady=(0, 6))
        tk.Label(b2, text="⌕ Tìm", bg=C_SOFT, fg=C_MUTED, font=(FONT, 9)).pack(side="left")
        self.fp_search = tk.StringVar()
        ttk.Entry(b2, textvariable=self.fp_search, width=24).pack(side="left", padx=(4, 12))
        self.fp_search.trace_add("write", lambda *a: self._fp_refresh())
        tk.Label(b2, text="Hiện", bg=C_SOFT, fg=C_MUTED, font=(FONT, 9)).pack(side="left")
        self.fp_show = tk.StringVar(value="Tất cả")
        sc = ttk.Combobox(b2, textvariable=self.fp_show, state="readonly", width=14,
                          values=("Tất cả", "Chưa có", "Đã có", "Đang chọn"))
        sc.pack(side="left", padx=4)
        sc.bind("<<ComboboxSelected>>", lambda e: self._fp_refresh())

        wrap, self.fp_tree = self._tree(p, ("name", "date", "size", "status"),
                                        ("TÊN FILE", "NGÀY UP", "DUNG LƯỢNG", "TRẠNG THÁI"),
                                        (360, 100, 100, 190), height=12, check=True, stretch=("name",))
        wrap.pack(fill="both", expand=True, padx=(12, 0))
        self.fp_tree.bind("<Button-1>", self._fp_click, add="+")
        self.fp_tree.bind("<space>", self._fp_toggle_sel)
        self.fp_tree.bind("<<TreeviewSelect>>", lambda e: self._show_full(self.fp_tree))
        self.fp_tree.heading("#0", image=self.img_off, anchor="center",
                             command=lambda: self._fp_pick_visible(
                                 not all(c in self.fp["picked"] for c in self.fp_tree.get_children())
                                 if self.fp else True))
        self.fp_empty = tk.Label(self.fp_tree, text="Bấm \"⌕ Quét file\" ở một thư mục bên trái\n"
                                                    "để xem tất cả file của thư mục đó.",
                                 bg=C_CARD, fg=C_MUTED, font=(FONT, 11), justify="center")
        self.fp_empty.place(relx=0.5, rely=0.4, anchor="center")

        bot = ttk.Frame(p, style="Card.TFrame")
        bot.pack(fill="x", pady=(10, 0), padx=(12, 0))
        self.fp_mark = ttk.Button(bot, text="☑  Thêm vào Danh sách đã có", style="Accent.TButton",
                                  command=lambda: self._fp_mark(True), state="disabled")
        self.fp_mark.pack(side="left")
        self.fp_unmark = ttk.Button(bot, text="↺  Bỏ khỏi Danh sách đã có", command=lambda: self._fp_mark(False),
                                    state="disabled")
        self.fp_unmark.pack(side="left", padx=8)
        self.fp_save = ttk.Button(bot, text="✓  Lưu", style="Success.TButton", command=self._fp_save_click,
                                  state="disabled")
        self.fp_save.pack(side="right")
        self.fp_count = tk.StringVar()
        ttk.Label(p, textvariable=self.fp_count, style="Muted.TLabel").pack(anchor="w", padx=(12, 0), pady=(6, 0))

    def _fp_clear(self):
        self.fp_tree.delete(*self.fp_tree.get_children())
        self.fp_title.set("Danh sách file")
        self.fp_info.set("")
        self.fp_count.set("")
        self.fp_empty.place(relx=0.5, rely=0.4, anchor="center")
        for b in (self.fp_mark, self.fp_unmark, self.fp_save):
            b.config(state="disabled")

    def _fp_changes(self):
        if not self.fp:
            return 0
        return sum(1 for r in self.fp["rows"].values() if r["owned"] != r["orig"])

    def scan_folder_files(self, i):
        """Nút 'Quét file' của 1 thư mục: đọc tất cả file -> hiện ở khung bên phải."""
        if requests is None:
            messagebox.showerror(APP_NAME, "Thiếu thư viện 'requests'.")
            return
        if self.fp and self._fp_changes():
            ans = messagebox.askyesnocancel(APP_NAME, f"Thư mục \"{self.fp['fname']}\" có {self._fp_changes()} "
                                                      "thay đổi chưa lưu.\nLưu trước khi chuyển thư mục?")
            if ans is None:
                return
            if ans:
                self._fp_save()
        f = self.cfg["folders"][i]
        code = fid(f)
        if not resolve_src(self.cfg, f.get("url", "")):
            messagebox.showwarning(APP_NAME, "Nguồn không hợp lệ - bấm Sửa để chọn lại thư mục trong link chia sẻ.")
            return
        self.active_folder = i
        self.refresh_folders()
        self.fp = {"index": i, "code": code, "fname": f.get("name") or code, "rows": {}, "order": [],
                   "picked": set(), "loading": True}
        self.fp_tree.delete(*self.fp_tree.get_children())
        self.fp_empty.place_forget()
        self.fp_title.set(self.fp["fname"])
        self.fp_info.set("Đang quét tất cả file (cả thư mục con)...")
        self.fp_count.set("")
        for b in (self.fp_mark, self.fp_unmark, self.fp_save):
            b.config(state="disabled")
        cfg = json.loads(json.dumps(self.cfg))
        token = object()
        self.fp["token"] = token

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
                    d = fs.item_date(it)
                    out.append((fc, name, it.get("size"), d))
                okc = {o[0] for o in out}
                gaps = find_gaps([(it.get("_sub", ""), it.get("name") or "") for it in files
                                  if it.get("linkcode") in okc])
                dates = [o[3] for o in out if o[3]]
                ex = {"gaps": gaps}
                if dates:
                    ex["latest_up"] = max(dates).isoformat()
                self.q.put(("call", lambda: self._set_folder_extra(code, ex), (), {}, threading.Event()))
                for g_ in gaps:
                    self.q.put(("log", f"[{f.get('name') or code}] ⚠ Có thể thiếu tập: {g_}"))
                self.fp_skipped = skipped
                self.fp_errors = list(fs.errors)
                subdirs = list(fs.subdirs)
                self.q.put(("call", lambda: self._set_subs(code, subdirs), (), {}, threading.Event()))
                subs = ", ".join(f"{k or '(gốc)'}: {v}" for k, v in fs.subs.items())
                self.q.put(("log", f"[{f.get('name') or code}] Quét file: {len(files)} file · " + subs))
                for sub, err in fs.errors:
                    self.q.put(("log", f"[{f.get('name') or code}] ⚠ Thư mục con \"{sub}\" đọc lỗi: {err}"))
                self.q.put(("fp_loaded", token, i, real, out))
            except Exception as e:
                self.q.put(("fp_error", token, i, str(e)))
        threading.Thread(target=job, daemon=True).start()

    def _fp_loaded(self, token, i, real, files):
        if not self.fp or self.fp.get("token") is not token:
            return
        f = self.cfg["folders"][i]
        if not f.get("name") and real:
            f["name"] = real
            self.fp["fname"] = real
            self.fp_title.set(real)
        idx = self.owned_index()
        rows, seen = {}, set()
        for fc, name, size, d in files:
            if fc in seen:
                continue
            seen.add(fc)
            own = self.is_owned(idx, fc, self.fp["code"], name)
            h = self.history.get(fc, {})
            rows[fc] = {"name": name, "size": size, "date": d.strftime("%d/%m/%Y") if d else "",
                        "owned": own, "orig": own, "hist": h.get("status", ""), "sub": self.sub_of.get(fc, "")}
        order = sorted(rows, key=lambda c: (natural_key(rows[c]["sub"]), natural_key(rows[c]["name"])))
        self.fp.update(rows=rows, order=order, loading=False)
        for c in order:
            r = rows[c]
            self.fp_tree.insert("", "end", iid=c, text="", image=self.img_off,
                                values=(sub_label(r["sub"], r["name"]), r["date"], human_size(r["size"]), ""))
        n_own = sum(1 for r in rows.values() if r["owned"])
        n_sub = len({r["sub"] for r in rows.values() if r["sub"]})
        sk = getattr(self, "fp_skipped", {}) or {}
        self.fp_info.set(f"{len(order)} file" + (f" (trong {n_sub} thư mục con)" if n_sub else "")
                         + f"  ·  {n_own} đã có  ·  {len(order) - n_own} chưa có."
                         + (f"   Bỏ qua {sum(sk.values())} file: " + ", ".join(f"{k} ×{v}" for k, v in sk.items())
                            if sk else "   Tích chọn file → \"Thêm vào Danh sách đã có\" → \"Lưu\".")
                         + (f"   ⚠ {len(self.fp_errors)} thư mục con đọc lỗi (xem nhật ký)"
                            if getattr(self, "fp_errors", None) else ""))
        self._update_folder_stats(i, len(order), n_own, error="")
        self._fp_refresh()

    def _ack_gaps(self, i):
        f = self.cfg["folders"][i]
        f["gap_ack"] = "|".join(f.get("gaps") or [])
        save_json(CONFIG_FILE, self.cfg)
        self.refresh_folders()

    def _set_folder_extra(self, code, extra):
        for f in self.cfg["folders"]:
            if fid(f) == code:
                f.update(extra)
                save_json(CONFIG_FILE, self.cfg)
                self.refresh_folders()
                break

    def _link_label(self, lbl, url, color):
        """Nhãn link: bấm để mở, chuột phải copy, rê chuột gạch chân."""
        if not url:
            return
        base = lbl.cget("font")
        lbl.bind("<Button-1>", lambda e: open_target(url))
        lbl.bind("<Button-3>", lambda e: self._copy_text(url, "Đã copy link: " + url))
        lbl.bind("<Enter>", lambda e: lbl.config(font=tkfont.Font(font=base, underline=True)))
        lbl.bind("<Leave>", lambda e: lbl.config(font=base))

    def _copy_text(self, text, msg=""):
        self.clipboard_clear()
        self.clipboard_append(text)
        if msg:
            self.status_var.set(msg)

    def _toggle_subs(self, code):
        (self._subs_open.discard if code in self._subs_open else self._subs_open.add)(code)
        self.refresh_folders()

    def _set_subs(self, code, subdirs):
        for f in self.cfg["folders"]:
            if fid(f) == code:
                if f.get("subs") != subdirs:
                    f["subs"] = subdirs
                    save_json(CONFIG_FILE, self.cfg)
                    self.refresh_folders()
                break

    def _update_folder_stats(self, i, total, owned, error=None, reviewed=None):
        f = self.cfg["folders"][i]
        f.update(total=total, owned=owned, last_scan=time.time())
        if error is not None:
            f["last_error"] = error
        if reviewed is not None:
            f["reviewed"] = reviewed
        self.save_config(); self.refresh_folders()

    def _fp_label(self, r):
        if r["owned"] and not r["orig"]:
            return "✔  Đã có (chưa lưu)", "done"
        if not r["owned"] and r["orig"]:
            return "↺  Sẽ bỏ khỏi DS (chưa lưu)", "err"
        if r["owned"]:
            return "✔  Đã có", "done"
        if r["hist"] in WATCH_STATUSES:
            return "⬇  Đang tải", "dl"
        return "●  Chưa có", "new"

    def _fp_visible(self, c):
        r = self.fp["rows"][c]
        qq = strip_accents(self.fp_search.get().strip())
        if qq and qq not in strip_accents(r["name"]):
            return False
        return {"Tất cả": True, "Chưa có": not r["owned"], "Đã có": r["owned"],
                "Đang chọn": c in self.fp["picked"]}.get(self.fp_show.get(), True)

    def _fp_refresh(self):
        if not self.fp or self.fp.get("loading"):
            return
        n = 0
        for c in self.fp["order"]:
            if not self.fp_tree.exists(c):
                continue
            if self._fp_visible(c):
                self.fp_tree.move(c, "", "end")
                text, tag = self._fp_label(self.fp["rows"][c])
                self.fp_tree.set(c, "status", text)
                self.fp_tree.item(c, image=self.img_on if c in self.fp["picked"] else self.img_off,
                                  tags=(["odd"] if n % 2 else []) + [tag])
                n += 1
            else:
                self.fp_tree.detach(c)
        rows = self.fp["rows"]
        own = sum(1 for r in rows.values() if r["owned"])
        ch = self._fp_changes()
        picked = len(self.fp["picked"])
        self.fp_count.set(f"Đang chọn {picked} file   ·   Đã có {own}/{len(rows)}"
                          + (f"   ·   {ch} thay đổi CHƯA LƯU" if ch else ""))
        kids = self.fp_tree.get_children()
        self.fp_tree.heading("#0", image=self.img_on if kids and all(k in self.fp["picked"] for k in kids)
                             else self.img_off)
        self.fp_mark.config(state="normal" if picked else "disabled",
                            text=f"☑  Thêm vào Danh sách đã có ({picked})" if picked else "☑  Thêm vào Danh sách đã có")
        self.fp_unmark.config(state="normal" if picked else "disabled")
        reviewed = self.cfg["folders"][self.fp["index"]].get("reviewed")
        self.fp_save.config(state="normal" if (ch or not reviewed) else "disabled")

    def _fp_pick_visible(self, on):
        if not self.fp:
            return
        for c in self.fp_tree.get_children():
            (self.fp["picked"].add if on else self.fp["picked"].discard)(c)
        self._fp_refresh()

    def _fp_pick_until(self):
        if not self.fp:
            return
        sel = self.fp_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Bấm vào 1 dòng (VD: tập cuối cùng bạn đã có) rồi bấm lại nút này.")
            return
        kids = list(self.fp_tree.get_children())
        last = max(kids.index(x) for x in sel if x in kids)
        for c in kids[:last + 1]:
            self.fp["picked"].add(c)
        self._fp_refresh()

    def _fp_click(self, e):
        if not self.fp:
            return None
        if self.fp_tree.identify_region(e.x, e.y) not in ("tree", "cell") or self.fp_tree.identify_column(e.x) != "#0":
            return None
        c = self.fp_tree.identify_row(e.y)
        if c:
            p = self.fp["picked"]
            p.discard(c) if c in p else p.add(c)
            self._fp_refresh()
        return "break"

    def _fp_toggle_sel(self, _e=None):
        if not self.fp:
            return "break"
        sel = self.fp_tree.selection()
        if sel:
            on = any(c not in self.fp["picked"] for c in sel)
            for c in sel:
                (self.fp["picked"].add if on else self.fp["picked"].discard)(c)
            self._fp_refresh()
        return "break"

    def _fp_mark(self, on):
        if not self.fp:
            return
        for c in self.fp["picked"]:
            self.fp["rows"][c]["owned"] = on
        self.fp["picked"].clear()
        self._fp_refresh()

    def _fp_save_click(self):
        n = self._fp_save()
        if n is not None:
            self.status_var.set(n)

    def _fp_save(self):
        if not self.fp or self.fp.get("loading"):
            return None
        fp = self.fp
        f = self.cfg["folders"][fp["index"]]
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
        self._update_folder_stats(fp["index"], len(fp["rows"]), own, reviewed=True)
        msg = (f"[{fp['fname']}] Đã lưu: +{add} file vào Danh sách đã có" + (f", bỏ {rem} file" if rem else "")
               + f". Thư mục đã duyệt: {own}/{len(fp['rows'])} file đã có.")
        self.log(msg)
        self.fp_info.set(f"{len(fp['rows'])} file  ·  {own} đã có  ·  {len(fp['rows']) - own} chưa có.   ✔ Đã lưu.")
        self._fp_refresh()
        return msg

    # ================================================================ TAB QUÉT & TẢI
    def _build_scan(self):
        if LAYOUT == "workspace":
            return self._build_scan_ws()
        if LAYOUT == "movie":
            return self._build_scan_movie()
        cards = ttk.Frame(self.tab_scan, style="Card.TFrame")
        cards.pack(fill="x")
        self.stat_vars = {}
        sc = STAT_COLORS or (C_STAT1, C_BLUE, C_ORANGE, C_GREEN)
        for i, (key, title, color, glyph) in enumerate((("folders", "Thư mục sẽ quét", sc[0], "▦"),
                                                 ("new", "File mới chưa có", sc[1], "●"),
                                                 ("dl", "Đang tải", sc[2], "⬇"),
                                                 ("owned", "Danh sách đã có", sc[3], "✔"))):
            card, var = self._stat_card(cards, title, color, glyph)
            card.grid(row=0, column=i, sticky="we", padx=(0 if i == 0 else 10, 0))
            cards.columnconfigure(i, weight=1)
            self.stat_vars[key] = var

        self._build_energy(self.tab_scan)
        bar = ttk.Frame(self.tab_scan, style="Card.TFrame")
        bar.pack(fill="x", pady=(12, 10))
        ttk.Label(bar, text="Chỉ hiện những file CHƯA có trong Danh sách đã có (thư mục chưa duyệt sẽ không tự tải).",
                  style="Muted.TLabel").pack(side="left")
        self.btn_stop = ttk.Button(bar, text="■  Dừng", style="Danger.TButton", command=self.stop_flag.set,
                                   state="disabled")
        self.btn_go = ttk.Button(bar, text="⬇  Quét & Tải", style="Accent.TButton",
                                 command=lambda: self.start_scan(True))
        self.btn_scan = ttk.Button(bar, text="⌕  Quét", command=lambda: self.start_scan(False))
        self.btn_stop.pack(side="right")
        self.btn_go.pack(side="right", padx=8)
        self.btn_scan.pack(side="right")

        sel = tk.Frame(self.tab_scan, bg=C_SOFT, highlightbackground=C_SOFT_BORDER, highlightthickness=1)
        sel.pack(fill="x", pady=(0, 8))
        r1 = tk.Frame(sel, bg=C_SOFT, padx=10, pady=6)
        r1.pack(fill="x")
        ttk.Button(r1, text="Chọn tất cả", image=self.img_on, compound="left",
                   command=lambda: self.check_all(True)).pack(side="left")
        ttk.Button(r1, text="Bỏ chọn", image=self.img_off, compound="left",
                   command=lambda: self.check_all(False)).pack(side="left", padx=6)
        self.sel_var = tk.StringVar(value="Đã chọn: 0")
        tk.Label(r1, textvariable=self.sel_var, bg=C_SOFT, fg=C_ACCENT, font=(FONT, 10, "bold")
                 ).pack(side="left", padx=12)
        self.btn_dl_sel = ttk.Button(r1, text="⬇  Tải mục đã chọn", style="Cta.TButton",
                                     command=self.start_download_selected, state="disabled")
        self.btn_dl_sel.pack(side="right")
        self.btn_own_sel = ttk.Button(r1, text="☑  Đánh dấu đã có", command=self.mark_selected_owned,
                                      state="disabled")
        self.btn_own_sel.pack(side="right", padx=8)
        r2 = tk.Frame(sel, bg=C_SOFT, padx=10)
        r2.pack(fill="x", pady=(0, 6))
        tk.Label(r2, text="⌕ Tìm", bg=C_SOFT, fg=C_MUTED, font=(FONT, 9)).pack(side="left")
        self.scan_search_var = tk.StringVar()
        ttk.Entry(r2, textvariable=self.scan_search_var, width=26).pack(side="left", padx=(4, 12))
        self.scan_search_var.trace_add("write", lambda *a: self._apply_scan_filter())
        tk.Label(r2, text="Hiện", bg=C_SOFT, fg=C_MUTED, font=(FONT, 9)).pack(side="left")
        self.scan_show_var = tk.StringVar(value="Tất cả")
        sh = ttk.Combobox(r2, textvariable=self.scan_show_var, state="readonly", width=14,
                          values=("Tất cả", "Mới", "Đang tải", "Lỗi", "Chưa duyệt", "Đã chọn"))
        sh.pack(side="left", padx=4)
        sh.bind("<<ComboboxSelected>>", lambda e: self._apply_scan_filter())

        wrap, self.scan_tree = self._tree(self.tab_scan, ("folder", "note", "name", "date", "size", "status"),
                                          ("PHIM", "GHI CHÚ", "TÊN FILE", "NGÀY UP", "DUNG LƯỢNG", "TRẠNG THÁI"),
                                          (170, 170, 330, 100, 100, 220), height=10, check=True,
                                          stretch=("folder", "name", "note"))
        wrap.pack(fill="both", expand=True)
        self.checked = set()
        self.scan_tree.heading("#0", image=self.img_off, anchor="center", command=self._toggle_all_header)
        self.scan_tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.scan_tree.bind("<space>", self._toggle_selected_rows)
        self.scan_tree.bind("<Double-1>", self._open_selected)
        self.scan_tree.bind("<<TreeviewSelect>>", lambda e: self._show_full(self.scan_tree))
        self.scan_items = {}
        self.scan_order = []
        self.scan_sort = (None, False)
        for c in ("folder", "note", "name", "date", "size", "status"):
            self.scan_tree.heading(c, command=lambda c=c: self._sort_scan(c))

        ttk.Label(self.tab_scan, text="Nhật ký   (bấm ô vuông để chọn, nhấp đúp để mở file nguồn, "
                                      "bấm tiêu đề cột để sắp xếp)", style="Muted.TLabel").pack(anchor="w", pady=(10, 4))
        lb = tk.Frame(self.tab_scan, bg=C_BORDER, padx=1, pady=1)
        lb.pack(fill="x")
        self.log_box = tk.Text(lb, height=6, wrap="word", font=("Consolas", 9), bg=C_LOG_BG, fg=C_LOG_FG,
                               insertbackground="white", relief="flat", padx=10, pady=8)
        self.log_box.pack(fill="both")

    def _row_visible(self, iid):
        q = strip_accents(self.scan_search_var.get().strip())
        if q and q not in strip_accents(" ".join(str(v) for v in self.scan_tree.item(iid, "values"))):
            return False
        mv = getattr(self, "mv_sel", None)
        if mv:
            it = self.scan_items.get(iid)
            if not it or it[4] != mv:
                return False
        show = self.scan_show_var.get()
        tags = self.scan_tree.item(iid, "tags")
        return {"Tất cả": True, "Mới": "new" in tags,
                "Đang tải": "dl" in tags or ("done" in tags and LAYOUT == "classic"),
                "Lỗi": "err" in tags, "Chưa duyệt": "skip" in tags, "Xong": "done" in tags,
                "Đã chọn": iid in self.checked}.get(show, True)

    def _set_row(self, iid, status, tag):
        if self.scan_tree.exists(iid):
            vals = list(self.scan_tree.item(iid, "values"))
            vals[5] = status
            tags = [t for t in self.scan_tree.item(iid, "tags") if t == "odd"] + [tag]
            self.scan_tree.item(iid, values=vals, tags=tags)

    def _update_sel_count(self):
        n = len(self._checked())
        total = len(self.scan_tree.get_children())
        self.sel_var.set(f"Đã chọn: {n}/{total}")
        vis = [i for i in self.scan_tree.get_children() if i in self.checked]
        self.scan_tree.heading("#0", image=self.img_on if total and len(vis) == total else self.img_off)
        busy = bool(self.worker and self.worker.is_alive())
        self.btn_dl_sel.config(state="normal" if n and not busy else "disabled",
                               text=f"⬇  Tải mục đã chọn ({n})" if n else "⬇  Tải mục đã chọn")
        self.btn_own_sel.config(state="normal" if n and not busy else "disabled")

    def _show_full(self, tree):
        """Bấm 1 dòng -> hiện đầy đủ nội dung dòng đó ở thanh trạng thái (khi cột bị hẹp)."""
        sel = tree.selection()
        if sel:
            vals = [str(v) for v in tree.item(sel[0], "values") if str(v).strip()]
            self.status_var.set("   ·   ".join(vals))

    def check_new_only(self):
        for i in self.scan_tree.get_children():
            self._set_check(i, "new" in self.scan_tree.item(i, "tags"))
        self._update_sel_count()

    def _open_selected(self, e=None):
        if e is not None and self.scan_tree.identify_column(e.x) == "#0":
            return
        sel = self.scan_tree.selection()
        for code in sel[:5]:
            m = self.item_meta.get(code) or {}
            if m.get("path") and os.path.exists(m["path"]):
                if os.name == "nt":
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(m["path"])])
                else:
                    open_target(os.path.dirname(m["path"]))
            elif m.get("share"):
                open_target(f"https://mypikpak.com/s/{m['share']}")

    def mark_selected_owned(self):
        codes = self._checked()
        if not codes:
            return
        for c in codes:
            it = self.scan_items.get(c)
            if it:
                fcode, fname, name, size, folder_code = it
                self.add_owned(fcode, folder_code, fname, name, size, "manual")
                if self.scan_tree.exists(c):
                    self.scan_tree.delete(c)
                self.checked.discard(c)
        self.scan_order = [i for i in self.scan_order if self.scan_tree.exists(i)]
        self.save_owned()
        self._new_count = max(0, getattr(self, "_new_count", 0) - len(codes))
        self.rows_ver += 1
        self.log(f"Đã thêm {len(codes)} file vào Danh sách đã có (sẽ không tải).")
        self._apply_scan_filter()
        self.update_stats()

    def start_scan(self, download, auto=False, only=None):
        if self.worker and self.worker.is_alive():
            return False
        warn = (lambda m: self.log("[Tự quét] " + m)) if auto else (lambda m: messagebox.showwarning(APP_NAME, m))
        if requests is None:
            warn("Thiếu thư viện 'requests'. Chạy: pip install requests")
            return False
        self.save_config()
        if not self.cfg["folders"]:
            warn("Chưa có thư mục phim nào (tab Thư mục phim).")
            return False
        if not any(f.get("enabled", True) for f in self.cfg["folders"]):
            warn("Chưa chọn thư mục nào để quét (tab Thư mục phim).")
            return False
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.scan_items = {}
        self.scan_order = []
        self.checked = set()
        self._new_count = 0
        self.rows_ver += 1
        self.progress.config(value=0, maximum=max(1, sum(1 for f in self.cfg["folders"] if f.get("enabled", True))))
        if only:
            self.select_page("scan")
        self._run_worker(self._scan_job, download, auto, only)
        return True

    def _run_worker(self, target, *args):
        self.stop_flag.clear()
        for b in (self.btn_scan, self.btn_go, self.btn_dl_sel, self.btn_own_sel):
            b.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def start_download_selected(self):
        if self.worker and self.worker.is_alive():
            return
        codes = self._checked()
        if not codes:
            return
        items = [self.scan_items[c] for c in codes if c in self.scan_items]
        idx = self.owned_index()
        items = [it for it in items if not self.is_owned(idx, it[0], it[4], it[2])]
        if items:
            self._run_worker(self._download_job, items)

    def _download_job(self, items):
        try:
            cfg = json.loads(json.dumps(self.cfg))
            if self._health_check(cfg, auto=False, items=items):
                self._download_items(cfg, items)
        except Exception as e:
            self.log(f"LỖI: {e}")
            self.report_error("Lỗi khi quét / tải", str(e), exc=e)
        finally:
            self.q.put(("done", "Đã dừng." if self.stop_flag.is_set() else "Xong."))

    def diagnose_folder(self, i):
        """Quét 1 thư mục và ghi ra file .txt: mọi thư mục con, mọi file, và LÝ DO file bị bỏ qua."""
        f = self.cfg["folders"][i]
        code = fid(f)
        fname = f.get("name") or code
        out_path = DATA_DIR / f"ChanDoan_{safe_name(fname)}.txt"
        cfg = json.loads(json.dumps(self.cfg))
        owned = json.loads(json.dumps(self.owned))
        self.status_var.set(f"Đang chẩn đoán {fname}...")
        self.log(f"[{fname}] Chẩn đoán: đang đọc toàn bộ thư mục...")

        def job():
            src = resolve_src(cfg, f.get("url", ""))
            lines = [f"{APP_TITLE} {APP_VERSION} - CHẨN ĐOÁN THƯ MỤC", f"Thời gian: {dt.datetime.now():%d/%m/%Y %H:%M:%S}",
                     f"Thư mục: {fname}", f"Nguồn: {f.get('src_label') or ''}  {f.get('url')}",
                     f"Đuôi file cần tải: {cfg.get('extensions', '')}",
                     f"Từ khóa lọc: chỉ lấy=[{f.get('include', '')}]  loại=[{f.get('exclude', '')}]"]
            if not is_share(src):
                pass
            lines.append("")
            exts = {e.lower() if e.startswith(".") else "." + e.lower()
                    for e in cfg.get("extensions", "").split() if e.strip()}
            inc, exc = f.get("include", ""), f.get("exclude", "")
            stats = {"file": 0, "ok": 0, "skip": 0, "owned": 0}
            try:
                fs = make_source(cfg, f, self.log)
                files = list(fs.walk())
                for sub, err in fs.errors:
                    lines.append(f"✘ LỖI ĐỌC [{sub}]: {err}")
                lines.append("Thư mục con: " + (", ".join(f"{k or '(gốc)'}: {v} file" for k, v in fs.subs.items()) or "-"))
                lines.append("")
                for it in sorted(files, key=lambda x: (natural_key(x.get("_sub", "")), natural_key(x.get("name", "")))):
                    nm, cc = it.get("name", ""), it.get("linkcode", "")
                    stats["file"] += 1
                    ext = os.path.splitext(nm)[1].lower()
                    if exts and ext not in exts:
                        why = f"✘ BỎ QUA: đuôi {ext or '(không đuôi)'} không có trong danh sách đuôi"
                    elif (inc or exc) and not match_keywords(nm, inc, exc):
                        why = "✘ BỎ QUA: bị lọc bởi từ khóa của thư mục"
                    elif cc in owned:
                        why = "● ĐÃ CÓ"
                    else:
                        why = "✔ CHƯA CÓ → sẽ hiện khi quét"
                    stats["skip" if why.startswith("✘") else "owned" if why.startswith("●") else "ok"] += 1
                    lines.append(f"    {sub_label(it.get('_sub', ''), nm)}  |  {human_size(it.get('size'))}  |  {why}")
                lines.insert(7, f"TỔNG: {stats['file']} file · chưa có {stats['ok']} · đã có {stats['owned']} · "
                                f"bị bỏ qua {stats['skip']}\n")
            except Exception as e:
                lines.append(f"✘ LỖI: {e}")
            try:
                with open(out_path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
                    fh.write("\n".join(lines))
                self.q.put(("call", lambda: self._diagnose_done(fname, out_path, stats), (), {}, threading.Event()))
            except Exception as e:
                self.q.put(("log", f"[{fname}] Chẩn đoán lỗi: {e}"))
        threading.Thread(target=job, daemon=True).start()

    def _diagnose_done(self, fname, path, stats):
        self.log(f"[{fname}] Chẩn đoán xong: {stats['file']} file · chưa có {stats['ok']} · đã có {stats['owned']} · "
                 f"bỏ qua {stats['skip']}  →  {path}")
        self.status_var.set(f"Đã lưu kết quả chẩn đoán: {path.name}")
        try:
            if os.name == "nt":
                os.startfile(str(path))
        except OSError:
            pass

    def _health_check(self, cfg, auto, items=None):
        """Kiểm tra IM LẶNG trước khi tải: rclone + đăng nhập PikPak, ổ HDD đã cắm, chỗ trống.
        Chỉ báo khi có vấn đề. Trả về False nếu người dùng chọn không tải."""
        if not cfg.get("health_check", True):
            return True
        probs = []
        items = items or []
        need = sum(int(it[3] or 0) for it in items)
        uses_share = any(is_share(f.get("url", "")) for f in cfg["folders"] if f.get("enabled", True))
        r = find_rclone()
        if not r:
            probs.append("Chưa có rclone.exe trong thư mục tool - không tải được từ My PikPak về HDD "
                         "(Cài đặt → rclone → Tải rclone).")
        elif (any(f.get("pikpak_dir") for f in cfg["folders"] if f.get("enabled", True)) or uses_share) \
                and getattr(self, "pk_ok", None) is False:
            probs.append("Chưa kết nối được PikPak (rclone) - kiểm tra tài khoản PikPak trong Cài đặt.")
        if uses_share and not (cfg.get("pikpak_user") and cfg.get("pikpak_pass")):
            probs.append("Có link chia sẻ PikPak nhưng chưa lưu tài khoản PikPak (Cài đặt → Tài khoản PikPak).")
        codes = {it[4] for it in items} if items else {fid(f) for f in cfg["folders"] if f.get("enabled", True)}
        chk = []
        for f in cfg["folders"]:
            if fid(f) not in codes or not f.get("local_dir"):
                continue
            d = from_portable(f["local_dir"])
            n = sum(int(it[3] or 0) for it in items if it[4] == fid(f))
            drv = os.path.splitdrive(os.path.abspath(d))[0]
            if drv and not os.path.exists(drv + os.sep):
                probs.append(f"Không thấy ổ {drv} (đích HDD của \"{f.get('name') or d}\") - ổ chưa cắm?")
                continue
            try:
                os.makedirs(d, exist_ok=True)
                chk.append((d, n))
            except OSError as e:
                probs.append(f"Không tạo được thư mục đích {d}: {e}")
        seen_drive = {}
        for d, n in chk:
            if not os.path.isdir(d):
                continue
            drv = os.path.splitdrive(os.path.abspath(d))[0] or d
            seen_drive[drv] = (d, seen_drive.get(drv, (d, 0))[1] + n)
        for drv, (d, n) in seen_drive.items():
            try:
                free = shutil.disk_usage(d).free
                if free < max(5 * 1024 ** 3, n + 1024 ** 3):
                    probs.append(f"Ổ {drv} chỉ còn trống {human_size(free)}" + (f" (cần ~{human_size(n)})" if n else "") + ".")
            except OSError:
                pass
        self.q.put(("call", lambda: self._show_health(probs), (), {}, threading.Event()))
        if not probs:
            self.log("✔ Kiểm tra trước khi tải: OK")
            return True
        for p_ in probs:
            self.log("⚠ Kiểm tra trước khi tải: " + p_)
        sig = "|".join(probs)
        last_sig, last_ts = getattr(self, "_health_last", ("", 0))
        if sig != last_sig or time.time() - last_ts > 3 * 3600:
            self._health_last = (sig, time.time())
            self.q.put(("notify", "⚠ Kiểm tra trước khi tải", " · ".join(probs)[:240]))
        if auto:
            return True
        try:
            return self.call_ui(lambda: messagebox.askyesno(APP_NAME + " - Kiểm tra trước khi tải",
                                                            "Phát hiện vấn đề:\n\n• " + "\n• ".join(probs) +
                                                            "\n\nVẫn tiếp tục tải?"), timeout=600)
        except Exception:
            return True

    def _show_health(self, probs):
        self._health_probs = list(probs)
        try:
            if probs:
                self.side_health.config(text="⚠ " + "\n⚠ ".join(probs))
                if LAYOUT == "classic":
                    self.side_health.pack(fill="x", pady=(4, 0), before=self.side_pk)
                else:
                    self.side_health.pack(fill="x", pady=(8, 0))
            else:
                self.side_health.pack_forget()
        except (AttributeError, tk.TclError):
            pass

    def _scan_job(self, download, auto=False, only=None):
        cfg = json.loads(json.dumps(self.cfg))
        exts = {e.lower() if e.startswith(".") else "." + e.lower()
                for e in cfg.get("extensions", "").split() if e.strip()}
        history = json.loads(json.dumps(self.history))
        idx = self.owned_index()
        new_items, seen = [], set()
        stats = {"owned": 0, "dl": 0, "retry": 0, "err": 0, "unrev": 0, "failed": []}
        targets = [(i, f) for i, f in enumerate(cfg["folders"])
                   if ((fid(f) in only) if only else f.get("enabled", True))]
        now_ts = time.time()
        self.log(f"=== {dt.datetime.now():%d/%m/%Y %H:%M} | Quét {len(targets)}/{len(cfg['folders'])} thư mục ===")
        try:
            for n, (orig_i, f) in enumerate(targets, 1):
                if self.stop_flag.is_set():
                    break
                code = fid(f)
                fname = f.get("name") or code
                self.q.put(("status", f"Đang quét {n}/{len(targets)}: {fname}"))
                if not resolve_src(cfg, f.get("url", "")):
                    self.q.put(("folderstat", orig_i, {"last_scan": time.time(),
                                                       "last_error": "Nguồn không hợp lệ"}))
                    continue
                fs = make_source(cfg, f, self.log)
                files, err = None, None
                for _ in range(3):
                    try:
                        files = list(fs.walk())
                        if not f.get("name"):
                            real = getattr(fs, "title", None) or (os.path.basename(os.path.normpath(fs.path))
                                                                  if isinstance(fs, LocalSource) else "")
                            if real:
                                fname = real
                                self.q.put(("foldername", orig_i, real))
                        self.note_listing(files)
                        if fs.errors:
                            err = RuntimeError("; ".join(f"{a}: {b}" for a, b in fs.errors))
                            if _ < 2 and not self.stop_flag.wait(3):
                                continue        # thử lại cả thư mục
                            self.log(f"[{fname}] ⚠ {len(fs.errors)} thư mục con đọc lỗi: {err}")
                        break
                    except Exception as e:
                        err = e
                        if self.stop_flag.wait(3):
                            break
                if files is None:
                    self.log(f"[{fname}] LỖI sau 3 lần thử: {err}")
                    self.report_error(f"Quét thư mục lỗi: {fname}", str(err),
                                      exc=err if isinstance(err, BaseException) else None)
                    stats["failed"].append(fname)
                    self.q.put(("folderstat", orig_i, {"last_scan": time.time(), "last_error": str(err)[:120]}))
                    self.q.put(("progress", n, len(targets)))
                    continue
                reviewed = bool(f.get("reviewed"))
                idx = self.owned_index()
                inc, exc = f.get("include", ""), f.get("exclude", "")
                total = owned_n = new_n = 0
                rows, skipped, allnames, latest = [], {}, [], None
                for it in files:
                    name, fcode = it.get("name") or "", it.get("linkcode")
                    if not fcode or not name:
                        continue
                    if exts and os.path.splitext(name)[1].lower() not in exts:
                        if fcode not in seen:
                            e = os.path.splitext(name)[1].lower() or "(không đuôi)"
                            skipped[e] = skipped.get(e, 0) + 1
                        continue
                    if (inc or exc) and not match_keywords(name, inc, exc):
                        continue
                    allnames.append((it.get("_sub", ""), name))
                    d0 = fs.item_date(it)
                    if d0 and (latest is None or d0 > latest):
                        latest = d0
                    if fcode in seen:
                        continue
                    seen.add(fcode)
                    total += 1
                    if self.is_owned(idx, fcode, code, name):
                        owned_n += 1
                        continue
                    new_n += 1
                    d = fs.item_date(it)
                    sub = it.get("_sub", "")
                    rows.append(((natural_key(sub), natural_key(name)), fcode, name, d, it.get("size"), sub))
                for _k, fcode, name, d, size, sub in sorted(rows, key=lambda r: r[0]):
                    movie = movie_of(f, sub, name)
                    row = (movie, one_line(f.get("note", "")), sub_label(sub, name), d.strftime("%d/%m/%Y") if d else "",
                           human_size(size))
                    item = (fcode, movie, name, size, code)
                    h = history.get(fcode, {})
                    st = h.get("status", "")
                    put = (lambda s_, t_: self.q.put(("row", fcode, row + (s_,), t_, item)))
                    if not reviewed:
                        stats["unrev"] += 1
                        put("◔  Thư mục chưa duyệt", "skip")
                    elif st in WATCH_STATUSES and now_ts - float(h.get("ts", now_ts) or now_ts) < STALE_HOURS * 3600:
                        stats["dl"] += 1
                        put("⬇  Đã mở, chờ tải xong", "dl")
                    elif st in RETRY_STATUSES:
                        tries = int(h.get("tries", 1) or 1)
                        if tries < MAX_TRIES:
                            stats["retry"] += 1
                            put(f"↻  Thử lại (lỗi {tries}/{MAX_TRIES})", "new")
                            new_items.append(item)
                        else:
                            stats["err"] += 1
                            put(f"⚠  Lỗi {tries} lần - hãy kiểm tra", "err")
                    else:
                        put("●  Mới", "new")
                        new_items.append(item)
                gaps = find_gaps(allnames)
                gsig = "|".join(gaps)
                extra = {"gaps": gaps, "latest_up": latest.isoformat() if latest else f.get("latest_up", "")}
                if gaps and gsig != f.get("gap_ack") and gsig != f.get("gap_notified"):
                    stats.setdefault("gaps", []).append((fname, gaps))
                    extra["gap_notified"] = gsig
                    for g_ in gaps:
                        self.log(f"[{fname}] ⚠ Có thể thiếu tập: {g_}")
                sd = int(cfg.get("stale_days", 7) or 0)
                if sd and latest and reviewed:
                    days = (dt.date.today() - latest).days
                    if days >= sd and f.get("stale_notified") != dt.date.today().isoformat():
                        stats.setdefault("stale", []).append((fname, days))
                        extra["stale_notified"] = dt.date.today().isoformat()
                        self.log(f"[{fname}] ⏳ {days} ngày chưa có tập mới (tập mới nhất up {latest:%d/%m/%Y}) - "
                                 "kiểm tra xem bên up có chuyển sang thư mục khác không.")
                self.q.put(("folderstat", orig_i, dict({"last_scan": time.time(), "last_error": "",
                                                        "subs": list(fs.subdirs), "total": total, "owned": owned_n},
                                                       **extra)))
                n_sub = len({it.get("_sub") for it in files if it.get("_sub")})
                if skipped:
                    self.log(f"[{fname}] Bỏ qua {sum(skipped.values())} file khác đuôi: "
                             + ", ".join(f"{k} ×{v}" for k, v in skipped.items())
                             + "  (thêm đuôi trong Cài đặt → Tải về nếu cần)")
                self.log(f"[{fname}] {total} file" + (f" ({n_sub} thư mục con)" if n_sub else "")
                         + f" · đã có {owned_n} · chưa có {new_n}"
                         + ("" if reviewed else "  (chưa duyệt — vào tab Thư mục bấm Quét file)"))
                self.q.put(("progress", n, len(targets)))

            self.q.put(("newcount", len(new_items)))
            failed = stats["failed"]
            summary = (f"{dt.datetime.now():%H:%M %d/%m} · {len(targets)} thư mục · {len(new_items)} file mới"
                       + (f" · {len(failed)} thư mục lỗi" if failed else ""))
            self.q.put(("summary", summary))
            self.log(f"Tổng kết: {len(new_items)} file mới cần tải ({stats['retry']} thử lại), "
                     f"{stats['dl']} đang chờ tải xong, {stats['unrev']} file ở thư mục chưa duyệt.")
            if failed:
                self.log("Thư mục lỗi: " + ", ".join(failed))
                if auto:
                    self.q.put(("retry_soon", 600))
                self.q.put(("notify", f"{len(failed)} thư mục quét lỗi", ", ".join(failed[:3])))
            if stats.get("gaps"):
                self.q.put(("notify", f"⚠ {len(stats['gaps'])} thư mục có thể thiếu tập",
                            "; ".join(f"{n_}: {g_[0]}" for n_, g_ in stats["gaps"][:3])))
            if stats.get("stale"):
                self.q.put(("notify", f"⏳ {len(stats['stale'])} thư mục lâu không có tập mới",
                            ", ".join(f"{n_} ({d_} ngày)" for n_, d_ in stats["stale"][:4])))
            if download and new_items and not self.stop_flag.is_set():
                if self._health_check(cfg, auto, new_items):
                    self._download_items(cfg, new_items, auto=auto)
                else:
                    self.log("Đã hủy tải (kiểm tra trước khi tải chưa đạt). Danh sách file mới vẫn ở bảng.")
            elif new_items and not download:
                self.q.put(("notify", f"Có {len(new_items)} file mới", self._names_preview([x[2] for x in new_items])))
        except Exception as e:
            self.log(f"LỖI: {e}")
            self.report_error("Lỗi khi quét / tải", str(e), exc=e)
        finally:
            self.q.put(("done", "Đã dừng." if self.stop_flag.is_set() else
                        ("Tự quét xong. " if auto else "Xong. ") ))

    def _download_items(self, cfg, items, auto=False):
        """Tải lần lượt từng file: về máy -> kiểm tra dung lượng -> copy sang HDD -> lưu vào My PikPak."""
        self.q.put(("progress", 0, len(items)))
        ok_names, bad = [], 0
        failed = []
        if self.cfg.get("iphone_on", True):
            ipd = resolve_iphone_dir(self.cfg.get("iphone_dir"))
            try:
                os.makedirs(ipd, exist_ok=True)
                self.log(f"📱 Sẽ copy thêm 1 bản vào: {ipd}")
            except OSError as e:
                self.log(f"⚠ Không tạo được thư mục COPY_TO_IPHONE {ipd}: {e}")
        else:
            self.log("📱 Copy vào COPY_TO_IPHONE đang TẮT (Cài đặt → Chung).")

        def run(item):
            try:
                return self._fetch_one(cfg, item)
            except Exception as e:
                self._last_exc = e
                self._fetch_fail(item, STATUS_FAIL, str(e))
                return False
        for i, item in enumerate(items, 1):
            if self.stop_flag.is_set():
                break
            self.q.put(("status", f"Đang tải {i}/{len(items)}: {item[2]}"))
            if run(item):
                ok_names.append(item[2])
            else:
                failed.append(item)
            self.q.put(("progress", i, len(items)))
            if i < len(items) and not self.stop_flag.is_set():
                self.stop_flag.wait(max(0, int(cfg.get("delay", 2) or 0)))
        # file lỗi giữa chừng (đã xóa file lỗi) -> thử tải lại ngay, tối đa RETRY_NOW lượt
        for rnd in range(1, RETRY_NOW + 1):
            if not failed or self.stop_flag.is_set():
                break
            wait = 20 * rnd
            self.log(f"↻ Thử tải lại {len(failed)} file lỗi (lượt {rnd}/{RETRY_NOW}) sau {wait} giây...")
            self.q.put(("status", f"Chờ {wait}s rồi tải lại {len(failed)} file lỗi..."))
            if self.stop_flag.wait(wait):
                break
            again = []
            for item in failed:
                if self.stop_flag.is_set():
                    again.append(item)
                    continue
                self.q.put(("rowstatus", item[0], f"↻  Đang tải lại (lượt {rnd})...", "dl"))
                if run(item):
                    ok_names.append(item[2])
                else:
                    again.append(item)
            failed = again
        bad = len(failed)
        self.log(f"Tải xong {len(ok_names)}/{len(items)} file." + (
            f" {bad} file vẫn lỗi - đã nằm trong danh sách tải lại (lần quét sau tự tải lại): "
            + self._names_preview([x[2] for x in failed]) if bad else ""))
        if ok_names:
            self.q.put(("notify", f"✔ Tải xong {len(ok_names)} file", self._names_preview(ok_names)))
            self.q.put(("call", self.schedule_backup, (), {}, threading.Event()))
        return bool(ok_names)

    def _fetch_fail(self, item, status, msg):
        fcode, fname, name, size, folder_code = item
        h = dict(self.history.get(fcode) or {})
        tries = int(h.get("tries", 0) or 0) + 1
        h.update(status=status, tries=tries, error=msg[:300])
        self.q.put(("hist", fcode, h))
        self.q.put(("rowstatus", fcode, f"⚠  {status} (lần {tries}/{MAX_TRIES}): {msg[:80]}", "err"))
        self.log(f"⚠ [{name}] {status}: {msg}")
        if tries >= 2:      # lần đầu lỗi -> tool tự tải lại; chỉ tạo báo cáo khi tải lại vẫn lỗi
            self.report_error(f"{status} (lần {tries}): {name}", msg, item=item,
                              exc=getattr(self, "_last_exc", None))
        self._last_exc = None

    def _remove_broken(self, dst, size, force=False):
        """Xóa file copy dở / lỗi (file .part và file đích nếu thiếu dung lượng). Trả về True nếu có xóa."""
        removed = False
        for p_ in (dst + ".part", dst):
            try:
                if not os.path.isfile(p_):
                    continue
                if p_ == dst and not force and size and os.path.getsize(p_) >= size * 0.995:
                    continue                       # file đích đủ dung lượng -> giữ
                for _ in range(5):                 # file có thể còn bị giữ vài giây
                    try:
                        os.remove(p_)
                        removed = True
                        self.log(f"✕ Đã xóa file lỗi: {p_}")
                        break
                    except PermissionError:
                        time.sleep(2)
            except OSError as e:
                self.log(f"⚠ Không xóa được file lỗi {p_}: {e}")
        return removed

    # ================================================================ BÁO CÁO LỖI (để copy gửi Claude)
    def report_error(self, title, msg="", item=None, exc=None):
        """Ghi 1 file báo cáo lỗi vào Data\\BaoLoi\\ (an toàn gọi từ mọi luồng). Không ghi mật khẩu."""
        import platform
        import traceback
        now = time.time()
        times = [t for t in getattr(self, "_err_times", []) if now - t < 3600]
        if len(times) >= 30:                  # tối đa 30 báo cáo / giờ
            return None
        self._err_times = times + [now]
        try:
            d = DATA_DIR / "BaoLoi"
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"BaoLoi_{dt.datetime.now():%Y%m%d_%H%M%S}_{len(times):02d}.txt"
            cfg = json.loads(json.dumps(self.cfg))
            for k in ("pikpak_pass", "admin_hash", "admin_salt", "profiles", "window"):
                cfg.pop(k, None)
            if cfg.get("pikpak_user"):
                u = cfg["pikpak_user"]
                cfg["pikpak_user"] = u[:3] + "***" + (u[u.find("@"):] if "@" in u else "")
            lines = ["=== BÁO CÁO LỖI - " + APP_NAME + " ===",
                     f"Thời gian : {dt.datetime.now():%d/%m/%Y %H:%M:%S}",
                     f"Máy       : {MACHINE}  ·  {platform.platform()}  ·  Python {platform.python_version()}"
                     + ("  ·  bản exe" if getattr(sys, "frozen", False) else ""),
                     f"Thư mục   : {BASE}",
                     f"rclone    : {find_rclone() or '(chưa có)'}",
                     f"Link gốc  : {cfg.get('share_root', '')}",
                     "", "--- LỖI ---", title, str(msg or "")]
            if item:
                fcode, fname, name, size, folder_code = item
                meta = dict(self.item_meta.get(fcode) or {})
                fc = next((f for f in cfg.get("folders", []) if f.get("id") == folder_code), {})
                lines += ["", "--- FILE ---", f"Tên       : {name}", f"Dung lượng: {human_size(size)} ({size})",
                          f"Phim      : {fname}", f"Nguồn file: {meta.get('path') or meta.get('share') or '?'}",
                          f"Thư mục phim: {json.dumps(fc, ensure_ascii=False)}"]
            if exc is not None:
                lines += ["", "--- TRACEBACK ---"] + traceback.format_exception(type(exc), exc, exc.__traceback__)
            lines += ["", "--- CẤU HÌNH (đã bỏ mật khẩu) ---", json.dumps(cfg, ensure_ascii=False, indent=1)[:6000],
                      "", "--- NHẬT KÝ GẦN NHẤT ---"] + list(self.log_lines)[-60:]
            path.write_text("\n".join(str(x).rstrip("\n") for x in lines), encoding="utf-8")
            self.last_report = path
            self.q.put(("call", self._show_err_badge, (), {}, threading.Event()))
            return path
        except Exception:
            return None

    def _show_err_badge(self):
        d = DATA_DIR / "BaoLoi"
        n = len(list(d.glob("BaoLoi_*.txt"))) if d.is_dir() else 0
        try:
            if n:
                self.side_err.config(text=f"⚠ {n} báo cáo lỗi - bấm để COPY báo cáo mới nhất (dán vào Claude)")
                self.side_err.pack(fill="x", pady=(6 if LAYOUT == "classic" else 8, 0))
            else:
                self.side_err.pack_forget()
        except (AttributeError, tk.TclError):
            pass

    def copy_last_report(self, _e=None):
        d = DATA_DIR / "BaoLoi"
        files = sorted(d.glob("BaoLoi_*.txt")) if d.is_dir() else []
        if not files:
            messagebox.showinfo(APP_NAME, "Chưa có báo cáo lỗi nào.")
            return
        txt = files[-1].read_text(encoding="utf-8", errors="replace")
        self._copy_text(txt, f"Đã copy báo cáo lỗi {files[-1].name} - dán vào Claude để sửa.")
        self.notify("Đã copy báo cáo lỗi", "Dán (Ctrl+V) vào Claude để sửa.")

    def open_reports(self):
        d = DATA_DIR / "BaoLoi"
        d.mkdir(parents=True, exist_ok=True)
        open_target(str(d))

    def clear_reports(self):
        d = DATA_DIR / "BaoLoi"
        for f_ in (d.glob("BaoLoi_*.txt") if d.is_dir() else []):
            try:
                f_.unlink()
            except OSError:
                pass
        self._show_err_badge()

    def _tk_exception(self, exc, val, tb):
        """Lỗi không lường trước trong giao diện -> ghi báo cáo thay vì im lặng."""
        val.__traceback__ = tb
        self.log(f"LỖI: {val}")
        self.report_error("Lỗi giao diện (không lường trước)", str(val), exc=val)

    def _fetch_one(self, cfg, item):
        """1 file: ① Save từ link chia sẻ vào My PikPak -> ② rclone tải từ My PikPak về HDD -> Danh sách đã có."""
        fcode, fname, name, size, folder_code = item
        meta = dict(self.item_meta.get(fcode) or (self.history.get(fcode) or {}).get("src") or {})
        if not meta:
            raise SourceError("Không còn thông tin nguồn của file - quét lại thư mục.")
        fcfg = next((f for f in cfg["folders"] if fid(f) == folder_code), None) or {}
        movie = fname or movie_of(fcfg, meta.get("sub", ""), name)
        hdd_dir = local_dir_for(cfg, fcfg, movie)
        pk_dir = pikpak_folder(cfg, fcfg, movie)
        if not meta.get("share"):
            raise SourceError("Nguồn không phải link chia sẻ PikPak - bấm Sửa thư mục phim để chọn lại nguồn.")
        if not pk_dir:
            raise SourceError("Thư mục phim chưa đặt Đích 1 (My PikPak) - vào tab Thư mục phim, bấm Sửa để đặt.")
        if not hdd_dir:
            raise SourceError("Thư mục phim chưa đặt Đích 2 (HDD) - vào tab Thư mục phim, bấm Sửa để đặt.")
        try:
            size = int(size or 0)
        except (TypeError, ValueError):
            size = 0
        now = dt.datetime.now()
        rec = dict(self.history.get(fcode) or {})
        rec.update({"folder": movie, "movie": movie, "source": fcfg.get("name", ""), "folder_code": folder_code,
                    "name": name, "size": size, "ts": now.timestamp(), "sent_at": now.strftime("%d/%m/%Y %H:%M"),
                    "status": STATUS_DL, "src": meta, "error": ""})
        self.q.put(("hist", fcode, dict(rec)))
        last = [0.0, -1]
        phase = ["⬇", "Đang tải"]

        def prog(pct, speed=""):
            if pct != last[1] and (time.time() - last[0] > 0.5 or pct >= 100):
                last[0], last[1] = time.time(), pct
                self.q.put(("rowstatus", fcode, f"{phase[0]} {ebar(pct)} {pct:>3}%   {speed}", "dl"))
                self.q.put(("status", f"{phase[1]} {name}: {pct}%  {speed}"))
                self.q.put(("energy", "dl", pct, f"{phase[0]} {name}   {speed}".rstrip()))
        self.q.put(("energy", "dl", 0, f"⬇ {name}"))

        rclone = find_rclone()
        remote = cfg.get("pikpak_remote", "pikpak") or "pikpak"
        extra = ["--bwlimit", cfg["bwlimit"]] if str(cfg.get("bwlimit", "")).strip() else []
        src_remote, saved = None, ""
        # ----- 1. Đích 1: Save (restore) từ link chia sẻ vào My PikPak
        if meta.get("share"):
            if not rclone:
                raise SourceError("Cần rclone.exe để tải từ link chia sẻ PikPak.")
            folder_path = pk_dir or pikpak_join(cfg.get("pikpak_root", "") or "My Pack", safe_name(movie))
            target = f"{remote}:{pikpak_join(folder_path, name)}"
            self.q.put(("rowstatus", fcode, "☁  ① Đang Save vào My PikPak...", "dl"))
            self.q.put(("energy", "up", 10, f"☁ Save: {name}"))
            code_, out, _e = run_rclone(rclone, ["lsf", target], 60)
            if not (code_ == 0 and out.strip()):
                api = pikpak_api(cfg, self.log)
                pid = api.folder_id(folder_path)
                api.restore(meta["share"], meta.get("pct", ""), [meta["id"]], pid)
                found = False
                for _ in range(30):                # chờ PikPak lưu xong
                    if self.stop_flag.wait(2):
                        return False
                    code_, out, _e = run_rclone(rclone, ["lsf", target], 60)
                    if code_ == 0 and out.strip():
                        found = True
                        break
                    code_, out, _e = run_rclone(rclone, ["lsf", f"{remote}:My Pack/{name}"], 60)
                    if code_ == 0 and out.strip():     # PikPak lưu vào My Pack -> chuyển sang đích
                        run_rclone(rclone, ["moveto", f"{remote}:My Pack/{name}", target], 300)
                        found = True
                        break
                if not found:
                    raise SourceError("Đã gửi lệnh lưu nhưng chưa thấy file trong My PikPak (PikPak xử lý chậm?) - "
                                      "lần sau thử lại.")
            src_remote = target
            saved = target
            self.q.put(("energy", "up", 100, f"✔ Đã Save: {name}"))
            self.log(f"☁ ① Đã Save vào My PikPak: {target}")
        def stopped():
            rec["status"] = STATUS_FAIL
            self.q.put(("hist", fcode, dict(rec)))
            self.q.put(("rowstatus", fcode, "■  Đã dừng", "skip"))
            return False

        # ----- 2. Đích 2: rclone tải từ My PikPak về HDD (đa luồng)
        os.makedirs(hdd_dir, exist_ok=True)
        dst = os.path.join(hdd_dir, safe_name(name))
        if os.path.isfile(dst) and (os.path.getsize(dst) == size if size else os.path.getsize(dst) > 0):
            self.log(f"[{name}] HDD đã có đủ file - bỏ qua bước tải.")
        else:
            phase[:] = ["⬇", "② Tải từ My PikPak về HDD"]
            last[1] = -1
            self.q.put(("rowstatus", fcode, "⬇  ② Đang tải từ My PikPak về HDD...", "dl"))
            ok, msg = rclone_copy(rclone, src_remote, dst, prog, self.stop_flag, extra)
            if self.stop_flag.is_set() and not ok:
                self._remove_broken(dst, size, force=True)
                return stopped()
            if not ok:
                removed = self._remove_broken(dst, size, force=True)
                self._fetch_fail(item, STATUS_FAIL, f"Tải về HDD lỗi: {msg or 'lỗi không rõ'}" +
                                 (" · đã xóa file lỗi" if removed else "") +
                                 " · tập đã Save trong My PikPak, lần sau chỉ tải lại về HDD")
                return False
            got = os.path.getsize(dst) if os.path.isfile(dst) else 0
            if size and got < size * 0.995:        # tải thiếu -> xóa file lỗi, tải lại
                self._remove_broken(dst, size, force=True)
                self._fetch_fail(item, STATUS_BAD, f"Tải về HDD thiếu: {human_size(got)} / {human_size(size)} - "
                                                   "đã xóa file lỗi, đưa vào danh sách tải lại")
                return False
            self.log(f"⬇ ② Đã tải về HDD: {dst}")
        phase[:] = ["📱", "Copy vào COPY_TO_IPHONE"]
        last[1] = -1
        self._copy_to_iphone(item, fcode, name, dst, size, prog)
        rec.update(status=STATUS_DONE, done_ts=time.time(), path=dst, hdd=dst, tries=0, error="",
                   upload="done", upload_msg=saved, upload_ts=time.time())
        self.q.put(("hist", fcode, dict(rec)))
        self.q.put(("owned_add", fcode, folder_code, movie, name, size, "tool"))
        self.q.put(("rowstatus", fcode, "✔  Xong · My PikPak · HDD" + (" · iPhone" if cfg.get("iphone_on", True) else ""),
                    "done"))
        self.log(f"✔ Xong: {name}")
        return True

    def _copy_to_iphone(self, item, fcode, name, src, size, prog):
        """Copy thêm 1 bản từ HDD vào thư mục chung COPY_TO_IPHONE. Lỗi chỉ báo, không làm hỏng tập đã tải."""
        if not self.cfg.get("iphone_on", True) or self.stop_flag.is_set() or not src or not os.path.isfile(src):
            return
        d = resolve_iphone_dir(self.cfg.get("iphone_dir"))
        dst = os.path.join(d, safe_name(name))
        try:
            if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(src)):
                return
            os.makedirs(d, exist_ok=True)
            if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
                self.log(f"📱 [{name}] Đã có sẵn trong COPY_TO_IPHONE.")
                return                             # đã có sẵn
            self.q.put(("rowstatus", fcode, "📱  Đang copy vào COPY_TO_IPHONE...", "dl"))
            self.q.put(("energy", "dl", 0, f"📱 {name}"))
            ok, msg = copy_with_progress(src, dst, prog, self.stop_flag, chunk=16 << 20)
            if not ok:
                self._remove_broken(dst, size, force=True)
                raise OSError(msg or "lỗi không rõ")
            self.log(f"📱 Đã copy vào COPY_TO_IPHONE: {dst}")
        except Exception as e:
            self.log(f"⚠ [{name}] Copy vào COPY_TO_IPHONE lỗi: {e}")
            self.report_error(f"Copy vào COPY_TO_IPHONE lỗi: {name}", str(e), item=item,
                              exc=e if not isinstance(e, OSError) else None)

    def iphone_catch_up(self):
        """Copy bù vào COPY_TO_IPHONE các tập đã tải về HDD trong N ngày gần đây mà chưa có ở đó."""
        self.save_config()
        d = resolve_iphone_dir(self.cfg.get("iphone_dir"))
        days = 7
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
        if not todo:
            messagebox.showinfo(APP_NAME, f"Các tập tải trong {days} ngày gần đây đều đã có trong:\n{d}")
            return
        total = sum(os.path.getsize(a) for a, _b in todo)
        if not messagebox.askyesno(APP_NAME, f"Copy {len(todo)} tập ({human_size(total)}) đã tải trong {days} ngày "
                                             f"gần đây vào:\n{d} ?"):
            return

        def job():
            os.makedirs(d, exist_ok=True)
            ok_n = 0
            for i, (a, b) in enumerate(todo, 1):
                self.q.put(("status", f"📱 Copy vào COPY_TO_IPHONE {i}/{len(todo)}: {os.path.basename(a)}"))
                try:
                    ok, msg = copy_with_progress(a, b, lambda p, sp="", n=os.path.basename(a): self.q.put(
                        ("energy", "dl", p, f"📱 {n}   {sp}")), None, chunk=16 << 20)
                    if ok:
                        ok_n += 1
                        self.log(f"📱 Đã copy vào COPY_TO_IPHONE: {b}")
                    else:
                        self.log(f"⚠ Copy vào COPY_TO_IPHONE lỗi: {os.path.basename(a)}: {msg}")
                except Exception as e:
                    self.log(f"⚠ Copy vào COPY_TO_IPHONE lỗi: {os.path.basename(a)}: {e}")
            self.q.put(("status", f"📱 Xong: đã copy {ok_n}/{len(todo)} tập vào COPY_TO_IPHONE."))
        threading.Thread(target=job, daemon=True).start()

    def _browse_iphone(self):
        cur = self.iphone_dir_var.get().strip()
        p = filedialog.askdirectory(title="Chọn thư mục COPY_TO_IPHONE", initialdir=cur if os.path.isdir(cur) else os.path.expanduser("~"))
        if p:
            self.iphone_dir_var.set(os.path.normpath(p))
            self.save_config()

    def history_mark_done(self):
        sel = self.hist_tree.selection()
        for code in sel:
            h = self.history.get(code)
            if h:
                h["status"] = STATUS_DONE
                h["done_ts"] = time.time()
                self.add_owned(code, h.get("folder_code", ""), h.get("folder", ""), h.get("name", ""),
                               h.get("size"), "manual")
        if sel:
            self.save_owned(); self.save_history(); self.refresh_history()

    def log(self, msg):
        self.q.put(("log", msg))

    def _poll(self):
        hist_changed = owned_changed = False
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "call":
                    _, fn, args, holder, ev = msg
                    try:
                        holder["res"] = fn(*args)
                    except Exception as e:
                        holder["err"] = e
                    ev.set()
                    continue
                if kind in ("row", "rowstatus"):
                    self.rows_ver += 1
                if kind == "log":
                    line = f"{dt.datetime.now():%H:%M:%S}  {msg[1]}"
                    self.log_lines.append(line)
                    self.log_box.insert("end", line + "\n"); self.log_box.see("end")
                    try:
                        with open(LOG_FILE, "a", encoding="utf-8") as fh:
                            fh.write(f"{dt.datetime.now():%Y-%m-%d} {line}\n")
                    except OSError:
                        pass
                elif kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "progress":
                    self.progress.config(maximum=max(1, msg[2]), value=msg[1])
                    self._batch = (msg[1], msg[2])
                    self._dl_pct = 0
                    self._energy_total()
                elif kind == "energy":
                    self._energy_set(msg[1], msg[2], msg[3] if len(msg) > 3 else None)
                elif kind == "row":
                    _, iid, values, tag = msg[:4]
                    self.scan_items[iid] = msg[4]
                    if not self.scan_tree.exists(iid):
                        n = len(self.scan_tree.get_children())
                        tags = [t for t in (("odd" if n % 2 else ""), tag) if t]
                        on = tag == "new"
                        self.scan_tree.insert("", "end", iid=iid, text="", values=values, tags=tags,
                                              image=self.img_on if on else self.img_off)
                        if AVATARS:
                            self.scan_tree.item(iid, image=self._chk_img(iid, on))
                        self.scan_order.append(iid)
                        if on:
                            self.checked.add(iid)
                        if not self._row_visible(iid):
                            self.scan_tree.detach(iid)
                        self._update_sel_count()
                elif kind == "rowstatus":
                    self._set_row(msg[1], msg[2], msg[3])
                elif kind == "newcount":
                    self._new_count = msg[1]
                    self.update_stats()
                elif kind == "hist":
                    self.history[msg[1]] = msg[2]
                    hist_changed = True
                elif kind == "histmerge":
                    self.history.setdefault(msg[1], {}).update(msg[2])
                    hist_changed = True
                elif kind == "owned_add":
                    _, fcode, folder_code, fname, name, size, src = msg
                    self.add_owned(fcode, folder_code, fname, name, size, src)
                    owned_changed = True
                elif kind == "owned_remove":
                    self.remove_owned(msg[1], msg[2], msg[3])
                    owned_changed = True
                elif kind == "fetched":
                    self.enqueue_upload(msg[1])
                    hist_changed = True
                elif kind == "folderstat":
                    i, data = msg[1], msg[2]
                    if i < len(self.cfg["folders"]):
                        self.cfg["folders"][i].update(data)
                        save_json(CONFIG_FILE, self.cfg)
                        self._folders_dirty = True
                elif kind == "summary":
                    self.last_summary = msg[1]
                    self.cfg["last_summary"] = msg[1]
                    self._set_last(msg[1])
                elif kind == "retry_soon":
                    if self.cfg.get("auto_scan"):
                        self.next_auto_ts = min(self.next_auto_ts or 1e18, time.time() + msg[1])
                        self._update_auto_label()
                elif kind == "pkstatus":
                    self._set_pk_status(msg[1], msg[2])
                elif kind == "backup":
                    self._on_backup_done(msg[1], msg[2])
                elif kind == "upload":
                    self._on_upload_msg(msg[1], msg[2], msg[3])
                elif kind == "fp_loaded":
                    self._fp_loaded(msg[1], msg[2], msg[3], msg[4])
                elif kind == "fp_error":
                    if self.fp and self.fp.get("token") is msg[1]:
                        self.fp_info.set("⚠ Lỗi đọc thư mục: " + msg[3])
                        self._update_folder_stats(msg[2], self.cfg["folders"][msg[2]].get("total", 0),
                                                  self.cfg["folders"][msg[2]].get("owned", 0), error=msg[3][:120])
                elif kind == "completed":
                    res, manual, total = msg[1], msg[2], msg[3]
                    done_names = []
                    for code, path in res.items():
                        h = self.history.get(code)
                        if not h or h.get("status") == STATUS_DONE:
                            continue
                        h.update(status=STATUS_DONE, done_ts=time.time(), path=path)
                        if code not in self.owned:
                            self.add_owned(code, h.get("folder_code", ""), h.get("folder", ""), h.get("name", ""),
                                           h.get("size"), "tool")
                            owned_changed = True
                        self._set_row(code, "✔  Xong", "done")
                        self.q.put(("log", f"✔ Tải xong: {h.get('name', '')}"))
                        self.enqueue_upload(code)
                        done_names.append(h.get("name", ""))
                        hist_changed = True
                    if done_names:
                        self.notify(f"✔ Tải xong {len(done_names)} file", self._names_preview(done_names))
                        self.schedule_backup()
                    if manual:
                        self.status_var.set(f"Đã kiểm tra: {len(res)}/{total} tập tải xong.")
                elif kind == "shortfiles":
                    bad = []
                    for code, (path, got, need) in msg[1].items():
                        h = self.history.get(code)
                        if not h or h.get("status") not in WATCH_STATUSES + (STATUS_FAIL,):
                            continue
                        try:                     # đổi tên file hỏng để không bị nhận nhầm là đã xong
                            os.replace(path, path + ".hong")
                        except OSError:
                            pass
                        tries = int(h.get("tries", 0) or 0) + 1
                        h.update(status=STATUS_BAD, tries=tries, bad_info=f"{human_size(got)} / {human_size(need)}")
                        self.remove_owned(code, h.get("folder_code", ""), h.get("name", ""))
                        owned_changed = hist_changed = True
                        self._set_row(code, f"⚠  File thiếu dung lượng ({human_size(got)}/{human_size(need)}) - sẽ tải lại",
                                      "err")
                        self.q.put(("log", f"⚠ [{h.get('name', '')}] File tải về thiếu dung lượng "
                                           f"({human_size(got)} / {human_size(need)}) → đã đổi tên thành *.hong, bỏ khỏi "
                                           "Danh sách đã có, lần quét sau tự tải lại."))
                        bad.append(h.get("name", ""))
                    if bad:
                        self.notify(f"⚠ {len(bad)} file tải về bị thiếu dung lượng",
                                    self._names_preview(bad) + " - sẽ tự tải lại")
                elif kind == "foldername":
                    i, name = msg[1], msg[2]
                    if i < len(self.cfg["folders"]) and not self.cfg["folders"][i].get("name"):
                        self.cfg["folders"][i]["name"] = name
                        save_json(CONFIG_FILE, self.cfg)
                        self._folders_dirty = True
                elif kind == "focus":
                    if self.state() != "withdrawn":
                        self.bring_to_front()
                elif kind == "notify":
                    self.notify(msg[1], msg[2])
                elif kind == "tray":
                    what = msg[1]
                    if what == "show":
                        self.show_window()
                    elif what == "scan":
                        self.start_scan(True, auto=True)
                    elif what == "toggle_auto":
                        self.auto_var.set(not self.auto_var.get())
                        self._auto_changed()
                    elif what == "quit":
                        self.show_window()
                        self.quit_app()
                        return
                elif kind == "done":
                    self.status_var.set(msg[1])
                    try:
                        if self.energy["dl"][1].get() not in ("—",):
                            self.energy["dl"][1].set("✔ " + str(msg[1]).strip())
                    except (AttributeError, KeyError):
                        pass
                    for b in (self.btn_scan, self.btn_go):
                        b.config(state="normal")
                    self.btn_stop.config(state="disabled")
                    self._update_sel_count()
                    if getattr(self, "_folders_dirty", False):
                        self._folders_dirty = False
                        self.refresh_folders()
                    self.update_stats()
        except queue.Empty:
            pass
        if hist_changed:
            self.save_history()
            self.refresh_history()
            self.hist_ver += 1
        if owned_changed:
            self.save_owned()
        self.after(150, self._poll)

    def call_ui(self, fn, *args, timeout=20):
        """Chạy fn trong luồng giao diện (Tk) và chờ kết quả (gọi từ luồng nền)."""
        if threading.current_thread() is threading.main_thread():
            return fn(*args)
        holder, ev = {}, threading.Event()
        self.q.put(("call", fn, args, holder, ev))
        if not ev.wait(timeout):
            raise RuntimeError("Tool đang bận, thử lại sau.")
        if "err" in holder:
            raise holder["err"]
        return holder.get("res")

    # ================================================================ PHẦN DÙNG LẠI
    def _set_icon(self):
        self.icon_big = self.icon_small = None
        try:
            self.icon_big = tk.PhotoImage(data=ICON64)
            self.icon_small = tk.PhotoImage(data=ICON28)
            self.iconphoto(True, self.icon_big)
        except tk.TclError:
            pass
        ico = BASE / "icon.ico"
        if getattr(sys, "frozen", False):
            ico = Path(getattr(sys, "_MEIPASS", BASE)) / "icon.ico"
        if os.name == "nt" and ico.is_file():
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                pass

    def _install_edit_bindings(self):
        for cls in ("TEntry", "Entry", "Text", "TCombobox", "TSpinbox"):
            self.bind_class(cls, "<<Paste>>", self._paste)
            self.bind_class(cls, "<Button-3>", self._context_menu, add="+")
            self.bind_class(cls, "<Control-KeyPress>", self._ctrl_keys, add="+")
        self._menu = tk.Menu(self, tearoff=0, font=(FONT, 10))
        self._menu_target = None
        for label, ev in (("Cắt", "<<Cut>>"), ("Sao chép", "<<Copy>>"), ("Dán", "<<Paste>>")):
            self._menu.add_command(label=label, command=lambda e=ev: self._menu_target and
                                   self._menu_target.event_generate(e))
        self._menu.add_separator()
        self._menu.add_command(label="Chọn tất cả", command=lambda: self._select_all(self._menu_target))

    def _readonly(self, w):
        try:
            return str(w.cget("state")) in ("readonly", "disabled")
        except tk.TclError:
            return False

    def _paste(self, e):
        w = e.widget
        if self._readonly(w):
            return "break"
        txt = None
        if os.name == "nt":
            try:
                txt = read_clipboard_windows()
            except Exception:
                txt = None
        if txt is None:
            try:
                txt = self.clipboard_get()
            except tk.TclError:
                return "break"
        txt = clean_paste(txt)
        if w.winfo_class() == "Text":
            try:
                w.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            w.insert("insert", txt)
            w.see("insert")
        else:
            txt = one_line(txt) if "\n" in txt else txt   # ô 1 dòng: nối các dòng lại
            try:
                w.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            w.insert("insert", txt)
        return "break"

    def _ctrl_keys(self, e):
        # Ctrl+V/C/X/A theo phím vật lý -> dùng được cả khi bật bộ gõ / bàn phím tiếng Việt
        if e.keysym.lower() in ("v", "c", "x", "a"):
            if e.keysym.lower() == "a":
                return self._select_all(e.widget)
            return None
        ev = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>"}.get(e.keycode)
        if ev:
            e.widget.event_generate(ev)
            return "break"
        if e.keycode == 65:
            return self._select_all(e.widget)
        return None

    def _select_all(self, w):
        if w is None:
            return "break"
        try:
            if w.winfo_class() == "Text":
                w.tag_add("sel", "1.0", "end-1c")
            else:
                w.select_range(0, "end")
                w.icursor("end")
        except tk.TclError:
            pass
        return "break"

    def _context_menu(self, e):
        self._menu_target = e.widget
        e.widget.focus_set()
        ro = self._readonly(e.widget)
        for i in (0, 2):  # Cắt, Dán
            self._menu.entryconfig(i, state="disabled" if ro else "normal")
        self._menu.tk_popup(e.x_root, e.y_root)
        return "break"

    def _make_check_images(self):
        def box(checked):
            n = 18
            img = tk.PhotoImage(width=n, height=n)
            border = C_ACCENT if checked else C_CHECK_BORDER
            fill = C_ACCENT if checked else C_FIELD
            for y in range(n):
                row = []
                for x in range(n):
                    corner = (x in (0, n - 1)) and (y in (0, n - 1))
                    if corner:
                        row.append(C_CARD)
                    elif x in (0, n - 1) or y in (0, n - 1):
                        row.append(border)
                    else:
                        row.append(fill)
                img.put("{" + " ".join(row) + "}", to=(0, y))
            if checked:  # dấu tích trắng
                pts = [(4, 9), (5, 10), (6, 11), (7, 12), (8, 11), (9, 10), (10, 9), (11, 8), (12, 7), (13, 6)]
                for x, y in pts:
                    for dx, dy in ((0, 0), (0, -1), (1, 0)):
                        img.put(C_ON_ACCENT, to=(x + dx, y + dy))
            return img
        self.img_on, self.img_off = box(True), box(False)

    PAGE_INFO = {
        "folders": ("Thư mục phim", "Nguồn (thư mục trong link chia sẻ PikPak) → ① Save My PikPak → ② tải về HDD · quét file, đánh dấu tập đã có"),
        "scan": ("Quét & Tải", "Tìm tập mới chưa có trong Danh sách đã có → copy về HDD → rclone upload lên My PikPak"),
        "history": ("Lịch sử tải", "Theo dõi tải xong · copy vào thư mục phim · upload PikPak"),
        "settings": ("Cài đặt", "Chung · My PikPak · rclone · Máy này & Sao lưu"),
    }

    def _build_header(self, parent):
        """Thanh tiêu đề trang (trắng, gọn) phía trên nội dung."""
        top = tk.Frame(parent, bg=C_CARD)
        top.pack(fill="x", side="top")
        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill="x", side="top")
        inner = tk.Frame(top, bg=C_CARD, padx=22, pady=12)
        inner.pack(fill="x")
        left = tk.Frame(inner, bg=C_CARD)
        left.pack(side="left", fill="x", expand=True)
        self.top_title = tk.Label(left, text="", bg=C_CARD, fg=C_TEXT, font=(FONT, 16, "bold"), anchor="w")
        self.top_title.pack(anchor="w")
        self.top_sub = tk.Label(left, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 9), anchor="w")
        self.top_sub.pack(anchor="w")
        self.top_auto = tk.Label(inner, text="", bg=C_SOFT, fg=C_ACCENT_HOVER, font=(FONT, 10, "bold"),
                                 padx=14, pady=6, cursor="hand2")
        self.top_auto.pack(side="right")
        self.top_upd = tk.Label(inner, text="⟳  Cập nhật", bg=C_CARD, fg=C_MUTED, font=(FONT, 10, "bold"),
                                padx=12, pady=6, cursor="hand2", highlightbackground=C_BORDER, highlightthickness=1)
        self.top_upd.pack(side="right", padx=(0, 10))
        self.top_upd.bind("<Button-1>", lambda e: self.check_update(silent=False))
        self.top_auto.bind("<Button-1>", lambda e: (self.select_page("settings"), self._settings_page("gen")))
        self.header_auto_text = ""
        self.top_lock = tk.Label(inner, text="🔒  Đã khóa", bg=C_CARD, fg=C_MUTED, font=(FONT, 10, "bold"), padx=12,
                                 pady=6, cursor="hand2", highlightbackground=C_BORDER, highlightthickness=1)
        self.top_lock.pack(side="right", padx=(0, 10))
        self.top_lock.bind("<Button-1>", lambda e: self.admin_lock() if self.admin_is_unlocked() else (
            self.admin_unlock() and self.status_var.set("🔓 Đã mở khóa tab Thư mục phim / Cài đặt.")))
        if len(removed_themes(self.cfg)) < len(THEMES) - 1:
            self.top_theme = tk.Label(inner, text="◐  Giao diện", bg=C_CARD, fg=C_MUTED, font=(FONT, 10, "bold"),
                                      padx=12, pady=6, cursor="hand2", highlightbackground=C_BORDER,
                                      highlightthickness=1)
            self.top_theme.pack(side="right", padx=(0, 10))
            self.top_theme.bind("<Button-1>", lambda e: self._theme_menu(self.top_theme))
        if BTN_3D:
            for w in (self.top_auto, self.top_upd, self.top_lock, getattr(self, "top_theme", None)):
                if w is not None:
                    w.config(relief="raised", bd=2, highlightthickness=0)

    # ================================================================ MẬT KHẨU ADMIN
    @staticmethod
    def _pw_hash(pw, salt):
        return hashlib.sha256((salt + "|" + pw).encode("utf-8")).hexdigest()

    def admin_is_unlocked(self):
        return getattr(self, "_admin_until", 0) > 0

    def _admin_activity(self, _e=None):
        self._admin_last = time.time()

    def _admin_tick(self):
        """Tự khóa lại sau N phút không thao tác."""
        try:
            mins = int(self.cfg.get("admin_lock_min", 10) or 0)
            if self.admin_is_unlocked() and mins > 0 and time.time() - self._admin_last > mins * 60:
                self.admin_lock(f"🔒 Tự khóa sau {mins} phút không thao tác.")
        except Exception:
            pass
        self.after(20000, self._admin_tick)

    def _pw_dialog(self, title, prompt, confirm=False):
        """Hộp nhập mật khẩu (ẩn ký tự). confirm=True: nhập 2 lần. Trả về chuỗi hoặc None."""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=C_CARD)
        win.transient(self)
        win.resizable(False, False)
        body = tk.Frame(win, bg=C_CARD, padx=20, pady=16)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="🔒  " + prompt, bg=C_CARD, fg=C_TEXT, font=(FONT, 10, "bold"), justify="left",
                 wraplength=360).pack(anchor="w")
        v1, v2 = tk.StringVar(), tk.StringVar()
        e1 = ttk.Entry(body, textvariable=v1, show="●", width=34)
        e1.pack(anchor="w", pady=(10, 0))
        if confirm:
            tk.Label(body, text="Nhập lại mật khẩu", bg=C_CARD, fg=C_MUTED, font=(FONT, 9)).pack(anchor="w",
                                                                                               pady=(8, 0))
            ttk.Entry(body, textvariable=v2, show="●", width=34).pack(anchor="w", pady=(2, 0))
        err = tk.Label(body, text="", bg=C_CARD, fg=C_RED, font=(FONT, 9))
        err.pack(anchor="w", pady=(6, 0))
        res = {"v": None}

        def ok(_e=None):
            a = v1.get()
            if confirm:
                if len(a) < 4:
                    err.config(text="Mật khẩu ít nhất 4 ký tự.")
                    return
                if a != v2.get():
                    err.config(text="Hai lần nhập không giống nhau.")
                    return
            res["v"] = a
            win.destroy()
        bf = tk.Frame(body, bg=C_CARD)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="✓  OK", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(bf, text="Hủy", command=win.destroy).pack(side="right", padx=8)
        win.bind("<Return>", ok)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        win.geometry(f"+{self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)}"
                     f"+{self.winfo_rooty() + 160}")
        e1.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        return res["v"]

    def _admin_set_pw(self, pw):
        salt = os.urandom(8).hex()
        self.cfg["admin_salt"], self.cfg["admin_hash"] = salt, self._pw_hash(pw, salt)
        self.save_config()

    def admin_unlock(self, ask=True):
        """Tab Thư mục phim / Cài đặt cần mật khẩu admin. Mở khóa 1 lần dùng tới khi khóa lại / tự khóa."""
        if self.admin_is_unlocked():
            self._admin_last = time.time()
            return True
        if not ask:
            return False
        if not self.cfg.get("admin_hash"):
            pw = self._pw_dialog("Tạo mật khẩu admin", "Tab Thư mục phim và Cài đặt được khóa bằng mật khẩu admin để "
                                 "tránh bấm nhầm. Tạo mật khẩu (ít nhất 4 ký tự):", confirm=True)
            if not pw:
                return False
            self._admin_set_pw(pw)
            self.log("🔑 Đã tạo mật khẩu admin.")
        else:
            for _ in range(3):
                pw = self._pw_dialog("Mật khẩu admin", "Nhập mật khẩu admin để mở tab Thư mục phim / Cài đặt:")
                if pw is None:
                    return False
                if self._pw_hash(pw, self.cfg.get("admin_salt", "")) == self.cfg.get("admin_hash"):
                    break
                messagebox.showwarning(APP_NAME, "Sai mật khẩu admin.")
            else:
                return False
        self._admin_until, self._admin_last = time.time(), time.time()
        self._admin_badge()
        return True

    def admin_lock(self, msg="🔒 Đã khóa tab Thư mục phim / Cài đặt."):
        self._admin_until = 0
        self._admin_badge()
        if getattr(self, "page", None) in self.LOCKED_PAGES:
            self.select_page("scan")
        self.status_var.set(msg)

    def admin_change_pw(self):
        if self.cfg.get("admin_hash"):
            old = self._pw_dialog("Đổi mật khẩu admin", "Nhập mật khẩu admin hiện tại:")
            if old is None:
                return
            if self._pw_hash(old, self.cfg.get("admin_salt", "")) != self.cfg.get("admin_hash"):
                messagebox.showwarning(APP_NAME, "Sai mật khẩu admin hiện tại.")
                return
        new = self._pw_dialog("Đổi mật khẩu admin", "Mật khẩu admin mới (ít nhất 4 ký tự):", confirm=True)
        if new:
            self._admin_set_pw(new)
            messagebox.showinfo(APP_NAME, "Đã đổi mật khẩu admin.")

    def _admin_badge(self):
        try:
            if self.admin_is_unlocked():
                self.top_lock.config(text="🔓  Khóa lại", fg=C_GREEN)
            else:
                self.top_lock.config(text="🔒  Đã khóa", fg=C_MUTED)
        except (AttributeError, tk.TclError):
            pass

    # ================================================================ GIAO DIỆN
    def _theme_menu(self, widget):
        m = tk.Menu(self, tearoff=0)
        var = tk.StringVar(value=self.layout)
        rem = removed_themes(self.cfg)
        for key in THEMES:
            if key not in rem:
                m.add_radiobutton(label=("★  " if key == self.layout else "⭐  Đặt mặc định: ") + theme_label(self.cfg, key),
                                  variable=var, value=key, command=lambda k=key: self.switch_theme(k))
        extra = [k for k in THEMES if k != "classic" and k not in rem]
        if extra:
            m.add_separator()
            for k in extra:
                m.add_command(label=f"🗑  Xóa {theme_label(self.cfg, k, True)}...", command=lambda k=k: self.remove_theme(k))
        try:
            m.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 2)
        finally:
            m.grab_release()

    def _restart_ui(self, msg):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "Tool đang quét / tải - đợi xong rồi đổi giao diện.")
            return False
        if not messagebox.askyesno(APP_NAME, msg + "\n\nTool sẽ tự khởi động lại (dữ liệu, cài đặt giữ nguyên)."):
            return False
        self.save_config()
        self.save_history()
        restart_self()
        self.quit_app(force=True)
        return True

    def switch_theme(self, name):
        if name not in THEMES or name == self.layout:
            return
        old = self.cfg.get("ui_theme")
        self.cfg["ui_theme"] = name
        if not self._restart_ui(f"Đặt mặc định: {theme_label(self.cfg, name)}"):
            self.cfg["ui_theme"] = old

    def _set_removed(self, rem):
        self.cfg["removed_themes"] = sorted(rem)

    def remove_theme(self, name):
        """Xóa giao diện thêm. Giao diện gốc không xóa được. Khôi phục ở Cài đặt > Chung."""
        if name == "classic" or name not in THEMES:
            return
        old = (self.cfg.get("ui_theme"), list(self.cfg.get("removed_themes") or []))
        rem = removed_themes(self.cfg) | {name}
        if self.layout != name:                    # xóa giao diện không đang dùng -> không cần khởi động lại
            if messagebox.askyesno(APP_NAME, f"Xóa {theme_label(self.cfg, name, True)}?\n(Khôi phục lại được ở Cài đặt → Chung → "
                                             "Giao diện.)"):
                self._set_removed(rem)
                self.save_config()
                if len(rem) >= len(THEMES) - 1:
                    try:
                        self.top_theme.pack_forget()
                    except (AttributeError, tk.TclError):
                        pass
                self.log(f"🗑 Đã xóa {theme_label(self.cfg, name, True)}.")
                self._settings_refresh_theme()
            return
        self._set_removed(rem)
        self.cfg["ui_theme"] = "classic"
        if not self._restart_ui(f"Xóa {theme_label(self.cfg, name, True)} và quay về giao diện gốc?\n"
                                "(Khôi phục lại được ở Cài đặt → Chung → Giao diện.)"):
            self.cfg["ui_theme"], self.cfg["removed_themes"] = old

    def restore_theme(self, name):
        if name not in THEMES:
            return
        rem = removed_themes(self.cfg) - {name}
        self._set_removed(rem)
        self.save_config()
        self.log(f"↺ Đã khôi phục {theme_label(self.cfg, name, True)}.")
        old = self.cfg.get("ui_theme")
        self.cfg["ui_theme"] = name
        if not self._restart_ui(f"Đã khôi phục {theme_label(self.cfg, name, True)}. Chuyển sang giao diện này luôn?"):
            self.cfg["ui_theme"] = old
            self.save_config()
            self._settings_refresh_theme()

    def _settings_refresh_theme(self):
        try:
            for w in self._theme_box.winfo_children():
                w.destroy()
            self._fill_theme_box(self._theme_box)
        except (AttributeError, tk.TclError):
            pass

    def _fill_theme_box(self, fr):
        """Danh sách giao diện: ⭐ Đặt mặc định (tool mở bằng giao diện này) · 🗑 Xóa (trừ giao diện gốc)."""
        rem = removed_themes(self.cfg)
        ttk.Label(fr, text="Mặc định hiện tại: " + theme_label(self.cfg, self.layout), style="Muted.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        for r, key in enumerate(THEMES, 1):
            ttk.Label(fr, text=theme_label(self.cfg, key)).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 14))
            if key in rem:
                ttk.Label(fr, text="đã xóa", style="Muted.TLabel").grid(row=r, column=1, sticky="w")
                ttk.Button(fr, text="↺  Khôi phục", style="Small.TButton",
                           command=lambda k=key: self.restore_theme(k)).grid(row=r, column=2, sticky="w", padx=6)
                continue
            if key == self.layout:
                ttk.Label(fr, text="★ mặc định", style="Muted.TLabel").grid(row=r, column=1, sticky="w")
            else:
                ttk.Button(fr, text="⭐  Đặt mặc định", style="Small.TButton",
                           command=lambda k=key: self.switch_theme(k)).grid(row=r, column=1, sticky="w")
            if key == "classic":
                ttk.Label(fr, text="(gốc - không xóa được)", style="Muted.TLabel").grid(row=r, column=2, sticky="w",
                                                                                     padx=6)
            else:
                ttk.Button(fr, text="🗑  Xóa", style="DangerSmall.TButton",
                           command=lambda k=key: self.remove_theme(k)).grid(row=r, column=2, sticky="w", padx=6)
            ttk.Button(fr, text="✎  Đổi tên", style="Small.TButton",
                       command=lambda k=key: self.rename_theme(k)).grid(row=r, column=3, sticky="w")

    def rename_theme(self, key):
        """Đổi tên hiển thị của 1 giao diện (để trống = tên mặc định)."""
        from tkinter import simpledialog
        cur = theme_label(self.cfg, key)
        new = simpledialog.askstring(APP_NAME, f"Tên mới cho \"{cur}\"\n(để trống = tên mặc định: {THEME_NAMES[key]})",
                                     initialvalue=cur, parent=self)
        if new is None:
            return
        names = dict(self.cfg.get("theme_names") or {})
        new = new.strip()[:80]
        if new and new != THEME_NAMES[key]:
            names[key] = new
        else:
            names.pop(key, None)
        self.cfg["theme_names"] = names
        self.save_config()
        self.log(f"✎ Đổi tên giao diện: {theme_label(self.cfg, key)}")
        self._settings_refresh_theme()

    # ================================================================ BỐ CỤC WORKSPACE / THEO PHIM (v2.0)
    AV_COLORS = ("#e11d48", "#7c3aed", "#0891b2", "#ea580c", "#16a34a", "#475569", "#db2777", "#0d9488",
                 "#2563eb", "#ca8a04")

    @staticmethod
    def _initials(name):
        words = [w for w in re.split(r"[\s\-_.·]+", str(name or "").strip()) if w and w[0].isalnum()]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    def _av_color(self, name):
        return self.AV_COLORS[int(hashlib.md5(str(name).encode("utf-8")).hexdigest(), 16) % len(self.AV_COLORS)]

    def _pil_font(self, size, bold=True):
        from PIL import ImageFont
        key = (size, bold)
        cache = self.__dict__.setdefault("_pil_fonts", {})
        if key not in cache:
            f = None
            for nm in (("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else
                       ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")):
                try:
                    f = ImageFont.truetype(nm, size)
                    break
                except OSError:
                    continue
            cache[key] = f or ImageFont.load_default()
        return cache[key]

    def _avatar_pil(self, name, size):
        from PIL import Image, ImageDraw
        sc = 3                                      # vẽ to rồi thu nhỏ cho mịn
        S = size * sc
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.26), fill=self._av_color(name))
        txt = self._initials(name)
        f = self._pil_font(int(S * 0.40))
        try:
            bb = d.textbbox((0, 0), txt, font=f)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            d.text(((S - tw) / 2 - bb[0], (S - th) / 2 - bb[1]), txt, font=f, fill="#ffffff")
        except Exception:
            pass
        return im.resize((size, size), Image.LANCZOS)

    def avatar_img(self, name, size=26):
        """Ảnh vuông bo góc có 2 chữ cái đầu tên phim (cần Pillow). Không có Pillow -> None."""
        if not AVATARS or PILImage is None:
            return None
        key = ("av", name, size)
        cache = self.__dict__.setdefault("_img_cache", {})
        if key not in cache:
            try:
                from PIL import ImageTk
                cache[key] = ImageTk.PhotoImage(self._avatar_pil(name, size))
            except Exception:
                cache[key] = None
        return cache[key]

    def _chk_img(self, iid, on):
        """Ảnh cột đầu bảng Quét & Tải: ô chọn (+ ảnh chữ tên phim ở bố cục Workspace / Theo phim)."""
        if not AVATARS or PILImage is None:
            return self.img_on if on else self.img_off
        try:
            name = str(self.scan_tree.item(iid, "values")[0])
        except (tk.TclError, IndexError):
            return self.img_on if on else self.img_off
        key = ("chk", name, bool(on))
        cache = self.__dict__.setdefault("_img_cache", {})
        if key not in cache:
            try:
                from PIL import Image, ImageDraw, ImageTk
                sc, h = 3, 26
                W = (18 + 10 + h) * sc
                im = Image.new("RGBA", (W, h * sc), (0, 0, 0, 0))
                d = ImageDraw.Draw(im)
                y = (h - 18) // 2 * sc
                box = (0, y, 18 * sc - 1, y + 18 * sc - 1)
                if on:
                    d.rounded_rectangle(box, radius=4 * sc, fill=C_ACCENT)
                    d.line([(4 * sc, y + 9 * sc), (8 * sc, y + 13 * sc), (14 * sc, y + 5 * sc)],
                           fill=C_ON_ACCENT, width=2 * sc)
                else:
                    d.rounded_rectangle(box, radius=4 * sc, fill=C_FIELD, outline=C_CHECK_BORDER, width=2 * sc)
                im.paste(self._avatar_pil(name, h * sc), ((18 + 10) * sc, 0))
                cache[key] = ImageTk.PhotoImage(im.resize((W // sc, h), Image.LANCZOS))
            except Exception:
                cache[key] = None
        return cache[key] or (self.img_on if on else self.img_off)

    def _hidden_side_attrs(self, host):
        """Các ô của thanh bên cũ mà phần lõi vẫn cập nhật - tạo sẵn (ẩn) cho bố cục mới."""
        mk = lambda **kw: tk.Label(host, text="", bg=C_CARD, fg=C_MUTED, **kw)
        for nm in ("side_owned", "side_auto", "side_last", "side_bk", "side_pk", "side_rd", "side_foot"):
            if not hasattr(self, nm):
                setattr(self, nm, mk())
        self._side_wraps = []

    def _alerts_bar(self, parent):
        self.alerts = tk.Frame(parent, bg=C_BG)
        self.alerts.pack(fill="x", padx=18)
        self.side_health = tk.Label(self.alerts, text="", bg=C_WARN_BG, fg=C_ORANGE, font=(FONT, 9, "bold"),
                                    anchor="w", justify="left", padx=10, pady=6, wraplength=1100)
        self.side_err = tk.Label(self.alerts, text="", bg=C_ERR_BG, fg=C_ERR_FG, font=(FONT, 9, "bold"), anchor="w",
                                 justify="left", cursor="hand2", padx=10, pady=6)
        self.side_err.bind("<Button-1>", self.copy_last_report)

    def _icon_btn(self, parent, text, cmd, bg=None, fg=None, tip_dot=False):
        bg = bg or C_CARD
        b = tk.Label(parent, text=text, bg=bg, fg=fg or C_TEXT, font=(FONT, 11), width=3, pady=5, cursor="hand2",
                     highlightbackground=C_BORDER, highlightthickness=1)
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg=C_BTN_HOVER))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _ws_statusbar(self, parent):
        bar = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        bar.pack(fill="x", side="bottom")
        inner = tk.Frame(bar, bg=C_CARD, padx=18, pady=5)
        inner.pack(fill="x")
        self.ws_dots = {}
        for key, text in (("pk", "PikPak"), ("rc", "rclone"), ("bk", "Sao lưu"), ("pc", "⌂ " + MACHINE)):
            f = tk.Frame(inner, bg=C_CARD)
            f.pack(side="left", padx=(0, 18))
            dot = tk.Label(f, text="●" if key != "pc" else "", bg=C_CARD, fg=C_MUTED, font=(FONT, 8))
            dot.pack(side="left")
            lb = tk.Label(f, text=text, bg=C_CARD, fg=C_MUTED, font=(FONT, 9))
            lb.pack(side="left", padx=(3, 0))
            self.ws_dots[key] = (dot, lb)
        self.progress = ttk.Progressbar(inner, style="Pro.Horizontal.TProgressbar", mode="determinate", length=160)
        self.progress.pack(side="right")
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        tk.Label(inner, textvariable=self.status_var, bg=C_CARD, fg=C_MUTED, font=(FONT, 9)).pack(side="right",
                                                                                                 padx=12)

    # ---------------------------------------------------------------- Workspace (ảnh 6 / 7)
    def _build_ws_layout(self, body):
        side = tk.Frame(body, bg=C_SIDE, width=236)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.side = side
        tk.Frame(body, bg=C_BORDER, width=1).pack(side="left", fill="y")
        main = tk.Frame(body, bg=C_BG)
        main.pack(side="left", fill="both", expand=True)
        # ----- thanh trên: đường dẫn + tiêu đề | tìm kiếm · Chỉ quét · Quét & Tải · ◐ 🔒 ⟳
        top = tk.Frame(main, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        top.pack(fill="x")
        ti = tk.Frame(top, bg=C_CARD, padx=24, pady=10)
        ti.pack(fill="x")
        left = tk.Frame(ti, bg=C_CARD)
        left.pack(side="left")
        self.top_sub = tk.Label(left, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 9), anchor="w")
        self.top_sub.pack(anchor="w")
        self.top_title = tk.Label(left, text="", bg=C_CARD, fg=C_TEXT, font=(FONT, 17, "bold"), anchor="w")
        self.top_title.pack(anchor="w")
        right = tk.Frame(ti, bg=C_CARD)
        right.pack(side="right")
        self.top_upd = self._icon_btn(right, "⟳", lambda: self.check_update(silent=False))
        self.top_upd.pack(side="right")
        self.top_lock = self._icon_btn(right, "🔒", lambda: self.admin_lock() if self.admin_is_unlocked() else (
            self.admin_unlock() and self.status_var.set("🔓 Đã mở khóa tab Thư mục phim / Cài đặt.")))
        self.top_lock.pack(side="right", padx=(0, 8))
        if len(removed_themes(self.cfg)) < len(THEMES) - 1:
            self.top_theme = self._icon_btn(right, "◐", lambda: self._theme_menu(self.top_theme))
            self.top_theme.pack(side="right", padx=(0, 8))
        tk.Frame(right, bg=C_BORDER, width=1, height=28).pack(side="right", padx=12)
        self.btn_stop = ttk.Button(right, text="■", style="Danger.TButton", width=3, command=self.stop_flag.set,
                                   state="disabled")
        self.btn_stop.pack(side="right", padx=(6, 0))
        self.btn_go = ttk.Button(right, text="⬇  Quét & Tải", style="Accent.TButton",
                                 command=lambda: self.start_scan(True))
        self.btn_go.pack(side="right")
        self.btn_scan = ttk.Button(right, text="⌕  Chỉ quét", command=lambda: self.start_scan(False))
        self.btn_scan.pack(side="right", padx=(0, 8))
        self.scan_search_var = tk.StringVar()
        sf = tk.Frame(right, bg=C_FIELD, highlightbackground=C_BORDER, highlightthickness=1)
        sf.pack(side="right", padx=(0, 14))
        tk.Label(sf, text="⌕", bg=C_FIELD, fg=C_MUTED, font=(FONT, 10)).pack(side="left", padx=(8, 2))
        se = tk.Entry(sf, textvariable=self.scan_search_var, width=30, relief="flat", bg=C_FIELD, fg=C_TEXT,
                      insertbackground=C_TEXT, font=(FONT, 10))
        se.pack(side="left", ipady=5)
        tk.Label(sf, text="Ctrl K", bg=C_PANEL, fg=C_MUTED, font=(FONT, 8), padx=4).pack(side="left", padx=6)
        self.bind_all("<Control-k>", lambda e: (self.select_page("scan"), se.focus_set()))
        self.top_auto = tk.Label(top, text="")              # (ẩn) chữ "Quét lần tới" kiểu cũ
        self._alerts_bar(main)
        self._ws_statusbar(main)
        nb = self._make_notebook(main)
        nb.pack(fill="both", expand=True, padx=18, pady=(14, 0))

        # ----- thanh bên: logo · LÀM VIỆC · QUẢN LÝ · thẻ Thư viện · thẻ Tự quét
        brand = tk.Frame(side, bg=C_SIDE)
        brand.pack(fill="x", padx=16, pady=(16, 12))
        if self.icon_small:
            tk.Label(brand, image=self.icon_small, bg=C_SIDE).pack(side="left", padx=(0, 10))
        bt = tk.Frame(brand, bg=C_SIDE)
        bt.pack(side="left")
        tk.Label(bt, text=APP_TITLE, bg=C_SIDE, fg=C_SIDE_BRAND, font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(bt, text=APP_VERSION.replace(" by ", " · "), bg=C_SIDE, fg=C_SIDE_MUTED, font=(FONT, 8)).pack(anchor="w")
        self.nav = {}
        frames = {"folders": self.tab_folders, "scan": self.tab_scan, "history": self.tab_history,
                  "settings": self.tab_settings}

        def group(text):
            tk.Label(side, text=text, bg=C_SIDE, fg=C_SIDE_MUTED, font=(FONT, 8, "bold")).pack(anchor="w", padx=20,
                                                                                            pady=(12, 4))

        def item(key, icon, text, hint, n):
            row = tk.Frame(side, bg=C_SIDE, cursor="hand2")
            row.pack(fill="x", padx=10, pady=1)
            bar = tk.Frame(row, bg=C_SIDE, width=3)
            bar.pack(side="left", fill="y")
            ic = tk.Label(row, text=icon, bg=C_SIDE, fg=C_SIDE_MUTED, font=(FONT, 11), width=2)
            ic.pack(side="left", padx=(8, 6), pady=7)
            lb = tk.Label(row, text=text, bg=C_SIDE, fg=C_SIDE_TEXT, font=(FONT, 10, "bold"))
            lb.pack(side="left")
            badge = tk.Label(row, text="", bg=C_ACCENT, fg=C_ON_ACCENT, font=(MONO, 8, "bold"), padx=6)
            hint_l = tk.Label(row, text=hint, bg=C_SIDE, fg=C_SIDE_MUTED, font=(FONT, 8))
            hint_l.pack(side="right", padx=8)
            self.nav[key] = {"row": row, "bar": bar, "icon": ic, "label": lb, "badge": badge, "frame": frames[key],
                             "hint": hint_l}
            for w in (row, ic, lb, badge, hint_l):
                w.bind("<Button-1>", lambda e, k=key: self.select_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
            self.bind_all(f"<Control-Key-{n}>", lambda e, k=key: self.select_page(k))
        group("LÀM VIỆC")
        item("scan", "⬇", "Quét & Tải", "", 2)
        item("history", "☰", "Lịch sử tải", "Ctrl+3", 3)
        group("QUẢN LÝ  🔒")
        item("folders", "▦", "Thư mục phim", "", 1)
        item("settings", "⚙", "Cài đặt", "", 4)

        bottom = tk.Frame(side, bg=C_SIDE)
        bottom.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        lib = tk.Frame(bottom, bg=C_SIDE_CARD, padx=12, pady=10)
        lib.pack(fill="x", pady=(0, 8))
        tk.Label(lib, text="THƯ VIỆN", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
        r = tk.Frame(lib, bg=C_SIDE_CARD)
        r.pack(anchor="w")
        self.ws_lib_num = tk.Label(r, text="0", bg=C_SIDE_CARD, fg=C_SIDE_BRAND, font=(FONT, 18, "bold"))
        self.ws_lib_num.pack(side="left")
        tk.Label(r, text=" tập đã có", bg=C_SIDE_CARD, fg=C_SIDE_TEXT, font=(FONT, 9)).pack(side="left", pady=(6, 0))
        self.ws_lib_sub = tk.Label(lib, text="", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=(FONT, 8), anchor="w",
                                   justify="left", wraplength=190)
        self.ws_lib_sub.pack(anchor="w")
        self.ws_lib_bar = EnergyBar(lib, C_SIDE_CARD, height=10, colors=(C_GREEN, C_GREEN),
                                    empty=_mix(C_SIDE_CARD, C_SIDE_MUTED, 0.3))
        self.ws_lib_bar.pack(fill="x", pady=(6, 0))
        au = tk.Frame(bottom, bg=C_SIDE_CARD, padx=12, pady=10)
        au.pack(fill="x")
        r = tk.Frame(au, bg=C_SIDE_CARD)
        r.pack(fill="x")
        tk.Label(r, text="Tự quét", bg=C_SIDE_CARD, fg=C_SIDE_TEXT, font=(FONT, 10, "bold")).pack(side="left")
        self.ws_switch = tk.Canvas(r, width=38, height=20, bg=C_SIDE_CARD, highlightthickness=0, cursor="hand2")
        self.ws_switch.pack(side="right")
        self.ws_switch.bind("<Button-1>", lambda e: (self.auto_var.set(not self.auto_var.get()), self._auto_changed(),
                                                     self._ws_draw_switch()))
        self.ws_count = tk.Label(au, text="--:--", bg=C_SIDE_CARD, fg=C_SIDE_BRAND, font=(FONT, 20, "bold"))
        self.ws_count.pack(anchor="w")
        self.ws_count_sub = tk.Label(au, text="", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=(FONT, 8), anchor="w")
        self.ws_count_sub.pack(anchor="w")
        self.ws_count_bar = EnergyBar(au, C_SIDE_CARD, height=10, colors=(C_SIDE_ACTIVE, C_SIDE_ACTIVE),
                                      empty=_mix(C_SIDE_CARD, C_SIDE_MUTED, 0.3))
        self.ws_count_bar.pack(fill="x", pady=(6, 0))
        r2 = tk.Frame(au, bg=C_SIDE_CARD)
        r2.pack(fill="x", pady=(6, 0))
        tk.Label(r2, text="mỗi", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=(FONT, 8)).pack(side="left")
        cb = ttk.Combobox(r2, textvariable=self.interval_var, values=INTERVAL_CHOICES, width=4, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._auto_changed())
        tk.Label(r2, text="phút", bg=C_SIDE_CARD, fg=C_SIDE_MUTED, font=(FONT, 8)).pack(side="left")
        self._hidden_side_attrs(side)
        self._ws_draw_switch()

    def _ws_draw_switch(self):
        c = getattr(self, "ws_switch", None)
        if c is None:
            return
        on = bool(self.auto_var.get())
        c.delete("all")
        col = C_GREEN if on else _mix(C_SIDE_CARD, C_SIDE_MUTED, 0.45)
        c.create_oval(1, 1, 19, 19, fill=col, outline="")
        c.create_oval(19, 1, 37, 19, fill=col, outline="")
        c.create_rectangle(10, 1, 28, 19, fill=col, outline="")
        x = 21 if on else 3
        c.create_oval(x, 3, x + 14, 17, fill="#ffffff", outline="")

    def _build_scan_ws(self):
        t = self.tab_scan
        # ----- hàng thẻ: 4 thẻ số + thẻ ĐANG TẢI
        cards = tk.Frame(t, bg=C_CARD)
        cards.pack(fill="x")
        self.stat_vars = {k: tk.StringVar() for k in ("folders", "new", "dl", "owned")}
        self.ws_stat = {}
        sc = STAT_COLORS or (C_ACCENT, C_ACCENT, C_GREEN, C_RED)
        for i, (key, icon, title) in enumerate((("folders", "▦", "Thư mục theo dõi"), ("new", "●", "Tập mới"),
                                                ("today", "✔", "Xong hôm nay"), ("err", "!", "Lỗi cần xem"))):
            card = tk.Frame(cards, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1, padx=14, pady=12)
            card.grid(row=0, column=i, sticky="nswe", padx=(0, 10))
            cards.columnconfigure(i, weight=1)
            hr = tk.Frame(card, bg=C_CARD)
            hr.pack(anchor="w")
            tk.Label(hr, text=icon, bg=_mix(C_CARD, sc[i], 0.14), fg=sc[i], font=(FONT, 9, "bold"), width=2).pack(
                side="left")
            tk.Label(hr, text=title, bg=C_CARD, fg=C_TEXT, font=(FONT, 9)).pack(side="left", padx=(6, 0))
            num = tk.Label(card, text="0", bg=C_CARD, fg=C_TEXT, font=(FONT, 22, "bold"))
            num.pack(anchor="w", pady=(6, 0))
            sub = tk.Label(card, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 8), anchor="w", justify="left",
                           wraplength=170)
            sub.pack(anchor="w")
            self.ws_stat[key] = (num, sub)
        dl = tk.Frame(cards, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1, padx=14, pady=10)
        dl.grid(row=0, column=4, sticky="nswe")
        cards.columnconfigure(4, weight=3)
        self._build_energy_card(dl)

        # ----- bảng: tab lọc · ô lọc · thao tác chọn
        box = tk.Frame(t, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        box.pack(fill="both", expand=True, pady=(14, 0))
        hb = tk.Frame(box, bg=C_CARD, padx=12, pady=10)
        hb.pack(fill="x")
        self.scan_show_var = tk.StringVar(value="Tất cả")
        tabs = tk.Frame(hb, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        tabs.pack(side="left")
        self.ws_tabs = {}
        for name in ("Tất cả", "Mới", "Đang tải", "Lỗi", "Chưa duyệt", "Xong"):
            b = tk.Label(tabs, text=name, bg=C_PANEL, fg=C_TEXT, font=(FONT, 9), padx=10, pady=5, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, n=name: self._ws_set_tab(n))
            self.ws_tabs[name] = b
        ff = tk.Frame(hb, bg=C_FIELD, highlightbackground=C_BORDER, highlightthickness=1)
        ff.pack(side="left", padx=10)
        tk.Label(ff, text="⌕", bg=C_FIELD, fg=C_MUTED).pack(side="left", padx=(6, 0))
        tk.Entry(ff, textvariable=self.scan_search_var, width=22, relief="flat", bg=C_FIELD, fg=C_TEXT,
                 insertbackground=C_TEXT, font=(FONT, 9)).pack(side="left", ipady=4, padx=4)
        self.scan_search_var.trace_add("write", lambda *a: self._apply_scan_filter())
        selb = tk.Frame(hb, bg=C_SOFT, highlightbackground=C_SOFT_BORDER, highlightthickness=1, padx=6, pady=3)
        selb.pack(side="right")
        self.sel_var = tk.StringVar(value="Đã chọn: 0")
        tk.Label(selb, textvariable=self.sel_var, bg=C_SOFT, fg=C_ACCENT, font=(FONT, 9, "bold")).pack(side="left",
                                                                                                     padx=6)
        self.btn_own_sel = ttk.Button(selb, text="☑  Đánh dấu đã có", style="Small.TButton",
                                      command=self.mark_selected_owned, state="disabled")
        self.btn_own_sel.pack(side="left", padx=4)
        self.btn_dl_sel = ttk.Button(selb, text="⬇  Tải mục đã chọn", style="Cta.TButton",
                                     command=self.start_download_selected, state="disabled")
        self.btn_dl_sel.pack(side="left", padx=4)
        ttk.Button(selb, text="Bỏ chọn", style="Small.TButton", command=lambda: self.check_all(False)).pack(
            side="left", padx=(4, 0))
        self._scan_tree_common(box)
        self._ws_set_tab("Tất cả")

        # ----- nhật ký phía dưới: Nhật ký · Lỗi · Hàng đợi
        self._build_log_panel(t)

    def _scan_tree_common(self, parent, hide=("note",)):
        wrap, self.scan_tree = self._tree(parent, ("folder", "note", "name", "date", "size", "status"),
                                          ("PHIM", "GHI CHÚ", "TÊN FILE", "NGÀY UP", "DUNG LƯỢNG", "TRẠNG THÁI"),
                                          (200, 150, 330, 110, 100, 230), height=10, check=True,
                                          stretch=("folder", "name"))
        wrap.pack(fill="both", expand=True)
        if AVATARS and PILImage is not None:
            self.scan_tree.column("#0", width=72, minwidth=72)
        self.scan_tree["displaycolumns"] = [c for c in ("folder", "note", "name", "date", "size", "status")
                                            if c not in hide]
        self.checked = set()
        self.scan_tree.heading("#0", image=self.img_off, anchor="center", command=self._toggle_all_header)
        self.scan_tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.scan_tree.bind("<space>", self._toggle_selected_rows)
        self.scan_tree.bind("<Double-1>", self._open_selected)
        self.scan_tree.bind("<<TreeviewSelect>>", lambda e: self._show_full(self.scan_tree))
        self.scan_items = {}
        self.scan_order = []
        self.scan_sort = (None, False)
        for c in ("folder", "note", "name", "date", "size", "status"):
            self.scan_tree.heading(c, command=lambda c=c: self._sort_scan(c))
        return wrap

    def _ws_set_tab(self, name):
        self.scan_show_var.set(name)
        for n, b in getattr(self, "ws_tabs", {}).items():
            on = n == name
            b.config(bg=C_CARD if on else C_PANEL, fg=C_TEXT if on else C_MUTED,
                     font=(FONT, 9, "bold" if on else "normal"))
        self._apply_scan_filter()

    def _build_energy_card(self, card):
        """Thẻ ĐANG TẢI: tên file · % lớn · thanh tải · My PikPak · Tổng đợt (dùng chung self.energy)."""
        hr = tk.Frame(card, bg=C_CARD)
        hr.pack(fill="x")
        tk.Label(hr, text="●  ĐANG TẢI", bg=C_CARD, fg=C_ORANGE, font=(FONT, 8, "bold")).pack(side="left")
        self.ws_batch = tk.Label(hr, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 8))
        self.ws_batch.pack(side="right")
        r = tk.Frame(card, bg=C_CARD)
        r.pack(fill="x", pady=(4, 0))
        iv, pv = tk.StringVar(value="—"), tk.StringVar(value="0%")
        tk.Label(r, textvariable=iv, bg=C_CARD, fg=C_TEXT, font=(FONT, 10, "bold"), anchor="w").pack(side="left")
        tk.Label(r, textvariable=pv, bg=C_CARD, fg=C_ACCENT, font=(FONT, 17, "bold")).pack(side="right")
        bar = EnergyBar(card, C_CARD, height=14, colors=ENERGY_SETS.get("dl"))
        bar.pack(fill="x", pady=(2, 4))
        self.energy = {"dl": (bar, iv, pv)}
        self.ws_dl_sub = tk.Label(card, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 8), anchor="w")
        self.ws_dl_sub.pack(anchor="w")
        for key, text in (("up", "☁ My PikPak"), ("all", "Σ Tổng đợt")):
            rr = tk.Frame(card, bg=C_CARD)
            rr.pack(fill="x", pady=(2, 0))
            tk.Label(rr, text=text, bg=C_CARD, fg=C_MUTED, font=(FONT, 8), width=12, anchor="w").pack(side="left")
            pv2, iv2 = tk.StringVar(value="0%"), tk.StringVar()
            tk.Label(rr, textvariable=pv2, bg=C_CARD, fg=C_TEXT, font=(FONT, 8, "bold"), width=5, anchor="e").pack(
                side="right")
            b2 = EnergyBar(rr, C_CARD, height=10, colors=ENERGY_SETS.get(key))
            b2.pack(side="left", fill="x", expand=True, padx=(4, 6))
            self.energy[key] = (b2, iv2, pv2)
        self._batch = (0, 0)
        self._dl_pct = 0

    def _build_log_panel(self, parent):
        lp = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        lp.pack(fill="x", pady=(12, 0))
        hb = tk.Frame(lp, bg=C_CARD, padx=12, pady=6)
        hb.pack(fill="x")
        self.ws_log_tabs = {}
        for name in ("Nhật ký", "Lỗi", "Hàng đợi"):
            b = tk.Label(hb, text=name, bg=C_CARD, fg=C_MUTED, font=(FONT, 9), padx=8, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, n=name: self._log_tab(n))
            self.ws_log_tabs[name] = b
        lbl = tk.Label(hb, text="⌃ Thu gọn", bg=C_CARD, fg=C_MUTED, font=(FONT, 9), cursor="hand2")
        lbl.pack(side="right")
        cp = tk.Label(hb, text="⧉ Copy", bg=C_CARD, fg=C_MUTED, font=(FONT, 9), cursor="hand2")
        cp.pack(side="right", padx=10)
        cp.bind("<Button-1>", lambda e: (self.clipboard_clear(), self.clipboard_append(
            self.log_box.get("1.0", "end")), self.status_var.set("⧉ Đã copy nhật ký.")))
        body = tk.Frame(lp, bg=C_LOG_BG)
        body.pack(fill="x")
        self.log_box = tk.Text(body, height=5, wrap="word", font=("Consolas", 9), bg=C_LOG_BG, fg=C_LOG_FG,
                               insertbackground="white", relief="flat", padx=12, pady=8)
        self.log_box.pack(fill="both")
        self.ws_alt_box = tk.Text(body, height=5, wrap="word", font=("Consolas", 9), bg=C_LOG_BG, fg=C_LOG_FG,
                                  relief="flat", padx=12, pady=8)

        def toggle(_e=None):
            if body.winfo_ismapped():
                body.pack_forget()
                lbl.config(text="⌄ Mở rộng")
            else:
                body.pack(fill="x")
                lbl.config(text="⌃ Thu gọn")
        lbl.bind("<Button-1>", toggle)
        self._log_tab("Nhật ký")

    def _log_tab(self, name):
        self._log_tab_name = name
        for n, b in getattr(self, "ws_log_tabs", {}).items():
            b.config(fg=C_TEXT if n == name else C_MUTED, font=(FONT, 9, "bold" if n == name else "normal"))
        if name == "Nhật ký":
            self.ws_alt_box.pack_forget()
            self.log_box.pack(fill="both")
            return
        self.log_box.pack_forget()
        self.ws_alt_box.pack(fill="both")
        self.ws_alt_box.config(state="normal")
        self.ws_alt_box.delete("1.0", "end")
        if name == "Lỗi":
            lines = [ln for ln in list(getattr(self, "log_lines", []))
                     if any(x in ln for x in ("⚠", "✕", "Lỗi", "lỗi"))][-60:]
            self.ws_alt_box.insert("end", "\n".join(lines) or "Không có lỗi.")
        else:
            rows = [self.scan_tree.item(i, "values") for i in self.scan_order if self.scan_tree.exists(i)
                    and any(t in self.scan_tree.item(i, "tags") for t in ("new", "dl"))]
            self.ws_alt_box.insert("end", "\n".join(f"{v[0]}  ·  {v[2]}  ·  {v[4]}  ·  {v[5]}" for v in rows)
                                   or "Hàng đợi trống.")
        self.ws_alt_box.config(state="disabled")

    # ---------------------------------------------------------------- Theo phim (ảnh 5)
    def _build_movie_layout(self, body):
        rail = tk.Frame(body, bg=C_SIDE, width=78)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self.side = rail
        tk.Frame(body, bg=C_BORDER, width=1).pack(side="left", fill="y")
        main = tk.Frame(body, bg=C_BG)
        main.pack(side="left", fill="both", expand=True)
        self.top_title = tk.Label(main, text="")             # (ẩn) tiêu đề trang
        self.top_sub = tk.Label(main, text="")
        self.top_auto = tk.Label(main, text="")
        self._alerts_bar(main)
        self._ws_statusbar(main)
        nb = self._make_notebook(main)
        nb.pack(fill="both", expand=True)
        if self.icon_small:
            tk.Label(rail, image=self.icon_small, bg=C_SIDE).pack(pady=(16, 14))
        self.nav = {}
        frames = {"folders": self.tab_folders, "scan": self.tab_scan, "history": self.tab_history,
                  "settings": self.tab_settings}
        for n, (key, icon, text) in enumerate((("scan", "⬇", "Tải"), ("history", "☰", "Lịch sử"),
                                               ("folders", "▦", "Phim"), ("settings", "⚙", "Cài đặt")), 1):
            row = tk.Frame(rail, bg=C_SIDE, cursor="hand2")
            row.pack(fill="x", padx=8, pady=3)
            bar = tk.Frame(row, bg=C_SIDE, width=3)
            bar.pack(side="left", fill="y")
            col = tk.Frame(row, bg=C_SIDE)
            col.pack(side="left", fill="x", expand=True, pady=6)
            ic = tk.Label(col, text=icon, bg=C_SIDE, fg=C_SIDE_MUTED, font=(FONT, 14))
            ic.pack()
            lb = tk.Label(col, text=text, bg=C_SIDE, fg=C_SIDE_TEXT, font=(FONT, 8))
            lb.pack()
            badge = tk.Label(row, text="", bg=C_ACCENT, fg=C_ON_ACCENT, font=(MONO, 7, "bold"), padx=4)
            self.nav[key] = {"row": row, "bar": bar, "icon": ic, "label": lb, "badge": badge, "frame": frames[key],
                             "col": col}
            for w in (row, col, ic, lb, badge):
                w.bind("<Button-1>", lambda e, k=key: self.select_page(k))
                w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))
            self.bind_all(f"<Control-Key-{n}>", lambda e, k=key: self.select_page(k))
        bot = tk.Frame(rail, bg=C_SIDE)
        bot.pack(side="bottom", fill="x", pady=(0, 12))

        def rail_btn(icon, text, cmd):
            f = tk.Frame(bot, bg=C_SIDE, cursor="hand2")
            f.pack(fill="x", pady=4)
            a = tk.Label(f, text=icon, bg=C_SIDE, fg=C_SIDE_TEXT, font=(FONT, 13))
            a.pack()
            b = tk.Label(f, text=text, bg=C_SIDE, fg=C_SIDE_MUTED, font=(FONT, 8))
            b.pack()
            for w in (f, a, b):
                w.bind("<Button-1>", lambda e: cmd())
            return a
        if len(removed_themes(self.cfg)) < len(THEMES) - 1:
            self.top_theme = rail_btn("◐", "Màu", lambda: self._theme_menu(self.top_theme))
        self.top_lock = rail_btn("🔒", "Khóa", lambda: self.admin_lock() if self.admin_is_unlocked() else (
            self.admin_unlock() and self.status_var.set("🔓 Đã mở khóa tab Thư mục phim / Cài đặt.")))
        self.top_upd = rail_btn("⟳", "Bản mới", lambda: self.check_update(silent=False))
        self._hidden_side_attrs(rail)

    def _build_scan_movie(self):
        t = self.tab_scan
        t.configure(padding=0)
        pw = tk.Frame(t, bg=C_BG)
        pw.pack(fill="both", expand=True)
        # ----- cột danh sách phim
        lst = tk.Frame(pw, bg=C_CARD, width=290, highlightbackground=C_BORDER, highlightthickness=1)
        lst.pack(side="left", fill="y")
        lst.pack_propagate(False)
        tk.Label(lst, text="Thư mục phim", bg=C_CARD, fg=C_TEXT, font=(FONT, 12, "bold")).pack(anchor="w", padx=16,
                                                                                             pady=(14, 0))
        self.mv_list_sub = tk.Label(lst, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 8))
        self.mv_list_sub.pack(anchor="w", padx=16)
        sf = tk.Frame(lst, bg=C_FIELD, highlightbackground=C_BORDER, highlightthickness=1)
        sf.pack(fill="x", padx=14, pady=(8, 8))
        tk.Label(sf, text="⌕", bg=C_FIELD, fg=C_MUTED).pack(side="left", padx=(6, 0))
        self.mv_search = tk.StringVar()
        tk.Entry(sf, textvariable=self.mv_search, relief="flat", bg=C_FIELD, fg=C_TEXT, insertbackground=C_TEXT,
                 font=(FONT, 9)).pack(side="left", fill="x", expand=True, ipady=4, padx=4)
        self.mv_search.trace_add("write", lambda *a: self._mv_refresh_list(force=True))
        addb = tk.Label(lst, text="+  Thêm thư mục", bg=C_CARD, fg=C_TEXT, font=(FONT, 10), pady=8, cursor="hand2",
                        highlightbackground=C_BORDER, highlightthickness=1)
        addb.pack(side="bottom", fill="x", padx=14, pady=12)
        addb.bind("<Button-1>", lambda e: self.admin_unlock() and self.open_folder_dialog())
        cv = tk.Canvas(lst, bg=C_CARD, highlightthickness=0)
        sb = ttk.Scrollbar(lst, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(fill="both", expand=True)
        self.mv_rows = tk.Frame(cv, bg=C_CARD)
        win = cv.create_window(0, 0, window=self.mv_rows, anchor="nw")
        self.mv_rows.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
        self.mv_canvas = cv
        self.mv_sel = None            # mã thư mục phim đang xem (None = tất cả)
        self._mv_sig = None

        # ----- phần chính
        right = tk.Frame(pw, bg=C_BG)
        right.pack(side="left", fill="both", expand=True)
        head = tk.Frame(right, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        head.pack(fill="x")
        hi = tk.Frame(head, bg=C_CARD, padx=22, pady=12)
        hi.pack(fill="x")
        self.mv_avatar = tk.Label(hi, bg=C_CARD)
        self.mv_avatar.pack(side="left", padx=(0, 14))
        tt = tk.Frame(hi, bg=C_CARD)
        tt.pack(side="left")
        self.mv_title = tk.Label(tt, text="Tất cả phim", bg=C_CARD, fg=C_TEXT, font=(FONT, 16, "bold"))
        self.mv_title.pack(anchor="w")
        self.mv_chips = tk.Frame(tt, bg=C_CARD)
        self.mv_chips.pack(anchor="w", pady=(2, 0))
        hr = tk.Frame(hi, bg=C_CARD)
        hr.pack(side="right")
        self.btn_stop = ttk.Button(hr, text="■", style="Danger.TButton", width=3, command=self.stop_flag.set,
                                   state="disabled")
        self.btn_stop.pack(side="right", padx=(6, 0))
        self.btn_go = ttk.Button(hr, text="⬇  Quét & Tải tất cả", style="Accent.TButton",
                                 command=lambda: self.start_scan(True))
        self.btn_go.pack(side="right")
        self.btn_scan = ttk.Button(hr, text="⌕  Quét phim này", command=self._mv_scan_this)
        self.btn_scan.pack(side="right", padx=8)
        self.mv_edit = ttk.Button(hr, text="✎  Sửa", command=self._mv_edit)
        self.mv_edit.pack(side="right")
        body = tk.Frame(right, bg=C_BG, padx=22, pady=14)
        body.pack(fill="both", expand=True)
        cards = tk.Frame(body, bg=C_BG)
        cards.pack(fill="x")
        self.stat_vars = {k: tk.StringVar() for k in ("folders", "new", "dl", "owned")}
        self.mv_stat = []
        for i, (icon, color) in enumerate((("▦", C_ACCENT), ("✔", C_GREEN), ("●", C_ACCENT), ("!", C_RED))):
            c = tk.Frame(cards, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1, padx=14, pady=10)
            c.grid(row=0, column=i, sticky="we", padx=(0 if i == 0 else 10, 0))
            cards.columnconfigure(i, weight=1)
            tk.Label(c, text=icon, bg=_mix(C_CARD, color, 0.14), fg=color, font=(FONT, 12, "bold"), width=3,
                     pady=6).pack(side="left", padx=(0, 10))
            tc = tk.Frame(c, bg=C_CARD)
            tc.pack(side="left")
            num = tk.Label(tc, text="0", bg=C_CARD, fg=C_TEXT, font=(FONT, 16, "bold"))
            num.pack(anchor="w")
            sub = tk.Label(tc, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 8))
            sub.pack(anchor="w")
            self.mv_stat.append((num, sub))
        tb = tk.Frame(body, bg=C_BG)
        tb.pack(fill="x", pady=(14, 8))
        tabs = tk.Frame(tb, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        tabs.pack(side="left")
        self.scan_show_var = tk.StringVar(value="Tất cả")
        self.scan_search_var = tk.StringVar()
        self.mv_tab = "Tất cả"
        self.ws_tabs = {}
        for name in ("Tất cả", "Mới", "Đã có", "Lỗi"):
            b = tk.Label(tabs, text=name, bg=C_PANEL, fg=C_TEXT, font=(FONT, 9), padx=12, pady=5, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, n=name: self._mv_set_tab(n))
            self.ws_tabs[name] = b
        selb = tk.Frame(tb, bg=C_SOFT, highlightbackground=C_SOFT_BORDER, highlightthickness=1, padx=6, pady=3)
        selb.pack(side="right")
        self.sel_var = tk.StringVar(value="Đã chọn: 0")
        tk.Label(selb, textvariable=self.sel_var, bg=C_SOFT, fg=C_ACCENT, font=(FONT, 9, "bold")).pack(side="left",
                                                                                                     padx=6)
        self.btn_own_sel = ttk.Button(selb, text="☑  Đã có", style="Small.TButton",
                                      command=self.mark_selected_owned, state="disabled")
        self.btn_own_sel.pack(side="left", padx=4)
        self.btn_dl_sel = ttk.Button(selb, text="⬇  Tải", style="Cta.TButton", command=self.start_download_selected,
                                     state="disabled")
        self.btn_dl_sel.pack(side="left", padx=(4, 0))
        stack = tk.Frame(body, bg=C_BG)
        stack.pack(fill="both", expand=True)
        self.mv_scan_wrap = self._scan_tree_common(stack, hide=("note",))
        wrap, self.mv_own_tree = self._tree(stack, ("ep", "name", "size", "added"),
                                            ("TẬP", "TÊN FILE", "DUNG LƯỢNG", "NGÀY THÊM"), (80, 420, 110, 140),
                                            height=10, stretch=("name",))
        self.mv_own_wrap = wrap
        self.mv_own_tree.bind("<Double-1>", self._mv_open_owned)
        # ----- hàng đợi phía dưới
        q = tk.Frame(right, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        q.pack(fill="x", side="bottom")
        qi = tk.Frame(q, bg=C_CARD, padx=22, pady=10)
        qi.pack(fill="x")
        ql = tk.Frame(qi, bg=C_CARD)
        ql.pack(side="left", padx=(0, 18))
        tk.Label(ql, text="HÀNG ĐỢI", bg=C_CARD, fg=C_MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
        self.mv_q_num = tk.Label(ql, text="0 / 0", bg=C_CARD, fg=C_TEXT, font=(FONT, 15, "bold"))
        self.mv_q_num.pack(anchor="w")
        self.energy = {}
        self.mv_q_cards = []
        for i in range(4):
            c = tk.Frame(qi, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1, padx=10, pady=8)
            c.pack(side="left", fill="x", expand=True, padx=(0, 10 if i < 3 else 0))
            c.pack_propagate(True)
            r = tk.Frame(c, bg=C_CARD)
            r.pack(fill="x")
            iv, pv = tk.StringVar(value="—"), tk.StringVar(value="")
            tk.Label(r, textvariable=iv, bg=C_CARD, fg=C_TEXT, font=(FONT, 9, "bold"), anchor="w", width=24).pack(
                side="left", fill="x", expand=True)
            tk.Label(r, textvariable=pv, bg=C_CARD, fg=C_TEXT, font=(FONT, 9, "bold")).pack(side="right")
            bar = EnergyBar(c, C_CARD, height=10, colors=ENERGY_SETS.get("up" if i == 3 else "dl"))
            bar.pack(fill="x", pady=(6, 2))
            sub = tk.Label(c, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 8), anchor="w")
            sub.pack(anchor="w")
            self.mv_q_cards.append((c, iv, pv, bar, sub))
        c0 = self.mv_q_cards[0]
        self.energy["dl"] = (c0[3], c0[1], c0[2])
        c3 = self.mv_q_cards[3]
        self.energy["up"] = (c3[3], tk.StringVar(), c3[2])
        self.energy["all"] = (EnergyBar(q, C_CARD), tk.StringVar(), tk.StringVar())
        self._batch = (0, 0)
        self._dl_pct = 0
        self.log_box = tk.Text(t, height=1)                  # (ẩn) nhật ký - xem ở tab Lịch sử / Cài đặt
        self._mv_set_tab("Tất cả")
        self._mv_refresh_list(force=True)

    def _mv_folder(self):
        for f in self.cfg["folders"]:
            if fid(f) == self.mv_sel:
                return f
        return None

    def _mv_select(self, code):
        self.mv_sel = code
        self._mv_refresh_list(force=True)
        self._mv_refresh_head()
        self._apply_scan_filter()
        self._mv_fill_owned()

    def _mv_set_tab(self, name):
        self.mv_tab = name
        for n, b in self.ws_tabs.items():
            on = n == name
            b.config(bg=C_CARD if on else C_PANEL, fg=C_TEXT if on else C_MUTED,
                     font=(FONT, 9, "bold" if on else "normal"))
        if name == "Đã có":
            self.mv_scan_wrap.pack_forget()
            self.mv_own_wrap.pack(fill="both", expand=True)
            self._mv_fill_owned()
        else:
            self.mv_own_wrap.pack_forget()
            self.mv_scan_wrap.pack(fill="both", expand=True)
            self.scan_show_var.set(name)
            self._apply_scan_filter()

    def _mv_owned_of(self, code):
        return [r for r in self.owned.values() if (r.get("folder") or "") == code]

    def _mv_fill_owned(self):
        tr = getattr(self, "mv_own_tree", None)
        if tr is None:
            return
        tr.delete(*tr.get_children())
        rows = []
        codes = [self.mv_sel] if self.mv_sel else [fid(f) for f in self.cfg["folders"]]
        for code in codes:
            for r in self._mv_owned_of(code):
                ep = episode_of(r.get("name", ""))
                rows.append(((ep[1], ep[2]) if ep else (999, 0), r))
        rows.sort(key=lambda x: x[0], reverse=True)
        for i, (k, r) in enumerate(rows[:3000]):
            ep = ("S%d E%d" % k if k[0] not in (0, 999) else (str(k[1]) if k[0] != 999 else "")) if k else ""
            try:
                sz = human_size(int(r.get("size") or 0)) if r.get("size") else ""
            except (TypeError, ValueError):
                sz = ""
            when = dt.datetime.fromtimestamp(r["ts"]).strftime("%d/%m/%Y %H:%M") if r.get("ts") else ""
            tr.insert("", "end", values=(ep, r.get("name", ""), sz, when), tags=("done",) + (("odd",) if i % 2 else ()))

    def _mv_open_owned(self, _e=None):
        sel = self.mv_own_tree.selection()
        if not sel:
            return
        name = self.mv_own_tree.item(sel[0], "values")[1]
        for h in self.history.values():
            if h.get("name") == name:
                p = h.get("hdd") or h.get("path")
                if p and os.path.exists(p):
                    open_target(os.path.dirname(p))
                    return
        self.status_var.set("Không tìm thấy file này trên máy (có thể đã chuyển chỗ).")

    def _mv_scan_this(self):
        f = self._mv_folder()
        self.start_scan(False, only={fid(f)} if f else None)

    def _mv_edit(self):
        f = self._mv_folder()
        if not f:
            self.select_page("folders")
            return
        if self.admin_unlock():
            self.open_folder_dialog(self.cfg["folders"].index(f))

    def _mv_counts(self, code=None):
        """Đếm dòng bảng Quét & Tải theo phim: (tất cả, mới, lỗi, đang tải)."""
        a = n = e = d = 0
        for iid in self.scan_order:
            it = self.scan_items.get(iid)
            if code and (not it or it[4] != code):
                continue
            if not self.scan_tree.exists(iid):
                continue
            tg = self.scan_tree.item(iid, "tags")
            a += 1
            n += "new" in tg
            e += "err" in tg
            d += "dl" in tg
        return a, n, e, d

    def _mv_refresh_list(self, force=False):
        if not hasattr(self, "mv_rows"):
            return
        q = strip_accents(self.mv_search.get().strip())
        counts = {}
        for iid in self.scan_order:
            it = self.scan_items.get(iid)
            if it and self.scan_tree.exists(iid) and "new" in self.scan_tree.item(iid, "tags"):
                counts[it[4]] = counts.get(it[4], 0) + 1
        sig = (q, self.mv_sel, tuple((fid(f), f.get("name"), f.get("last_error", ""), f.get("reviewed"),
                                      counts.get(fid(f), 0)) for f in self.cfg["folders"]))
        if sig == self._mv_sig and not force:
            return
        self._mv_sig = sig
        for w in self.mv_rows.winfo_children():
            w.destroy()
        total_new = sum(counts.values())
        self.mv_list_sub.config(text=f"{len(self.cfg['folders'])} phim · {total_new} tập mới")

        def add_row(code, name, sub, badge, bcolor):
            on = code == self.mv_sel
            bg = C_SEL if on else C_CARD
            row = tk.Frame(self.mv_rows, bg=bg, cursor="hand2")
            row.pack(fill="x")
            tk.Frame(row, bg=C_ACCENT if on else bg, width=3).pack(side="left", fill="y")
            img = self.avatar_img(name if code else "Tất cả", 34)
            av = tk.Label(row, image=img, bg=bg) if img else tk.Label(row, text=self._initials(name), bg=bg,
                                                                       fg=C_ACCENT, font=(FONT, 10, "bold"), width=3)
            av.image = img
            av.pack(side="left", padx=(10, 10), pady=7)
            tc = tk.Frame(row, bg=bg)
            tc.pack(side="left", fill="x", expand=True)
            tk.Label(tc, text=name, bg=bg, fg=C_TEXT, font=(FONT, 10, "bold"), anchor="w").pack(anchor="w")
            tk.Label(tc, text=sub, bg=bg, fg=C_MUTED, font=(FONT, 8), anchor="w").pack(anchor="w")
            ws = [row, av, tc] + list(tc.winfo_children())
            if badge:
                b = tk.Label(row, text=badge, bg=_mix(bg, bcolor, 0.16), fg=bcolor, font=(FONT, 8, "bold"), padx=6)
                b.pack(side="right", padx=10)
                ws.append(b)
            for w in ws:
                w.bind("<Button-1>", lambda e, c=code: self._mv_select(c))
                w.bind("<MouseWheel>", lambda e: self.mv_canvas.yview_scroll(int(-e.delta / 120), "units"))
        add_row(None, "Tất cả phim", f"{total_new} tập trong đợt quét", str(total_new) if total_new else "", C_ACCENT)
        for f in self.cfg["folders"]:
            name = f.get("name") or "?"
            if q and q not in strip_accents(name):
                continue
            code = fid(f)
            last = ""
            eps = [episode_of(r.get("name", "")) for r in self._mv_owned_of(code)]
            eps = [e[2] for e in eps if e]
            if eps:
                last = f"Tập mới nhất: {max(eps)}"
            n = counts.get(code, 0)
            if f.get("last_error"):
                badge, col = "!", C_RED
            elif not f.get("reviewed"):
                badge, col = "?", C_MUTED
            elif n:
                badge, col = f"+{n}", C_ORANGE
            else:
                badge, col = "", C_MUTED
            add_row(code, name, last or (f.get("note") or ""), badge, col)
        self._mv_refresh_head()

    def _mv_refresh_head(self):
        if not hasattr(self, "mv_title"):
            return
        f = self._mv_folder()
        name = f.get("name") if f else "Tất cả phim"
        self.mv_title.config(text=name)
        img = self.avatar_img(name, 44)
        self.mv_avatar.config(image=img or "", text="" if img else self._initials(name))
        self.mv_avatar.image = img
        for w in self.mv_chips.winfo_children():
            w.destroy()
        chips = []
        if f:
            chips = [one_line(f.get("note", "")), f.get("pikpak_dir", ""), from_portable(f.get("local_dir", ""))]
        else:
            chips = [f"{len(self.cfg['folders'])} thư mục phim"]
        for c in [c for c in chips if c][:4]:
            tk.Label(self.mv_chips, text=c if len(c) <= 40 else c[:37] + "...", bg=C_PANEL, fg=C_MUTED,
                     font=(FONT, 8), padx=8, pady=1, highlightbackground=C_BORDER, highlightthickness=1).pack(
                side="left", padx=(0, 6))
        self.btn_scan.config(text="⌕  Quét phim này" if f else "⌕  Chỉ quét tất cả")
        code = fid(f) if f else None
        a, n, e, d = self._mv_counts(code)
        own = len(self._mv_owned_of(code)) if code else len(self.owned)
        gap = ""
        if f and f.get("gaps"):
            m = re.search(r"thiếu\s*([\d–,\s-]+)", str(f["gaps"][0]))
            gap = f"Tập {m.group(1).strip()}" if m else "Có"
        vals = ((str(f.get("total", 0)) if f else str(len(self.cfg["folders"])),
                 "Tập trên PikPak" if f else "Thư mục phim"),
                (str(own), "Đã có (Danh sách đã có)"),
                (str(n), "Tập mới"),
                ((gap or "0") if f else str(e), "Có thể thiếu" if f else "Lỗi cần xem"))
        for (num, sub), (v, s_) in zip(self.mv_stat, vals):
            num.config(text=v)
            sub.config(text=s_)
        for nm, cnt in (("Tất cả", a), ("Mới", n), ("Đã có", own), ("Lỗi", e)):
            b = self.ws_tabs.get(nm)
            if b:
                b.config(text=f"{nm}  {cnt}")

    def _layout_tick(self):
        """Cập nhật các ô riêng của bố cục Workspace / Theo phim (mỗi giây)."""
        try:
            if LAYOUT == "workspace":
                self._ws_refresh()
            elif LAYOUT == "movie":
                self._mv_refresh_list()
                self._mv_refresh_head()
                self._mv_refresh_queue()
            if hasattr(self, "ws_dots"):
                pk = getattr(self, "pk_ok", None)
                self.ws_dots["pk"][0].config(fg=C_GREEN if pk else (C_RED if pk is False else C_MUTED))
                self.ws_dots["pk"][1].config(text="PikPak" + (" VIP" if pk else ""))
                rc = getattr(self, "_rc_cached", None)
                if rc is None or time.time() - getattr(self, "_rc_t", 0) > 30:
                    self._rc_cached, self._rc_t = bool(find_rclone()), time.time()
                self.ws_dots["rc"][0].config(fg=C_GREEN if self._rc_cached else C_RED)
                bk = self.cfg.get("last_backup") or ""
                self.ws_dots["bk"][0].config(fg=C_GREEN if bk else C_MUTED)
                self.ws_dots["bk"][1].config(text="Sao lưu " + (bk[-5:] if bk else "—"))
        except Exception:
            pass
        self.after(1000, self._layout_tick)

    def _ws_refresh(self):
        on = [f for f in self.cfg["folders"] if f.get("enabled", True)]
        unrev = sum(1 for f in on if not f.get("reviewed"))
        today = dt.date.today()
        done = [h for h in self.history.values() if h.get("status") == STATUS_DONE and h.get("done_ts")
                and dt.date.fromtimestamp(h["done_ts"]) == today]
        gb = sum(int(h.get("size") or 0) for h in done if str(h.get("size") or "").isdigit())
        errs = [i for i in self.scan_order if self.scan_tree.exists(i) and "err" in self.scan_tree.item(i, "tags")]
        ferr = [f for f in on if f.get("last_error")]
        new = getattr(self, "_new_count", 0)
        S = self.ws_stat
        S["folders"][0].config(text=str(len(on)))
        S["folders"][1].config(text=f"{unrev} thư mục chưa duyệt" if unrev else "tất cả đã duyệt")
        S["new"][0].config(text=str(new))
        S["new"][1].config(text="từ lần quét gần nhất")
        S["today"][0].config(text=str(len(done)))
        S["today"][1].config(text=f"{human_size(gb)} đã tải" if gb else "chưa có")
        ne = len(errs) + len(ferr)
        S["err"][0].config(text=str(ne))
        first = (self.scan_tree.item(errs[0], "values")[0] if errs else (ferr[0].get("name") if ferr else ""))
        S["err"][1].config(text=first or "không có lỗi")
        d, n = getattr(self, "_batch", (0, 0))
        self.ws_batch.config(text=f"{min(d + 1, n)} / {n} trong đợt" if n else "")
        info = self.energy["dl"][1].get()
        m = re.search(r"([\d.,]+\s*[KMG]i?B/s)", info)
        self.ws_dl_sub.config(text=("Tốc độ " + m.group(1)) if m else "")
        # tab lọc: số đếm
        cnt = {"Tất cả": 0, "Mới": 0, "Đang tải": 0, "Lỗi": 0, "Chưa duyệt": 0, "Xong": 0}
        for i in self.scan_order:
            if not self.scan_tree.exists(i):
                continue
            tg = self.scan_tree.item(i, "tags")
            cnt["Tất cả"] += 1
            cnt["Mới"] += "new" in tg
            cnt["Đang tải"] += "dl" in tg
            cnt["Lỗi"] += "err" in tg
            cnt["Chưa duyệt"] += "skip" in tg
            cnt["Xong"] += "done" in tg
        for nm, b in self.ws_tabs.items():
            b.config(text=f"{nm}  {cnt.get(nm, 0)}")
        # thẻ Thư viện + Tự quét
        self.ws_lib_num.config(text=f"{len(self.owned):,}".replace(",", "."))
        drv = ""
        for f in on:
            p = from_portable(f.get("local_dir", ""))
            if p:
                drv = os.path.splitdrive(os.path.abspath(p))[0] or p
                break
        sub = f"{len(self.cfg['folders'])} phim"
        if drv:
            try:
                du = shutil.disk_usage(drv + os.sep if drv.endswith(":") else drv)
                sub += f" · HDD {drv} còn {human_size(du.free)}"
                self.ws_lib_bar.set(du.used * 100 / max(1, du.total))
            except OSError:
                pass
        self.ws_lib_sub.config(text=sub)
        self._ws_draw_switch()
        if self.next_auto_ts and self.auto_var.get():
            left = max(0, int(self.next_auto_ts - time.time()))
            self.ws_count.config(text=f"{left // 60:02d}:{left % 60:02d}" if left < 6000 else f"{left // 3600}h")
            iv = int(self.cfg.get("auto_interval", 60) or 60) * 60
            self.ws_count_sub.config(text=f"đến lần quét tới · mỗi {iv // 60} phút")
            self.ws_count_bar.set(100 - left * 100 / max(1, iv))
        else:
            self.ws_count.config(text="Tắt")
            self.ws_count_sub.config(text="bật công tắc để tự quét")
            self.ws_count_bar.set(0)
        if getattr(self, "_log_tab_name", "Nhật ký") != "Nhật ký" and int(time.time()) % 3 == 0:
            self._log_tab(self._log_tab_name)

    def _mv_refresh_queue(self):
        d, n = getattr(self, "_batch", (0, 0))
        self.mv_q_num.config(text=f"{min(d + 1, n) if n else 0} / {n}")
        busy = bool(self.worker and self.worker.is_alive())
        pend = [i for i in self.scan_order if self.scan_tree.exists(i)
                and any(t in self.scan_tree.item(i, "tags") for t in ("new", "dl"))]
        dl = [i for i in pend if "dl" in self.scan_tree.item(i, "tags")]
        nxt = [i for i in pend if i not in dl]
        c0 = self.mv_q_cards[0]
        if not busy:
            c0[1].set("—" if not dl else c0[1].get())
        info = c0[1].get()
        m = re.search(r"([\d.,]+\s*[KMG]i?B/s)", info)
        c0[4].config(text=("⬇ " + m.group(1)) if m else ("Đang chờ" if busy else "Sẵn sàng"))
        c0[0].config(highlightbackground=C_ACCENT if busy else C_BORDER)
        for k, c in enumerate(self.mv_q_cards[1:3]):
            if k < len(nxt):
                v = self.scan_tree.item(nxt[k], "values")
                c[1].set(str(v[2])[:34])
                c[2].set("0%")
                c[3].set(0)
                c[4].config(text=f"Chờ · {v[4]}")
            else:
                c[1].set("—")
                c[2].set("")
                c[3].set(0)
                c[4].config(text="")
        c3 = self.mv_q_cards[3]
        if not c3[1].get() or c3[1].get() == "—":
            c3[1].set("☁ My PikPak")
        ups = len(getattr(self, "up_queued", ()) or ())
        c3[4].config(text=f"{ups} tập đang Save" if ups else "Đã Save đủ")

    # ================================================================ NHÃN TRẠNG THÁI CÓ VIỀN (giao diện 3)
    PILL_TAG_COLORS = (("err", "C_RED"), ("dl", "C_ORANGE"), ("done", "C_GREEN"), ("new", "C_BLUE"),
                       ("skip", "C_SKIP"))

    def _pill_color(self, tags):
        for t, key in self.PILL_TAG_COLORS:
            if t in tags:
                return globals()[key]
        return C_MUTED

    def _pill_refresh(self):
        """Đặt nhãn (Label có viền) đè lên ô Trạng thái của các dòng đang thấy trong bảng Quét & Tải."""
        tr = getattr(self, "scan_tree", None)
        if tr is None:
            return
        pills = self.__dict__.setdefault("_pills", {})
        used = set()
        try:
            if tr.winfo_ismapped():
                for iid in tr.get_children():
                    bb = tr.bbox(iid, "status")
                    if not bb:
                        continue
                    x, y, w, h = bb
                    vals = tr.item(iid, "values")
                    text = re.sub(r"\s{2,}", "  ", re.sub(r"[▰▱]+\s*", "", str(vals[5]) if len(vals) > 5 else "")).strip()
                    if not text:
                        continue
                    col = self._pill_color(tr.item(iid, "tags"))
                    sel = iid in tr.selection()
                    lb = pills.get(iid)
                    if lb is None:
                        lb = tk.Label(tr, font=(FONT, 9), padx=7, pady=0, highlightthickness=1, bd=0,
                                      cursor="hand2")
                        lb.bind("<Button-1>", lambda e, i=iid: (tr.selection_set(i), tr.focus(i)))
                        lb.bind("<Double-1>", lambda e: self._open_selected(e))
                        lb.bind("<MouseWheel>", lambda e: tr.yview_scroll(int(-e.delta / 120), "units"))
                        pills[iid] = lb
                    base = C_SEL if sel else (C_ODD if "odd" in tr.item(iid, "tags") else C_CARD)
                    maxw = max(40, w - 12)
                    t = text if len(text) * 7 < maxw else text[:max(4, maxw // 7 - 1)] + "…"
                    lb.config(text=t, fg=col, bg=_mix(base, col, 0.08), highlightbackground=col,
                              highlightcolor=col)
                    lh = lb.winfo_reqheight()
                    lb.place(x=x + 6, y=y + max(0, (h - lh) // 2))
                    used.add(iid)
        except tk.TclError:
            pass
        for iid, lb in list(pills.items()):
            if iid not in used:
                if not tr.exists(iid):
                    lb.destroy()
                    del pills[iid]
                else:
                    lb.place_forget()

    def _pill_tick(self):
        self._pill_refresh()
        self.after(300, self._pill_tick)

    LOCKED_PAGES = ("folders", "settings")

    def select_page(self, key, ask=True):
        if key in self.LOCKED_PAGES and not self.admin_unlock(ask):
            if getattr(self, "page", None) is None:
                key = "scan"
            else:
                return False
        self.page = key
        self.nb.select(self.nav[key]["frame"])
        t, sub = self.PAGE_INFO.get(key, ("", ""))
        if LAYOUT == "workspace":
            sub = ("Quản lý  /" if key in self.LOCKED_PAGES else "Làm việc  /")
        try:
            self.top_title.config(text=t)
            self.top_sub.config(text=sub)
        except AttributeError:
            pass
        for k, n in self.nav.items():
            on = k == key
            bg = C_SIDE_HOVER if on else C_SIDE
            for w in ("row", "icon", "label", "col", "hint"):
                if w in n:
                    n[w].config(bg=bg)
            n["bar"].config(bg=C_SIDE_ACTIVE if on else bg)
            n["icon"].config(fg=C_SIDE_ACTIVE if on else C_SIDE_MUTED)
            n["label"].config(fg=C_SIDE_SEL_TEXT if on else C_SIDE_TEXT)
        if LED_LIST and getattr(self, "led_cards", None) is not None:
            self._led_nav_style(key)

    def _nav_hover(self, key, inside):
        if getattr(self, "page", None) == key:
            return
        bg = C_SIDE_HOVER if inside else C_SIDE
        n = self.nav[key]
        for w in ("row", "icon", "label", "bar", "col", "hint"):
            if w in n:
                n[w].config(bg=bg)

    def set_badge(self, key, value, color=None):
        b = self.nav[key]["badge"]
        if value:
            b.config(text=str(value), bg=color or C_ACCENT)
            if not getattr(self, "side_collapsed", False):
                b.pack(side="right", padx=10)
        else:
            b.config(text="")
            b.pack_forget()

    def _build_statusbar(self, parent):
        bar = ttk.Frame(parent, style="Bg.TFrame", padding=(18, 6, 18, 8))
        bar.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(bar, style="Pro.Horizontal.TProgressbar", mode="determinate", length=220)
        self.progress.pack(side="right")
        self.status_var = tk.StringVar(value="Sẵn sàng.")
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(side="left")

    def _build_energy(self, parent):
        """Bảng tiến trình: % + thanh năng lượng cho file đang tải, upload My PikPak và tổng đợt."""
        box = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        box.pack(fill="x", pady=(12, 0))
        inner = tk.Frame(box, bg=C_PANEL, padx=14, pady=10)
        inner.pack(fill="x")
        inner.columnconfigure(2, weight=1)
        self.energy = {}
        for r, (key, icon, title, color) in enumerate((("dl", "⬇", "TẢI VỀ", C_ACCENT),
                                                      ("up", "☁", "MY PIKPAK", C_BLUE),
                                                      ("all", "Σ", "TỔNG ĐỢT", C_GREEN))):
            tk.Label(inner, text=f"{icon}  {title}", bg=C_PANEL, fg=color, font=(FONT, 9, "bold"), width=12,
                     anchor="w").grid(row=r, column=0, sticky="w", pady=4)
            info = tk.StringVar(value="—")
            tk.Label(inner, textvariable=info, bg=C_PANEL, fg=C_MUTED, font=(FONT, 9), width=44, anchor="w"
                     ).grid(row=r, column=1, sticky="w", padx=(0, 10))
            bar = EnergyBar(inner, C_PANEL, height=20 if key == "dl" else 14, seg=40 if key == "dl" else 30,
                            colors=ENERGY_SETS.get(key))
            bar.grid(row=r, column=2, sticky="we", pady=4)
            pct = tk.StringVar(value="0%")
            tk.Label(inner, textvariable=pct, bg=C_PANEL, fg=color, font=(MONO, 15 if key == "dl" else 11, "bold"),
                     width=5, anchor="e").grid(row=r, column=3, sticky="e", padx=(10, 0))
            self.energy[key] = (bar, info, pct)
        self._batch = (0, 0)
        self._dl_pct = 0

    def _energy_set(self, key, pct, info=None):
        try:
            bar, iv, pv = self.energy[key]
        except (AttributeError, KeyError):
            return
        try:
            pct = max(0, min(100, int(round(float(pct)))))
        except (TypeError, ValueError):
            pct = 0
        bar.set(pct)
        pv.set(f"{pct}%")
        if info is not None:
            info = str(info)
            iv.set(info if len(info) <= 60 else info[:57] + "...")
        if key == "dl":
            self._dl_pct = pct
            m = re.search(r"([\d.]+)\s*([KMG])i?B/s", str(info or ""))
            if m:
                v = float(m.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024}[m.group(2)]
                self._dl_speed = v
            self._energy_total()

    def _energy_total(self):
        done, n = getattr(self, "_batch", (0, 0))
        if not n:
            return
        cur = self._dl_pct if done < n else 0
        tot = min(100, (done + cur / 100) / n * 100)
        bar, iv, pv = self.energy["all"]
        bar.set(tot)
        pv.set(f"{int(tot)}%")
        iv.set(f"{min(done + (1 if done < n else 0), n)} / {n}")

    def _stat_card(self, parent, title, color, glyph=""):
        """Thẻ số liệu kiểu đồng hồ máy: nhãn nhỏ in hoa, số lớn font màn hình, vạch màu + đèn báo."""
        card = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
        tk.Frame(card, bg=color, width=7 if STAT_ICONS else 5).pack(side="left", fill="y")
        body = tk.Frame(card, bg=C_PANEL, padx=14, pady=10)
        body.pack(side="left", fill="both", expand=True)
        var = tk.StringVar(value="0")
        top = tk.Frame(body, bg=C_PANEL)
        top.pack(fill="x")
        tk.Label(top, text="●", bg=C_PANEL, fg=color, font=(FONT, 8)).pack(side="left")
        tk.Label(top, text="  " + title.upper(), bg=C_PANEL, fg=C_MUTED, font=(FONT, 8, "bold")).pack(side="left")
        if glyph and STAT_ICONS:                     # ô vuông màu nổi có biểu tượng trắng
            s_ = 28
            cv = tk.Canvas(top, width=s_ + 2, height=s_ + 3, bg=C_PANEL, highlightthickness=0)
            cv.pack(side="right")
            sh = _mix(color, "#000000", 0.35)
            for (x0, y0, c_) in ((1, 3, sh), (1, 1, color)):
                rr = 7
                cv.create_rectangle(x0 + rr, y0, x0 + s_ - rr, y0 + s_, fill=c_, outline="")
                cv.create_rectangle(x0, y0 + rr, x0 + s_, y0 + s_ - rr, fill=c_, outline="")
                for ox, oy in ((0, 0), (s_ - 2 * rr, 0), (0, s_ - 2 * rr), (s_ - 2 * rr, s_ - 2 * rr)):
                    cv.create_oval(x0 + ox, y0 + oy, x0 + ox + 2 * rr, y0 + oy + 2 * rr, fill=c_, outline="")
            cv.create_rectangle(5, 3, s_ - 3, 11, fill=_mix(color, "#ffffff", 0.3), outline="")
            cv.create_text(s_ / 2 + 1, s_ / 2 + 1, text={"▦": "■", "●": "●", "⬇": "⬇", "✔": "✔"}.get(glyph, glyph),
                           fill="#ffffff", font=(FONT, 11, "bold"))
        elif glyph:
            tk.Label(top, text=glyph, bg=C_PANEL, fg=C_GLYPH, font=(FONT, 12)).pack(side="right")
        tk.Label(body, textvariable=var, bg=C_PANEL, fg=color,
                 font=(FONT, 24, "bold") if STAT_ICONS else (MONO, 22, "bold")).pack(anchor="w", pady=(2, 0))
        return card, var

    def _apply_scan_filter(self):
        n = 0
        for iid in self.scan_order:
            if not self.scan_tree.exists(iid):
                continue
            if self._row_visible(iid):
                self.scan_tree.move(iid, "", "end")
                tags = [t for t in self.scan_tree.item(iid, "tags") if t != "odd"] + (["odd"] if n % 2 else [])
                self.scan_tree.item(iid, tags=tags)
                n += 1
            else:
                self.scan_tree.detach(iid)
        self._update_sel_count()

    def _sort_scan(self, col):
        cur, rev = self.scan_sort
        rev = (not rev) if cur == col else False
        self.scan_sort = (col, rev)
        idx = ("folder", "note", "name", "date", "size", "status").index(col)

        def key(iid):
            v = self.scan_tree.item(iid, "values")[idx] if self.scan_tree.exists(iid) else ""
            if col == "date":
                try:
                    return dt.datetime.strptime(v, "%d/%m/%Y")
                except ValueError:
                    return dt.datetime.min
            if col == "size":
                try:
                    return int(self.scan_items.get(iid, (0, 0, 0, 0))[3] or 0)
                except (TypeError, ValueError):
                    return 0
            return strip_accents(v)
        self.scan_order.sort(key=key, reverse=rev)
        heads = {"folder": "THƯ MỤC", "note": "GHI CHÚ", "name": "TÊN FILE", "date": "NGÀY UP",
                 "size": "DUNG LƯỢNG", "status": "TRẠNG THÁI"}
        for c, t in heads.items():
            self.scan_tree.heading(c, text=t + ((" ▼" if rev else " ▲") if c == col else ""))
        self._apply_scan_filter()

    def _checked(self):
        return [i for i in self.scan_order if i in self.checked and self.scan_tree.exists(i)]

    def _set_check(self, iid, on):
        (self.checked.add if on else self.checked.discard)(iid)
        self.scan_tree.item(iid, image=self._chk_img(iid, on))

    def check_all(self, on):
        for i in self.scan_tree.get_children():
            self._set_check(i, on)
        self._update_sel_count()

    def _toggle_all_header(self):
        kids = self.scan_tree.get_children()
        self.check_all(not (kids and all(i in self.checked for i in kids)))

    def _on_tree_click(self, e):
        if self.scan_tree.identify_region(e.x, e.y) not in ("tree", "cell") or self.scan_tree.identify_column(e.x) != "#0":
            return None
        iid = self.scan_tree.identify_row(e.y)
        if iid:
            self._set_check(iid, iid not in self.checked)
            self._update_sel_count()
        return "break"

    def _toggle_selected_rows(self, _e=None):
        sel = self.scan_tree.selection()
        if sel:
            on = any(i not in self.checked for i in sel)
            for i in sel:
                self._set_check(i, on)
            self._update_sel_count()
        return "break"

    def open_folder_dialog(self, index=None):
        """Thêm / sửa 1 thư mục phim: Nguồn · Tên phim · Ghi chú · Đích HDD · Đích My PikPak (+ nâng cao)."""
        old = dict(self.cfg["folders"][index]) if index is not None else {}
        win = tk.Toplevel(self)
        win.title("Sửa thư mục phim" if old else "Thêm thư mục phim")
        win.configure(bg=C_CARD)
        win.transient(self)
        win.resizable(True, False)
        try:
            win.iconphoto(False, self.icon_big)
        except (tk.TclError, TypeError):
            pass
        body = ttk.Frame(win, style="Card.TFrame", padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        hd = tk.Frame(body, bg=C_CARD)
        hd.grid(row=0, column=0, columnspan=3, sticky="we", pady=(0, 12))
        tk.Frame(hd, bg=C_ACCENT, width=4, height=22).pack(side="left", padx=(0, 10))
        tk.Label(hd, text=("SỬA THƯ MỤC PHIM" if old else "THÊM THƯ MỤC PHIM"), bg=C_CARD, fg=C_TEXT,
                 font=(FONT, 12, "bold")).pack(side="left")
        defaults = {"local_dir": from_portable(self.cfg.get("library_root", "") or r"D:\DOWNLOAD HH3D"),
                    "pikpak_dir": self.cfg.get("pikpak_root", "") or "My Pack/2026"}
        v = {k: tk.StringVar(value=old.get(k, defaults.get(k, "")) if old else defaults.get(k, ""))
             for k in ("name", "url", "include", "exclude", "local_dir", "pikpak_dir")}
        v["local_dir"].set(from_portable(old.get("local_dir", "")) if old else defaults["local_dir"])
        v["url"].set(resolve_src(self.cfg, old.get("url", "")) or old.get("url", ""))
        en = tk.BooleanVar(value=old.get("enabled", True))
        use_hdd = tk.BooleanVar(value=True)      # đích HDD bắt buộc
        use_pk = tk.BooleanVar(value=bool(v["pikpak_dir"].get()))
        use_pk.set(True)                         # Đích 1 (My PikPak) bắt buộc
        sub_movie = tk.BooleanVar(value=old.get("sub_movie", False))
        src_label = tk.StringVar(value=old.get("src_label", ""))
        r = 1

        def label(text, row, sub=None):
            box = tk.Frame(body, bg=C_CARD)
            box.grid(row=row, column=0, sticky="nw", pady=6, padx=(0, 14))
            tk.Label(box, text=text, bg=C_CARD, fg=C_TEXT, font=(FONT, 10, "bold"), anchor="w").pack(anchor="w")
            if sub:
                tk.Label(box, text=sub, bg=C_CARD, fg=C_MUTED, font=(FONT, 8), anchor="w").pack(anchor="w")

        def field(text, key, sub=None, buttons=()):
            nonlocal r
            label(text, r, sub)
            e = ttk.Entry(body, textvariable=v[key], width=62)
            e.grid(row=r, column=1, sticky="we", pady=6)
            if buttons:
                bf = tk.Frame(body, bg=C_CARD)
                bf.grid(row=r, column=2, padx=(8, 0), sticky="w")
                for t, cmd in buttons:
                    ttk.Button(bf, text=t, style="Small.TButton", command=cmd).pack(side="left", padx=(0, 4))
            r += 1
            return e

        def pick_dir(key, title, initial=None):
            p = filedialog.askdirectory(parent=win, title=title, initialdir=initial or None)
            if p:
                v[key].set(os.path.normpath(p))
                if key == "url" and not v["name"].get().strip():
                    v["name"].set(os.path.basename(os.path.normpath(p)))

        def pick_pk():
            self.open_pikpak_browser(target_var=v["pikpak_dir"], parent=win)

        first = field("Nguồn phim *", "url", "Thư mục con trong link chia sẻ PikPak",
                      (("☁ Chọn trong link chia sẻ...", lambda: self.open_share_browser(
                          v["url"], v["name"], src_label, parent=win)),))
        tk.Label(body, textvariable=src_label, bg=C_CARD, fg=C_GREEN, font=(FONT, 9, "bold")).grid(
            row=r, column=1, columnspan=2, sticky="w")
        r += 1
        tk.Label(body, text="Bấm \"Chọn trong link chia sẻ...\" rồi mở tới thư mục phim  ·  hoặc dán link "
                            "https://mypikpak.com/s/XXXX/<mã thư mục>   (có mật khẩu: thêm ?pwd=xxxx)",
                 bg=C_CARD, fg=C_MUTED, font=(FONT, 8)).grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        field("Tên phim", "name", "Để trống = tên thư mục")
        label("Ghi chú", r)
        nf = tk.Frame(body, bg=C_BORDER, padx=1, pady=1)
        nf.grid(row=r, column=1, columnspan=2, sticky="we", pady=6)
        note = tk.Text(nf, height=3, wrap="word", relief="flat", font=(FONT, 10), padx=6, pady=4, bg=C_FIELD,
                       fg=C_TEXT, insertbackground=C_ACCENT, selectbackground=C_ACCENT, selectforeground=C_ON_ACCENT,
                       undo=True, highlightthickness=0)
        note.pack(fill="x")
        note.insert("1.0", old.get("note", ""))
        r += 1
        tk.Frame(body, bg=C_BORDER, height=1).grid(row=r, column=0, columnspan=3, sticky="we", pady=(10, 6))
        r += 1
        tk.Label(body, text="ĐÍCH ĐẾN", bg=C_CARD, fg=C_ACCENT, font=(FONT, 9, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w")
        r += 1
        label("Đích 1 · My PikPak *", r, "Save trước tiên (trên máy chủ)")
        e_pk = ttk.Entry(body, textvariable=v["pikpak_dir"], width=62)
        e_pk.grid(row=r, column=1, sticky="we", pady=6)
        ttk.Button(body, text="Chọn...", style="Small.TButton", command=pick_pk).grid(row=r, column=2,
                                                                                     padx=(8, 0), sticky="w")
        r += 1
        label("Đích 2 · HDD *", r, "Tải từ My PikPak về PC")
        e_hdd = ttk.Entry(body, textvariable=v["local_dir"], width=62)
        e_hdd.grid(row=r, column=1, sticky="we", pady=6)
        ttk.Button(body, text="Chọn...", style="Small.TButton",
                   command=lambda: pick_dir("local_dir", "Chọn thư mục lưu trên HDD")).grid(row=r, column=2,
                                                                                          padx=(8, 0), sticky="w")
        r += 1
        tk.Label(body, text="Link chia sẻ  →  ① Save vào My PikPak  →  ② rclone tải từ My PikPak về HDD",
                 bg=C_CARD, fg=C_MUTED, font=(FONT, 8)).grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        ttk.Checkbutton(body, text="Tạo thư mục con theo tên phim ở đích (VD  ...\\Tiên Nghịch\\  ·  My Pack/2026/Tiên Nghịch/)",
                        variable=sub_movie).grid(row=r, column=1, columnspan=2, sticky="w", pady=(2, 0))
        r += 1
        preview = tk.StringVar()
        tk.Label(body, textvariable=preview, bg=C_PANEL, fg=C_GREEN, font=(MONO, 9), anchor="w", justify="left",
                 padx=10, pady=6).grid(row=r, column=1, columnspan=2, sticky="we", pady=(6, 0))
        r += 1

        def upd(*_):
            e_hdd.config(state="normal" if use_hdd.get() else "disabled")
            e_pk.config(state="normal" if use_pk.get() else "disabled")
            mv = "<Tên phim>"
            lines = []
            if use_hdd.get() and v["local_dir"].get().strip():
                lines.append("HDD      › " + os.path.join(v["local_dir"].get().strip(), mv if sub_movie.get() else "")
                             .rstrip("\\/") + os.sep)
            if use_pk.get() and v["pikpak_dir"].get().strip():
                lines.append("PIKPAK   › " + pikpak_join(v["pikpak_dir"].get(), mv if sub_movie.get() else "") + "/")
            lines.sort(key=lambda x: 0 if x.startswith("PIKPAK") else 1)
            lines = [("① " if x.startswith("PIKPAK") else "② ") + x for x in lines]
            if not v["pikpak_dir"].get().strip():
                lines.append("⚠ Chưa chọn thư mục My PikPak (Đích 1, bắt buộc)")
            if not v["local_dir"].get().strip():
                lines.append("⚠ Chưa chọn thư mục HDD (Đích 2, bắt buộc)")
            preview.set("\n".join(lines))
        for var in (use_hdd, use_pk, sub_movie, v["local_dir"], v["pikpak_dir"]):
            var.trace_add("write", upd)
        upd()

        # ----- nâng cao (gập)
        adv_open = tk.BooleanVar(value=bool(old.get("include") or old.get("exclude") or
                                            old.get("split", "folder") != "folder"))
        adv_btn = tk.Label(body, text="", bg=C_CARD, fg=C_MUTED, font=(FONT, 9, "bold"), cursor="hand2")
        adv_btn.grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 0))
        r += 1
        adv = tk.Frame(body, bg=C_CARD)
        adv.grid(row=r, column=0, columnspan=3, sticky="we")
        adv.columnconfigure(1, weight=1)
        r += 1
        split = tk.StringVar(value=SPLIT_CHOICES.get(old.get("split", "folder"), SPLIT_CHOICES["folder"]))
        rows = (("Tách tên phim", ttk.Combobox(adv, textvariable=split, values=tuple(SPLIT_CHOICES.values()),
                                               state="readonly", width=50)),
                ("Chỉ lấy file có", ttk.Entry(adv, textvariable=v["include"], width=62)),
                ("Bỏ qua file có", ttk.Entry(adv, textvariable=v["exclude"], width=62)))
        for i, (t, w) in enumerate(rows):
            tk.Label(adv, text=t, bg=C_CARD, fg=C_TEXT, font=(FONT, 10)).grid(row=i, column=0, sticky="w",
                                                                              pady=5, padx=(0, 14))
            w.grid(row=i, column=1, sticky="we" if isinstance(w, ttk.Entry) else "w", pady=5)
        tk.Label(adv, text="Từ khóa cách nhau dấu phẩy, không phân biệt dấu / hoa thường.", bg=C_CARD, fg=C_MUTED,
                 font=(FONT, 8)).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(adv, text="Quét thư mục này", variable=en).grid(row=4, column=1, sticky="w", pady=(6, 0))

        def toggle_adv(_e=None, flip=True):
            if flip:
                adv_open.set(not adv_open.get())
            adv_btn.config(text=("▾" if adv_open.get() else "▸") + "  NÂNG CAO  (tách tên phim · lọc từ khóa)")
            if adv_open.get():
                adv.grid()
            else:
                adv.grid_remove()
        adv_btn.bind("<Button-1>", toggle_adv)
        toggle_adv(flip=False)

        def save(_e=None):
            src = clean_src(self.cfg, v["url"].get())
            if not src or not is_share(src):
                messagebox.showwarning(APP_NAME, "Nguồn phải là thư mục trong link chia sẻ PikPak - bấm \"Chọn trong "
                                                 "link chia sẻ...\" (hoặc dán link https://mypikpak.com/s/...).",
                                       parent=win)
                return
            hdd = v["local_dir"].get().strip()
            pk = pikpak_join(v["pikpak_dir"].get())
            if not pk:
                messagebox.showwarning(APP_NAME, "Chọn thư mục My PikPak để Save vào (Đích 1, bắt buộc).", parent=win)
                return
            if not hdd:
                messagebox.showwarning(APP_NAME, "Chọn thư mục lưu trên HDD (Đích 2, bắt buộc).", parent=win)
                return
            key = src_key(self.cfg, src)
            for j, f in enumerate(self.cfg["folders"]):
                if j != index and src_key(self.cfg, f.get("url", "")) == key:
                    messagebox.showwarning(APP_NAME, f"Thư mục này đã có trong danh sách (dòng {j + 1}).", parent=win)
                    return
            same = old and src_key(self.cfg, old.get("url", "")) == key
            rec = dict(old) if same else {"id": old.get("id") or new_folder_id()}
            if not v["name"].get().strip() and not is_share(src):
                v["name"].set(os.path.basename(os.path.normpath(resolve_src(self.cfg, src))))
            rec.update({"name": v["name"].get().strip(), "url": src, "note": note.get("1.0", "end-1c").strip(),
                        "include": v["include"].get().strip(), "exclude": v["exclude"].get().strip(),
                        "local_dir": to_portable(hdd), "pikpak_dir": pk, "sub_movie": sub_movie.get(),
                        "split": next((k for k, t in SPLIT_CHOICES.items() if t == split.get()), "auto"),
                        "enabled": en.get(), "dest_rev": 3, "src_label": src_label.get().strip()})
            if hdd:
                self.cfg["library_root"] = to_portable(hdd)       # nhớ làm mặc định cho thư mục mới
            if pk:
                self.cfg["pikpak_root"] = pk
            if index is None:
                self.cfg["folders"].append(rec)
            else:
                self.cfg["folders"][index] = rec
            self.save_config(); self.refresh_folders()
            win.destroy()

        bb = tk.Frame(body, bg=C_CARD)
        bb.grid(row=r, column=0, columnspan=3, sticky="e", pady=(18, 0))
        if old.get("url"):
            ttk.Button(bb, text="↗  Mở nguồn", command=lambda: open_target(source_link(self.cfg, old))).pack(
                side="left", padx=(0, 8))
        ttk.Button(bb, text="Hủy", command=win.destroy).pack(side="left")
        ttk.Button(bb, text="✓  Lưu", style="Accent.TButton", command=save).pack(side="left", padx=(8, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Control-s>", save)
        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_reqwidth()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win.winfo_reqheight()) // 3)
        win.geometry(f"+{x}+{y}")
        win.grab_set()
        first.focus_set()

    def folder_export(self):
        p = filedialog.asksaveasfilename(title="Xuất danh sách thư mục", defaultextension=".json",
                                         initialfile=f"PikPakFolders_{dt.date.today():%Y%m%d}.json",
                                         filetypes=[("JSON", "*.json")])
        if p:
            save_json(p, {"app": APP_NAME, "exported": dt.datetime.now().isoformat(timespec="seconds"),
                          "folders": self.cfg["folders"]})
            messagebox.showinfo(APP_NAME, f"Đã xuất {len(self.cfg['folders'])} thư mục.")

    def folder_import(self):
        p = filedialog.askopenfilename(title="Nhập danh sách thư mục", filetypes=[("JSON", "*.json")])
        if not p:
            return
        data = load_json(p, {})
        items = data.get("folders") if isinstance(data, dict) else data
        if not isinstance(items, list):
            messagebox.showwarning(APP_NAME, "File không đúng định dạng.")
            return
        have = {src_key(self.cfg, f.get("url", "")) for f in self.cfg["folders"]}
        added = 0
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
        self.save_config(); self.refresh_folders()
        messagebox.showinfo(APP_NAME, f"Đã thêm {added} thư mục, bỏ qua {len(items) - added} thư mục đã có.")

    def folder_bulk(self):
        win = tk.Toplevel(self)
        win.title("Dán nhiều nguồn")
        win.geometry("720x420")
        win.configure(bg=C_CARD)
        win.transient(self)
        ttk.Label(win, text="Mỗi dòng 1 nguồn (link chia sẻ PikPak, có thể kèm mã thư mục con). "
                            "Có thể ghi tên trước:   Tên phim | P:\\Shared\\Doraemon",
                  style="Muted.TLabel").pack(anchor="w", padx=12, pady=(12, 6))
        fr = tk.Frame(win, bg=C_BORDER, padx=1, pady=1)
        fr.pack(fill="both", expand=True, padx=12)
        txt = tk.Text(fr, wrap="none", relief="flat", font=(MONO, 10), padx=8, pady=6, bg=C_FIELD, fg=C_TEXT,
                      insertbackground=C_ACCENT)
        txt.pack(fill="both", expand=True)

        def ok():
            added = 0
            for line in txt.get("1.0", "end").splitlines():
                line = line.strip()
                if not line:
                    continue
                name, url = ("", line)
                if "|" in line:
                    name, url = [x.strip() for x in line.split("|", 1)]
                added += self._add_folder(name, url)
            self.save_config(); self.refresh_folders()
            messagebox.showinfo(APP_NAME, f"Đã thêm {added} thư mục.", parent=win)
            win.destroy()
        ttk.Button(win, text="＋  Thêm", style="Accent.TButton", command=ok).pack(pady=10)

    def _build_settings(self):
        f = self.tab_settings
        self.rd_var = tk.StringVar(value=from_portable(self.cfg.get("raidrive_root", "")))
        self.rdbase_var = tk.StringVar(value=self.cfg.get("rd_remote_base", ""))
        self.method_var = tk.StringVar(value=DL_METHODS.get(self.cfg.get("dl_method", "auto"), DL_METHODS["auto"]))
        self.delay_var = tk.IntVar(value=int(self.cfg.get("delay", 2)))
        self.ext_var = tk.StringVar(value=self.cfg.get("extensions", ""))
        self.bw_var = tk.StringVar(value=str(self.cfg.get("bwlimit", "") or ""))
        self.rdauto_var = tk.BooleanVar(value=bool(self.cfg.get("rd_autostart", True)))
        self.rdtray_var = tk.BooleanVar(value=bool(self.cfg.get("rd_to_tray", True)))
        self.rdexe_var = tk.StringVar(value=self.cfg.get("raidrive_exe", "") or "")
        self.share_root_var = tk.StringVar(value=self.cfg.get("share_root", "") or "")
        self.iphone_on_var = tk.BooleanVar(value=bool(self.cfg.get("iphone_on", True)))
        self.iphone_dir_var = tk.StringVar(value=resolve_iphone_dir(self.cfg.get("iphone_dir")))
        self.thr_var = tk.IntVar(value=int(self.cfg.get("copy_threads", 4) or 4))
        self.rdmin_var = tk.IntVar(value=int(self.cfg.get("rd_check_min", 2) or 0))
        self.map_status = tk.StringVar(value="")
        self.notify_var = tk.BooleanVar(value=bool(self.cfg.get("notify", True)))
        self.tray_var = tk.BooleanVar(value=bool(self.cfg.get("tray_on_close", True)))
        self.startwin_var = tk.BooleanVar(value=bool(self.cfg.get("start_with_windows", False)))
        self.startscan_var = tk.BooleanVar(value=bool(self.cfg.get("startup_scan", True)))
        self.health_var = tk.BooleanVar(value=bool(self.cfg.get("health_check", True)))
        self.stale_var = tk.IntVar(value=int(self.cfg.get("stale_days", 7) or 0))
        self.pk_root_var = tk.StringVar(value=self.cfg.get("pikpak_root", ""))
        self.backup_on_var = tk.BooleanVar(value=bool(self.cfg.get("backup_on", True)))
        self.pk_status = tk.StringVar(value="")
        self.bk_status = tk.StringVar(value=("Lần sao lưu gần nhất: " + self.cfg["last_backup"])
                                      if self.cfg.get("last_backup") else "Chưa sao lưu lần nào.")

        # ----- thanh chọn mục
        top = ttk.Frame(f, style="Card.TFrame")
        top.pack(fill="x")
        seg = tk.Frame(top, bg=C_PANEL, padx=3, pady=3)
        seg.pack(side="left")
        self._set_tabs = {}
        body = ttk.Frame(f, style="Card.TFrame")
        body.pack(fill="both", expand=True, pady=(12, 0))
        self._set_pages = {}
        for key, text in (("gen", "⚙  Chung"), ("pikpak", "☁  My PikPak"),
                          ("rclone", "⇄  rclone"), ("machine", "⌂  Máy này & Sao lưu")):
            lb = tk.Label(seg, text=text, bg=C_PANEL, fg=C_MUTED, font=(FONT, 10, "bold"), padx=14, pady=6,
                          cursor="hand2")
            lb.pack(side="left", padx=1)
            lb.bind("<Button-1>", lambda e, k=key: self._settings_page(k))
            self._set_tabs[key] = lb
            pg = ttk.Frame(body, style="Card.TFrame")
            self._set_pages[key] = pg

        app = self

        class G:
            def __init__(self, parent):
                self.p, self.r = parent, 0
                parent.columnconfigure(1, weight=1)

            def section(self, text, sub=None):
                hd = tk.Frame(self.p, bg=C_CARD)
                hd.grid(row=self.r, column=0, columnspan=3, sticky="we", pady=(18 if self.r else 0, 4))
                tk.Frame(hd, bg=C_ACCENT, width=3, height=14).pack(side="left", padx=(0, 8))
                tk.Label(hd, text=text.upper(), bg=C_CARD, fg=C_ACCENT, font=(FONT, 9, "bold")).pack(side="left")
                tk.Frame(hd, bg=C_BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(10, 0))
                self.r += 1
                if sub:
                    ttk.Label(self.p, text=sub, style="Muted.TLabel", wraplength=820, justify="left").grid(
                        row=self.r, column=0, columnspan=3, sticky="w", pady=(0, 6))
                    self.r += 1

            def entry(self, label, var, browse=None, hint=None, show=None, width=None, btn="Chọn..."):
                ttk.Label(self.p, text=label).grid(row=self.r, column=0, sticky="w", pady=5, padx=(0, 12))
                ttk.Entry(self.p, textvariable=var, show=show or "", width=width or 0).grid(
                    row=self.r, column=1, sticky="w" if width else "we")
                if browse:
                    ttk.Button(self.p, text=btn, command=browse).grid(row=self.r, column=2, padx=(8, 0))
                self.r += 1
                if hint:
                    self.hint(hint)

            def spin(self, label, var, lo, hi):
                ttk.Label(self.p, text=label).grid(row=self.r, column=0, sticky="w", pady=5, padx=(0, 12))
                ttk.Spinbox(self.p, from_=lo, to=hi, width=7, textvariable=var).grid(row=self.r, column=1, sticky="w")
                self.r += 1

            def check(self, text, var, state="normal"):
                ttk.Checkbutton(self.p, text=text, variable=var, state=state).grid(
                    row=self.r, column=0, columnspan=3, sticky="w", pady=4)
                self.r += 1

            def combo(self, label, var, values, width=40):
                ttk.Label(self.p, text=label).grid(row=self.r, column=0, sticky="w", pady=5, padx=(0, 12))
                ttk.Combobox(self.p, textvariable=var, state="readonly", width=width, values=values).grid(
                    row=self.r, column=1, sticky="w")
                self.r += 1

            def hint(self, text):
                ttk.Label(self.p, text=text, style="Muted.TLabel", wraplength=820, justify="left").grid(
                    row=self.r, column=1, columnspan=2, sticky="w", pady=(0, 4))
                self.r += 1

            def frame(self):
                fr = ttk.Frame(self.p, style="Card.TFrame")
                fr.grid(row=self.r, column=0, columnspan=3, sticky="w", pady=(6, 0))
                self.r += 1
                return fr

            def label(self, var, **kw):
                ttk.Label(self.p, textvariable=var, wraplength=820, justify="left", **kw).grid(
                    row=self.r, column=0, columnspan=3, sticky="w", pady=(4, 0))
                self.r += 1

            def readout(self, rows):
                """Bảng đồng hồ: đèn + các dòng 'NHÃN  giá trị' font màn hình. Trả về (đèn, {khóa: StringVar})."""
                box = tk.Frame(self.p, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=1)
                box.grid(row=self.r, column=0, columnspan=3, sticky="we", pady=(4, 6))
                self.r += 1
                led = tk.Label(box, text="●", bg=C_PANEL, fg=C_MUTED, font=(FONT, 26))
                led.grid(row=0, column=0, rowspan=max(1, len(rows)), sticky="n", padx=(14, 10), pady=8)
                vals = {}
                for i, (k, t) in enumerate(rows):
                    tk.Label(box, text=t.upper(), bg=C_PANEL, fg=C_MUTED, font=(FONT, 8, "bold"), anchor="w",
                             width=18).grid(row=i, column=1, sticky="w", pady=(8 if i == 0 else 1, 1))
                    vals[k] = tk.StringVar(value="—")
                    tk.Label(box, textvariable=vals[k], bg=C_PANEL, fg=C_TEXT, font=(MONO, 10), anchor="w",
                             justify="left", wraplength=640).grid(row=i, column=2, sticky="w", padx=(0, 14),
                                                                  pady=(8 if i == 0 else 1, 1))
                box.grid_rowconfigure(len(rows), minsize=8)
                return led, vals

        # ----- 1. Chung
        g = G(self._set_pages["gen"])
        g.section("Giao diện", "⭐ Đặt mặc định: tool mở bằng giao diện đó (đổi xong tự khởi động lại).  🗑 Xóa: bỏ "
                               "giao diện (khôi phục lại được). Giao diện 1 (gốc v1.3) không xóa được. Giao diện 3 giống "
                               "giao diện 2 nhưng thanh tải là dải liền, trạng thái hiện thành nhãn có viền màu.")
        self._theme_box = g.frame()
        self._fill_theme_box(self._theme_box)
        g.section("Mật khẩu admin", "Tab Thư mục phim và Cài đặt cần mật khẩu admin mới mở được (tránh bấm nhầm). "
                                    "Quên mật khẩu: tắt tool, mở Data\\config.json xóa 2 dòng \"admin_hash\" và "
                                    "\"admin_salt\" rồi mở lại tool để tạo mật khẩu mới.")
        fr = g.frame()
        ttk.Button(fr, text="🔑  Đổi mật khẩu admin", command=self.admin_change_pw).pack(side="left")
        ttk.Button(fr, text="🔒  Khóa ngay", command=self.admin_lock).pack(side="left", padx=8)
        ttk.Label(fr, text="Tự khóa sau", style="Muted.TLabel").pack(side="left", padx=(16, 4))
        lock_var = tk.StringVar(value=str(self.cfg.get("admin_lock_min", 10)))
        cb = ttk.Combobox(fr, textvariable=lock_var, values=("0", "5", "10", "15", "30", "60"), width=4,
                          state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: (self.cfg.__setitem__("admin_lock_min", int(lock_var.get())),
                                                   self.save_config()))
        ttk.Label(fr, text="phút không thao tác  (0 = không tự khóa)", style="Muted.TLabel").pack(side="left", padx=4)
        g.section("Tự động")
        fr = g.frame()
        ttk.Checkbutton(fr, text="Tự quét & tải mỗi", variable=self.auto_var, command=self._auto_changed).pack(side="left")
        cb = ttk.Combobox(fr, textvariable=self.interval_var, values=INTERVAL_CHOICES, width=4, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._auto_changed())
        ttk.Label(fr, text="phút  (tool phải đang mở hoặc chạy dưới khay)").pack(side="left")
        g.check("Khởi động cùng Windows (chạy ẩn dưới khay)", self.startwin_var)
        g.check("Quét & tải ngay sau khi khởi động (chờ 1 phút cho có mạng)", self.startscan_var)
        tray_state = "normal" if TRAY_OK else "disabled"
        g.check("Bấm X thì thu nhỏ xuống khay hệ thống (góc đồng hồ)", self.tray_var, tray_state)
        g.check("Thông báo Windows khi có file mới / tải xong / lỗi", self.notify_var, tray_state)
        g.section("Cách tải", "1) Đích 1 - Save: tập mới trong link chia sẻ được lưu vào My PikPak của bạn (sao chép "
                              "trên máy chủ PikPak, nhanh, không tốn mạng).  2) Đích 2 - HDD: rclone (tài khoản của "
                              "bạn) tải tập đó từ My PikPak về thư mục HDD (đa luồng).  Đích đặt riêng cho từng thư mục "
                              "phim ở tab Thư mục phim.")
        g.entry("Link chia sẻ gốc", self.share_root_var, lambda: open_target(self.share_root_var.get().strip()), btn="↗ Mở",
                hint="Link thư mục PikPak được chia sẻ cho bạn. Khi thêm thư mục phim, bấm \"Chọn trong link chia "
                     "sẻ...\" để chọn thư mục con từ link này. Có mật khẩu: thêm ?pwd=xxxx vào cuối link.")
        g.check("Copy thêm 1 bản vào thư mục COPY_TO_IPHONE (mọi phim chung 1 thư mục)", self.iphone_on_var)
        fr_ip = g.frame()
        ttk.Button(fr_ip, text="📱  Copy các tập đã tải gần đây vào COPY_TO_IPHONE...",
                   command=self.iphone_catch_up).pack(side="left")
        ttk.Button(fr_ip, text="↗  Mở thư mục", command=lambda: (
            os.makedirs(resolve_iphone_dir(self.iphone_dir_var.get()), exist_ok=True),
            open_target(resolve_iphone_dir(self.iphone_dir_var.get())))).pack(side="left", padx=8)
        g.entry("Thư mục COPY_TO_IPHONE", self.iphone_dir_var, self._browse_iphone,
                hint="Mỗi tập tải về HDD xong được copy thêm 1 bản vào đây (không chia thư mục con) để chép sang "
                     "iPhone. File ở đây bạn tự xóa sau khi chép - tool không tải lại.")
        g.entry("Giới hạn tốc độ upload", self.bw_var, width=12,
                hint="VD 20M = 20 MB/s, 500K = 500 KB/s. Để trống = không giới hạn (áp dụng cho rclone upload My PikPak).")
        g.spin("Nghỉ giữa 2 file (giây)", self.delay_var, 0, 60)
        g.entry("Đuôi file cần tải", self.ext_var, hint="Cách nhau bằng dấu cách; để trống = mọi loại file")
        g.section("Kiểm tra & cảnh báo", "Chạy im lặng, chỉ báo khi có vấn đề.")
        g.check("Kiểm tra trước khi tải: rclone + đăng nhập PikPak, ổ đích HDD đã cắm, còn đủ chỗ trống",
                self.health_var)
        g.spin("Nhắc khi thư mục không có tập mới sau (ngày, 0 = tắt)", self.stale_var, 0, 90)
        g.hint("Tự báo \"có thể thiếu tập\" khi số tập bị nhảy và báo file tải về bị thiếu dung lượng (tự tải lại).")

        # ----- 2. My PikPak
        g = G(self._set_pages["pikpak"])
        g.section("Trạng thái kết nối")
        self.pk_led, self.pk_vals = g.readout((("state", "Kết nối"), ("user", "Tài khoản đang dùng"),
                                               ("quota", "Dung lượng"), ("rclone", "rclone"),
                                               ("checked", "Kiểm tra lúc")))
        fr = g.frame()
        ttk.Button(fr, text="⟳  Kiểm tra kết nối", style="Accent.TButton",
                   command=lambda: self.check_pikpak(silent=False, detail=True)).pack(side="left")
        ttk.Button(fr, text="⚙  Đổi tài khoản PikPak...", command=self.open_pikpak_login).pack(side="left", padx=8)
        self.rclone_dl_btn = ttk.Button(fr, text="⬇  Tải rclone.exe về thư mục tool", command=self.get_rclone)
        self.rclone_status = tk.StringVar()
        g.label(self.rclone_status, style="Muted.TLabel")
        g.section("Mặc định cho thư mục mới", "Thư mục My PikPak điền sẵn khi thêm thư mục phim mới "
                                              "(mỗi thư mục phim vẫn đổi riêng được).")
        g.entry("Thư mục lưu My PikPak", self.pk_root_var, lambda: self.open_pikpak_browser())
        self._refresh_rclone_status()

        # ----- 4. rclone
        g = G(self._set_pages["rclone"])
        g.section("Trạng thái rclone", "rclone dùng để lưu phim vào My PikPak (sao chép trên máy chủ, nhanh) và tải "
                                       "Không có rclone.exe thì tool tự tải về.")
        self.rc_led, self.rc_vals = g.readout((("state", "Trạng thái"), ("ver", "Phiên bản"), ("path", "File"),
                                               ("conf", "Cấu hình"), ("checked", "Kiểm tra lúc")))
        fr = g.frame()
        ttk.Button(fr, text="⟳  Kiểm tra rclone", style="Accent.TButton",
                   command=self.check_rclone).pack(side="left")
        ttk.Button(fr, text="⬇  Tải lại / cập nhật rclone mới nhất",
                   command=lambda: self.check_rclone(update=True)).pack(side="left", padx=8)
        ttk.Button(fr, text="▸  Mở thư mục tool", command=lambda: open_target(str(BASE))).pack(side="left")

        # ----- 5. Máy này & Sao lưu
        g = G(self._set_pages["machine"])
        g.section(f"Máy này: {MACHINE}",
                  "Tool để trên ổ di động, cắm vào nhiều máy: mỗi máy tự nhớ đường dẫn riêng (thư mục HDD...). "
                  "Đường dẫn nằm trên chính ổ di động được lưu không phụ thuộc ký tự ổ.")
        pw = ttk.Frame(self._set_pages["machine"], style="Card.TFrame")
        pw.grid(row=g.r, column=0, columnspan=3, sticky="we")
        g.r += 1
        wrap, self.prof_tree = self._tree(pw, ("name", "updated", "paths"), ("MÁY", "CẬP NHẬT", "ĐƯỜNG DẪN"),
                                          (160, 130, 460), height=4, stretch=("paths",))
        wrap.pack(fill="x")
        fr = g.frame()
        ttk.Button(fr, text="⧉  Chép thiết lập từ máy đã chọn", command=self.copy_profile_selected).pack(side="left")
        ttk.Button(fr, text="✕  Xóa hồ sơ máy đã chọn", style="Danger.TButton",
                   command=self.delete_profile_selected).pack(side="left", padx=8)
        g.section("Sao lưu dữ liệu", "Phòng khi ổ cứng hỏng: config.json (thư mục, cài đặt), owned.json (Danh sách "
                                      f"đã có), history.json (lịch sử) được nén và đưa lên My PikPak/{BACKUP_DIR}/.")
        g.check("Sau mỗi lần tải xong, tự sao lưu dữ liệu lên PikPak", self.backup_on_var)
        fr = g.frame()
        ttk.Button(fr, text="☁  Sao lưu lên PikPak ngay", style="Accent.TButton", command=self.backup_now).pack(side="left")
        ttk.Button(fr, text="⟲  Khôi phục từ PikPak...", command=self.restore_from_pikpak).pack(side="left", padx=8)
        ttk.Button(fr, text="⇩  Sao lưu ra file...", command=self.backup_to_file).pack(side="left")
        ttk.Button(fr, text="⇧  Khôi phục từ file...", command=self.restore_from_file).pack(side="left", padx=8)
        g.label(self.bk_status, style="Muted.TLabel")
        g.section("Thư mục Data", "Mọi dữ liệu (cấu hình, Danh sách đã có, lịch sử, đăng nhập PikPak, nhật ký) nằm trong "
                                  "thư mục Data cạnh tool. Lên bản mới: chép thư mục Data của bản cũ sang là xong.")
        fr = g.frame()
        ttk.Button(fr, text="▸  Mở thư mục Data", command=self.open_data_dir).pack(side="left")
        ttk.Label(fr, text=str(DATA_DIR), style="Muted.TLabel").pack(side="left", padx=10)
        self.refresh_profiles()

        # ----- thanh lưu
        bottom = tk.Frame(f, bg=C_SOFT, highlightbackground=C_SOFT_BORDER, highlightthickness=1)
        bottom.pack(fill="x", side="bottom", pady=(10, 0))
        bi = tk.Frame(bottom, bg=C_SOFT, padx=10, pady=8)
        bi.pack(fill="x")
        ttk.Button(bi, text="✓  Lưu cài đặt", style="Success.TButton",
                   command=lambda: (self.save_config(), self.refresh_profiles(),
                                    self.status_var.set("✔ Đã lưu cài đặt cho máy " + MACHINE))).pack(side="left")
        ttk.Button(bi, text="◉  Thử thông báo",
                   command=lambda: (self.save_config(), self.notify(APP_TITLE, "Thông báo hoạt động bình thường."))
                   ).pack(side="left", padx=8)
        self._settings_page("gen")

    def _settings_page(self, key):
        for k, pg in self._set_pages.items():
            pg.pack_forget()
            on = k == key
            self._set_tabs[k].config(bg=C_CARD if on else C_PANEL, fg=C_ACCENT if on else C_MUTED)
        self._set_pages[key].pack(fill="both", expand=True)
        if key == "rclone":
            self.check_rclone()
        elif key == "pikpak" and not getattr(self, "_pk_detail_done", False):
            self.check_pikpak(silent=True, detail=True)


    # ================================================================ HỒ SƠ MÁY (ổ di động)
    def _apply_profile(self, prof):
        for k in MACHINE_KEYS:
            if k in prof:
                self.cfg[k] = from_portable(prof[k]) if k in PATH_KEYS else prof[k]

    def _init_machine_profile(self):
        """Áp dụng đường dẫn riêng của máy đang chạy. Trả về True nếu là máy mới (cần hỏi)."""
        profiles = self.cfg.setdefault("profiles", {})
        if MACHINE in profiles:
            self._apply_profile(profiles[MACHINE])
            return False
        if not profiles:
            return False               # máy đầu tiên: dùng luôn cấu hình hiện có
        # máy mới: lấy theo máy dùng gần nhất, rồi tự dò lại những đường dẫn không có trên máy này
        last = max(profiles.values(), key=lambda p: p.get("updated", 0))
        self._apply_profile(last)
        self._fix_missing_paths()
        return True

    def _fix_missing_paths(self):
        if not self.cfg.get("download_dir"):
            self.cfg["download_dir"] = default_download_dir()
        if self.cfg.get("raidrive_root") and not os.path.isdir(rd_root(self.cfg)):
            self.cfg["raidrive_root"] = ""
        if self.cfg.get("library_root") and not os.path.isdir(self.cfg["library_root"]):
            self.cfg["organize"] = False

    def _store_machine_profile(self):
        prof = {k: (to_portable(self.cfg.get(k, "")) if k in PATH_KEYS else self.cfg.get(k)) for k in MACHINE_KEYS}
        prof["updated"] = time.time()
        self.cfg.setdefault("profiles", {})[MACHINE] = prof

    def refresh_profiles(self):
        if not hasattr(self, "prof_tree"):
            return
        self.prof_tree.delete(*self.prof_tree.get_children())
        for i, (name, p) in enumerate(sorted(self.cfg.get("profiles", {}).items(),
                                             key=lambda kv: -kv[1].get("updated", 0))):
            when = dt.datetime.fromtimestamp(p.get("updated", 0)).strftime("%H:%M %d/%m/%Y") if p.get("updated") else ""
            paths = f"Ổ RaiDrive: {p.get('raidrive_root') or '-'}"
            tags = ["odd"] if i % 2 else []
            if name == MACHINE:
                tags.append("done")
            self.prof_tree.insert("", "end", iid=name, values=(name + ("  (máy này)" if name == MACHINE else ""),
                                                               when, paths), tags=tags)

    def copy_profile_selected(self):
        sel = self.prof_tree.selection()
        if not sel or sel[0] == MACHINE:
            messagebox.showinfo(APP_NAME, "Chọn 1 máy KHÁC trong danh sách để chép thiết lập.")
            return
        self._apply_profile(self.cfg["profiles"][sel[0]])
        self._fix_missing_paths()
        self._reload_setting_vars()
        self.save_config(); self.refresh_profiles()
        messagebox.showinfo(APP_NAME, f"Đã chép thiết lập từ máy \"{sel[0]}\". Kiểm tra lại các đường dẫn rồi bấm Lưu.")

    def delete_profile_selected(self):
        sel = self.prof_tree.selection()
        if not sel or sel[0] == MACHINE:
            messagebox.showinfo(APP_NAME, "Chọn 1 máy khác (không xóa được hồ sơ của máy đang dùng).")
            return
        if messagebox.askyesno(APP_NAME, f"Xóa hồ sơ máy \"{sel[0]}\"?"):
            self.cfg["profiles"].pop(sel[0], None)
            self.save_config(); self.refresh_profiles()

    def _reload_setting_vars(self):
        for var, key in ((self.rd_var, "raidrive_root"), (self.pk_root_var, "pikpak_root")):
            var.set(self.cfg.get(key, "") or "")
        self.startwin_var.set(bool(self.cfg.get("start_with_windows")))

    def _new_machine_dialog(self):
        others = [n for n in self.cfg.get("profiles", {}) if n != MACHINE]
        msg = (f"Đây là lần đầu tool chạy trên máy \"{MACHINE}\".\n\n"
               f"Tool đã chép thiết lập từ máy \"{others[0] if others else '?'}\" - kiểm tra lại ổ RaiDrive, "
               "thư mục tải về, thư mục phim HDD của máy này.\n\nMở Cài đặt để kiểm tra đường dẫn?")
        if messagebox.askyesno(APP_NAME + " - Máy mới", msg):
            self.select_page("settings")
            self._settings_page("machine")
        self.save_config(); self.refresh_profiles()

    # ================================================================ PIKPAK: tài khoản + kết nối
    def _set_pk_status(self, text, ok):
        self.pk_ok = ok
        color = C_SIDE_OK if ok is True else (C_SIDE_BAD if ok is False else C_SIDE_MUTED)
        try:
            self.side_pk.config(text=text, fg=color)
        except (AttributeError, tk.TclError):
            pass
        if hasattr(self, "pk_status"):
            self.pk_status.set(text)

    def check_pikpak(self, silent=True, detail=False):
        """Tự đăng nhập (từ tài khoản đã nhớ) và kiểm tra kết nối PikPak - chạy nền.
        detail=True: đọc thêm dung lượng, phiên bản rclone cho bảng trạng thái tab My PikPak."""
        self._set_pk_status("☁ PikPak: đang kết nối...", None)
        cfg = json.loads(json.dumps(self.cfg))
        if detail:
            self._pk_detail_done = True
            self._pk_panel(None, {"state": "đang kiểm tra...", "user": cfg.get("pikpak_user") or "(chưa có)"})

        def job():
            r = find_rclone(cfg.get("rclone_path", ""))
            if not r:
                self.q.put(("pkstatus", "☁ PikPak: chưa có rclone.exe - bấm vào đây để tải", False))
                if detail:
                    self.q.put(("call", lambda: self._pk_panel(False, {
                        "state": "✘ Chưa có rclone.exe", "rclone": "chưa có - bấm \"Tải rclone.exe\"",
                        "quota": "—", "checked": f"{dt.datetime.now():%H:%M:%S %d/%m}"}), (), {}, threading.Event()))
                return
            remote = cfg.get("pikpak_remote", "pikpak") or "pikpak"
            conf_ok = RCLONE_CONF.is_file() and f"[{remote}]" in RCLONE_CONF.read_text(encoding="utf-8", errors="ignore")
            if not conf_ok:
                # chuyển cấu hình cũ (rclone mặc định của Windows) vào thư mục tool nếu có
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                try:
                    out = subprocess.run([r, "config", "file"], capture_output=True, text=True, timeout=20,
                                         creationflags=flags).stdout
                    old = Path(out.strip().splitlines()[-1].strip()) if out.strip() else None
                    if old and old.is_file() and f"[{remote}]" in old.read_text(encoding="utf-8", errors="ignore"):
                        shutil.copy(old, RCLONE_CONF)
                        conf_ok = True
                except Exception:
                    pass
            user, pw = cfg.get("pikpak_user", ""), dec_secret(cfg.get("pikpak_pass", ""))
            user = user or rclone_conf_user(remote)
            if not conf_ok and user and pw:
                code, out, err = run_rclone(r, ["config", "create", remote, "pikpak", "user", user, "pass", pw,
                                                "--obscure", "--non-interactive"], 60)
                conf_ok = code == 0
            if not conf_ok:
                self.q.put(("pkstatus", "☁ PikPak: chưa đăng nhập (bấm để thiết lập)", None))
                return
            t0 = time.time()
            code, out, err = run_rclone(r, ["lsd", f"{remote}:"], 60)
            ms = int((time.time() - t0) * 1000)
            if code == 0:
                self.q.put(("pkstatus", "☁ PikPak: ✔ đã kết nối" + (f" ({user})" if user else ""), True))
            else:
                self.q.put(("pkstatus", "☁ PikPak: ⚠ lỗi kết nối - " + (err or out).strip()[-120:], False))
            if not silent:
                self.q.put(("log", "PikPak: " + ("kết nối OK" if code == 0 else "lỗi kết nối")))
            if detail:
                info = {"checked": f"{dt.datetime.now():%H:%M:%S %d/%m}",
                        "state": (f"✔ Đã kết nối  ·  {ms} ms" if code == 0 else
                                  "✘ Lỗi: " + (err or out).strip()[-160:]),
                        "user": user or "(chưa lưu tài khoản)"}
                c2, o2, _e = run_rclone(r, ["version"], 30)
                info["rclone"] = (o2.splitlines()[0].strip() if c2 == 0 and o2.strip() else "?") + f"   ·   {r}"
                if code == 0:
                    c3, o3, e3 = run_rclone(r, ["about", f"{remote}:", "--json"], 60)
                    try:
                        j = json.loads(o3)
                        tot, used = int(j.get("total") or 0), int(j.get("used") or 0)
                        free = int(j.get("free") or max(0, tot - used))
                        pct = used * 100 // tot if tot else 0
                        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                        info["quota"] = (f"{bar} {pct}%   ·   đã dùng {human_size(used)} / {human_size(tot)}   ·   "
                                         f"trống {human_size(free)}") if tot else f"đã dùng {human_size(used)}"
                    except (ValueError, TypeError):
                        info["quota"] = "không đọc được"
                else:
                    info["quota"] = "—"
                ok = code == 0
                self.q.put(("call", lambda: self._pk_panel(ok, info), (), {}, threading.Event()))
        threading.Thread(target=job, daemon=True).start()

    def _pk_panel(self, ok, info):
        try:
            self.pk_led.config(fg=C_GREEN if ok else (C_RED if ok is False else C_ACCENT))
            for k, v in info.items():
                if k in self.pk_vals:
                    self.pk_vals[k].set(v)
        except (AttributeError, tk.TclError):
            pass

    # ================================================================ RAIDRIVE: trạng thái ổ
    def check_raidrive(self, silent=True):
        """Kiểm tra ổ RaiDrive (chạy nền): có ổ không, RaiDrive.exe có chạy, dung lượng, thời gian phản hồi."""
        if getattr(self, "_rd_busy", False):
            return
        self._rd_busy = True
        cfg = json.loads(json.dumps(self.cfg))
        if hasattr(self, "rd_var"):
            rd = self.rd_var.get().strip()
            cfg["raidrive_root"] = (rd[:2] + os.sep) if len(rd) == 2 and rd[1] == ":" else rd
        try:
            self.rd_vals["state"].set("đang kiểm tra...")
        except (AttributeError, tk.TclError):
            pass

        def job():
            root = rd_root(cfg)
            info = {"checked": f"{dt.datetime.now():%H:%M:%S %d/%m}"}
            app_on = raidrive_running()
            info["app"] = {True: "✔ đang chạy", False: "✘ không chạy - mở RaiDrive", None: "—"}[app_on]
            ok = False
            if not root:
                info.update(state="✘ Chưa đặt ổ RaiDrive", space="—", ping="—", root="—")
            elif not os.path.isdir(root):
                info.update(state=f"✘ Không thấy ổ {root} - RaiDrive chưa kết nối", space="—", ping="—", root="—")
            else:
                t0 = time.time()
                try:
                    names = [n for n in os.listdir(root) if not n.startswith((".", "$"))]
                    ms = int((time.time() - t0) * 1000)
                    ok = True
                    info["ping"] = f"{ms} ms" + ("   (chậm)" if ms > 3000 else "")
                    dirs = [n for n in names if os.path.isdir(os.path.join(root, n))]
                    info["root"] = f"{len(dirs)} thư mục, {len(names) - len(dirs)} file:  " + ", ".join(
                        sorted(dirs, key=natural_key)[:6]) + (" ..." if len(dirs) > 6 else "")
                    info["state"] = f"✔ Đã kết nối  ·  {root}"
                except OSError as e:
                    info.update(state=f"✘ Ổ {root} lỗi: {e}", ping="—", root="—")
                try:
                    du = shutil.disk_usage(root)
                    pct = du.used * 100 // du.total if du.total else 0
                    info["space"] = (f"{'█' * (pct // 5)}{'░' * (20 - pct // 5)} {pct}%   ·   đã dùng "
                                     f"{human_size(du.used)} / {human_size(du.total)}   ·   trống {human_size(du.free)}")
                except OSError:
                    info["space"] = "không đọc được"
            self.q.put(("call", lambda: self._rd_done(ok, info, silent), (), {}, threading.Event()))
        threading.Thread(target=job, daemon=True).start()

    def _rd_done(self, ok, info, silent):
        self._rd_busy = False
        prev = getattr(self, "rd_ok", None)
        self.rd_ok = ok
        try:
            self.rd_led.config(fg=C_GREEN if ok else C_RED)
            for k, v in info.items():
                if k in self.rd_vals:
                    self.rd_vals[k].set(v)
        except (AttributeError, tk.TclError):
            pass
        try:
            self.side_rd.config(text=("▣ RaiDrive: ✔ " + (rd_root(self.cfg) or "")) if ok else
                                ("▣ RaiDrive: ✘ " + info.get("state", "").lstrip("✘ ")),
                                fg=C_SIDE_OK if ok else C_SIDE_BAD)
        except (AttributeError, tk.TclError):
            pass
        if prev is True and ok is False:
            self.notify("⚠ Mất kết nối ổ RaiDrive", info.get("state", ""))
        if not silent:
            self.log("RaiDrive: " + info.get("state", ""))

    def _rd_tray(self, timeout=120, settle=25):
        """Chạy nền: thu cửa sổ RaiDrive xuống khay."""
        def job():
            try:
                if hide_raidrive_windows(timeout, settle, log=self.log):
                    self.log("▣ Đã thu nhỏ RaiDrive xuống khay hệ thống.")
            except Exception as e:
                self.log(f"⚠ Không thu nhỏ được RaiDrive xuống khay: {e}")
                self.report_error("Không thu nhỏ được RaiDrive", str(e), exc=e)
        threading.Thread(target=job, daemon=True).start()

    def ensure_raidrive(self, wait=90, startup=False):
        """Chạy nền: thư mục phim dùng ổ RaiDrive mà RaiDrive.exe chưa mở -> tự mở RaiDrive, chờ ổ kết nối."""
        cfg = self.cfg
        if not cfg.get("rd_autostart", True) or os.name != "nt":
            return False
        if not any(str(f.get("url", "")).startswith(RD_TOKEN) for f in cfg["folders"] if f.get("enabled", True)):
            return False
        root = rd_root(cfg)
        if raidrive_running() is not False:
            if startup and cfg.get("rd_to_tray", True):       # RaiDrive mở sẵn (VD khởi động cùng Windows)
                self._rd_tray(timeout=20, settle=8)
            return bool(root and os.path.isdir(root))
        exe = find_raidrive_exe(cfg.get("raidrive_exe", ""))
        if not exe:
            self.log("⚠ RaiDrive chưa mở và không tìm thấy RaiDrive.exe - chọn đường dẫn trong Cài đặt → RaiDrive.")
            return False
        try:
            flags = 0x00000008 | 0x00000200       # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([exe], cwd=os.path.dirname(exe), creationflags=flags, close_fds=True, env=clean_env())
        except OSError as e:
            if getattr(e, "winerror", 0) == 740:      # RaiDrive đòi quyền Admin -> mở qua Windows (hỏi UAC)
                try:
                    os.startfile(exe)
                except OSError as e2:
                    self.log(f"⚠ Không mở được RaiDrive ({exe}): {e2}")
                    return False
            else:
                self.log(f"⚠ Không mở được RaiDrive ({exe}): {e}")
                return False
        self.log("▣ RaiDrive chưa mở - đã tự mở RaiDrive, chờ ổ kết nối...")
        if cfg.get("rd_to_tray", True):
            self._rd_tray()
        self.q.put(("status", "Đang mở RaiDrive, chờ ổ kết nối..."))
        t0 = time.time()
        while time.time() - t0 < wait:
            if root and os.path.isdir(root):
                self.log(f"▣ Ổ RaiDrive {root} đã kết nối ({int(time.time() - t0)} giây).")
                self.q.put(("status", "RaiDrive đã kết nối."))
                break
            time.sleep(2)
        else:
            self.log(f"⚠ Đã mở RaiDrive nhưng sau {wait} giây chưa thấy ổ {root} - kiểm tra kết nối trong RaiDrive.")
        self.q.put(("call", lambda: self.check_raidrive(silent=True), (), {}, threading.Event()))
        return bool(root and os.path.isdir(root))

    def _browse_rd_exe(self):
        p = filedialog.askopenfilename(title="Chọn RaiDrive.exe", filetypes=[("RaiDrive", "RaiDrive.exe"),
                                                                              ("Chương trình", "*.exe")])
        if p:
            self.rdexe_var.set(os.path.normpath(p))

    def _rd_tick(self):
        mins = int(self.cfg.get("rd_check_min", 2) or 0)
        if mins and any(str(f.get("url", "")).startswith(RD_TOKEN) for f in self.cfg["folders"]):
            self.check_raidrive(silent=True)
        self.after(max(1, mins or 5) * 60000, self._rd_tick)

    # ================================================================ SAO LƯU / KHÔI PHỤC
    def _backup_remote(self):
        return f"{self.cfg.get('pikpak_remote', 'pikpak') or 'pikpak'}:" + pikpak_join(self.cfg.get("pikpak_root", ""),
                                                                                       BACKUP_DIR)

    def schedule_backup(self):
        if not self.cfg.get("backup_on", True) or self._backup_pending:
            return
        if not find_rclone(self.cfg.get("rclone_path", "")):
            return
        self._backup_pending = True
        self.after(20000, lambda: self.up_q.put("__backup__"))   # gom nhiều file tải xong thành 1 lần sao lưu

    def backup_now(self):
        if not self._need_rclone():
            return
        self.save_config()
        self.bk_status.set("Đang sao lưu lên PikPak...")
        self._backup_pending = True
        self.up_q.put("__backup__")

    def _do_backup(self):
        import tempfile
        try:
            r = find_rclone(self.cfg.get("rclone_path", ""))
            if not r:
                raise RuntimeError("chưa có rclone.exe")
            tmp = Path(tempfile.gettempdir()) / "PikPakShare_backup.zip"
            self.call_ui(lambda: save_json(CONFIG_FILE, self.cfg) if not self._no_save else None)
            make_backup_zip(tmp)
            dest = self._backup_remote()
            code, out, err = run_rclone(r, ["copyto", str(tmp), f"{dest}/PikPakShare_backup_latest.zip"], 300)
            if code != 0:
                raise RuntimeError((err or out).strip()[-150:])
            run_rclone(r, ["copyto", str(tmp), f"{dest}/PikPakShare_backup_{dt.date.today():%Y-%m-%d}.zip"], 300)
            self.q.put(("backup", True, dt.datetime.now().strftime("%H:%M %d/%m/%Y")))
        except Exception as e:
            self.q.put(("backup", False, str(e)))

    def _on_backup_done(self, ok, info):
        self._backup_pending = False
        if ok:
            self.cfg["last_backup"] = info
            save_json(CONFIG_FILE, self.cfg)
            self.side_bk.config(text="⟲ Sao lưu: " + info)
            self.bk_status.set(f"✔ Lần sao lưu gần nhất: {info}  →  {self._backup_remote()}")
            self.log(f"⟲ Đã sao lưu dữ liệu lên PikPak ({info}).")
        else:
            self.side_bk.config(text="⟲ Sao lưu lỗi")
            self.bk_status.set("⚠ Sao lưu lỗi: " + info)
            self.log("⚠ Sao lưu lên PikPak lỗi: " + info)

    def backup_to_file(self):
        self.save_config()
        p = filedialog.asksaveasfilename(title="Sao lưu dữ liệu", defaultextension=".zip",
                                         initialfile=f"PikPakShare_backup_{dt.date.today():%Y-%m-%d}.zip",
                                         filetypes=[("Zip", "*.zip")])
        if p:
            make_backup_zip(p)
            messagebox.showinfo(APP_NAME, "Đã sao lưu ra file:\n" + p)

    def restore_from_file(self):
        p = filedialog.askopenfilename(title="Chọn file sao lưu", filetypes=[("Zip", "*.zip")])
        if p:
            self._restore_zip(p)

    def restore_from_pikpak(self):
        r = self._need_rclone()
        if not r:
            return
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "PikPakShare_restore.zip"
        self.bk_status.set("Đang tải bản sao lưu từ PikPak...")
        self.update()
        code, out, err = run_rclone(r, ["copyto", f"{self._backup_remote()}/PikPakShare_backup_latest.zip",
                                        str(tmp)], 300)
        if code != 0 or not tmp.is_file():
            self.bk_status.set("⚠ Không tải được bản sao lưu: " + (err or out).strip()[-150:])
            return
        self._restore_zip(str(tmp))

    def open_data_dir(self):
        try:
            DATA_DIR.mkdir(exist_ok=True)
            if os.name == "nt":
                os.startfile(str(DATA_DIR))
            else:
                subprocess.Popen(["xdg-open", str(DATA_DIR)])
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Không mở được thư mục Data: {e}")

    # ================================================================ CẬP NHẬT PHẦN MỀM
    def check_update(self, silent=True):
        repo = (self.cfg.get("update_repo") or "").strip()
        if getattr(self, "_upd_busy", False):
            return
        if not repo:
            if not silent:
                self._update_menu()
            return
        self._upd_busy = True
        if not silent:
            self.status_var.set("Đang kiểm tra bản mới...")

        def job():
            try:
                tag, notes, url = github_latest(repo)
                self.q.put(("call", lambda: self._update_found(tag, notes, url, silent), (), {}, threading.Event()))
            except Exception as e:
                err = str(e)
                self.q.put(("call", lambda: self._update_error(err, silent), (), {}, threading.Event()))
            finally:
                self._upd_busy = False
        threading.Thread(target=job, daemon=True).start()

    def _update_error(self, err, silent):
        self.log(f"Kiểm tra cập nhật: {err}")
        if not silent:
            self.status_var.set("Không kiểm tra được bản mới.")
            self._update_menu(err)

    def _update_found(self, tag, notes, url, silent):
        newer = ver_tuple(tag) > ver_tuple(APP_VERSION)
        if newer:
            self.top_upd.config(text=f"⟳  Có bản {tag}", bg=C_ACCENT, fg=C_ON_ACCENT, highlightbackground=C_ACCENT)
            self.log(f"⟳ Có bản mới {tag} (đang dùng {APP_VERSION}).")
            self.notify("Có bản mới " + tag, "Bấm nút Cập nhật trên tool để cài.")
        if silent:
            return
        if not newer:
            self.status_var.set(f"Đang dùng bản mới nhất ({APP_VERSION}).")
            self._update_menu(f"Đang dùng bản mới nhất ({APP_VERSION.split(' by')[0]}). Bản trên GitHub: {tag}.")
            return
        msg = (f"Có bản mới {tag} (đang dùng {APP_VERSION.split(' by')[0]}).\n\n"
               + (notes.strip()[:900] + "\n\n" if notes.strip() else "")
               + "Tải về và cập nhật ngay? Thư mục Data (cấu hình, Danh sách đã có, lịch sử) được giữ nguyên.\n"
                 "Tool sẽ tự khởi động lại.")
        if url and messagebox.askyesno(APP_NAME + " - Cập nhật", msg):
            self._download_update(url, tag)

    def _update_menu(self, info=""):
        """Hộp thoại nhỏ: kiểm tra trên GitHub / cập nhật từ file zip."""
        win = tk.Toplevel(self)
        win.title("Cập nhật phần mềm")
        win.configure(bg=C_CARD)
        win.transient(self)
        win.resizable(False, False)
        b = ttk.Frame(win, style="Card.TFrame", padding=18)
        b.pack(fill="both", expand=True)
        ttk.Label(b, text="Cập nhật phần mềm", style="Section.TLabel").pack(anchor="w")
        ttk.Label(b, text=f"Đang dùng: {APP_VERSION}", style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        if info:
            ttk.Label(b, text=info, wraplength=460, justify="left").pack(anchor="w", pady=(0, 10))
        ttk.Label(b, text="Nguồn cập nhật (GitHub: tên-tài-khoản/tên-repo)", style="Muted.TLabel").pack(anchor="w")
        repo = tk.StringVar(value=self.cfg.get("update_repo", ""))
        ttk.Entry(b, textvariable=repo, width=50).pack(fill="x", pady=(2, 6))
        auto = tk.BooleanVar(value=bool(self.cfg.get("update_check", True)))
        ttk.Checkbutton(b, text="Tự kiểm tra bản mới mỗi lần mở tool", variable=auto).pack(anchor="w")

        def save():
            self.cfg["update_repo"] = repo.get().strip()
            self.cfg["update_check"] = auto.get()
            save_json(CONFIG_FILE, self.cfg)
        fr = ttk.Frame(b, style="Card.TFrame")
        fr.pack(fill="x", pady=(12, 0))
        ttk.Button(fr, text="⟳  Kiểm tra trên GitHub", style="Accent.TButton",
                   command=lambda: (save(), win.destroy(), self.check_update(silent=False))).pack(side="left")
        ttk.Button(fr, text="⇧  Cập nhật từ file zip...",
                   command=lambda: (save(), win.destroy(), self.update_from_file())).pack(side="left", padx=8)
        ttk.Label(b, text="Có file PikPak-Auto-Save_vX.Y.zip (VD: tải từ Claude) -> bấm \"Cập nhật từ file zip\". "
                          "Thư mục Data luôn được giữ nguyên.", style="Muted.TLabel", wraplength=460,
                  justify="left").pack(anchor="w", pady=(10, 0))
        win.bind("<Escape>", lambda e: win.destroy())

    def update_from_file(self):
        p = filedialog.askopenfilename(title="Chọn file cập nhật (PikPak-Auto-Save_vX.Y.zip)",
                                       filetypes=[("File zip", "*.zip")])
        if p:
            self._apply_update(p)

    def _download_update(self, url, tag):
        import tempfile
        dest = Path(tempfile.gettempdir()) / f"PikPak-Auto-Save_{tag}.zip"
        self.status_var.set(f"Đang tải bản {tag}...")

        def prog(pct, done):
            self.q.put(("status", f"Đang tải bản {tag}... " + (f"{pct}%" if pct >= 0 else human_size(done))))

        def job():
            try:
                download_file(url, dest, prog)
                self.q.put(("call", lambda: self._apply_update(str(dest), ask=False), (), {}, threading.Event()))
            except Exception as e:
                err = str(e)
                self.q.put(("call", lambda: messagebox.showerror(APP_NAME, f"Không tải được bản cập nhật: {err}"),
                            (), {}, threading.Event()))
        threading.Thread(target=job, daemon=True).start()

    def _apply_update(self, zip_path, ask=True):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(APP_NAME, "Tool đang quét / tải. Đợi xong rồi cập nhật.")
            return
        if ask and not messagebox.askyesno(APP_NAME, "Cập nhật tool từ file:\n" + zip_path +
                                           "\n\nThư mục Data được giữ nguyên. Bản cũ lưu ở thư mục _BanCu. "
                                           "Tool sẽ tự khởi động lại."):
            return
        try:
            self.save_config()
            new_ver, pending_exe = stage_update(zip_path)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Cập nhật không thành công: {e}")
            return
        self.log(f"⟳ Đã cập nhật lên {new_ver or 'bản mới'} - khởi động lại...")
        self._no_save = True
        self.save_history()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if pending_exe:       # bản exe: thay file exe sau khi tool thoát hẳn
            exe = Path(sys.executable)
            bat = BASE / "_capnhat.bat"
            waits = "".join(   # exe onefile có 2 tiến trình (khởi động + chính) -> chờ cả hai thoát
                f':w{n}\r\ntasklist /FI "PID eq {pid}" | find " {pid} " >nul && (ping -n 2 127.0.0.1 >nul & goto w{n})\r\n'
                for n, pid in enumerate({os.getpid(), os.getppid()}))
            bat.write_text(
                "@echo off\r\n" + waits +
                "ping -n 2 127.0.0.1 >nul\r\n"
                "set _r=0\r\n"
                f':mv\r\nmove /y "{pending_exe}" "{exe}" >nul 2>nul || (set /a _r+=1 & ping -n 2 127.0.0.1 >nul & '
                'if %_r% lss 15 goto mv)\r\n'
                f'start "" "{exe}" --after-update\r\n'
                'del "%~f0"\r\n', encoding="utf-8")
            subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, cwd=str(BASE), env=clean_env())
        else:
            restart_self(["--after-update"])
        self.quit_app(force=True)

    def _restore_zip(self, path):
        import zipfile
        try:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n in BACKUP_FILES]
                info = z.comment.decode("utf-8", "ignore")
                if not names:
                    raise ValueError("File không phải bản sao lưu của tool.")
                if not messagebox.askyesno(APP_NAME, f"Khôi phục dữ liệu từ bản sao lưu?\n\n{info}\n"
                                                     f"Gồm: {', '.join(names)}\n\nDữ liệu hiện tại sẽ được giữ lại "
                                                     "dạng *.bak. Tool sẽ tự khởi động lại."):
                    return
                for n in names:
                    if (DATA_DIR / n).is_file():
                        shutil.copy(DATA_DIR / n, DATA_DIR / (n + ".bak"))
                    z.extract(n, DATA_DIR)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Không khôi phục được: {e}")
            return
        self._no_save = True
        restart_self(["--after-update"])
        self.quit_app()

    # ================================================================ PIKPAK
    def _rclone(self):
        return find_rclone()

    def _refresh_rclone_status(self):
        if not hasattr(self, "rclone_status"):
            return
        have = bool(find_rclone())
        txt = (f"rclone.exe: ✔ có sẵn trong thư mục tool  ({RCLONE_EXE.parent})" if have else
               f"rclone.exe: ✘ chưa có trong thư mục tool  ({RCLONE_EXE.parent})")
        for var, btn in ((self.rclone_status, self.rclone_dl_btn),
                         (getattr(self, "rclone_status2", None), getattr(self, "rclone_dl_btn2", None))):
            if var is None:
                continue
            var.set(txt)
            if have:
                btn.pack_forget()
            else:
                btn.pack(side="left", padx=10)

    def _rclone_progress(self, pct):
        self.status_var.set(f"Đang tải rclone.exe... {pct}%")
        for b in (getattr(self, "rclone_dl_btn", None), getattr(self, "rclone_dl_btn2", None)):
            if b is not None:
                b.config(text=f"⬇  Đang tải rclone... {pct}%")
        try:
            self.side_pk.config(text=f"☁ Đang tải rclone.exe... {pct}%")
        except (AttributeError, tk.TclError):
            pass

    def _ask_rclone_first_run(self):
        """Mở tool mà chưa có rclone.exe -> TỰ tải về thư mục tool (không cần hỏi)."""
        if find_rclone() or getattr(self, "_rclone_dl", False):
            return
        self.log("Chưa có rclone.exe - đang tự tải về thư mục tool...")
        self.get_rclone(then=self.check_rclone)

    def check_rclone(self, update=False):
        """Kiểm tra rclone: có file không, phiên bản, cấu hình PikPak. Không có -> tự tải. update=True: tải bản mới."""
        if update or not find_rclone():
            if update and find_rclone():
                try:
                    os.replace(str(RCLONE_EXE), str(RCLONE_EXE) + ".old")
                except OSError:
                    pass
            self._rc_panel(None, {"state": "đang tải rclone.exe..."})
            self.get_rclone(then=self.check_rclone)
            return
        self._rc_panel(None, {"state": "đang kiểm tra..."})
        cfg = json.loads(json.dumps(self.cfg))

        def job():
            r = find_rclone()
            info = {"path": r, "checked": f"{dt.datetime.now():%H:%M:%S %d/%m}"}
            t0 = time.time()
            c, o, e = run_rclone(r, ["version"], 30)
            ok = c == 0
            info["ver"] = (o.splitlines()[0].strip() if o.strip() else "?") if ok else ("lỗi: " + (e or o).strip()[:120])
            remote = cfg.get("pikpak_remote", "pikpak") or "pikpak"
            has = RCLONE_CONF.is_file() and f"[{remote}]" in RCLONE_CONF.read_text(encoding="utf-8", errors="ignore")
            info["conf"] = f"{RCLONE_CONF}   ·   " + (f"✔ có kết nối [{remote}]" if has else
                                                   "✘ chưa có kết nối PikPak - nhập tài khoản ở tab My PikPak")
            try:
                old = Path(str(RCLONE_EXE) + ".old")
                if ok and old.is_file():
                    old.unlink()
            except OSError:
                pass
            info["state"] = (f"✔ Sẵn sàng  ·  {int((time.time() - t0) * 1000)} ms" if ok and has else
                             "⚠ rclone chạy được nhưng chưa có kết nối PikPak" if ok else "✘ rclone không chạy được")
            self.q.put(("call", lambda: self._rc_panel(ok and has if ok else False, info), (), {}, threading.Event()))
        threading.Thread(target=job, daemon=True).start()

    def _rc_panel(self, ok, info):
        try:
            self.rc_led.config(fg=C_GREEN if ok else (C_RED if ok is False else C_ACCENT))
            for k, v in info.items():
                if k in self.rc_vals:
                    self.rc_vals[k].set(v)
        except (AttributeError, tk.TclError):
            pass

    def get_rclone(self, then=None):
        """Tải rclone.exe về thư mục tool (chạy nền)."""
        if getattr(self, "_rclone_dl", False):
            return
        self._rclone_dl = True
        for b in (getattr(self, "rclone_dl_btn", None), getattr(self, "rclone_dl_btn2", None)):
            try:
                b.config(state="disabled")
            except (AttributeError, tk.TclError):
                pass

        def job():
            try:
                download_rclone(lambda pct: self.q.put(("call", lambda p=pct: self._rclone_progress(p), (), {},
                                                        threading.Event())))
                self.q.put(("call", lambda: (self.log("✔ Đã tải rclone.exe vào thư mục tool."),
                                             self.status_var.set("Đã tải rclone.exe."),
                                             self._refresh_rclone_status(), self.check_pikpak(silent=True),
                                             then and then()), (), {}, threading.Event()))
            except Exception as e:
                msg = f"Không tải được rclone.exe: {e}"
                self.q.put(("call", lambda: (self.log("⚠ " + msg), self.status_var.set(msg),
                                             messagebox.showwarning(APP_NAME, msg + "\n\nTải tay ở https://rclone.org/downloads/ "
                                                                    f"(Windows 64-bit), giải nén, chép rclone.exe vào:\n{RCLONE_EXE.parent}")),
                            (), {}, threading.Event()))
            finally:
                self._rclone_dl = False
                self.q.put(("call", lambda: [b.config(state="normal", text=t) for b, t in (
                    (getattr(self, "rclone_dl_btn", None), "⬇  Tải rclone.exe về thư mục tool"),
                    (getattr(self, "rclone_dl_btn2", None), "⬇  Tải rclone.exe")) if b is not None],
                    (), {}, threading.Event()))
        threading.Thread(target=job, daemon=True).start()

    def _need_rclone(self, parent=None, then=None):
        self.save_config()
        r = self._rclone()
        if not r:
            if messagebox.askyesno(APP_NAME, "Chưa có rclone.exe trong thư mục tool:\n"
                                             f"{RCLONE_EXE.parent}\n\nTải rclone.exe (miễn phí, ~20MB) về ngay?",
                                   parent=parent):
                self.get_rclone(then)
        return r

    def open_pikpak_login(self):
        r = self._need_rclone()
        if not r:
            return
        win = tk.Toplevel(self)
        win.title("Đăng nhập PikPak")
        win.configure(bg=C_CARD)
        win.transient(self)
        body = ttk.Frame(win, style="Card.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Tài khoản PikPak", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Nhập email / mật khẩu PikPak. Tool nhớ tài khoản (mật khẩu được mã hóa) để mỗi lần mở "
                             "- kể cả trên máy khác khi dùng ổ di động - tự đăng nhập và kiểm tra kết nối.",
                  style="Muted.TLabel", wraplength=420, justify="left").grid(row=1, column=0, columnspan=2, sticky="w",
                                                                              pady=(4, 10))
        u = tk.StringVar(value=self.cfg.get("pikpak_user", ""))
        pw = tk.StringVar(value=dec_secret(self.cfg.get("pikpak_pass", "")))
        remember = tk.BooleanVar(value=True)
        ttk.Label(body, text="Email / tài khoản").grid(row=2, column=0, sticky="w", pady=4)
        eu = ttk.Entry(body, textvariable=u, width=36)
        eu.grid(row=2, column=1, sticky="we", pady=4, padx=(10, 0))
        ttk.Label(body, text="Mật khẩu").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=pw, show="•", width=36).grid(row=3, column=1, sticky="we", pady=4, padx=(10, 0))
        ttk.Checkbutton(body, text="Ghi nhớ tài khoản và mật khẩu", variable=remember).grid(
            row=4, column=1, sticky="w", padx=(10, 0), pady=(4, 0))
        st = tk.StringVar()
        ttk.Label(body, textvariable=st, style="Muted.TLabel", wraplength=420, justify="left").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"

        def save():
            if not u.get().strip() or not pw.get():
                st.set("Nhập đủ email và mật khẩu.")
                return
            st.set("Đang đăng nhập...")
            win.update()
            run_rclone(r, ["config", "delete", remote], 20)
            code, out, err = run_rclone(r, ["config", "create", remote, "pikpak", "user", u.get().strip(),
                                            "pass", pw.get(), "--obscure", "--non-interactive"], 60)
            if code != 0:
                st.set("⚠ Không tạo được cấu hình: " + (err or out).strip()[-300:])
                return
            code, out, err = run_rclone(r, ["lsd", f"{remote}:"], 60)
            if code == 0:
                self.cfg["pikpak_user"] = u.get().strip() if remember.get() else ""
                self.cfg["pikpak_pass"] = enc_secret(pw.get()) if remember.get() else ""
                self.save_config()
                self._set_pk_status("☁ PikPak: ✔ đã kết nối (" + u.get().strip() + ")", True)
                messagebox.showinfo(APP_NAME, "Đăng nhập PikPak thành công.", parent=win)
                win.destroy()
            else:
                st.set("⚠ Đăng nhập lỗi: " + (err or out).strip()[-300:])
        bb = ttk.Frame(body, style="Card.TFrame")
        bb.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(bb, text="Hủy", command=win.destroy).pack(side="left")
        ttk.Button(bb, text="✓  Đăng nhập", style="Accent.TButton", command=save).pack(side="left", padx=(8, 0))
        win.bind("<Return>", lambda e: save())
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()
        eu.focus_set()

    def test_pikpak(self):
        r = self._need_rclone()
        if not r:
            return
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"
        self.pk_status.set("Đang kiểm tra...")
        self.update()
        code, out, err = run_rclone(r, ["lsd", f"{remote}:"], 60)
        if code == 0:
            n = len([x for x in out.splitlines() if x.strip()])
            self.pk_status.set(f"✔ Kết nối PikPak OK ({n} thư mục ở thư mục gốc).")
        else:
            self.pk_status.set("⚠ Chưa kết nối được. Bấm \"Đăng nhập PikPak...\".  " + (err or out).strip()[-200:])

    def open_share_browser(self, url_var, name_var=None, label_var=None, parent=None):
        """Chọn thư mục con trong link chia sẻ PikPak (đăng nhập tài khoản của bạn để đọc link)."""
        root_link = (self.share_root_var.get().strip() if hasattr(self, "share_root_var") else "") or \
            (self.cfg.get("share_root") or "").strip()
        cur = url_var.get().strip()
        if not is_share(root_link):
            root_link = cur if is_share(cur) else ""
        if not is_share(root_link):
            messagebox.showwarning(APP_NAME, "Chưa có link chia sẻ gốc - nhập ở Cài đặt → Chung → Link chia sẻ gốc.",
                                   parent=parent)
            return
        if not (self.cfg.get("pikpak_user") and self.cfg.get("pikpak_pass")):
            messagebox.showinfo(APP_NAME, "Cần đăng nhập tài khoản PikPak để đọc link chia sẻ.\n"
                                          "Cài đặt → My PikPak → \"Đổi tài khoản PikPak...\"", parent=parent)
            return
        sid, root_parent, pwd = share_parts(root_link)
        win = tk.Toplevel(parent or self)
        win.title("Chọn thư mục phim trong link chia sẻ")
        win.configure(bg=C_CARD)
        win.transient(parent or self)
        h = max(560, min(self.winfo_screenheight() - 110, 1000))       # cao gần hết màn hình, thấy đủ thư mục
        win.geometry(f"720x{h}+{self.winfo_rootx() + 160}+{max(0, (self.winfo_screenheight() - h) // 2 - 20)}")
        win.minsize(560, 420)
        body = ttk.Frame(win, style="Card.TFrame", padding=14)
        body.pack(fill="both", expand=True)
        path_var = tk.StringVar()
        ttk.Label(body, textvariable=path_var, style="Section.TLabel", wraplength=600).pack(anchor="w")
        lf = tk.Frame(body, bg=C_BORDER, padx=1, pady=1)
        lf.pack(fill="both", expand=True, pady=8)
        lb = tk.Listbox(lf, font=(FONT, 10), relief="flat", activestyle="none", selectbackground=C_SEL,
                        selectforeground=C_ACCENT, bg=C_FIELD, fg=C_TEXT, highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(fill="both", expand=True)
        info = tk.StringVar()
        ttk.Label(body, textvariable=info, style="Muted.TLabel", wraplength=600).pack(anchor="w")
        stack = [(root_parent, "Link chia sẻ")]          # (mã thư mục, tên)
        st = {"token": "", "rows": [], "busy": False}

        def crumbs():
            return " › ".join(n for _i, n in stack)

        def load():
            if st["busy"]:
                return
            st["busy"] = True
            info.set("Đang đọc link chia sẻ...")
            path_var.set(crumbs())
            res = queue.Queue()
            folder = stack[-1][0]

            def job():
                try:
                    api = pikpak_api(self.cfg, self.log)
                    if not st["token"]:
                        files, st["token"] = api.share_list(sid, pwd, root_parent)
                        if folder != root_parent:
                            files, _t = api.share_list(sid, pwd, folder, st["token"])
                    elif folder:
                        files, _t = api.share_list(sid, pwd, folder, st["token"])
                    else:
                        files, st["token"] = api.share_list(sid, pwd, None)
                    res.put(("ok", files))
                except Exception as e:
                    res.put(("err", str(e)))
            threading.Thread(target=job, daemon=True).start()

            def poll():
                try:
                    kind, data = res.get_nowait()
                except queue.Empty:
                    win.after(150, poll)
                    return
                st["busy"] = False
                if not win.winfo_exists():
                    return
                lb.delete(0, "end")
                st["rows"] = []
                if len(stack) > 1:
                    lb.insert("end", "↰  ..")
                    st["rows"].append(("up", None, ".."))
                if kind == "err":
                    info.set("⚠ " + data[:300])
                    return
                dirs = sorted((f for f in data if "folder" in str(f.get("kind"))),
                              key=lambda f: natural_key(f.get("name") or ""))
                files = sorted((f for f in data if "folder" not in str(f.get("kind"))),
                               key=lambda f: natural_key(f.get("name") or ""))
                for f in dirs:
                    lb.insert("end", "▦  " + (f.get("name") or "?"))
                    st["rows"].append(("dir", f.get("id"), f.get("name") or "?"))
                for f in files:
                    try:
                        sz = human_size(int(f.get("size") or 0))
                    except (TypeError, ValueError):
                        sz = ""
                    lb.insert("end", f"      {f.get('name') or '?'}    ({sz})")
                    lb.itemconfig("end", fg=C_MUTED)
                    st["rows"].append(("file", f.get("id"), f.get("name") or "?"))
                info.set(f"{len(dirs)} thư mục · {len(files)} file.  Nhấp đúp để mở thư mục.  Chọn thư mục phim rồi "
                         "bấm \"✓ Chọn\".")
            poll()

        def selected():
            sel = lb.curselection()
            return st["rows"][sel[0]] if sel and sel[0] < len(st["rows"]) else None

        def open_sel(_e=None):
            row = selected()
            if not row:
                return
            if row[0] == "up" and len(stack) > 1:
                stack.pop()
                load()
            elif row[0] == "dir":
                stack.append((row[1], row[2]))
                load()

        def choose():
            row = selected()
            if row and row[0] == "dir":
                fid_, name, path = row[1], row[2], crumbs() + " › " + row[2]
            else:
                fid_, name, path = stack[-1][0], stack[-1][1], crumbs()
            if not fid_:
                messagebox.showwarning(APP_NAME, "Hãy mở / chọn 1 thư mục phim (không chọn cả link gốc).", parent=win)
                return
            url_var.set(f"https://mypikpak.com/s/{sid}/{fid_}" + (f"?pwd={pwd}" if pwd else ""))
            if label_var is not None:
                label_var.set("☁ " + path)
            if name_var is not None and not name_var.get().strip():
                name_var.set(name)
            win.destroy()

        lb.bind("<Double-Button-1>", open_sel)
        lb.bind("<Return>", open_sel)
        bf = tk.Frame(body, bg=C_CARD)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="✓  Chọn", style="Accent.TButton", command=choose).pack(side="right")
        ttk.Button(bf, text="Hủy", command=win.destroy).pack(side="right", padx=8)
        ttk.Button(bf, text="⟳  Tải lại", command=load).pack(side="left")
        load()

    def open_pikpak_browser(self, target_var=None, parent=None):
        r = self._need_rclone(parent=parent)
        if not r:
            return
        target_var = target_var or self.pk_root_var
        remote = self.cfg.get("pikpak_remote", "pikpak") or "pikpak"
        win = tk.Toplevel(parent or self)
        win.title("Chọn thư mục trên My PikPak")
        win.configure(bg=C_CARD)
        win.transient(parent or self)
        h = max(560, min(self.winfo_screenheight() - 110, 1000))
        win.geometry(f"640x{h}+{self.winfo_rootx() + 200}+{max(0, (self.winfo_screenheight() - h) // 2 - 20)}")
        win.minsize(480, 420)
        body = ttk.Frame(win, style="Card.TFrame", padding=14)
        body.pack(fill="both", expand=True)
        cur = [pikpak_join(target_var.get())]
        path_var = tk.StringVar()
        ttk.Label(body, textvariable=path_var, style="Section.TLabel", wraplength=600).pack(anchor="w")
        lf = tk.Frame(body, bg=C_BORDER, padx=1, pady=1)
        lf.pack(fill="both", expand=True, pady=8)
        lb = tk.Listbox(lf, font=(FONT, 10), relief="flat", activestyle="none", selectbackground=C_SEL,
                        selectforeground=C_ACCENT, bg=C_FIELD, fg=C_TEXT, highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(fill="both", expand=True)
        info = tk.StringVar()
        ttk.Label(body, textvariable=info, style="Muted.TLabel").pack(anchor="w")

        def load(path):
            info.set("Đang tải danh sách...")
            win.update()
            code, out, err = run_rclone(r, ["lsjson", f"{remote}:{path}", "--dirs-only"], 60)
            if code != 0:
                if path:   # thư mục chưa có -> quay về gốc
                    info.set("Thư mục chưa có trên PikPak, sẽ được tạo khi upload.")
                    cur[0] = path
                    path_var.set("PikPak / " + path)
                    lb.delete(0, "end")
                    lb.insert("end", "↰  ..")
                    return
                info.set("⚠ Lỗi: " + (err or out).strip()[-200:])
                return
            try:
                dirs = sorted((d.get("Name", "") for d in json.loads(out or "[]")), key=natural_key)
            except ValueError:
                dirs = []
            cur[0] = path
            path_var.set("PikPak / " + (path or "(thư mục gốc)"))
            lb.delete(0, "end")
            if path:
                lb.insert("end", "↰  ..")
            for d in dirs:
                lb.insert("end", "▦  " + d)
            info.set(f"{len(dirs)} thư mục. Nhấp đúp để mở.")

        def open_sel(_e=None):
            sel = lb.curselection()
            if not sel:
                return
            t = lb.get(sel[0])
            if t.startswith("↰"):
                load("/".join(cur[0].split("/")[:-1]))
            else:
                load(pikpak_join(cur[0], t[3:]))

        def mkdir():
            from tkinter import simpledialog
            name = simpledialog.askstring(APP_NAME, "Tên thư mục mới:", parent=win)
            if name and name.strip():
                code, out, err = run_rclone(r, ["mkdir", f"{remote}:{pikpak_join(cur[0], name)}"], 60)
                if code != 0:
                    info.set("⚠ " + (err or out).strip()[-200:])
                load(cur[0])

        def choose():
            target_var.set(cur[0])
            if target_var is self.pk_root_var:
                self.save_config()
            win.destroy()
        lb.bind("<Double-1>", open_sel)
        bb = ttk.Frame(body, style="Card.TFrame")
        bb.pack(fill="x", pady=(8, 0))
        ttk.Button(bb, text="＋  Thư mục mới", command=mkdir).pack(side="left")
        ttk.Button(bb, text="✓  Chọn thư mục này", style="Accent.TButton", command=choose).pack(side="right")
        ttk.Button(bb, text="Hủy", command=win.destroy).pack(side="right", padx=8)
        win.grab_set()
        win.after(100, lambda: load(cur[0]))

    @staticmethod
    def _upload_text(h):
        u = h.get("upload", "")
        return {"pending": "⏳  Chờ lưu", "done": "✔  Đã lưu My PikPak", "error": "⚠  Lỗi lưu PikPak",
                "skip": "—"}.get(
            u, h.get("upload_msg", "") if u == "uploading" else "")

    @staticmethod
    def _up_file(h):
        """File để upload My PikPak: bản trong COPY TO IPHONE (nếu còn), không thì bản trên HDD."""
        for k in ("up_path", "path", "hdd"):
            pth = h.get(k) or ""
            if pth and os.path.isfile(pth):
                return pth
        return ""

    def enqueue_upload(self, code, force=False):
        h = self.history.get(code)
        if not h:
            return False
        if h.get("upload") in ("pending", "uploading") or (h.get("upload") in ("done", "skip") and not force):
            return False
        src = self._up_file(h)
        if code in self.up_queued or not (h.get("remote_src") or src):
            return False
        h["upload"] = "pending"
        h.pop("upload_msg", None)
        self.up_queued.add(code)
        self.up_q.put(code)
        return True

    def _resume_uploads(self):
        n = 0
        for code, h in self.history.items():
            if h.get("upload") in ("pending", "uploading") and code not in self.up_queued:
                h["upload"] = ""
                n += self.enqueue_upload(code, force=True)
        if n:
            self.log(f"PikPak: tiếp tục upload {n} file còn dở.")
            self.save_history(); self.refresh_history()

    def history_upload_selected(self):
        if not self._need_rclone():
            return
        n = 0
        for code in self.hist_tree.selection():
            n += self.enqueue_upload(code, force=True)
        self.save_history(); self.refresh_history()
        self.status_var.set(f"Đã thêm {n} file vào hàng chờ upload PikPak." if n else
                            "Không có file nào upload được (chỉ upload file đã tải xong và còn trên máy).")

    def _uploader_loop(self):
        """Luồng nền: lần lượt upload từng file lên PikPak bằng rclone."""
        while True:
            code = self.up_q.get()
            if code == "__backup__":
                self._do_backup()
                continue
            try:
                h = dict(self.history.get(code, {}))
                path = self._up_file(h)
                rsrc = h.get("remote_src", "")
                if not rsrc and (not path or not os.path.isfile(path)):
                    self.q.put(("upload", code, "error", "Không thấy file trên máy"))
                    continue
                r = find_rclone(self.cfg.get("rclone_path", ""))
                if not r:
                    self.q.put(("upload", code, "error", "Chưa có rclone.exe"))
                    continue
                fc = next((f for f in self.cfg["folders"] if fid(f) == h.get("folder_code")), None)
                pkf = pikpak_folder(self.cfg, fc, h.get("movie") or h.get("folder", ""))
                if not pkf:
                    self.q.put(("upload", code, "error", "Thư mục phim không đặt đích My PikPak"))
                    continue
                dest = f"{self.cfg.get('pikpak_remote', 'pikpak') or 'pikpak'}:{pkf}"
                if rsrc:      # file gốc đã nằm trên PikPak -> sao chép trên máy chủ (nhanh, không tốn mạng)
                    self.q.put(("upload", code, "uploading", "☁  Đang lưu..."))
                    ok, msg = rclone_copy(r, rsrc, f"{dest}/{h.get('name', '')}")
                    if not ok and path and os.path.isfile(path):
                        ok, msg = rclone_copy(r, path, f"{dest}/{h.get('name', '')}",
                                              lambda pct, sp: (self.q.put(("upload", code, "uploading",
                                                                            f"↑ {ebar(pct)} {pct}%")),
                                                               self.q.put(("energy", "up", pct,
                                                                           f"↑ {h.get('name', '')}   {sp}"))))
                    self.q.put(("upload", code, "done" if ok else "error", dest if ok else msg))
                    continue
                self.q.put(("upload", code, "uploading", f"↑ {ebar(0)} 0%"))
                self.q.put(("energy", "up", 0, f"↑ {h.get('name', '')}"))
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                bw = str(self.cfg.get("bwlimit", "") or "").strip()
                p = subprocess.Popen([r, "--config", str(RCLONE_CONF), "copyto", path, f"{dest}/{os.path.basename(path)}",
                                      *(["--bwlimit", bw] if bw else []),
                                      "--retries", "3", "--low-level-retries", "10",
                                      "--stats", "2s", "--stats-one-line", "--stats-log-level", "NOTICE"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", creationflags=flags)
                last, tail = "", []
                for line in p.stdout:
                    tail = (tail + [line.strip()])[-5:]
                    m = re.search(r"(\d{1,3})%", line)
                    if m and m.group(1) != last:
                        last = m.group(1)
                        sp = re.search(r"([\d.]+\s*[KMG]i?B/s)", line)
                        self.q.put(("upload", code, "uploading", f"↑ {ebar(last)} {last}%"))
                        self.q.put(("energy", "up", last, f"↑ {h.get('name', '')}   " + (sp.group(1) if sp else "")))
                rc = p.wait()
                if rc == 0:
                    self.q.put(("upload", code, "done", dest))
                else:
                    self.q.put(("upload", code, "error", " | ".join(x for x in tail if x)[-200:]))
            except Exception as e:
                self.q.put(("upload", code, "error", str(e)))

    def _on_upload_msg(self, code, state, info):
        if state in ("done", "error"):
            self.up_queued.discard(code)
            nm = (self.history.get(code) or {}).get("name", "")
            if state == "done":
                self._energy_set("up", 100, f"✔ Đã lưu: {nm}")
            else:
                self._energy_set("up", 0, f"⚠ Lỗi lưu: {nm}")
        h = self.history.get(code)
        if not h:
            return
        h["upload"] = state
        h["upload_msg"] = info
        if self.hist_tree.exists(code):
            self.hist_tree.set(code, "pikpak", self._upload_text(h))
        if self.scan_tree.exists(code):
            if state == "uploading":
                self._set_row(code, "✔  HDD  ·  " + str(info).strip(), "dl")
            elif state in ("done", "error"):
                self._set_row(code, "✔  Xong · HDD · My PikPak" if state == "done" else "✔  HDD  ·  ⚠ lỗi lưu PikPak",
                              "done" if state == "done" else "err")
        if state == "done":
            h["upload_ts"] = time.time()
            self.log(f"☁ Đã lưu vào My PikPak: {h.get('name', '')}  →  {info}")
            pass
            self.save_history()
        elif state == "error":
            self.log(f"⚠ Lưu My PikPak lỗi: {h.get('name', '')} — {info}")
            self.report_error(f"Lưu My PikPak lỗi: {h.get('name', '')}", info)
            self.save_history()

    def _browse_rd(self):
        p = filedialog.askdirectory(title="Chọn ổ RaiDrive (mount PikPak)")
        if p:
            p = os.path.normpath(p)
            self.rd_var.set(p if len(p) > 3 else p[:2] + os.sep)

    @staticmethod
    def _ensure_dir(p):
        try:
            os.makedirs(p, exist_ok=True)
        except OSError:
            pass
        return p

    def check_mapping(self):
        """So 1 thư mục trên ổ RaiDrive với đường dẫn rclone tương ứng -> biết rclone tải thẳng được không."""
        self.save_config()
        r = find_rclone()
        if not r:
            self.map_status.set("Chưa có rclone.exe (tab Lưu trữ & PikPak).")
            return
        root = rd_root(self.cfg)
        if not root or not os.path.isdir(root):
            self.map_status.set(f"Không thấy ổ RaiDrive {root or '(chưa đặt)'}.")
            return
        cands = [resolve_src(self.cfg, f.get("url", "")) for f in self.cfg["folders"]
                 if str(f.get("url", "")).startswith(RD_TOKEN)]
        local = next((c for c in cands if c and os.path.isdir(c)), root)
        remote = remote_of(self.cfg, local)
        self.map_status.set(f"Đang so {local}  ↔  {remote} ...")
        cfg = dict(self.cfg)

        def job():
            try:
                names_l = {n for n in os.listdir(local) if not n.startswith(".")}
                code, out, err = run_rclone(r, ["lsf", remote, "--max-depth", "1"], 120)
                names_r = {x.rstrip("/") for x in out.splitlines() if x.strip()}
                if code != 0:
                    msg = f"✘ rclone không đọc được {remote}: {(err or out).strip()[:160]}"
                    ok = False
                elif not names_l and not names_r:
                    msg, ok = "Thư mục trống - chọn thư mục phim có file rồi kiểm tra lại.", None
                else:
                    same = len(names_l & names_r) / max(1, len(names_l | names_r))
                    ok = same >= 0.8
                    if not ok:                     # thử đoán thư mục gốc (VD ổ RaiDrive = My Pack)
                        rel = os.path.relpath(local, rd_root(cfg)).replace("\\", "/")
                        rel = "" if rel == "." else rel
                        for base in ("My Pack", "", "Shared", "My Pack/Shared"):
                            if base == cfg.get("rd_remote_base", ""):
                                continue
                            rm = f"{cfg.get('pikpak_remote', 'pikpak') or 'pikpak'}:{pikpak_join(base, rel)}"
                            c2, o2, _e2 = run_rclone(r, ["lsf", rm, "--max-depth", "1"], 120)
                            n2 = {x.rstrip("/") for x in o2.splitlines() if x.strip()}
                            if c2 == 0 and names_l and len(names_l & n2) / max(1, len(names_l | n2)) >= 0.8:
                                self.q.put(("call", lambda b=base: (self.rdbase_var.set(b), self.save_config()),
                                            (), {}, threading.Event()))
                                ok, same = True, len(names_l & n2) / max(1, len(names_l | n2))
                                break
                    msg = (f"✔ Khớp ({same:.0%}): rclone tải thẳng từ PikPak được." if ok else
                           f"✘ Chỉ khớp {same:.0%} - kiểm tra ô \"Thư mục PikPak tương ứng gốc ổ\" "
                           f"(VD ổ mount thư mục 'My Pack' thì ghi My Pack).")
                self.q.put(("call", lambda: (self.map_status.set(msg), self.log("Kiểm tra ổ RaiDrive: " + msg)),
                            (), {}, threading.Event()))
            except Exception as e:
                self.q.put(("call", lambda: self.map_status.set(f"Lỗi: {e}"), (), {}, threading.Event()))
        threading.Thread(target=job, daemon=True).start()

    def save_config(self):
        if hasattr(self, "rd_var"):
            rd = self.rd_var.get().strip()
            self.cfg["raidrive_root"] = (rd[:2] + os.sep) if len(rd) == 2 and rd[1] == ":" else rd
            self.cfg["rd_remote_base"] = pikpak_join(self.rdbase_var.get())
            self.cfg["dl_method"] = "copy"
            self.cfg["extensions"] = self.ext_var.get().strip()
            self.cfg["bwlimit"] = re.sub(r"\s+", "", self.bw_var.get())
            self.cfg["rd_autostart"] = self.rdauto_var.get()
            self.cfg["rd_to_tray"] = self.rdtray_var.get()
            self.cfg["raidrive_exe"] = self.rdexe_var.get().strip()
            self.cfg["share_root"] = self.share_root_var.get().strip()
            self.cfg["iphone_on"] = self.iphone_on_var.get()
            self.cfg["iphone_dir"] = resolve_iphone_dir(self.iphone_dir_var.get())
            self.cfg["copy_threads"] = 1
            try:
                self.cfg["rd_check_min"] = max(0, int(self.rdmin_var.get()))
            except (tk.TclError, ValueError):
                self.cfg["rd_check_min"] = 2
            self.cfg["notify"] = self.notify_var.get()
            self.cfg["tray_on_close"] = self.tray_var.get()
            self.cfg["startup_scan"] = self.startscan_var.get()
            self.cfg["backup_on"] = self.backup_on_var.get()
            self.cfg["pikpak_root"] = pikpak_join(self.pk_root_var.get())
            want = self.startwin_var.get()
            if want != self.cfg.get("start_with_windows") or want:
                try:
                    set_startup(want)   # luôn ghi lại đường dẫn mới nhất khi đang bật
                    self.cfg["start_with_windows"] = want
                except OSError as e:
                    self.log(f"Không đặt được khởi động cùng Windows: {e}")
            self.cfg["health_check"] = self.health_var.get()
            try:
                self.cfg["stale_days"] = max(0, int(self.stale_var.get()))
            except (tk.TclError, ValueError):
                self.cfg["stale_days"] = 7
            for key, var, lo, dflt in (("delay", self.delay_var, 0, 2),):
                try:
                    self.cfg[key] = max(lo, int(var.get()))
                except (tk.TclError, ValueError):
                    self.cfg[key] = dflt
        if hasattr(self, "auto_var"):
            self.cfg["auto_scan"] = self.auto_var.get()
            try:
                self.cfg["auto_interval"] = max(5, int(self.interval_var.get()))
            except (tk.TclError, ValueError):
                self.cfg["auto_interval"] = 60
        if getattr(self, "_no_save", False):
            return
        self._store_machine_profile()
        save_json(CONFIG_FILE, self.cfg)

    def _build_history(self):
        btns = ttk.Frame(self.tab_history, style="Card.TFrame")
        btns.pack(fill="x", pady=(0, 10))
        ttk.Button(btns, text="✔  Đánh dấu Xong", command=self.history_mark_done).pack(side="left")
        ttk.Button(btns, text="☁  Lưu lại vào My PikPak", command=self.history_upload_selected).pack(side="left", padx=8)
        ttk.Button(btns, text="⧉  Copy báo cáo lỗi mới nhất", command=self.copy_last_report).pack(side="left")
        ttk.Button(btns, text="▸  Thư mục báo cáo", command=self.open_reports).pack(side="left", padx=(8, 8))
        ttk.Button(btns, text="↺  Xóa mục chọn (để tải lại)", command=self.history_delete).pack(side="left")
        ttk.Button(btns, text="✕  Xóa toàn bộ", style="Danger.TButton", command=self.history_clear).pack(side="left", padx=8)
        self.hist_count = tk.StringVar()
        ttk.Label(btns, textvariable=self.hist_count, style="Muted.TLabel").pack(side="right")
        flt = ttk.Frame(self.tab_history, style="Card.TFrame")
        flt.pack(fill="x", pady=(0, 8))
        ttk.Label(flt, text="⌕ Tìm", style="Muted.TLabel").pack(side="left")
        self.hist_search_var = tk.StringVar()
        ttk.Entry(flt, textvariable=self.hist_search_var, width=30).pack(side="left", padx=(6, 14))
        self.hist_search_var.trace_add("write", lambda *a: self.refresh_history())
        ttk.Label(flt, text="Trạng thái", style="Muted.TLabel").pack(side="left")
        self.hist_show_var = tk.StringVar(value="Tất cả")
        hc = ttk.Combobox(flt, textvariable=self.hist_show_var, state="readonly", width=14,
                          values=("Tất cả", "Đang tải", "Xong", "Lỗi", "Hôm nay", "Lỗi upload"))
        hc.pack(side="left", padx=6)
        hc.bind("<<ComboboxSelected>>", lambda e: self.refresh_history())
        self.hist_sort = ("sent", True)
        wrap, self.hist_tree = self._tree(self.tab_history, ("folder", "name", "sent", "status", "pikpak"),
                                          ("THƯ MỤC", "TÊN FILE", "THỜI GIAN", "TRẠNG THÁI", "PIKPAK"),
                                          (190, 420, 130, 140, 150), stretch=("folder", "name"))
        wrap.pack(fill="both", expand=True)
        for c in ("folder", "name", "sent", "status"):
            self.hist_tree.heading(c, command=lambda c=c: self._sort_history(c))
        self.hist_tree.bind("<Double-1>", self._open_history_file)
        ttk.Label(self.tab_history, text="Nhấp đúp 1 tập đã tải xong để mở thư mục chứa file.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        self.refresh_history()

    @staticmethod
    def _status_tag(status):
        if status == STATUS_DONE:
            return "done"
        if status in RETRY_STATUSES:
            return "err"
        if status in WATCH_STATUSES:
            return "dl"
        return "err" if status.startswith("Lỗi") else ""

    @staticmethod
    def _status_text(status):
        return {STATUS_DONE: "✔  Xong", STATUS_DL: "⬇  Đang tải", STATUS_NEW: "●  Tập mới"}.get(status, status)

    def _sort_history(self, col):
        cur, rev = self.hist_sort
        self.hist_sort = (col, (not rev) if cur == col else (col == "sent"))
        self.refresh_history()

    def refresh_history(self):
        self.hist_tree.delete(*self.hist_tree.get_children())
        col, rev = getattr(self, "hist_sort", ("sent", True))
        keyf = {"folder": lambda kv: strip_accents(kv[1].get("folder", "")),
                "name": lambda kv: strip_accents(kv[1].get("name", "")),
                "status": lambda kv: kv[1].get("status", ""),
                "sent": lambda kv: kv[1].get("ts", 0) or 0}[col]
        items = sorted(self.history.items(), key=keyf, reverse=rev)
        q = strip_accents(self.hist_search_var.get().strip()) if hasattr(self, "hist_search_var") else ""
        show = self.hist_show_var.get() if hasattr(self, "hist_show_var") else "Tất cả"
        today = dt.date.today()

        def keep(h):
            st = h.get("status", "")
            if q and q not in strip_accents(f"{h.get('folder', '')} {h.get('name', '')}"):
                return False
            if show == "Đang tải":
                return st in WATCH_STATUSES
            if show == "Xong":
                return st == STATUS_DONE
            if show == "Lỗi":
                return st == STATUS_FAIL or st.startswith("Lỗi")
            if show == "Lỗi upload":
                return h.get("upload") == "error"
            if show == "Hôm nay":
                try:
                    return dt.datetime.fromtimestamp(h.get("ts", 0) or 0).date() == today
                except (OSError, ValueError, OverflowError):
                    return False
            return True
        items = [kv for kv in items if keep(kv[1])]
        heads = {"folder": "THƯ MỤC", "name": "TÊN TẬP", "sent": "THỜI GIAN", "status": "TRẠNG THÁI"}
        for c, t in heads.items():
            self.hist_tree.heading(c, text=t + ((" ▼" if rev else " ▲") if c == col else ""))
        for i, (code, h) in enumerate(items):
            st = h.get("status", "")
            tags = [t for t in (("odd" if i % 2 else ""), self._status_tag(st)) if t]
            self.hist_tree.insert("", "end", iid=code, values=(h.get("folder", ""), h.get("name", ""),
                                                               h.get("sent_at", ""), self._status_text(st),
                                                               self._upload_text(h)), tags=tags)
        self.hist_count.set(f"Hiện {len(items)}/{len(self.history)} tập")
        if hasattr(self, "stat_vars"):
            self.update_stats()

    def _open_history_file(self, _e=None):
        sel = self.hist_tree.selection()
        if not sel:
            return
        path = self.history.get(sel[0], {}).get("path")
        if path and os.path.exists(path) and os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif path and os.path.exists(path):
            self.status_var.set(path)
        else:
            self.status_var.set("Chưa có đường dẫn file (tập chưa tải xong hoặc đã bị chuyển/xóa).")

    def save_history(self):
        save_json(HISTORY_FILE, self.history)

    def history_delete(self):
        sel = self.hist_tree.selection()
        if not sel or not messagebox.askyesno(APP_NAME, f"Xóa {len(sel)} tập khỏi lịch sử? Lần quét sau sẽ tải lại."):
            return
        for code in sel:
            self.history.pop(code, None)
        self.save_history(); self.refresh_history()

    def history_clear(self):
        if messagebox.askyesno(APP_NAME, "Xóa toàn bộ lịch sử đã tải?"):
            self.history = {}
            self.save_history(); self.refresh_history()

    @staticmethod
    def _names_preview(names, n=3):
        out = ", ".join(os.path.splitext(x)[0] for x in names[:n])
        return out + (f" và {len(names) - n} tập khác" if len(names) > n else "")

    def _start_tray(self):
        if not TRAY_OK:
            return
        try:
            import base64, io
            img = PILImage.open(io.BytesIO(base64.b64decode(ICON64)))
            put = lambda what: (lambda: self.q.put(("tray", what)))
            menu = pystray.Menu(
                pystray.MenuItem("Mở PikPak Auto Save", put("show"), default=True),
                pystray.MenuItem("Quét & Tải ngay", put("scan")),
                pystray.MenuItem(lambda item: "Tắt tự quét" if self.cfg.get("auto_scan") else "Bật tự quét",
                                 put("toggle_auto")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Thoát", put("quit")))
            self.tray = pystray.Icon("PikPakShare", img, APP_NAME, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception as e:
            self.tray = None
            self.log(f"Không tạo được biểu tượng khay: {e}")

    def notify(self, title, msg):
        self.log(f"» {title}: {msg}")
        if self.tray and self.cfg.get("notify", True):
            try:
                self.tray.notify(msg, title)
            except Exception:
                pass

    def _restore_window(self):
        w = self.cfg.get("window") or {}
        if re.fullmatch(r"\d+x\d+[+-]-?\d+[+-]-?\d+", str(w.get("geometry", ""))):
            self.geometry(w["geometry"])
            self._normal_geom = w["geometry"]
        if w.get("zoomed"):
            self.after(50, lambda: self.state("zoomed"))

    def _track_geom(self, e):
        if e.widget is self and self.state() == "normal":
            self._normal_geom = self.geometry()

    def _init_col_memory(self):
        """Nhớ độ rộng cột các bảng (kéo vạch giữa tiêu đề cột) - lưu khi thả chuột và khi tắt tool."""
        self._col_trees = {"scan": self.scan_tree, "hist": self.hist_tree, "fp": self.fp_tree}
        saved = self.cfg.get("col_w") or {}
        for key, tree in self._col_trees.items():
            widths = saved.get(key) or {}
            for c in tree["columns"]:
                if c in widths:
                    try:
                        tree.column(c, width=int(widths[c]), stretch=False)
                    except (tk.TclError, ValueError):
                        pass
            if widths:   # cột cuối giãn theo cửa sổ để không bị khoảng trống
                tree.column(tree["columns"][-1], stretch=True)
            tree.bind("<ButtonRelease-1>", lambda e, t=tree: self._col_released(e, t), add="+")

    def _col_released(self, e, tree):
        if tree.identify_region(e.x, e.y) in ("separator", "heading"):
            self._save_cols()
            save_json(CONFIG_FILE, self.cfg) if not self._no_save else None

    def _save_cols(self):
        if not getattr(self, "_col_trees", None):
            return
        out = {}
        for key, tree in self._col_trees.items():
            try:
                out[key] = {c: int(tree.column(c, "width")) for c in tree["columns"]}
            except tk.TclError:
                pass
        self.cfg["col_w"] = out

    def _remember_window(self):
        self._save_cols()
        st = self.state()
        if st in ("normal", "zoomed"):
            self._was_zoomed = st == "zoomed"
        self.cfg["window"] = {"geometry": self._normal_geom or self.geometry(), "zoomed": self._was_zoomed}

    def show_window(self):
        if self.state() == "withdrawn":
            self.deiconify()
            if self._was_zoomed:
                self.state("zoomed")
        self.bring_to_front()

    def on_close(self):
        if self.tray and self.cfg.get("tray_on_close", True):
            self._remember_window()
            self.save_config()
            self.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.notify(APP_TITLE, "Tool vẫn chạy dưới khay hệ thống. Nhấp đúp biểu tượng để mở lại.")
            return
        self.quit_app()

    def quit_app(self, force=False):
        if self.worker and self.worker.is_alive() and not force:
            if not messagebox.askyesno(APP_NAME, "Tool đang quét/tải. Vẫn thoát?"):
                return
            self.stop_flag.set()
        if self.state() != "withdrawn" and not self._no_save:
            self._remember_window()
        if not self._no_save:
            self.save_config()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.destroy()

    def _auto_changed(self):
        self.save_config()
        if self.cfg.get("auto_scan"):
            self.next_auto_ts = time.time() + int(self.cfg.get("auto_interval", 60)) * 60
            self.log(f"Bật tự quét mỗi {self.cfg['auto_interval']} phút.")
        else:
            self.next_auto_ts = None
            self.log("Tắt tự quét.")
        self._update_auto_label()
        if self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def _update_auto_label(self):
        if self.next_auto_ts:
            txt = f"⏱  Quét lần tới: {dt.datetime.fromtimestamp(self.next_auto_ts):%H:%M}"
        else:
            txt = "⏱  Tự quét: tắt"
        self.header_auto_text = txt
        try:
            self.top_auto.config(text=txt)
            self.side_auto.config(text=txt.replace("⏱  ", "⏱ "))
        except (tk.TclError, AttributeError):
            pass

    def _auto_tick(self):
        self.after(15000, self._auto_tick)
        now = time.time()
        if self.cfg.get("auto_scan") and not self.next_auto_ts:
            self.next_auto_ts = now + int(self.cfg.get("auto_interval", 60)) * 60
        if self.next_auto_ts and now >= self.next_auto_ts:
            if self.worker and self.worker.is_alive():
                self.next_auto_ts = now + 120          # đang bận -> thử lại sau 2 phút
            else:
                self.log("⏱ Tự quét theo lịch...")
                self.start_scan(True, auto=True)
                self.next_auto_ts = (now + int(self.cfg.get("auto_interval", 60)) * 60
                                     if self.cfg.get("auto_scan") else None)
        self._update_auto_label()

    def bring_to_front(self):
        """Đưa tool lên trước, GIỮ NGUYÊN kích thước (không làm mất trạng thái phóng to)."""
        try:
            if os.name == "nt":
                import ctypes
                u32 = ctypes.windll.user32
                hwnd = u32.GetParent(self.winfo_id()) or self.winfo_id()
                if u32.IsIconic(hwnd):
                    u32.ShowWindow(hwnd, 9)  # SW_RESTORE: chỉ khi đang thu nhỏ -> về đúng kích thước cũ
                self.lift()
                u32.keybd_event(0x12, 0, 0, 0)  # nhấn ALT để Windows cho phép đưa cửa sổ lên trước
                u32.SetForegroundWindow(hwnd)
                u32.keybd_event(0x12, 0, 2, 0)
            else:
                if self.state() == "iconic":
                    self.deiconify()
                self.lift()
            self.focus_force()
        except Exception:
            pass

if __name__ == "__main__":
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DuyAnh.PikPakShare")
        except Exception:
            pass
    if "--after-update" in sys.argv:
        time.sleep(2.5)           # chờ bản cũ thoát hẳn
    migrate_exe_name()
    if not run_newer_script():
        App(auto="--auto" in sys.argv, startup="--startup" in sys.argv).mainloop()

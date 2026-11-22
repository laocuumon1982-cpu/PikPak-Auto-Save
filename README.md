# PikPak Auto Save

Tool Windows (giao diện web trong cửa sổ app - pywebview / Edge WebView2; giao diện Tkinter cũ làm dự phòng) theo dõi các thư mục phim trong **link chia sẻ PikPak** được chia sẻ cho bạn. Có tập mới thì:

1. **Đích 1 – Save vào My PikPak** (tài khoản của bạn): lưu tập mới từ link chia sẻ vào thư mục bạn chọn – sao chép trên máy chủ PikPak, không tốn mạng.
2. **Đích 2 – HDD của PC**: rclone (tài khoản của bạn) tải tập đó từ My PikPak về thư mục HDD bạn chọn (đa luồng).

**Điều khiển từ iPhone / iPad** (v3.3): bật trong Cài đặt → tab 📱 iPhone / iPad, đặt mã PIN, quét mã QR bằng iPhone cùng Wi-Fi rồi "Thêm vào MH chính" – phim vẫn tải về HDD của PC.

Mỗi đợt tool **Save tất cả tập mới vào My PikPak trước**, rồi mới tải lần lượt từng tập về HDD.

Tập đã xong được đưa vào *Danh sách đã có* để lần sau không tải lại. Cùng bộ với [Auto Download - PikPak](https://github.com/laocuumon1982-cpu/PikPakAutoDownload).

- Chạy bằng Python: `ChayTool.bat` (cài thư viện trước bằng `CaiDat.bat`, cần `pywebview`).
- Mã nguồn: `auto_download_pikpak_share.py` (phần lõi + giao diện Tk cũ), `pikpak_web.py` + thư mục `web/` (giao diện web), `pikpak_remote.py` (điều khiển từ iPhone / iPad).
- Bản exe portable: tải `PikPak-Auto-Save_Portable.zip` ở mục **Releases**.
- Dữ liệu người dùng nằm trong thư mục `Data` (không đưa lên đây).
- Hướng dẫn: `HUONG_DAN.txt`, cập nhật: `HUONG_DAN_CAP_NHAT.txt`, lịch sử phiên bản: `CHANGELOG.txt`.

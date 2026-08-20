# Triển khai ZBridge lên VPS (qua Cloudflare Tunnel)

Kiến trúc khi chạy thật: VPS **không mở port nào ra internet**. `cloudflared` gọi
ra ngoài tới Cloudflare, Cloudflare nhận HTTPS từ người dùng rồi đẩy qua tunnel
vào `frontend:8080`. Nginx trong `frontend` phục vụ web và proxy `/api` sang
`backend:8000`.

```
người dùng ──HTTPS──▶ Cloudflare ──tunnel──▶ frontend:8080 ──/api──▶ backend:8000
                                                                        │
                              postgres · redis · zalo-gateway · celery-worker
                              celery-alerts · celery-beat
```

## 1. Chuẩn bị VPS

Cần Docker Engine + Compose v2. Ubuntu 22.04/24.04:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # đăng xuất/đăng nhập lại
```

Tối thiểu nên có 2 vCPU / 4 GB RAM. Bước render Google Sheet thành ảnh là chỗ
tốn RAM nhất; nếu container `celery-worker` bị OOM kill thì nâng `WORKER_MEM_LIMIT`.

## 2. Tạo Cloudflare Tunnel

Zero Trust → Networks → Tunnels → **Create a tunnel** → chọn *Cloudflared*.

1. Copy **token** của tunnel, điền vào `CLOUDFLARE_TUNNEL_TOKEN`.
2. Tab **Public Hostname**: thêm hostname (ví dụ `zbridge.example.com`), Service =
   `HTTP`, URL = `frontend:8080`.

Không cần mở port 80/443 trên firewall, không cần cấp chứng chỉ TLS.

## 3. Cấu hình

```bash
git clone <repo> /opt/zbridge && cd /opt/zbridge
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Sinh secret:

```bash
openssl rand -hex 32       # JWT_SECRET
openssl rand -base64 32    # ZALO_GATEWAY_SECRET, ZALO_EVENT_SECRET, ZALO_SESSION_SECRET, POSTGRES_PASSWORD
```

Điền hết các biến trong `.env.prod`. Lưu ý:

- `DATABASE_URL` phải khớp `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`.
- `APP_URL` và `ALERT_LINK_BASE_URL` đặt bằng hostname công khai — link trong
  cảnh báo Telegram chỉ bấm được khi đây là domain thật (Telegram không tạo link
  tới `localhost`).
- `COOKIE_SECURE=true` vì trình duyệt nói HTTPS với Cloudflare.
- `IMAGE_TAG` nên ghim theo tag đã phát hành thay vì `latest` để redeploy tái lập được.

Đặt credential Google Service Account vào `secrets/google-service-account.json`
(chỉ `celery-worker` đọc, mount read-only), rồi **đổi chủ sở hữu sang uid của
container** — nếu không, worker chạy bằng uid 10001 sẽ không đọc được file mode
600 thuộc `ubuntu`, và mọi lượt nhắc công nợ fail với `GOOGLE_CREDENTIALS_INVALID`:

```bash
sudo chown 10001:10001 secrets/google-service-account.json
sudo chmod 400 secrets/google-service-account.json
```

Share thư mục Drive của từng khách hàng cho email service account đó.

## 4. Deploy lần đầu

Image được CI build và đẩy lên `ghcr.io` (xem `.github/workflows/build.yml`).
Nếu package ở chế độ private thì đăng nhập trước:

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
```

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

Service `migrate` chạy `alembic upgrade head` rồi thoát; `backend` chỉ khởi động
sau khi nó thành công. Kiểm tra:

```bash
curl -s https://zbridge.example.com/health
```

## 5. Liên kết bot Zalo

Đăng nhập web bằng `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_PASSWORD`, vào **Zalo
Bot** → *Kết nối Zalo* → quét QR bằng điện thoại. Session được mã hóa
(AES-256-GCM) và lưu trong volume `zalo-session`, nên restart không phải quét lại.

Sau đó vào **Khách hàng** → đồng bộ để nạp danh sách nhóm.

## 6. Cập nhật phiên bản

```bash
cd /opt/zbridge && git pull
# sửa IMAGE_TAG trong .env.prod nếu ghim tag
docker compose -f docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Migration tự chạy qua service `migrate` trước khi backend mới lên.

## 7. Backup

Backup được mã hoá bằng GPG (AES-256) rồi đẩy lên bucket S3 tương thích. Với
Cloudflare R2 (miễn phí 10GB, egress miễn phí, cùng tài khoản Cloudflare bạn đã
dùng cho tunnel):

1. R2 → Create bucket, ví dụ `zbridge-backups`.
2. Manage API tokens → tạo token **Object Read & Write** giới hạn đúng bucket đó.
3. Điền `RCLONE_CONFIG_R2_*`, `BACKUP_REMOTE=r2:zbridge-backups/prod`,
   `BACKUP_PASSPHRASE` vào `.env.prod`. Không cần chạy `rclone config`.
4. Đặt lifecycle rule trên bucket để tự xoá object cũ hơn 30–90 ngày.

```bash
./deploy/backup.sh                # chạy thử một lần
crontab -e
0 */6 * * * cd /opt/zbridge && ./deploy/backup.sh >> /var/log/zbridge-backup.log 2>&1
```

Sáu tiếng một lần là đủ: dữ liệu ở đây do người nhập tay nên thay đổi chậm, và
mỗi bản dump chỉ cỡ vài MB. Mất tối đa 6 tiếng nghĩa là xấu nhất một khách vừa
trả tiền bị đánh dấu còn nợ — sửa tay được.

Script kiểm tra dump không rỗng trước khi giữ lại, và **nếu backup lỗi thì bắn
cảnh báo CRITICAL về Telegram** qua đúng đường alert của app.

**Giữ `BACKUP_PASSPHRASE` ở nơi khác** (password manager). Mất nó là backup thành
rác. Phục hồi database:

```bash
gpg -d backups/postgres-YYYYmmdd-HHMMSS.sql.gz.gpg | gunzip | \
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  psql -U zbridge -d zbridge
```

Phục hồi session Zalo (chỉ cần khi muốn tránh quét lại QR):

```bash
gpg -d backups/zalo-session-YYYYmmdd-HHMMSS.tgz.gpg | \
  docker run --rm -i -v zbridge_zalo-session:/data alpine tar xzf - -C /data
```

Lưu ý: session chỉ giải mã được bằng đúng `ZALO_SESSION_SECRET` lúc nó được ghi.
Đổi secret đó mà không mã hoá lại thì phải quét QR lần nữa.

Mất volume `zalo-session` chỉ tốn một lần quét lại QR, không mất dữ liệu nghiệp vụ.

## 8. Vận hành

```bash
# log theo service
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f backend
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f celery-worker

# cảnh báo đã gửi
docker compose -f docker-compose.prod.yml --env-file .env.prod logs celery-alerts | grep ALERT_SENT
```

Lỗi được đẩy về Telegram (xem `ALERT_MIN_SEVERITY`), gộp theo lần 1 / 10 / 100
trong mỗi cửa sổ 15 phút. `celery-beat` ping `/health` mỗi 2 phút nên backend
hoặc database chết cũng có cảnh báo.

## 9. Hai giới hạn bắt buộc tôn trọng

- **`celery-beat` phải đúng 1 instance.** Hai scheduler sẽ nhân đôi mọi task định
  kỳ, nghĩa là khách hàng nhận nhắc công nợ hai lần.
- **`zalo-gateway` phải đúng 1 instance.** Chỉ có một session Zalo; instance thứ
  hai sẽ bị Zalo đóng phiên (`DuplicateConnection`) và bot mất kết nối.

Cả hai đều đã cố định trong `docker-compose.prod.yml` — đừng `--scale` chúng.

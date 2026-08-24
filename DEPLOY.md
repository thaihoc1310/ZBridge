# Triển khai ZBridge lên VPS

Toàn bộ hệ thống chạy bằng `docker compose` trên một VPS, ra internet qua
Cloudflare Tunnel. **VPS không mở port nào** — `cloudflared` gọi ra ngoài, nên
firewall không cần rule inbound nào, kể cả 80/443, và không cần cấp chứng chỉ TLS.

```
người dùng ──HTTPS──▶ Cloudflare ──tunnel──▶ frontend:8080 ──/api──▶ backend:8000
                                                                         │
                                            postgres · redis · zalo-gateway
                                            celery-worker · celery-ai
                                            celery-alerts · celery-beat
```

| Service | Việc nó làm | Ghi chú |
|---|---|---|
| `postgres` | dữ liệu khách hàng, công nợ, người dùng | volume `postgres-data` |
| `redis` | broker cho Celery + bộ đếm gộp cảnh báo | volume `redis-data` |
| `migrate` | `alembic upgrade head` rồi thoát | one-shot, backend chờ nó xong |
| `backend` | API FastAPI | |
| `frontend` | nginx: web + proxy `/api` | listen 8080, chạy uid 101 |
| `zalo-gateway` | nói chuyện với Zalo, giữ session | **chỉ 1 instance**, volume `zalo-session` |
| `celery-worker` | gửi tin, nhắc công nợ, tag tên, dọn log | queue `celery` |
| `celery-ai` | gọi OpenAI phân loại tag | queue `ai` |
| `celery-alerts` | gửi cảnh báo Telegram | queue `alerts`, **container duy nhất giữ token Telegram** |
| `celery-beat` | hẹn giờ các task định kỳ | **chỉ 1 instance** |
| `cloudflared` | tunnel ra Cloudflare | |

---

## 1. Chuẩn bị VPS

Ubuntu 22.04 hoặc 24.04, tối thiểu 2 vCPU / 4 GB RAM (4 vCPU / 8 GB thì thoải mái).
Chỗ tốn RAM nhất là render Google Sheet thành ảnh trong `celery-worker`; nếu nó bị
OOM kill thì nâng `WORKER_MEM_LIMIT`.

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

**Phải đăng xuất rồi đăng nhập lại** để nhận group `docker`, nếu không mọi lệnh
docker sẽ đòi `sudo`. Kiểm tra:

```bash
docker compose version   # cần v2 trở lên
docker ps                # chạy được mà không cần sudo
gpg --version            # backup cần gpg; Ubuntu 24.04 có sẵn
```

## 2. Tạo Cloudflare Tunnel

Zero Trust → Networks → Tunnels → **Create a tunnel** → chọn *Cloudflared*.

1. Copy **token** của tunnel (chuỗi dài bắt đầu bằng `eyJ...`) → sẽ điền vào
   `CLOUDFLARE_TUNNEL_TOKEN`.
2. Tab **Public Hostname** → Add a public hostname:
   - Subdomain + Domain: ví dụ `zbridge` + `example.com`
   - Service Type: `HTTP`
   - URL: `frontend:8080` ← tên service trong compose, không phải localhost

Muốn chạy thử trước khi có domain thì dùng quick tunnel (`cloudflared tunnel --url
http://frontend:8080`, không cần token). Nhưng URL đổi mỗi lần restart nên
`APP_URL` và `ALERT_LINK_BASE_URL` sẽ trỏ sai — chỉ dùng để xem cho vui.

## 3. Lấy code và cấu hình

```bash
sudo mkdir -p /opt/zbridge && sudo chown "$USER:$USER" /opt/zbridge
git clone https://github.com/thaihoc1310/ZBridge.git /opt/zbridge
cd /opt/zbridge
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Đỡ phải gõ lệnh dài, thêm vào `~/.bashrc`:

```bash
echo "alias dc='docker compose -f docker-compose.prod.yml --env-file .env.prod'" >> ~/.bashrc
source ~/.bashrc
```

Từ đây tài liệu dùng `dc` thay cho lệnh đầy đủ.

### Sinh secret

```bash
openssl rand -hex 32      # JWT_SECRET
openssl rand -base64 32   # ZALO_GATEWAY_SECRET
openssl rand -base64 32   # ZALO_EVENT_SECRET
openssl rand -base64 32   # ZALO_SESSION_SECRET
openssl rand -base64 24   # POSTGRES_PASSWORD
openssl rand -base64 24   # BACKUP_PASSPHRASE
```

Điền hết vào `.env.prod`. Những chỗ dễ sai:

- **`DATABASE_URL` phải khớp** `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`.
  Sai là backend không kết nối được và `migrate` fail.
- **`POSTGRES_PASSWORD` chỉ có tác dụng lần đầu tiên** Postgres khởi tạo volume.
  Đổi sau đó thì phải `ALTER USER` trong DB rồi mới sửa `.env.prod`, chứ sửa file
  không thôi là mất kết nối.
- `APP_URL` và `ALERT_LINK_BASE_URL` = hostname công khai (`https://zbridge.example.com`).
  Link trong cảnh báo Telegram chỉ bấm được nếu đây là domain thật hoặc IP —
  Telegram không tạo link tới `localhost`.
- `COOKIE_SECURE=true` vì trình duyệt nói HTTPS với Cloudflare.
- `INITIAL_ADMIN_PASSWORD` **chỉ dùng khi tạo admin trên DB trắng**. Sau đó đổi
  mật khẩu phải làm trong web, sửa biến này không có tác dụng gì.
- `IMAGE_TAG` nên ghim theo SHA hoặc tag đã phát hành thay vì `latest`, để lần
  redeploy sau ra đúng thứ đã chạy.

**`.env.prod` không bao giờ được commit.** `.gitignore` đã chặn `.env.*`, nhưng
đừng đổi tên file thành dạng khác rồi commit lẫn.

## 4. Google Service Account (cho nhắc công nợ)

Đặt file credential vào `secrets/google-service-account.json`, rồi **đổi chủ sở
hữu sang uid của container**:

```bash
sudo chown 10001:10001 secrets/google-service-account.json
sudo chmod 400 secrets/google-service-account.json
```

Bỏ bước này thì `celery-worker` (chạy uid 10001) không đọc được file mode 600
thuộc `ubuntu`, và **mọi lượt nhắc công nợ fail với `GOOGLE_CREDENTIALS_INVALID`**.

Sau đó share thư mục Drive của từng khách hàng cho email service account
(dạng `xxx@yyy.iam.gserviceaccount.com`), quyền Viewer là đủ.

## 5. Deploy lần đầu

Image do CI build và đẩy lên `ghcr.io` (xem `.github/workflows/build.yml`). Nếu
package để private thì đăng nhập trước:

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
```

```bash
dc pull
dc up -d
dc ps
```

> **Đừng liệt kê tên service sau `up -d`.** `dc up -d` trơn tạo toàn bộ 11 service.
> Nếu gõ `dc up -d backend frontend ...` thì compose **chỉ** tạo những cái được gọi
> tên, và bạn sẽ thiếu service mà không có gì báo. Thiếu `celery-ai` là mất phần
> lọc AI; thiếu `celery-beat` là mất toàn bộ tự động hoá.

`migrate` chạy `alembic upgrade head` rồi thoát với code 0; `backend`,
`celery-worker`, `celery-beat` chỉ khởi động sau khi nó xong.

## 6. Kiểm tra sau deploy

```bash
# 1. Tất cả service phải Up, 5 cái có healthcheck phải healthy
dc ps

# 2. Migration đã chạy
dc logs migrate | grep -c "Running upgrade"

# 3. Bootstrap: phân quyền + admin
dc logs backend | grep -E "RBAC_SYNCED|INITIAL_ADMIN_CREATED"

# 4. Web + API qua tunnel
curl -s https://zbridge.example.com/health
curl -s -o /dev/null -w "%{http_code}\n" https://zbridge.example.com/docs      # phải 404
curl -s -o /dev/null -w "%{http_code}\n" https://zbridge.example.com/api/users # phải 401

# 5. Đăng nhập trả về cookie có Secure + HttpOnly
curl -si -X POST https://zbridge.example.com/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"<INITIAL_ADMIN_EMAIL>","password":"<INITIAL_ADMIN_PASSWORD>"}' \
  | grep -i set-cookie

# 6. Worker nghe đúng queue
dc logs celery-worker | grep -A2 "\[queues\]"   # celery
dc logs celery-ai     | grep -A2 "\[queues\]"   # ai
dc logs celery-alerts | grep -A2 "\[queues\]"   # alerts

# 7. Đường cảnh báo Telegram còn sống
dc exec -T backend python -c "
import json, os, urllib.request
urllib.request.urlopen(urllib.request.Request(
    'http://127.0.0.1:8000/internal/zalo/alerts',
    data=json.dumps({'code':'DEPLOY_SMOKE_TEST','message':'kiem tra sau deploy',
                     'severity':'WARNING'}).encode(),
    headers={'Content-Type':'application/json',
             'X-Zalo-Event-Secret':os.environ['ZALO_EVENT_SECRET']}))"
dc logs celery-alerts | grep ALERT_SENT   # rồi mở Telegram xem có tin không

# 8. celery-worker đọc được credential Google
dc exec -T celery-worker python -c "
import asyncio
from app.services.google_sheets_service import google_sheets
print('google token:', 'OK' if asyncio.run(google_sheets._access_token()) else 'FAIL')"

# 9. Đang chạy commit nào
git log --oneline -1
dc images | grep zbridge
```

## 7. Liên kết bot Zalo

Đăng nhập web bằng `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_PASSWORD` → **Zalo Bot**
→ *Kết nối Zalo* → quét QR bằng điện thoại. Session được mã hoá AES-256-GCM và lưu
trong volume `zalo-session`, nên restart không phải quét lại.

Sau đó **Khách hàng** → nút đồng bộ để nạp danh sách nhóm từ Zalo. Mỗi nhóm thành
một khách hàng. Vào từng khách hàng để bật *Tag tên tự động* và *Nhắc công nợ*.

Nếu trang Zalo Bot báo *"mất kênh nhận tin nhắn đến"* thì bot vẫn gửi được nhưng
không nhận được tin đến; gateway tự kết nối lại, và trong lúc đó tag tên tạm dừng
để không nhắc lại người đã trả lời.

## 8. Phân loại tag bằng AI

Khi có người tag một thành viên đã cấu hình, hệ thống quyết định theo 3 lớp:

1. **Luật** — câu khớp chính xác danh sách bỏ qua (`ok`, `cảm ơn`, `đã rõ`...) thì
   bỏ luôn, không gọi AI. Tag trống (chỉ `@Tên`, không có chữ nào khác) tạo task
   ngay nhưng vẫn được AI đọc lại trước lúc gửi.
2. **AI** — hệ thống gửi tối đa 20 tin gần nhất trong ngày và phân loại từng người:
   `NEED_RESPONSE` / `ACKNOWLEDGEMENT` / `FYI` / `UNCERTAIN`. Chỉ **giữ tag** khi
   là `NEED_RESPONSE` và confidence ≥ `LLM_MENTION_CONFIDENCE` (mặc định 0.65).
   AI đọc lại ngay trước mỗi lượt gửi, nên câu trả lời đầy đủ của người khác đến
   sau tin nguồn cũng có thể kết thúc vòng.
3. **Fail-closed** — không có API key hoặc LLM lỗi thì lượt tag tên được hoãn để
   thử phân loại lại, không gửi Zalo khi chưa có verdict. Tắt AI trong Settings là
   thao tác override có chủ đích và giữ hành vi tag trực tiếp.

Chỉ có **P1/P2** và **T1/T2** được gửi sang LLM; tên thật, user id Zalo và mention
đều bị thay bằng nhãn. Nếu chính target nói, trường `sender` dùng đúng nhãn
`T1/T2`, nên model biết người nói có phải người đang được chờ hay không. Mặc định
(`LLM_PROVIDER=fptcloud`) nội dung chỉ đi tới hạ
tầng FPT Cloud trong nước; khi đổi sang `openai` thì request gửi kèm `store=False`
nên OpenAI không lưu lại.

### Tag khi khách hỏi giá

Tính năng thứ hai trong cùng modal **Tag tên tự động** của từng khách hàng, mặc
định **tắt**. Khi bật, tin nhắn của người **không** nằm trong danh sách tag mà
chứa token `giá`, hoặc cụm `bao nhiêu tiền` / `bnh tiền`, sẽ được gửi cho AI hỏi
xem có phải hỏi giá thật không. Chỉ tag khi AI trả `NEED_RESPONSE` với confidence
≥ `LLM_PRICE_CONFIDENCE` (mặc định 0.65). Người được tag lấy từ danh sách riêng,
còn khung giờ và thời gian chờ dùng chung với tag nhắc việc.

> **Nhánh này fail-closed và không retry như tag nhắc việc.** AI lỗi, hết key, hoặc tắt
> bộ phân loại → **không tag ai**, vì không có ai tag trước cả và chỉ mỗi AI đứng
> giữa chữ "giá" vô tình với việc bot làm phiền nhóm khách. Hệ quả là khi AI chết
> thì tính năng tắt câm, nên có cảnh báo Telegram riêng cho trường hợp này.

Đo bằng `backend/bench/price_bench.py` trên 18 case: 0 lần tag sai ở mọi ngưỡng
từ 0.5 đến 0.95, không bỏ sót ở 0.65.

Bật/tắt và sửa danh sách câu bỏ qua ở menu **Phân loại tag** trong web. Menu chỉ
hiện với vai trò có quyền `mention_policy:manage` — đây là chính sách chung cho
mọi nhóm nên tách khỏi `mention:read`/`mention:update` (vốn chỉ là cấu hình tag
của từng khách hàng). ADMIN tự có; vai trò khác phải tick trong **Người dùng →
Sửa vai trò**.

Cần `FPTAI_API_KEY` trong `.env.prod`. Chi phí đo bằng `backend/bench` khoảng
**$0.00012/lượt** với `DeepSeek-V4-Flash` (so với ~$0.0002 của `gpt-5.4-nano`).
Đổi model chỉ cần sửa `LLM_PROVIDER` / `LLM_MODEL` / `LLM_MENTION_CONFIDENCE` rồi
`dc up -d celery-ai`, không cần build lại. Nếu `celery-ai` chết hoặc không được tạo, sau
`MENTION_CLASSIFICATION_DEADLINE_MINUTES` (mặc định 15) thì hệ thống hoãn tag tên
để thử lại, dừng lượt báo giá và **bắn cảnh báo
`MENTION_CLASSIFICATION_STUCK`** về Telegram.

Nội dung tin nhắn dùng làm ngữ cảnh chỉ lưu `MENTION_CONTEXT_RETENTION_HOURS` giờ
(mặc định 24) rồi bị xoá tự động; riêng tin nguồn của vòng đang chạy được giữ lại
đến khi task kết thúc.

## 9. Backup và phục hồi

Backup gồm dump Postgres và gói session Zalo, nén rồi **mã hoá GPG AES-256**, sau
đó đẩy lên bucket S3 tương thích. Với Cloudflare R2 (10GB miễn phí, egress miễn phí):

1. R2 → Create bucket, ví dụ `zbridge-backups`.
2. Manage API tokens → token **Object Read & Write**, giới hạn đúng bucket đó.
3. Điền vào `.env.prod`: `RCLONE_CONFIG_R2_ACCESS_KEY_ID`,
   `RCLONE_CONFIG_R2_SECRET_ACCESS_KEY`, `RCLONE_CONFIG_R2_ENDPOINT`,
   `BACKUP_REMOTE=r2:zbridge-backups/prod`, `BACKUP_PASSPHRASE`.
   Không cần chạy `rclone config` — rclone đọc thẳng biến môi trường.
   (Cloudflare còn đưa một "Token value" dạng `cfat_...` — cái đó cho Cloudflare API,
   **không dùng** ở đây.)
4. Đặt lifecycle rule trên bucket để tự xoá object cũ hơn 30–90 ngày.

```bash
# Tạo file log trước, nếu không cron ghi không được và bạn mất log âm thầm
sudo touch /var/log/zbridge-backup.log
sudo chown "$USER:$USER" /var/log/zbridge-backup.log

./deploy/backup.sh          # chạy thử một lần, xem có lên R2 không
crontab -e
```

```cron
0 */6 * * * cd /opt/zbridge && ./deploy/backup.sh >> /var/log/zbridge-backup.log 2>&1
```

Sáu tiếng một lần là đủ: dữ liệu do người nhập tay nên thay đổi chậm, mỗi dump chỉ
cỡ vài MB, và `pg_dump` dùng snapshot MVCC nên không lock, không downtime. Mất tối
đa 6 tiếng nghĩa là xấu nhất một khách vừa trả tiền bị đánh dấu còn nợ — sửa tay được.

Script từ chối giữ dump nhỏ bất thường, và **backup lỗi thì bắn cảnh báo CRITICAL
về Telegram**. Kiểm tra định kỳ:

```bash
docker run --rm --env-file .env.prod rclone/rclone ls r2:zbridge-backups/prod
tail -20 /var/log/zbridge-backup.log
```

**Giữ `BACKUP_PASSPHRASE` ở nơi khác ngoài VPS** (password manager). VPS cháy là mất
luôn `.env.prod`, và khi đó backup trên R2 thành rác không giải mã được.

### Phục hồi database

```bash
docker run --rm --env-file .env.prod -v /tmp/restore:/out rclone/rclone \
  copy r2:zbridge-backups/prod /out --include "postgres-*"
gpg -d /tmp/restore/postgres-YYYYmmdd-HHMMSS.sql.gz.gpg | gunzip | \
  dc exec -T postgres psql -U zbridge -d zbridge
```

### Phục hồi session Zalo (để đỡ quét QR lại)

```bash
gpg -d /tmp/restore/zalo-session-YYYYmmdd-HHMMSS.tgz.gpg | \
  docker run --rm -i -v zbridge_zalo-session:/data alpine tar xzf - -C /data
dc restart zalo-gateway
dc logs zalo-gateway | grep BOT_CONNECTED
```

Session chỉ giải mã được bằng **đúng `ZALO_SESSION_SECRET` lúc nó được ghi**. Đổi
secret đó mà không mã hoá lại thì buộc phải quét QR lần nữa. Mất volume
`zalo-session` chỉ tốn một lần quét QR, không mất dữ liệu nghiệp vụ.

## 10. Cập nhật phiên bản

```bash
cd /opt/zbridge
git fetch origin && git reset --hard origin/main
# sửa IMAGE_TAG trong .env.prod nếu ghim theo tag/SHA
dc pull
dc up -d
dc ps
```

`git reset --hard` **không** ảnh hưởng `.env.prod` và `secrets/` vì chúng đã được
gitignore. Migration tự chạy qua `migrate` trước khi backend mới lên.

## 11. Rollback

```bash
# 1. Đổi IMAGE_TAG trong .env.prod về SHA hoặc tag của bản chạy tốt trước đó
# 2. Đưa code về đúng commit đó (để compose file khớp với image)
git reset --hard <commit-cũ>
dc pull && dc up -d
```

Lưu ý: **migration không tự lùi.** Nếu bản mới có migration đổi schema thì rollback
image thôi có thể không đủ; phải `alembic downgrade` thủ công hoặc phục hồi từ backup:

```bash
dc run --rm migrate alembic downgrade -1
```

Vì vậy nên backup ngay trước mỗi lần deploy có migration mới:
`./deploy/backup.sh`.

## 12. Vận hành hằng ngày

```bash
dc ps                                  # trạng thái
dc logs -f backend                     # log API
dc logs -f celery-worker               # gửi tin, nhắc nợ, tag tên
dc logs -f celery-ai                   # phân loại AI
dc logs celery-alerts | grep ALERT_SENT   # cảnh báo đã gửi
dc restart zalo-gateway                # bot lỗi thì thử cái này trước
docker stats --no-stream               # RAM/CPU từng container
```

Lỗi được đẩy về Telegram theo mức `ALERT_MIN_SEVERITY`, gộp theo lần 1 / 10 / 100
rồi mỗi 500 lần trong mỗi cửa sổ `ALERT_DEDUP_WINDOW_SECONDS`. Ngoài ra
`celery-beat` ping `/health` mỗi `ALERT_HEARTBEAT_INTERVAL_SECONDS` giây, nên
backend hoặc database chết cũng có cảnh báo — đây là thứ duy nhất phát hiện được
"backend chết hẳn", vì lúc đó không có lỗi nào được ghi ra để mà đẩy đi.

## 13. Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `backend` không lên, `dc ps` thấy `migrate` exit ≠ 0 | `DATABASE_URL` không khớp mật khẩu Postgres, hoặc migration lỗi | `dc logs migrate` |
| `frontend` `unhealthy` nhưng web vẫn vào được | healthcheck resolve `localhost` ra IPv6 | đã sửa ở `31939f0`, đảm bảo compose dùng `127.0.0.1` |
| Nhắc công nợ fail `GOOGLE_CREDENTIALS_INVALID` | credential không thuộc uid 10001 | `sudo chown 10001:10001 secrets/google-service-account.json` |
| Nhắc công nợ fail `GOOGLE_DRIVE_ACCESS_DENIED` | chưa share thư mục Drive cho service account | share lại, quyền Viewer |
| Bot `AUTH_REQUIRED` sau khi đổi secret | `ZALO_SESSION_SECRET` đã đổi nên session cũ không giải mã được | quét QR lại, hoặc phục hồi session từ backup cũ |
| Cảnh báo `MENTION_CLASSIFICATION_STUCK` | `celery-ai` không chạy hoặc thiếu `FPTAI_API_KEY` | `dc ps`, `dc logs celery-ai`; tag vẫn được gửi, chỉ là không qua AI |
| Không có cảnh báo Telegram nào | `TELEGRAM_*` trống, hoặc `celery-alerts` chết | `dc logs celery-alerts \| grep ALERT_DROPPED` |
| `celery-worker` bị OOM kill khi nhắc nợ | sheet quá lớn khi render ảnh | nâng `WORKER_MEM_LIMIT` |
| Web trả bản cũ sau khi deploy | Cloudflare cache | `index.html` đã đặt `no-cache`; purge cache ở Cloudflare nếu vẫn vậy |
| Đăng nhập xong bị đăng xuất ngay | `COOKIE_SECURE=true` mà truy cập bằng HTTP | vào bằng HTTPS qua tunnel |

## 14. Ba giới hạn bắt buộc tôn trọng

- **`celery-beat` đúng 1 instance.** Hai scheduler là mọi task định kỳ bắn đôi,
  nghĩa là **khách hàng nhận nhắc công nợ hai lần**.
- **`zalo-gateway` đúng 1 instance.** Chỉ có một session Zalo; instance thứ hai sẽ
  bị Zalo đóng phiên (`DuplicateConnection`) và bot mất kết nối.
- **`celery-worker` phải luôn chạy.** Ngoài việc gửi tin, nó còn giữ cơ chế cứu hộ
  cho AI (nhả các lượt tag bị kẹt) và job dọn dữ liệu. Không có nó thì AI kẹt là
  kẹt vĩnh viễn.

Cả ba đã cố định trong `docker-compose.prod.yml` — đừng `--scale` chúng.

## 15. Tham chiếu biến môi trường

Xem `.env.prod.example` để có danh sách đầy đủ kèm chú thích. Nhóm chính:

- **Image**: `REGISTRY`, `IMAGE_OWNER`, `IMAGE_TAG`
- **Hạ tầng**: `POSTGRES_*`, `DATABASE_URL`, `REDIS_URL`, `TZ`
- **Địa chỉ công khai**: `APP_URL`, `COOKIE_SECURE`, `ALERT_LINK_BASE_URL`
- **Secret**: `JWT_SECRET`, `ZALO_GATEWAY_SECRET`, `ZALO_EVENT_SECRET`,
  `ZALO_SESSION_SECRET`, `INITIAL_ADMIN_*`
- **Tunnel**: `CLOUDFLARE_TUNNEL_TOKEN`, `CLOUDFLARED_VERSION`
- **Cảnh báo**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ALERT_MIN_SEVERITY`,
  `ALERT_DEDUP_WINDOW_SECONDS`, `ALERT_HEARTBEAT_INTERVAL_SECONDS`,
  `LOGIN_FAILURE_ALERT_THRESHOLD`, `LOGIN_FAILURE_WINDOW_SECONDS`
- **AI phân loại tag**: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`,
  `LLM_TIMEOUT_SECONDS`, `LLM_MENTION_CONFIDENCE`, `LLM_PRICE_CONFIDENCE`,
  `FPTAI_API_KEY`, `OPENAI_API_KEY`,
  `MENTION_CLASSIFIER_INTERVAL_SECONDS`, `MENTION_CLASSIFICATION_DEADLINE_MINUTES`,
  `MENTION_CONTEXT_MESSAGES`, `MENTION_CONTEXT_RETENTION_HOURS`
- **Backup**: `BACKUP_PASSPHRASE`, `BACKUP_REMOTE`, `RETENTION_DAYS`, `RCLONE_CONFIG_R2_*`
- **Giới hạn tài nguyên**: `*_MEM_LIMIT`, `CELERY_CONCURRENCY`, `AI_CONCURRENCY`,
  `ALERT_CONCURRENCY`

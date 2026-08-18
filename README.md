# ZBridge

Nền tảng quản trị và tự động hóa công việc lặp lại trong các nhóm Zalo, dành cho doanh nghiệp nhỏ. Hệ thống quản lý một Zalo personal account, các nhóm mà tài khoản tham gia và những luồng tự động như tag tên, nhắc hẹn hoặc nhắc thanh toán.

## Thành phần

- `frontend`: React 19 + Vite + TypeScript + TanStack Query + Tailwind.
- `backend`: FastAPI + SQLAlchemy 2 async + Alembic + PostgreSQL.
- `zalo-gateway`: Node.js + TypeScript, adapter cô lập `zca-js` 2.1.2.
- `postgres`: nguồn dữ liệu bền vững cho tài khoản, nhóm, lịch sử và lịch tự động hóa.
- `redis`: hàng đợi tác vụ nhanh, bật AOF để tăng khả năng phục hồi.
- `celery-worker` và `celery-beat`: thực thi tác vụ nền, retry và đánh thức lịch đến hạn.

Browser chỉ giao tiếp với FastAPI. Zalo Gateway không publish port ra host trong Docker Compose.

## Chạy nhanh bằng Docker

```bash
cp .env.example .env
# Thay toàn bộ secret/password trong .env trước khi dùng thật
docker compose up --build
```

Mở [http://localhost:5173](http://localhost:5173). API docs ở [http://localhost:5173/docs](http://localhost:5173/docs).

Tài khoản admin ban đầu lấy từ `INITIAL_ADMIN_EMAIL` và `INITIAL_ADMIN_PASSWORD`. Backend tự tạo tài khoản này sau khi migration hoàn tất.

## Chế độ demo không cần Zalo thật

Đặt trong `.env`:

```text
ZALO_MOCK=true
```

Gateway sẽ cung cấp ba nhóm mẫu và mô phỏng gửi thành công. Chế độ thật là `ZALO_MOCK=false`.

## Kết nối Google Drive và Google Sheets

Tính năng **Nhắc thanh toán công nợ** dùng tài khoản dịch vụ Google để đọc thư mục của khách hàng, chọn file Google Sheets đầu tiên theo tên, xuất tab đầu thành ảnh rồi gửi ảnh, link và nội dung nhắc vào nhóm Zalo. Lịch bắt đầu vào ngày cấu hình mỗi tháng và mặc định lặp lại sau mỗi 3 ngày cho tới khi khách hàng đã thanh toán.

1. Trong Google Cloud, bật **Google Drive API** và **Google Sheets API**.
2. Tạo một Service Account và tải khóa JSON.
3. Lưu khóa tại `secrets/google-service-account.json`. Không đưa file này lên Git.
4. Chia sẻ thư mục Drive chứa các thư mục khách hàng cho địa chỉ `client_email` trong khóa JSON với quyền **Viewer**. Có thể chia sẻ từng thư mục khách hàng nếu không có một thư mục cha chung.
5. Đặt trong `.env`:

```text
GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/google-service-account.json
```

Mỗi khách hàng cần có link thư mục Drive trong hồ sơ. File dùng để nhắc phải là Google Sheets native và nằm trực tiếp trong thư mục đó; hệ thống không chọn file `.xlsx`. Nếu ngày cấu hình không tồn tại trong một tháng, lịch sẽ chạy vào ngày cuối cùng của tháng đó.

## Luồng kết nối Zalo thật

1. Đăng nhập trang quản trị.
2. Mở **Zalo Bot** → **Kết nối Zalo**.
3. Quét QR bằng ứng dụng Zalo trên điện thoại.
4. Mở **Khách hàng**; hệ thống tự sync khi vào trang, hoặc dùng nút refresh.
5. Mở một khách hàng → **Tag tên tự động** → chọn thành viên và thời gian chờ.
6. Với khách còn nợ, thêm thư mục Drive rồi mở **Nhắc thanh toán công nợ** để đặt ngày, giờ và nội dung gửi hàng tháng.

Khi một tin nhắn trong nhóm tag người đã chọn, gateway chuyển sự kiện nội bộ cho backend. Lịch tag lại được lưu trong PostgreSQL; Celery Beat đưa lịch đến hạn qua Redis và Celery worker gửi tag qua gateway. Tin do bot gửi được bỏ qua để không tạo vòng lặp.

Credential (`cookie`, `imei`, `userAgent`) được mã hóa AES-256-GCM tại `/data/zalo-session/session.enc` bằng `ZALO_SESSION_SECRET`. File session và secret không được trả về frontend hoặc ghi log.

> `zca-js` là API không chính thức mô phỏng Zalo Web. Việc sử dụng có thể khiến tài khoản bị giới hạn hoặc khóa. Nên dùng tài khoản bot riêng, thử nghiệm có kiểm soát và tự chịu rủi ro vận hành.

> Mỗi tài khoản chỉ chạy được một Zalo Web listener tại một thời điểm. Không mở Zalo Web bằng cùng tài khoản bot khi gateway đang chạy, nếu không listener automation có thể bị ngắt. Ứng dụng Zalo trên điện thoại vẫn dùng để quét QR và quản lý tài khoản.

## Phát triển từng service

Backend (cần PostgreSQL đang chạy):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

Worker nền cần Redis:

```bash
celery -A app.celery_app:celery_app worker --loglevel=INFO
celery -A app.celery_app:celery_app beat --loglevel=INFO
```

Gateway:

```bash
cd zalo-gateway
npm install
npm run dev
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## API chính

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `GET /api/dashboard`
- `GET /api/bot/status`, `POST /api/bot/connect`, `GET /api/bot/qr`
- `POST /api/bot/reconnect`, `POST /api/bot/disconnect`
- `GET /api/customers`, `POST /api/customers/sync`, `GET /api/customers/{id}`
- `GET /api/customers/{id}/members`
- `GET /api/customers/{id}/mention-automation`, `PUT /api/customers/{id}/mention-automation`
- `GET /api/customers/{id}/debt-reminder`, `PUT /api/customers/{id}/debt-reminder`
- `GET /health`

Gateway internal API được bảo vệ bằng `X-Gateway-Secret` (trừ health check).

## Kiểm tra trước khi commit

```bash
cd backend && ruff check . && pytest -q
cd ../zalo-gateway && npm run typecheck && npm run build
cd ../frontend && npm run build
docker compose config
```

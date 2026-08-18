# Software Requirements Specification

## Zalo Bot Management System — Phase 1 / Base Platform

**Version:** 0.1
**Status:** Initial Architecture  
**Primary Zalo Integration:** `zca-js`  
https://github.com/RFS-ADRENO/zca-js

**Backend:** FastAPI  
**Frontend:** React + Vite  
**Purpose:** Xây dựng nền tảng quản lý Zalo Bot và các group trước khi bổ sung reminder, customer, billing, Google Sheet, report và các automation khác.

---

# 1. Mục tiêu hệ thống

Xây dựng một hệ thống web cho phép quản trị một tài khoản Zalo Bot và các group Zalo mà tài khoản đó đang tham gia.

Phase đầu tiên tập trung xây dựng **base platform ổn định**, gồm:

1. Kết nối một tài khoản Zalo với hệ thống thông qua `zca-js`.
    
2. Theo dõi trạng thái kết nối của bot.
    
3. Đồng bộ danh sách các group mà bot đang tham gia.
    
4. Hiển thị và quản lý các group trên giao diện web.
    
5. Lưu `group_id` tương ứng với từng group.
    
6. Cho phép admin chọn một group.
    
7. Nhập nội dung tin nhắn.
    
8. Gửi tin nhắn text vào group đó.
    
9. Lưu lịch sử gửi tin nhắn.
    
10. Hiển thị trạng thái gửi thành công hoặc thất bại.
    
11. Cho phép sync lại danh sách group khi bot:
    
    - được add vào group mới;
        
    - bị remove khỏi group;
        
    - group đổi tên;
        
    - thông tin group thay đổi.
        
12. Thiết kế architecture đủ sạch để sau này bổ sung:
    
    - customer management;
        
    - reminder thanh toán;
        
    - trạng thái thanh toán;
        
    - scheduler;
        
    - Google Sheet;
        
    - screenshot/report;
        
    - gửi ảnh;
        
    - gửi file;
        
    - nhiều Zalo account.
        

Mục tiêu của Phase 1 **không phải xây toàn bộ hệ thống automation/billing**.

Mục tiêu của Phase 1 là hoàn thiện được luồng:

```text
Admin
  │
  ▼
React + Vite
  │
  ▼
FastAPI
  │
  ▼
Zalo Gateway
Node.js + zca-js
  │
  ▼
Zalo Account
  │
  ▼
Zalo Group
```

---

# 2. MVP Definition

MVP đầu tiên được coi là thành công khi có thể thực hiện flow:

> **Tôi mở dashboard → thấy bot online → sync được các group bot đang tham gia → thấy danh sách group trên giao diện → chọn một group → nhập "hello" → bấm Send → tin nhắn xuất hiện đúng trong group đó.**

Đây là foundation của toàn bộ hệ thống sau này.

---

# 3. Phạm vi Phase 1

## 3.1 Trong phạm vi

Phase 1 phải có:

- Admin Web UI.
    
- FastAPI Backend.
    
- PostgreSQL Database.
    
- Node.js Zalo Gateway.
    
- Tích hợp `zca-js`.
    
- Login Zalo Bot.
    
- Re-login/reconnect bot.
    
- Persist Zalo session.
    
- Bot connection status.
    
- Bot health status.
    
- Đồng bộ danh sách group.
    
- Refresh lại danh sách group.
    
- Lưu `group_id`.
    
- Lưu tên group.
    
- Lưu thông tin cơ bản của group.
    
- Hiển thị danh sách group.
    
- Search group.
    
- Xem chi tiết group.
    
- Chọn một group.
    
- Nhập text.
    
- Gửi text vào group.
    
- Lưu message log.
    
- Hiển thị trạng thái:
    
    - `SENT`
        
    - `FAILED`
        
- Hiển thị lỗi gửi nếu có.
    

---

# 4. Ngoài phạm vi Phase 1

Các tính năng sau **chưa làm trong version đầu tiên**:

- Nhắc thanh toán tự động.
    
- Scheduler theo ngày.
    
- Mark khách hàng đã thanh toán.
    
- Customer management đầy đủ.
    
- Google Sheets.
    
- Google Drive.
    
- Screenshot.
    
- Export PDF.
    
- Gửi ảnh.
    
- Gửi file.
    
- Message template.
    
- Multi-account Zalo.
    
- Auto reply.
    
- Chatbot AI.
    
- Đọc/xử lý message từ khách.
    
- Analytics phức tạp.
    
- Redis.
    
- Worker queue.
    
- Celery.
    
- Kubernetes.
    

Architecture phải cho phép bổ sung các tính năng trên mà **không cần viết lại phần core Zalo integration**.

---

# 5. Kiến trúc tổng thể

```text
┌────────────────────────────────────────┐
│               Admin UI                 │
│                                        │
│      React + Vite + TypeScript         │
└──────────────────┬─────────────────────┘
                   │
                   │ HTTP / REST
                   ▼
┌────────────────────────────────────────┐
│             FastAPI Backend            │
│                                        │
│  Auth                                  │
│  Groups                                │
│  Messages                              │
│  Bot                                   │
│  Health                                │
│                                        │
│  Business Logic                        │
└──────────────┬─────────────┬───────────┘
               │             │
               │             ▼
               │        PostgreSQL
               │
               │ Internal HTTP
               ▼
┌────────────────────────────────────────┐
│             Zalo Gateway               │
│                                        │
│       Node.js + TypeScript             │
│                                        │
│       Zalo Adapter                     │
│            │                           │
│            ▼                           │
│          zca-js                        │
└──────────────────┬─────────────────────┘
                   │
                   ▼
           Zalo Personal Account
                   │
          ┌────────┼─────────┐
          ▼        ▼         ▼
       Group A  Group B ... Group N
```

---

# 6. Nguyên tắc kiến trúc

FastAPI là **backend chính của hệ thống**.

Zalo Gateway chỉ có trách nhiệm:

> giao tiếp với Zalo thông qua `zca-js`.

Không đặt business logic vào Zalo Gateway.

Ví dụ:

```text
Customer
Payment
Billing
Reports
Scheduler
Users
Permissions
Database
```

đều thuộc FastAPI.

Gateway chỉ xử lý:

```text
connect Zalo
get bot status
get groups
send text
```

Sau này:

```text
send image
send file
receive events
```

cũng nằm tại Gateway.

---

# 7. Tại sao cần Zalo Gateway

`zca-js` là JavaScript/Node.js library.

FastAPI là Python.

Do đó không thể thiết kế:

```text
FastAPI
   │
   ▼
zca-js
```

một cách trực tiếp.

Thay vào đó:

```text
FastAPI
   │
   │ Internal HTTP
   ▼
Node Zalo Gateway
   │
   ▼
zca-js
```

Ví dụ FastAPI muốn gửi message:

```text
FastAPI

POST http://zalo-gateway:3001/messages/text

{
  "group_id": "...",
  "content": "Hello"
}
```

Gateway nhận request và sử dụng `zca-js` để gửi tin nhắn.

---

# 8. Isolation của Zalo Gateway

Frontend **không được gọi trực tiếp Zalo Gateway**.

Không:

```text
Browser
   │
   ▼
Zalo Gateway
```

Mà bắt buộc:

```text
Browser
   │
   ▼
FastAPI
   │
   ▼
Zalo Gateway
```

Gateway chỉ accessible trong internal Docker/network.

Ví dụ:

```text
frontend
   │
   ▼
backend:8000
   │
   ▼
zalo-gateway:3001
```

Port Gateway không cần public ra Internet trong production.

---

# 9. Stack công nghệ

## 9.1 Frontend

**React + Vite + TypeScript**

Libraries:

```text
React
Vite
TypeScript
React Router
TanStack Query
Tailwind CSS
shadcn/ui
```

### Vai trò

Frontend chỉ chịu trách nhiệm:

- UI.
    
- Navigation.
    
- Form.
    
- API calls.
    
- State liên quan UI.
    
- Hiển thị trạng thái từ Backend.
    

Business logic không đặt ở frontend.

---

# 10. Backend

**FastAPI**

Language:

```text
Python 3.12+
```

Libraries:

```text
FastAPI
Pydantic
SQLAlchemy 2
Alembic
PostgreSQL Driver
HTTPX
```

HTTPX được sử dụng để FastAPI gọi internal Zalo Gateway.

Ví dụ:

```python
await client.post(
    "http://zalo-gateway:3001/messages/text",
    json={
        "group_id": group_id,
        "content": content
    }
)
```

---

# 11. Database

Database:

**PostgreSQL**

ORM:

**SQLAlchemy 2**

Migration:

**Alembic**

Database lưu:

- User(admin/user, admin xem được thông tin hệ thống, thông tin bot, .., hiện làm role admin trước vì cơ bản về sau role user cũng tương tự thôi)
    
- Bot.
    
- Group.
    
- Message.
    
    

Sau này bổ sung:

- Customer.
    
- Payment.
    
- Report.
    
- Scheduler Job.
    
- ....
    

---

# 12. Zalo Gateway

Runtime:

```text
Node.js
```

Language:

```text
TypeScript
```

Library chính:

```text
zca-js
```

Gateway không lưu business data.

Gateway chỉ quản lý:

- Zalo runtime state.
    
- Authentication/session.
    
- `zca-js` API instance.
    
- Group retrieval.
    
- Message sending.
    

---

# 13. Zalo Gateway Structure

Đề xuất:(tham khảo, bổ sung nếu cần thiết)

```text
zalo-gateway/
│
├── src/
│   ├── index.ts
│   │
│   ├── routes/
│   │   ├── health.ts
│   │   ├── bot.ts
│   │   ├── groups.ts
│   │   └── messages.ts
│   │
│   ├── zalo/
│   │   ├── client.ts
│   │   ├── adapter.ts
│   │   ├── session.ts
│   │   └── types.ts
│   │
│   └── config/
│
├── package.json
├── tsconfig.json
└── Dockerfile
```

---

# 14. Zalo Adapter

Không được gọi `zca-js` rải rác trong Gateway.

Tạo abstraction:(tham khảo, bổ sung nếu cần thiết)

```typescript
interface ZaloClient {
  connect(): Promise<void>;

  disconnect(): Promise<void>;

  getStatus(): Promise<ConnectionStatus>;

  getGroups(): Promise<ZaloGroup[]>;

  sendText(
    groupId: string,
    content: string
  ): Promise<SendResult>;
}
```

Implementation:

```text
ZaloClient
    │
    ▼
ZcaJsClient
    │
    ▼
zca-js
```

Nếu sau này cần fork:

```text
ZaloClient
    │
    ├── ZcaJsClient
    │
    └── CustomZcaClient
```

Các route của Gateway không phụ thuộc trực tiếp implementation bên dưới.

---

# 15. Lợi ích của Zalo Adapter

Giả sử một ngày `zca-js` lỗi do Zalo đổi protocol.

Không cần sửa:

```text
Frontend
FastAPI
Database
Groups Module
Messages Module
Customer Module
Billing Module
Scheduler
```

Chỉ cần sửa:

```text
Zalo Gateway
    │
    ▼
ZcaJsClient
```

Hoặc thay:

```text
zca-js
```

bằng một implementation khác.

---

# 16. Deployment Phase 1

Sử dụng:

**Docker Compose**

Services:

```text
docker-compose
│
├── frontend
├── backend
├── zalo-gateway
└── postgres
```

Chưa cần:

```text
Redis
Celery
Kafka
Kubernetes
Temporal
```

---

# 17. Network Architecture

Production:

```text
                   Internet
                      │
                      ▼
                    Nginx
                      │
           ┌──────────┴───────────┐
           ▼                      ▼
      Frontend                 /api/*
     static files                │
                                 ▼
                              FastAPI
                                 │
                        ┌────────┴────────┐
                        ▼                 ▼
                   PostgreSQL       Zalo Gateway
                                          │
                                          ▼
                                        Zalo
```

Zalo Gateway không expose public endpoint.

---

# 18. Zalo Bot Account

Phase 1 hỗ trợ:

**1 Zalo account.**

Ví dụ:

```text
Account:
Company Billing Bot
```

Account này được add vào các group:

```text
Billing Bot
   │
   ├── Group khách A
   ├── Group khách B
   ├── Group khách C
   ├── ...
   └── Group khách 100
```

Database vẫn nên thiết kế để sau này hỗ trợ nhiều account nếu cần.

---

# 19. Bot Status

Dashboard phải hiển thị trạng thái bot.(với admin)

Ví dụ:

```text
ZALO BOT

● Connected

Account
Billing Bot

Groups
103

Last sync
18:00 14/08/2026

Last successful message
18:05 14/08/2026
```

Các status:

```text
CONNECTED
DISCONNECTED
CONNECTING
AUTH_REQUIRED
ERROR
```

---

# 20. Bot Connection Flow

Nếu chưa có session:(tham khảo, bổ sung nếu cần thiết, đọc kĩ zca-js)

```text
Admin
   │
   ▼
Connect Bot
   │
   ▼
FastAPI
   │
   ▼
Zalo Gateway
   │
   ▼
zca-js
   │
   ▼
Generate Login QR
   │
   ▼
Frontend hiển thị QR
   │
   ▼
Admin scan QR bằng Zalo
   │
   ▼
Authenticated
   │
   ▼
CONNECTED
```

---

# 21. Authentication UI(tham khảo, bổ sung nếu cần thiết, đọc kĩ zca-js)

Bot page:

```text
ZALO BOT

Status

🔴 Authentication Required

[ Connect Zalo ]
```

Sau khi click:

```text
Scan QR Code bằng Zalo

┌────────────────────┐
│                    │
│      QR CODE       │
│                    │
└────────────────────┘
```

Login thành công:

```text
🟢 Connected
```

---

# 22. Session Management

Zalo session phải được persist.

Không được yêu cầu scan QR mỗi lần Gateway restart nếu credential/session hiện tại vẫn còn hợp lệ.

Flow:

```text
Zalo Gateway starts
       │
       ▼
Load saved session
       │
       ▼
Try authenticate
       │
       ├──────── Success
       │            │
       │            ▼
       │        CONNECTED
       │
       └──────── Failed
                    │
                    ▼
              AUTH_REQUIRED
```

---

# 23. Session Storage(tham khảo, bổ sung nếu cần thiết)

Phase 1 có thể lưu Zalo session trong:

```text
encrypted persistent volume
```

Ví dụ:

```text
/data/zalo-session/
```

Không được:

- lưu session trong source code;
    
- commit session lên Git;
    
- gửi credential xuống frontend;
    
- log credential ra console.
    

Sau này có thể chuyển session storage sang database/secret manager nếu cần.

---

# 24. Bot Management Page

Route:

```text
/bot
```

Ví dụ UI:

```text
ZALO BOT

Connection
● Connected

Account
Billing Bot

Zalo User ID
983479823749

Groups discovered
103

Session
Active

Last health check
18:10

────────────────────────

[ Reconnect ]

[ Logout ]
```

---

# 25. Group Synchronization

Admin có button:

```text
[ Sync Groups ]
```

Flow:

```text
Admin
   │
   ▼
FastAPI
   │
   ▼
Zalo Gateway
   │
   ▼
zca-js
   │
   ▼
Get groups
   │
   ▼
FastAPI
   │
   ▼
Compare with database
   │
   ├── Insert
   ├── Update
   └── Mark unavailable
```

---

# 26. Group Sync Use Cases

Group sync phải xử lý được:

### Bot được add vào group mới

```text
Zalo:
A
B
C

Database:
A
B
```

Kết quả:

```text
C → INSERT
```

---

### Group đổi tên

Trước:

```text
ABC Support
```

Sau:

```text
ABC Support 2026
```

Sync:

```text
UPDATE name
```

Nhưng giữ nguyên:

```text
zalo_group_id
```

---

### Bot bị remove khỏi group

Không DELETE database record.

Thay:

```text
is_available = false
```

Mục đích:

- giữ history;
    
- giữ mapping tương lai;
    
- giữ audit.
    

---

### Bot được add lại

Nếu `zalo_group_id` xuất hiện lại:

```text
is_available = true
```

---

# 27. Group Database Model

Mỗi group lưu tối thiểu:

```text
id
zalo_account_id
zalo_group_id
name
avatar_url
member_count
is_available
last_synced_at
created_at
updated_at
```

Unique constraint:

```text
(zalo_account_id, zalo_group_id)
```

---

# 28. Trang Group List

Route:

```text
/groups
```

UI:

```text
Groups                                  [ Sync Groups (ko cần text, chỉ cần icon sync là được) ]

Search
[________________________________]  [filter button icon, khi bấm vào thì hiện 1 cái tab over lay hiện lên và có các cái option filter]

┌─────────────────────────────────────────────────────────┐
│ Group                     Members      Status           │
├─────────────────────────────────────────────────────────┤
│ ABC - Accounting             12        ● Available      │
│ XYZ Support                  18        ● Available      │
│ Customer Test                 6        ● Available      │
│ Old Customer                 14        ○ Unavailable    │
└─────────────────────────────────────────────────────────┘
```

---

# 29. Search Group

Cho phép search theo:

```text
group name
group id
```

Ví dụ:

```text
Search: ABC
```

Result:

```text
ABC Accounting
ABC Support
ABC Technical
```

---

# 30. Group Detail

Route:

```text
/groups/:id
```

Ví dụ:

```text

cột bên phải
ABC - Accounting

Status
● Available

Zalo Group ID
398274982374928374

Members
14

Last synced
14/08/2026 18:00

────────────────────────────
cột bên trái 
SEND MESSAGE button
(khi bấm vào thì hiện 1 popup tab lên kiểu 
┌───────────────────────────────┐
│ Nhập nội dung tin nhắn...     │
│                               │
│                               │
└───────────────────────────────┘
								[ Send ]
)

                      
```

---

# 31. Manual Send Message

Đây là **core feature quan trọng nhất Phase 1**.

Admin:

```text
Select group
    ↓
Enter message
    ↓
Send
```

Full flow:

```text
React UI
   │
   ▼
POST /api/groups/:id/messages
   │
   ▼
FastAPI Message Service
   │
   ├── Validate Group
   ├── Validate Bot
   ├── Create Message Record
   │
   ▼
Zalo Gateway
   │
   ▼
zca-js
   │
   ▼
Zalo
   │
   ▼
Target Group
```

---

# 32. Send Message Flow chi tiết

Frontend gửi:

```http
POST /api/groups/{id}/messages
```

Payload:

```json
{
  "type": "TEXT",
  "content": "Xin chào"
}
```

FastAPI:

```text
1. Find group in DB

2. Check:
   is_available == true

3. Check bot status

4. Create message:
   status = SENDING

5. Call Zalo Gateway
```

Internal request:

```http
POST /messages/text
```

Payload:

```json
{
  "group_id": "398274982374928374",
  "content": "Xin chào"
}
```

Gateway gọi:

```text
zca-js
```

Sau đó trả result cho FastAPI.

---

# 33. Successful Send

Nếu thành công:

FastAPI update:

```text
status = SENT
sent_at = now()
zalo_message_id = ...
```

Frontend hiển thị:

```text
✓ Message sent successfully
```

---

# 34. Failed Send

Nếu thất bại:

```text
status = FAILED
error_code = ...
error_message = ...
```

UI:

```text
✕ Message could not be sent.

Reason:
Bot is disconnected.
```

Không chỉ hiển thị:

```text
500 Internal Server Error
```


nghĩa là khi sent message sẽ hiện 1 cái vòng tròn xoay ở giữa over lay all  màn hình, khi có state thì hiện success hay failed gì đó kèm reason
---

# 35. Confirmation Before Send

Để tránh click nhầm:

```text
Send message?

Group:
ABC - Accounting

Message:
Xin chào...

[ Cancel ]          [ Send ]
```

Có thể bỏ confirmation trong development nếu thấy gây khó chịu, nhưng production nên có.

---

# 36. Message Model

Table:

```text
messages
```

Fields:

```text
id
zalo_group_id
type
content
status
zalo_message_id
error_code
error_message
created_at
sent_at
```

Phase 1:

```text
type = TEXT
```

Status:

```text
SENDING
SENT
FAILED
```

---

# 37. Message History

Group Detail hiển thị:
cả 1 tab là MESSAGE HISTORY, khi bấm vào thì nó hiện 1 popup tab lên , cho search, filter theo ngày, ....
```text
MESSAGE HISTORY

14/08 18:10

✓ SENT

Hello


14/08 18:05

✕ FAILED

Test

Error:
BOT_DISCONNECTED
```

---

# 38. Dashboard

Route:

```text
/
```

UI cơ bản:

```text
Zalo Bot Dashboard

mấy cái box dưới hiện theo hàng ngang nhé, ở dưới sẽ là chart analytics nhma chưa cần impliment

┌─────────────────────┐
│ Bot                 │
│ ● Connected         │
└─────────────────────┘

┌─────────────────────┐
│ Groups              │
│ 103                 │
└─────────────────────┘

┌─────────────────────┐
│ Messages Today      │
│ 12                  │
└─────────────────────┘

┌─────────────────────┐
│ Failed Today        │
│ 1                   │
└─────────────────────┘
```



Không cần analytics phức tạp trong Phase 1.

---

# 39. FastAPI Module Structure

Đề xuất:(tham khảo, bổ sung, thay đổi nếu cần thiết )

```text
backend/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── auth.py
│   │   ├── bot.py
│   │   ├── groups.py
│   │   ├── messages.py
│   │   └── health.py
│   │
│   ├── services/
│   │   ├── bot_service.py
│   │   ├── group_service.py
│   │   ├── message_service.py
│   │   └── zalo_gateway_client.py
│   │
│   ├── models/
│   │
│   ├── schemas/
│   │
│   ├── repositories/
│   │
│   ├── core/
│   │
│   └── db/
│
├── alembic/
├── tests/
├── pyproject.toml
└── Dockerfile
```

---

# 40. Zalo Gateway Client trong FastAPI

FastAPI không được gọi raw HTTP rải rác khắp project.(tham khảo, bổ sung, thay đổi nếu cần thiết )

Tạo:

```text
ZaloGatewayClient
```

Interface logic:

```python
class ZaloGatewayClient:

    async def get_status(self):
        ...

    async def get_groups(self):
        ...

    async def connect(self):
        ...

    async def send_text(
        self,
        group_id: str,
        content: str
    ):
        ...
```

Business modules chỉ gọi:

```text
ZaloGatewayClient
```

Không biết:

```text
zca-js
```

là gì.

---

# 41. FastAPI API Specification(tham khảo, bổ sung, thay đổi nếu cần thiết )

## Bot Status

```http
GET /api/bot/status
```

Response:

```json
{
  "status": "CONNECTED",
  "account_name": "Billing Bot",
  "group_count": 103
}
```

---

# 42. Connect Bot

```http
POST /api/bot/connect
```

Bắt đầu Zalo authentication.

---

# 43. Get Login QR

```http
GET /api/bot/qr
```

Response có thể chứa:

```json
{
  "status": "WAITING_FOR_SCAN",
  "qr": "..."
}
```

Có thể dùng:

- base64 image;
    
- hoặc temporary QR endpoint.
    

---

# 44. Reconnect Bot

```http
POST /api/bot/reconnect
```

---

# 45. Disconnect Bot

```http
POST /api/bot/disconnect
```

---

# 46. Group APIs

List:

```http
GET /api/groups
```

Query:

```text
search=
status=
page=
limit=
```

---

Get detail:

```http
GET /api/groups/{id}
```

---

Sync: (mặc định gọi khi vào page group hoặc f5 , ...)

```http
POST /api/groups/sync
```

---

# 47. Message APIs

Send:

```http
POST /api/groups/{id}/messages
```

Request:

```json
{
  "type": "TEXT",
  "content": "Xin chào..."
}
```

Response:

```json
{
  "id": "msg_123",
  "status": "SENT"
}
```

---

History:

```http
GET /api/groups/{id}/messages
```

---

# 48. Zalo Gateway Internal API

Các endpoint này **không public cho frontend**.

## Health

```http
GET /health
```

---

## Bot Status

```http
GET /bot/status
```

---

## Connect

```http
POST /bot/connect
```

---

## QR

```http
GET /bot/qr
```

---

## Reconnect

```http
POST /bot/reconnect
```

---

## Groups

```http
GET /groups
```

---

## Send Text

```http
POST /messages/text
```

Request:

```json
{
  "group_id": "398274982374928374",
  "content": "Hello"
}
```

---

# 49. Database Schema

## users ( chưa cần role)

```text
id
email
password_hash
created_at
updated_at
```

---

## zalo_accounts

```text
id
zalo_user_id
display_name
status
last_connected_at
last_error
created_at
updated_at
```

Phase 1 chỉ có một bot.

---

## zalo_groups

```text
id
zalo_account_id
zalo_group_id
name
avatar_url
member_count
is_available
last_synced_at
created_at
updated_at
```

Unique:

```text
(zalo_account_id, zalo_group_id)
```

---

## messages

```text
id
zalo_group_id
type
content
status
zalo_message_id
error_code
error_message
created_at
sent_at
```

---

# 50. Admin Authentication

Admin UI không public hoàn toàn.

Phase 1 tối thiểu hỗ trợ:

```text
email
password
```

Có thể sử dụng:

```text
JWT
+
HTTP-only cookie
```

Password hash:

```text
Argon2
```

Không lưu plain password.

---

# 51. Zalo Credentials Security

Zalo credential:

- Không expose frontend.
    
- Không gửi về browser.
    
- Không log.
    
- Không commit Git.
    
- Không lưu plain text trong source.
    
- Không đưa vào message log.
    

Nếu lưu persistent file:

```text
/data/zalo-session
```

volume phải được bảo vệ.

---


---

# 53. Error Handling(tham khảo, bổ sung, thay đổi nếu cần thiết )

FastAPI phải normalize các lỗi Gateway thành error code của hệ thống.

Tối thiểu:

```text
BOT_DISCONNECTED
AUTH_REQUIRED
GROUP_NOT_FOUND
GROUP_UNAVAILABLE
SEND_FAILED
ZALO_GATEWAY_UNAVAILABLE
ZALO_API_ERROR
UNKNOWN_ERROR
```

---

# 54. Bot mất kết nối

Flow:

```text
Admin sends message
       │
       ▼
FastAPI
       │
       ▼
Check bot
       │
    OFFLINE
       │
       ▼
Do not send
       │
       ▼
Return BOT_DISCONNECTED
```

UI:

```text
Bot is currently disconnected.

Please reconnect the bot before sending.
```

---

# 55. Gateway chết

Ví dụ:

```text
FastAPI
   │
   ▼
Zalo Gateway

Connection refused
```

FastAPI trả:

```text
ZALO_GATEWAY_UNAVAILABLE
```

Không crash Backend.

Dashboard phải có thể hiện:

```text
Bot status unavailable
```

---

# 56. Health Check

FastAPI:

```http
GET /health
```

Response:

```json
{
  "api": "UP",
  "database": "UP",
  "zalo_gateway": "UP",
  "zalo": "CONNECTED"
}
```

---

Gateway:

```http
GET /health
```

Response:

```json
{
  "gateway": "UP",
  "zalo": "CONNECTED"
}
```

---

# 57. Logging

FastAPI log:

```text
GROUP_SYNC_STARTED
GROUP_SYNC_COMPLETED

MESSAGE_SEND_STARTED
MESSAGE_SENT
MESSAGE_FAILED

ZALO_GATEWAY_ERROR
```

Gateway log:

```text
BOT_CONNECTING
BOT_CONNECTED
BOT_DISCONNECTED
BOT_AUTH_REQUIRED

ZALO_SEND_STARTED
ZALO_SEND_SUCCESS
ZALO_SEND_FAILED
```

Không log session secrets.

---

# 58. Non-functional Requirements

## Performance

Phase 1 phải hỗ trợ tối thiểu:

```text
500 groups
```

Danh sách group load:

```text
< 2 seconds
```

trong điều kiện bình thường.

Manual send không cần throughput cao.

---

# 59. Reliability

Restart FastAPI không được làm mất:

- group;
    
- message history;
    
- configuration.
    

Restart Zalo Gateway không được làm mất session nếu credential hiện tại vẫn valid.

---

# 60. Maintainability

Business logic không được phụ thuộc trực tiếp vào `zca-js`.

Không:

```text
FastAPI
   ↓
zca-js-specific logic
```

Đúng:

```text
FastAPI
   ↓
ZaloGatewayClient
   ↓
Gateway API
   ↓
ZaloClient interface
   ↓
zca-js
```

---

# 61. Repository Structure(tham khảo, bổ sung, thay đổi nếu cần thiết )

Không cần Turborepo vì project có cả Python và Node.

Đề xuất một repository:

```text
zalo-management/
│
├── frontend/
│   ├── src/
│   ├── package.json
│   └── Dockerfile
│
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── zalo-gateway/
│   ├── src/
│   ├── package.json
│   └── Dockerfile
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

Đây là **monorepo theo nghĩa một repository**, nhưng không cần JS monorepo framework.

---

# 62. Frontend Structure(tham khảo, bổ sung, thay đổi nếu cần thiết )

```text
frontend/src/
│
├── api/
│
├── components/
│
├── features/
│   ├── auth/
│   ├── bot/
│   ├── groups/
│   └── messages/
│
├── pages/
│
├── routes/
│
├── lib/
│
└── main.tsx
```

---

# 63. Frontend Routes(tham khảo, bổ sung, thay đổi nếu cần thiết )

Phase 1:

```text
/login

/

/bot

/groups

/groups/:id
```

---

# 64. Environment Variables(tham khảo, bổ sung, thay đổi nếu cần thiết )

Root `.env` / service-specific env:

```text
DATABASE_URL=

JWT_SECRET=

ZALO_GATEWAY_URL=

ZALO_GATEWAY_SECRET=

ZALO_SESSION_PATH=

APP_URL=

API_URL=
```

Frontend chỉ được expose env public cần thiết.

Không expose:

```text
DATABASE_URL
JWT_SECRET
ZALO session
Gateway secret
```

---

# 65. Local Development(tham khảo, bổ sung, thay đổi nếu cần thiết )

Developer environment:

```text
Developer PC
    │
    ├── React + Vite
    ├── FastAPI
    ├── Node Zalo Gateway
    └── PostgreSQL
```

Hoặc toàn bộ:

```bash
docker compose up
```

---

# 66. Docker Compose
(tham khảo, bổ sung, thay đổi nếu cần thiết )
Concept:

```text
services:

frontend
   │
   └── React/Vite

backend
   │
   └── FastAPI

zalo-gateway
   │
   └── Node + zca-js

postgres
```

Internal connectivity:

```text
backend
  │
  ├── postgres:5432
  │
  └── zalo-gateway:3001
```

---

---

# 68. Acceptance Criteria

Phase 1 được coi là DONE khi:

-  Có React + Vite Admin UI.
    
-  Có FastAPI Backend.
    
-  Có PostgreSQL.
    
-  Có SQLAlchemy models.
    
-  Có Alembic migrations.
    
-  Có Node.js Zalo Gateway.
    
-  Gateway tích hợp `zca-js`.
    
-  Admin login được.
    
-  Zalo Bot login bằng QR được.
    
-  Bot status hiển thị trên UI.
    
-  Session survive Gateway restart nếu vẫn hợp lệ.
    
-  Sync được danh sách group.
    
-  Group được lưu database.
    
-  Group mới được phát hiện sau sync.
    
-  Group bị remove được mark unavailable.
    
-  Group đổi tên được update.
    
-  UI hiển thị danh sách group.
    
-  Search được group.
    
-  Xem được `group_id`.
    
-  Chọn được một group.
    
-  Nhập được text.
    
-  Gửi được text vào group thật.
    
-  Tin xuất hiện đúng group.
    
-  Message được lưu database.
    
-  Hiển thị SENT.
    
-  Hiển thị FAILED và reason nếu lỗi.
    
-  Có message history.
    
-  Có FastAPI health endpoint.
    
-  Có Gateway health endpoint.
    
-  Zalo credentials không expose frontend.
    
    
-  Có Docker Compose để dựng toàn bộ system.
    

---


---

# 70. Milestone 1 — Zalo PoC

Trước khi làm UI đẹp, phải chứng minh:

```text
Node.js
   ↓
zca-js
   ↓
QR Login
   ↓
Get Groups
   ↓
Select Group ID
   ↓
Send "hello"
   ↓
Message appears
```

Nếu đoạn này không ổn thì dừng và xử lý Zalo integration trước.

---

# 71. Milestone 2 — Gateway

Sau PoC:

```text
curl
  │
  ▼
POST /messages/text
  │
  ▼
Zalo Gateway
  │
  ▼
zca-js
  │
  ▼
Group
```

Gateway phải hoạt động độc lập với FastAPI trước.

---

# 72. Milestone 3 — FastAPI Integration

Sau đó:

```text
FastAPI
   │
   ▼
ZaloGatewayClient
   │
   ▼
Gateway
```

FastAPI phải:

- get bot status;
    
- sync group;
    
- send text.
    

---

# 73. Milestone 4 — UI

Sau khi backend flow ổn mới hoàn thiện:

```text
Dashboard
Bot Page
Groups
Group Detail
Send Message
History
```

Không làm UI trước khi Zalo flow đã được chứng minh.

---

# 74. Phase 1.1 — Media

Khi Phase 1 ổn:

```text
TEXT
 ↓
IMAGE
 ↓
FILE
```

Bổ sung Gateway:

```text
POST /messages/image

POST /messages/file
```

Frontend:

```text
Send Message

[ Text ]
[ Image ]
[ File ]
```

---

# 75. Phase 2 — Customer Management (chưa cần impliment 75 76 77 78 đâu nhé :))

Sau đó mới tạo domain:

```text
Customer
   │
   ▼
Zalo Group
```

Customer model:

```text
id
name
zalo_group_id
google_sheet_url
active
created_at
updated_at
```

---

# 76. Phase 3 — Billing

Thêm:

```text
Billing Cycle

UNPAID
PAID
OVERDUE
```

Admin:

```text
[ Mark as Paid ]
```

---

# 77. Phase 4 — Scheduler / Queue

Lúc này mới thêm:

```text
Redis
+
Celery / task worker
```

Flow:

```text
Due Date
   │
   ▼
Queue Reminder
   │
   ▼
Worker
   │
   ▼
FastAPI/Zalo integration
   │
   ▼
Group
```

Không cần Redis trong Phase 1 manual-send.

---

# 78. Phase 5 — Google Sheet / Report

```text
Customer
   │
   ▼
Google Sheet
   │
   ▼
First Tab
   │
   ├── PDF
   └── PNG
         │
         ▼
      Zalo
```

---

# 79. Kiến trúc dài hạn

```text
                     React + Vite
                          │
                          ▼
                        FastAPI
                          │
        ┌─────────────────┼──────────────────┐
        │                 │                  │
        ▼                 ▼                  ▼
    Customers          Billing           Reports
        │                 │                  │
        └─────────────────┼──────────────────┘
                          │
                          ▼
                       Scheduler
                          │
                          ▼
                        Queue
                          │
                ┌─────────┴─────────┐
                ▼                   ▼
         Messaging Worker      Report Worker
                │                   │
                │              Google API
                │                   │
                │              PNG / PDF
                │                   │
                └─────────┬─────────┘
                          ▼
                    Zalo Gateway
                          │
                          ▼
                        zca-js
                          │
                          ▼
                   Zalo Bot Account
                          │
              ┌───────────┼────────────┐
              ▼           ▼            ▼
           Group 1     Group 2      Group 100
```

---


# 82. Final Phase 1 Goal

Kết quả cuối Phase 1 cần đạt được:

```text
              Admin Dashboard
                    │
                    ▼
              Bot: CONNECTED
                    │
                    ▼
              100+ Zalo Groups
                    │
                    ▼
              Select One Group
                    │
                    ▼
               Enter Message
                    │
                    ▼
                   Send
                    │
                    ▼
                 FastAPI
                    │
                    ▼
              Zalo Gateway
                    │
                    ▼
                  zca-js
                    │
                    ▼
                Zalo Group
                    │
                    ▼
            Message Received ✓
```

Sau khi foundation này ổn định mới bắt đầu phát triển các automation liên quan đến customer, billing, reminder và report.

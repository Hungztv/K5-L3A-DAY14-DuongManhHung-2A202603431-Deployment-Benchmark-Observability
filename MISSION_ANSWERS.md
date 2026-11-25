# Day 14 Lab — Mission Answers

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong mã nguồn (dòng 17–18):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub sẽ lộ secret ngay lập tức và vẫn nằm trong lịch sử git dù xoá file sau đó.
2. **Hardcode cấu hình vận hành (dòng 21–22):** `DEBUG = True` và `MAX_TOKENS = 500` viết cứng trong code, không thể thay đổi giữa dev / staging / production mà không sửa code.
3. **Dùng `print()` thay cho structured logging và in trực tiếp secret ra log (dòng 33–34):** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa khó tìm kiếm/lọc trên hệ thống log tập trung (Loki, Datadog), vừa làm lộ API key ra stdout.
4. **Không có Health Check & Readiness endpoint (`/health`, `/ready`):** Gọi `GET /health` trả về `404 Not Found`. Cloud platform (Render, Railway, Kubernetes) không thể biết container còn sống hay đã sẵn sàng nhận traffic để tự động restart hoặc ngắt route.
5. **Bind cứng `host="localhost"` và `port=8000` (dòng 51–52):** `localhost` chỉ lắng nghe loopback bên trong container (không nhận traffic từ ngoài container/proxy); port cố định `8000` không đọc biến `PORT` do nền tảng cloud cấp phát.
6. **Bật `reload=True` (dòng 53):** Chế độ auto-reload tiêu tốn tài nguyên theo dõi file và có thể làm gián đoạn request đột ngột trong môi trường production.
7. **Không có cơ chế Graceful Shutdown & Lifespan:** Khi container nhận `SIGTERM`, process dừng đột ngột làm cắt ngang các request đang xử lý và không đóng kết nối sạch sẽ.

### Exercise 1.2: Kết quả chạy bản `develop`

```bash
# GET /
HTTP 200
{"message":"Hello! Agent is running on my machine :)"}

# POST /ask?question=Hello (bản develop nhận question qua query param)
HTTP 200
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

# GET /health
HTTP 404
{"detail":"Not Found"}
```

### Exercise 1.3: So sánh `develop/app.py` vs `production/app.py`

Kết quả gọi bản `production` (chạy với `ENVIRONMENT=staging`):
- `GET /health` → `200`: `{"status":"ok","uptime_seconds":0.7,"version":"1.0.0","environment":"staging","timestamp":"2026-11-25T13:46:15.696010+00:00"}`
- `GET /ready` → `200`: `{"ready":true}`
- `POST /ask` (JSON `{"question":"Hello"}`) → `200`: `{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock)...","model":"gpt-4o-mini"}`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py`) | Tại sao quan trọng? |
| --- | --- | --- | --- |
| **Config & Secrets** | Hardcode trực tiếp (`OPENAI_API_KEY`, `DATABASE_URL`, dòng 17–18) | Đọc từ biến môi trường qua `config.settings` (dòng 24, 196–198) | Tuân thủ 12-Factor: không lộ secret lên git, cùng một image chạy được ở dev/staging/prod chỉ bằng cách đổi env vars. |
| **Health & Readiness** | Không có (`GET /health` → 404) | Có `GET /health` (dòng 135) và `GET /ready` trả 503 khi chưa ready (dòng 152) | Platform biết container còn sống (liveness) để restart và load balancer biết khi nào sẵn sàng nhận traffic (readiness). |
| **Logging** | `print()` plain text và in cả `OPENAI_API_KEY` (dòng 33–34) | Structured JSON logging qua `logging` + `json.dumps` (dòng 28–32, 111–122), không log secret | Dễ parse, tìm kiếm, lọc theo field (`event`, `level`, `question_length`) trên hệ thống giám sát và đảm bảo an toàn bảo mật. |
| **Shutdown / Lifespan** | Tắt đột ngột, không có `lifespan` hay xử lý signal | Có `lifespan` startup/shutdown (dòng 39–68) và bắt `SIGTERM` (dòng 180–189) | Cho phép hoàn thành request đang chạy (in-flight) và giải phóng kết nối sạch trước khi container thoát, tránh mất dữ liệu người dùng. |
| **Network & Binding** | `host="localhost"`, `port=8000`, `reload=True` (dòng 51–53) | `host="0.0.0.0"`, `port=settings.port`, `reload=settings.debug` (dòng 196–198) | Bắt buộc bind `0.0.0.0` và nghe theo `$PORT` để chạy trong Docker và trên Render/Railway/Cloud Run. |
| **API & Security** | Không có CORS, không validate input chặt | Có `CORSMiddleware` giới hạn origins (dòng 77–82), trả `422` khi thiếu `question` (dòng 107–108) | Ngăn truy cập cross-origin trái phép và trả thông báo lỗi chuẩn hoá thay vì lỗi nội bộ. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (bản Debian đầy đủ đi kèm compiler, header, tiện ích hệ thống nên rất nặng, hơn 1 GB).
2. **Working directory:** `/app` (`WORKDIR /app` — mọi lệnh `COPY`, `RUN`, `CMD` sau đó thực thi tương đối từ `/app`).
3. **Tại sao `COPY requirements.txt` trước `COPY . .` (hoặc `app.py`):** Docker cache từng layer theo thứ tự từ trên xuống. `requirements.txt` ít thay đổi hơn source code; đặt `COPY requirements.txt` và `RUN pip install` lên trước giúp khi chỉ sửa `app.py`, Docker tái sử dụng cache layer cài thư viện thay vì tải và cài lại toàn bộ dependencies mỗi lần build.
4. **Khác nhau giữa `CMD` và `ENTRYPOINT`:**
   - `CMD` cung cấp lệnh hoặc tham số **mặc định**, dễ bị ghi đè hoàn toàn khi truyền đối số ở cuối `docker run <image> <override_cmd>`.
   - `ENTRYPOINT` cố định **chương trình thực thi chính** của container; đối số truyền vào `docker run` sẽ được nối thêm làm tham số cho `ENTRYPOINT` (trừ khi dùng cờ `--entrypoint`).

### Exercise 2.2: Build và chạy container `my-agent:develop`

Lệnh build chạy từ gốc repo:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm -p 18020:8000 my-agent:develop
curl -s -X POST "http://localhost:18020/ask?question=What%20is%20Docker%3F"
```

Kết quả thực tế:
```json
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & So sánh kích thước image

Phân tích `02-docker/production/Dockerfile`:
- **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài công cụ biên dịch (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`):** Bắt đầu mới từ `python:3.11-slim`, tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local` cùng source code cần thiết, thiết lập `USER appuser` và `HEALTHCHECK`.
- **Tại sao image nhỏ hơn:** Không mang theo các gói build-time (`gcc`, `libpq-dev`, headers, cache apt/pip) và dùng base image `slim` thay vì bản `python:3.11` đầy đủ, vừa giảm dung lượng mạnh vừa thu hẹp bề mặt tấn công bảo mật.

**Số liệu đo thực tế bằng `docker images` và `docker image inspect`:**

| Image | Kích thước đo (`docker images`) | Bytes chính xác (`inspect`) |
| --- | ---: | ---: |
| `my-agent:develop` | **1.67 GB** (1,667.8 MB) | `1,667,784,111` |
| `my-agent:advanced` | **240 MB** (239.8 MB) | `239,815,354` |
| **Chênh lệch** | **−1,428.0 MB (−85.6%)** | Nhỏ hơn **6.95 lần** |

### Exercise 2.4: Kiến trúc Docker Compose stack (`02-docker/production/`)

```text
                        ┌─────────────────────────────┐
                        │           Client            │
                        └──────────────┬──────────────┘
                                       │ HTTP :80 / HTTPS :443
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Docker bridge network: internal                                         │
│                                                                         │
│   ┌───────────────────────┐                                             │
│   │   nginx (nginx:alpine)│  Reverse proxy, rate limit (10r/s),         │
│   │   ports: 80, 443      │  security headers                           │
│   └───────────┬───────────┘                                             │
│               │ proxy_pass http://agent:8000                            │
│               ▼                                                         │
│   ┌───────────────────────┐                                             │
│   │ agent (FastAPI :8000) │  (không expose port trực tiếp ra host)      │
│   └───┬───────────────┬───┘                                             │
│       │               │                                                 │
│       │ :6379         │ :6333                                           │
│       ▼               ▼                                                 │
│  ┌──────────┐   ┌──────────────┐                                        │
│  │  redis   │   │    qdrant    │                                        │
│  │ 7-alpine │   │   v1.9.0     │                                        │
│  └────┬─────┘   └──────┬───────┘                                        │
│       ▼                ▼                                                │
│  (redis_data)    (qdrant_data)    ← Persistent Docker volumes           │
└─────────────────────────────────────────────────────────────────────────┘
```

Các service khởi động: `redis` (healthy), `qdrant` (healthy), `agent` (healthy, `depends_on` redis & qdrant), `nginx` (expose port `80`). Các container giao tiếp nội bộ qua DNS tên service (`redis:6379`, `qdrant:6333`, `agent:8000`) trong mạng `internal`.

**Kết quả test thực tế qua Nginx (`http://localhost`):**
```text
GET http://localhost/health
{"status":"ok","uptime_seconds":7.1,"version":"2.0.0","timestamp":"2026-11-25T14:20:22.784127"}

POST http://localhost/ask  {"question":"Explain microservices"}
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.2 (Nền tảng chính — Render): Deploy agent Part 6 (`06-lab-complete/`)

- **Platform:** Render (Singapore, Free plan)
- **Public URL:** https://day14-production-agent-zlki.onrender.com
- **Redis Service:** `day14-agent-redis` (Render Key Value / Valkey 8, Singapore, kết nối qua Internal `REDIS_URL`)
- **Chi tiết cấu hình & lệnh test:** Xem [DEPLOYMENT.md](DEPLOYMENT.md)
- **Ảnh chụp minh chứng:**
  - [screenshots/dashboard.png](screenshots/dashboard.png) — Render Dashboard hiển thị `day14-production-agent` (Deployed) và `day14-agent-redis` (Available)
  - [screenshots/running.png](screenshots/running.png) — Trạng thái `Deploy succeeded | Live` kèm structured JSON logs
  - [screenshots/test.png](screenshots/test.png) — Kết quả chạy 4 lệnh kiểm tra CP6 (`200`, `200`, `401`, `200`)

**Kết quả 4 lệnh tự kiểm CP6 trên URL public:**
```text
GET  /health              -> 200  ({"status":"ok","environment":"production","uptime_seconds":191.4})
GET  /ready               -> 200  ({"status":"ready","redis":"ok"})
POST /ask (không có key)  -> 401
POST /ask (có X-API-Key)  -> 200  ({"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock)...","usage":{...}})
```

### So sánh `railway.toml` với `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` | Lý do khác biệt |
| --- | --- | --- | --- |
| **Định dạng & phạm vi** | TOML, cấu hình cho **1 service đơn lẻ** (`[build]`, `[deploy]`). | YAML Blueprint (IaC), khai báo được **cả stack nhiều service** (`type: web`, `type: redis`/`keyvalue`, disk, cron). | Railway quản lý tài nguyên (như Redis) tách rời theo project canvas; Render Blueprint hướng tới đồng bộ toàn bộ hạ tầng từ một file git. |
| **Cấu hình build/runtime** | `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"`), `dockerfilePath = "Dockerfile"`. | `runtime: docker` (hoặc `runtime: python` kèm `buildCommand`/`startCommand`), `plan`, `region`. | Render cho phép chốt sẵn gói (`free`/`starter`) và vùng (`singapore`) ngay trong file Blueprint. |
| **Health check** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`. | `healthCheckPath: /health` (camelCase), `autoDeploy: true`. | Quy ước schema riêng của từng nền tảng; Railway cho chỉnh chi tiết chính sách restart ngay trong file config. |
| **Quản lý biến môi trường & secrets** | Không khai báo env vars trong `railway.toml`; đặt qua Dashboard hoặc `railway variables set`. | Khai báo danh sách `envVars` trực tiếp: biến thường dùng `value:`, secret dùng `generateValue: true` hoặc `sync: false` (không ghi giá trị thật vào git). | Render cần schema khai báo trước biến để Blueprint tạo khung nhập secret an toàn khi sync repo. |

### Exercise 3.3: Phân tích CI/CD pipeline GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` tự động chạy 4 bước tuần tự (`waitFor`) khi push code lên `main`:
1. **`test`:** Chạy container `python:3.11-slim`, cài dependencies + `pytest` và chạy toàn bộ bộ test trước khi cho phép build.
2. **`build`:** Build Docker image gắn đồng thời 2 tag `$COMMIT_SHA` (bất biến để rollback) và `latest`, tận dụng `--cache-from` để tăng tốc.
3. **`push`:** Đẩy toàn bộ tag image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Gọi `gcloud run deploy` triển khai bản `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`), cấu hình `--min-instances=1` (tránh cold start), `--max-instances=10`, giới hạn `512Mi` RAM / `1` CPU và nạp secret trực tiếp từ Google Secret Manager (`--set-secrets`).

File `service.yaml` (Knative IaC) mô tả trạng thái mong muốn của service Cloud Run gồm `containerConcurrency: 80`, tài nguyên CPU/memory, tham chiếu secret qua `secretKeyRef`, cùng `livenessProbe` (`/health`) và `startupProbe` (`/ready`) để đảm bảo zero-downtime deployment.

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu:** Tại dependency `verify_api_key` (dòng 39–54) đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)`, gắn vào endpoint `POST /ask` bằng `Depends(verify_api_key)` (dòng 70). `/health` và `/` để public.
- **Khi thiếu / sai key:** Thiếu header `X-API-Key` trả `HTTP 401`; sai key trả `HTTP 403` (ở bản Part 6 chuẩn hoá cả thiếu và sai key đều trả `HTTP 401` dùng so sánh constant-time `hmac.compare_digest`).
- **Cách rotate key an toàn không downtime:** Hỗ trợ đồng thời danh sách 2 key hợp lệ (key cũ + key mới) qua biến môi trường (vd `AGENT_API_KEYS=old_key,new_key`) → phát key mới cho client → theo dõi log xác nhận không còn request dùng key cũ → gỡ key cũ khỏi env và restart/redeploy.

**Kết quả test thực tế (`AGENT_API_KEY=secret-key-123`):**
```text
# Không có key -> HTTP 401
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key -> HTTP 403
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# Có key hợp lệ -> HTTP 200
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **JWT Flow (`auth.py`):** Client gửi `username`/`password` tới `POST /auth/token` → server xác thực và ký JWT bằng thuật toán `HS256` chứa payload `sub`, `role`, `iat`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` ở các request `/ask` → `verify_token` kiểm tra chữ ký và hạn token không cần tra DB.
- **Rate Limiter (`rate_limiter.py`):**
  - **Thuật toán:** **Sliding Window Counter** dùng `collections.deque` lưu timestamp các request của từng user, loại bỏ timestamp cũ hơn `now - 60s` trước khi kiểm tra số lượng.
  - **Giới hạn:** `rate_limiter_user` = **10 requests/phút** (`student`), `rate_limiter_admin` = **100 requests/phút** (`teacher`).
  - **Bypass / nâng giới hạn cho admin:** Trong `app.py` (dòng 141), kiểm tra `role` từ JWT payload (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`) hoặc cho phép skip `limiter.check()` nếu `role == "admin"`.

**Kết quả test thực tế (đăng nhập `student` / `demo123`, gửi liên tiếp 13 request — đã che token):**
```text
# Không có token -> HTTP 401
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Lấy token -> HTTP 200
POST /auth/token {"username": "student", "password": "demo123"}
HTTP/1.1 200 OK
{"access_token": "eyJhbGciOiJIUzI1NiIs...<REDACTED>", "token_type": "bearer", "expires_in_minutes": 60}

# Vòng lặp gửi 13 request với Authorization: Bearer <REDACTED>
Req 01 -> HTTP 200  {"question":"Test 1","answer":"...","usage":{"requests_remaining":9,...}}
Req 02 -> HTTP 200  {"question":"Test 2","answer":"...","usage":{"requests_remaining":8,...}}
...
Req 10 -> HTTP 200  {"question":"Test 10","answer":"...","usage":{"requests_remaining":0,...}}
Req 11 -> HTTP 429  Retry-After: 59  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Req 12 -> HTTP 429  Retry-After: 59  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Req 13 -> HTTP 429  Retry-After: 59  {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost Guard — Cách triển khai và lý do cần cả Rate Limit lẫn Cost Guard

- **Tại sao cần cả hai:** Rate limit chỉ giới hạn **tốc độ** (số request/phút), nhưng một request LLM có prompt rất dài hoặc dùng model đắt tiền vẫn có thể tốn nhiều chi phí dù gọi chậm. Cost guard giới hạn trực tiếp **ngân sách tiền (USD)** theo token thực tế.
- **Cách triển khai chuẩn production (dùng Redis, như đã áp dụng ở Part 6 `app/cost_guard.py`):**
  1. Lưu tổng chi tiêu trong Redis theo key thời gian: `cost:daily:YYYY-MM-DD` (TTL 48 giờ) và `cost:monthly:YYYY-MM` (TTL 35 ngày) để mọi worker/instance dùng chung và không mất dữ liệu khi restart.
  2. **Trước khi gọi LLM (`check_budget`):** đọc giá trị hiện tại từ Redis; nếu vượt `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD` thì chặn ngay bằng `HTTP 402 Payment Required` (không tốn thêm chi phí LLM).
  3. **Sau khi gọi LLM (`record_cost`):** tính `cost = (input_tokens/1000)*PRICE_INPUT + (output_tokens/1000)*PRICE_OUTPUT` và cộng nguyên tử vào Redis bằng `INCRBYFLOAT` + đặt `EXPIRE`.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health check (`/health`) vs Readiness check (`/ready`)

- **Liveness (`GET /health`):** Kiểm tra *process có còn sống hay bị treo không*. Phải luôn trả `200` khi process hoạt động bình thường, **không** phụ thuộc vào Redis/DB bên ngoài — nếu `/health` trả lỗi khi Redis gặp sự cố, orchestrator sẽ liên tục restart container một cách vô ích (restart loop).
- **Readiness (`GET /ready`):** Kiểm tra *instance đã sẵn sàng nhận traffic thực chưa* (đã khởi tạo xong, không đang shutdown, kết nối được Redis `r.ping()`). Khi Redis mất kết nối, `/ready` trả `503 Service Unavailable` để load balancer tạm ngừng điều hướng traffic tới instance đó mà không kill container.

### Exercise 5.2: Graceful Shutdown

Khi container nhận `SIGTERM` (vd `docker stop` hoặc rolling deploy):
1. Đánh dấu không nhận request mới (readiness chuyển sang false, uvicorn đóng socket lắng nghe mới).
2. Chờ các request đang xử lý (in-flight) hoàn tất trả HTTP 200 cho client trong giới hạn `timeout_graceful_shutdown`.
3. Chạy đoạn cleanup trong FastAPI `lifespan` (đóng Redis connection pool, flush log/trace).
4. Thoát sạch với **exit code 0** trong < 10 giây (tránh bị Docker gửi `SIGKILL` — exit code 137).
- **Lưu ý quan trọng:** Nếu đăng ký custom `signal.signal(signal.SIGTERM, ...)` để ghi log, bắt buộc gọi lại handler trước đó của `uvicorn`, đồng thời trong Dockerfile dùng `exec uvicorn ...` để uvicorn làm **PID 1** nhận trực tiếp tín hiệu `SIGTERM`.

### Exercise 5.3: Stateless Design

- **Vì sao state trong RAM bị hỏng khi scale ngang:** Khi chạy 3 instance sau load balancer, Request 1 của user A vào Instance 1 (lưu history/rate limit trong RAM của Instance 1), Request 2 vào Instance 2 sẽ không thấy lịch sử trò chuyện hoặc đếm sai rate limit; khi restart container toàn bộ state cũng mất sạch.
- **Giải pháp:** Tách toàn bộ state (conversation history, rate limit sorted set, cost counter) ra **Redis** dùng chung. Mọi instance trở nên giống hệt nhau (stateless), có thể thêm/bớt hoặc thay thế bất kỳ lúc nào.

### Exercise 5.4 & 5.5: Load Balancing 3 Instances & Test Stateless

Chạy trong `05-scaling-reliability/production/`:
```bash
docker compose -p k5-day14-scaling up -d --build --scale agent=3
python test_stateless.py
docker compose -p k5-day14-scaling down -v
```

**Kết quả thực tế từ `python test_stateless.py` (Nginx cổng 8080, endpoint `POST /chat`):**
```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 400bded8-dc1c-48d1-9bf4-5fe48dcf17fd

Request 1: [instance-b92eef]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-d19b72]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-c97fd1]
  Q: What is Kubernetes?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 4: [instance-b92eef]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-d19b72]
  Q: What is Redis used for?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-c97fd1', 'instance-d19b72', 'instance-b92eef'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 request cùng 1 `session_id` được Nginx phân phối round-robin đều qua cả 3 container độc lập (`instance-b92eef`, `instance-d19b72`, `instance-c97fd1`), nhưng khi gọi `GET /chat/{session_id}/history` vẫn đọc đủ trọn vẹn 10 message (5 câu hỏi + 5 câu trả lời) vì toàn bộ session state được lưu tập trung trong Redis.

---

## Part 6: Final Project — Output `check_production_ready.py`

Chạy đầy đủ trong môi trường POSIX (`os.name = posix`) có Docker engine (`Docker 29.9.3`, `Docker Compose v5.8.0`) tại `06-lab-complete/`:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số chỉ số kiểm tra thực tế từ script chấm:
- **Docker image build & size:** Multi-stage `python:3.11-slim`, non-root `appuser`, `HEALTHCHECK`, kích thước **298 MB** (< 500 MB), build 17s.
- **Rate limiting & Stateless:** Trả `429` sau đúng 5 request (`RATE_LIMIT_PER_MINUTE=5`), sau khi restart agent vẫn trả `429` (state lưu trong Redis).
- **Readiness:** `/ready` trả `200` khi Redis chạy, trả `503` khi Redis mất kết nối trong khi `/health` vẫn `200`.
- **Cost guard:** Trả `402` ở request thứ 1 khi budget ≈ 0.
- **Structured logging:** `17` dòng log JSON hợp lệ.
- **Graceful shutdown:** Nhận `SIGTERM` lúc đang có request → request vẫn trả `200`, process thoát `exit code 0`; `docker stop` hoàn tất `exit code 0` trong `0.7s` (< 10s).

---

## AI Log

1. **Triển khai khung Part 6 (`06-lab-complete/`):**
   - *Hỏi AI:* Thiết kế chi tiết các module `config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py` (sliding window sorted set), `cost_guard.py`, `main.py` (JSON logging + lifespan + SIGTERM), multi-stage `Dockerfile`, `docker-compose.yml`, `railway.toml`, `render.yaml` theo đúng bảng hợp đồng 12 tiêu chí.
   - *Nhận được:* Bộ mã nguồn Python và cấu hình Docker/Render hoàn chỉnh.
   - *Tự kiểm tra & sửa:* Chạy `check_production_ready.py` đầy đủ trong môi trường POSIX + Docker (cả static, runtime với Redis container tạm thời, SIGTERM in-flight, build/run/stop image 298 MB) cho tới khi đạt `PASS 12/12 (43/43 checks passed)`.
2. **Khắc phục sự cố môi trường Docker & Dockerfile Part 7:**
   - *Hỏi AI:* Chẩn đoán lỗi WSL2 OOM (`0xc00000fd` / `out of memory allocating heap arena map`) trên Windows và lỗi `ModuleNotFoundError: No module named 'uvicorn'` ở `benchmark-observability/production/Dockerfile`.
   - *Nhận được:* Hướng dẫn giới hạn bộ nhớ WSL2 qua `.wslconfig` và bổ sung `ENV PYTHONUSERBASE=/home/agent/.local` + `chown` vào `production/Dockerfile`.
   - *Tự kiểm tra:* Xác nhận toàn bộ 6 service trong stack Part 7 chạy healthy và thực thi đầy đủ load test, eval, Locust scale 1 vs 3, trace Jaeger và Prometheus alerts.
3. **Tổng hợp câu trả lời Part 1–5 và báo cáo Part 7:**
   - *Hỏi AI:* Rà soát cấu trúc `MISSION_ANSWERS.md`, `DEPLOYMENT.md`, `BENCHMARK_REPORT.md` theo đúng rubric và checklist nộp bài.
   - *Tự kiểm tra:* Toàn bộ con số (kích thước image MB, output curl, latency/RPS trong JSON/CSV, trace_id và log JSON, thời gian alert firing, URL public Render) đều lấy trực tiếp từ lệnh chạy thực tế trên máy và khớp với các file báo cáo nộp kèm.

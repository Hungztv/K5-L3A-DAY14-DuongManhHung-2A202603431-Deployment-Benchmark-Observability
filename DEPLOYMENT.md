# Deployment Information — Day 14 Lab

## Public URL
https://day14-production-agent-zlki.onrender.com

## Platform
- **Cloud Platform:** Render (Free tier)
- **Region:** Singapore
- **Services deployed:**
  - Web Service: `day14-production-agent` (Runtime: Docker, Root Directory: `06-lab-complete`, Health Check Path: `/health`)
  - Key Value (Redis / Valkey 8): `day14-agent-redis` (Free plan, Internal URL connected via `REDIS_URL`)

## Test Commands

Đặt biến môi trường trước khi chạy (không hardcode API key trong tài liệu hay repo):

```bash
export BASE="https://day14-production-agent-zlki.onrender.com"
export AGENT_API_KEY="<YOUR_RENDER_AGENT_API_KEY>"
```

### 1. CP6 4-Command Self-Test (HTTP status codes)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
# Expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
# Expected: 200

curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'
# Expected: 401

curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
# Expected: 200
```

### 2. Full JSON Response Examples (Verified Live)

```bash
# Liveness probe
curl -sS "$BASE/health"
# {"status":"ok","environment":"production","uptime_seconds":191.4}

# Readiness probe (kiểm tra kết nối Redis)
curl -sS "$BASE/ready"
# {"status":"ready","redis":"ok"}

# Protected /ask endpoint
curl -sS -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","user_id":"test","usage":{"input_tokens":1,"output_tokens":24,"cost_usd":1.455e-05}}
```

### 3. Rate Limiting Test

```bash
for i in $(seq 1 12); do
  curl -sS -o /dev/null -w "Req $i -> HTTP %{http_code}\n" -X POST "$BASE/ask" \
    -H "X-API-Key: $AGENT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"question":"rate limit test"}'
done
# Sau 10 request/phút trả về HTTP 429 kèm header Retry-After: 60 (state lưu trong Redis)
```

> Lưu ý: Render Free instance sẽ sleep sau ~15 phút không có traffic; request đầu tiên có thể mất 30–50 giây để cold-start.

## Environment Variables Set on Render Dashboard

Các biến môi trường được cấu hình trực tiếp trên Render Dashboard (không ghi giá trị thật vào source code hay git):

- `PORT` (tự động cấp bởi Render, Dockerfile dùng `--port ${PORT:-8000}`)
- `ENVIRONMENT` (`production`)
- `REDIS_URL` (Internal Key Value URL của `day14-agent-redis`)
- `AGENT_API_KEY` (secret key đặt trên Render Dashboard)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)

## Screenshots

- [Deployment dashboard (Web Service + Redis)](screenshots/dashboard.png)
- [Service running & structured JSON logs](screenshots/running.png)
- [CP6 API verification test results](screenshots/test.png)

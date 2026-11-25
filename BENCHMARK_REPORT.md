# Benchmark & Observability Report — Day 14

**Họ tên:** Dương Mạnh Hùng — MSSV: 2A202603431 (K5-L3A)  
**Ngày chạy:** 25/11/2026  
**Môi trường:** Windows 11, Python 3.12.10, Docker Desktop 29.9.3 (Docker Compose v5.7.0, WSL2 4 CPU / 16 GB Host RAM)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| --- | --- | --- |
| p95 latency `/ask` | `< 500 ms` | Với mock LLM cơ bản (~120–180 ms + 20 ms retrieval), 95% người dùng cần nhận phản hồi dưới nửa giây để trải nghiệm tương tác mượt; đặt theo p95 bắt được suy giảm tail latency khi tải tăng. |
| Error rate `/ask` | `< 2.0%` | Upstream LLM mô phỏng có tỉ lệ lỗi tự nhiên ~1% (`MOCK_ERROR_RATE=0.01`); error budget 2% đủ dung sai cho nhiễu ngắn hạn nhưng phát hiện ngay khi upstream suy thoái (alert firing khi > 5% trong 1 phút). |
| Accuracy trên golden dataset | `≥ 85%` (mục tiêu `100%`) | Đảm bảo chất lượng trả lời trước mỗi lần merge/deploy, không cho phép regression trên 23 câu hỏi chuẩn. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Số liệu lấy trực tiếp từ `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json` (mỗi lần chạy `--requests 300`, `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
| ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | 3.85 | 202.4 | 236.4 | 1711.3 | 0.33% | PASS |
| 10 | 43.30 | 189.4 | 234.0 | 1684.8 | 1.33% | PASS |
| 50 | 103.81 | 201.2 | 289.5 | 1716.7 | 1.00% | PASS |
| 100 | 77.57 | 388.8 | 3229.4 | 3495.6 | 0.67% | FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency. Từ concurrency 1 → 10 → 50, RPS tăng mạnh từ `3.85` → `43.30` → `103.81 req/s` nhờ FastAPI/asyncio xử lý song song các tác vụ I/O-bound mà p95 vẫn giữ dưới ngưỡng SLO (`236.4 → 289.5 ms`). Tuy nhiên ở concurrency = `100`, single-process uvicorn trên 1 event loop bắt đầu bão hoà hàng đợi socket/CPU scheduling: throughput **tụt xuống** `77.57 req/s`, p50 tăng gần gấp đôi (`388.8 ms`), và p95 vọt lên `3229.4 ms` (vi phạm SLO `≤ 500 ms`).

### 2.2 Tail latency

Số liệu lấy trực tiếp từ `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json` (cùng `--requests 300 --concurrency 20`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | SLO p95 (≤ 500 ms) |
| --- | ---: | ---: | ---: | :---: |
| `0` | 193.2 | 219.9 | 237.1 | PASS |
| `0.03` (mặc định) | 252.3 | 232.6 | 1684.8 | PASS |
| `0.1` | 349.9 | 1702.4 | 1727.7 | FAIL |

**Nhận xét:** `p99` và `p95` nhạy hơn rất nhiều so với `avg`. Khi `MOCK_SLOW_RATE = 0.03` (3% request chậm thêm ~1.5s), `avg` chỉ tăng nhẹ từ `193.2 ms` lên `252.3 ms` (+59 ms) trông vẫn rất ổn, nhưng `p99` đã nhảy vọt hơn 7 lần lên `1684.8 ms`. Khi tăng lên `0.1` (10% request chậm > 5%), `avg` mới là `349.9 ms` (vẫn dưới 500 ms), nhưng `p95` đã tăng vọt lên `1702.4 ms` và vi phạm SLO. **Average che giấu trải nghiệm tệ của nhóm người dùng đuôi (tail latency)**, nên SLO bắt buộc đặt theo percentile (`p95`/`p99`).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Số liệu lấy trực tiếp từ `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` (23 câu hỏi trong `eval/golden_dataset.jsonl`):

| Chỉ số | Agent v1 (`eval_v1.json`) | Agent v2 (`eval_v2.json`) | Agent v2 sau sửa KB (`eval_v2_fixed.json`) |
| --- | --- | --- | --- |
| **Accuracy** | 4.35% (1/23) | 91.3% (21/23) | **100.0% (23/23)** |
| **Avg tokens / câu** | 58.8 | 109.0 | 113.8 |
| **Tổng cost (USD)** | \$0.000428 | \$0.000759 | \$0.000792 |
| **Cost / câu đúng (USD)** | \$0.00042795 | \$0.00003616 | **\$0.00003443** |
| **Latency p50 / p95 (ms)** | 170.9 / 204.6 | 203.8 / 232.0 | 202.4 / 1556.2* |
| **Regressions vs baseline** | — | 0 (vs v1, +20 câu) | 0 (vs v2, +2 câu) |
| **Quality gate** | **FAIL** | **PASS** (≥ 80%) | **PASS** (`--min-accuracy 1.0`) |

*\*Lưu ý về `p95 = 1556.2 ms` ở `eval_v2_fixed.json`: mẫu eval chỉ có 23 câu nên khi có 2 câu dính slow tail (`basic-01`: 1735.5 ms, `reliability-01`: 1704.6 ms) thì p95 nhảy ngay lên >1.5s. Đây là lý do thực tế không dùng eval để kết luận latency mà phải đo bằng load test nhiều trăm request.*

### Những câu v2 trả lời sai ban đầu và cách sửa

| ID | Keyword bị thiếu | Đã sửa gì (trong `develop/utils/mock_llm.py` & `production/utils/mock_llm.py`) |
| --- | --- | --- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["jwt"]` giải thích sự khác nhau giữa API key cố định và JWT (token có chữ ký số, chứa thông tin user và thời điểm hết hạn). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["hpa", "kubernetes", "autoscal"]` giải thích Kubernetes HPA tự động scale pod theo CPU, memory hoặc custom metrics (RPS, queue length). |

### Quality Gate trong CI (Exercise 7.3)

- Đã kiểm thử thực tế lệnh `python eval/run_eval.py --url http://127.0.0.1:8001 --baseline reports/eval_v2.json`: phát hiện **20 câu bị regression**, in `Quality gate: ❌ FAIL` và trả **exit code 1**.
- Đã thêm GitHub Actions workflow [`.github/workflows/eval.yml`](.github/workflows/eval.yml) tự động chạy trên mọi `pull_request`: khởi động agent v2 và gọi `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`. Nếu accuracy dưới ngưỡng hoặc có câu regression so với baseline, `run_eval.py` thoát với exit code `1` làm CI job fail và chặn merge PR.

### Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2

Agent v2 (có bước RAG retrieval) tốn gần gấp đôi số token mỗi câu (`109.0` → `113.8` vs `58.8` tokens của v1) và tăng nhẹ tổng chi phí (`\$0.000792` vs `\$0.000428`) cùng ~20–30 ms latency retrieval (`p50`: `202.4 ms` vs `170.9 ms`). Tuy nhiên, accuracy tăng vượt trội từ `4.35%` lên `100%`, khiến **chi phí trên mỗi câu trả lời đúng** giảm **12.4 lần** (từ `\$0.00042795` xuống `\$0.00003443`). Trong bài toán AI agent, đầu tư thêm context/retrieval mang lại hiệu quả kinh tế và chất lượng vượt trội so với việc giảm token nhưng trả lời sai.

---

## 4. Observability stack (production)

### Trả lời Exercise 7.1 & Exercise 7.4

- **Exercise 7.1 (Metrics & Cardinality):**
  - *Counter:* `http_requests_total`, `llm_requests_total`, `llm_tokens_total`, `llm_cost_usd_total` (chỉ tăng).
  - *Gauge:* `agent_in_flight_requests`, `agent_info` (lên xuống theo trạng thái hiện tại).
  - *Histogram:* `http_request_duration_seconds`, `llm_request_duration_seconds`, và metric tự thêm `agent_question_length_chars` (chia giá trị vào các bucket).
  - *Vì sao dùng `route.path` thay vì `request.url.path`:* Nếu dùng URL thật, khi bot quét hàng nghìn đường dẫn lạ (`/wp-admin`, `/.env`, `/a1b2c3`...) sẽ sinh ra hàng nghìn tổ hợp label khác nhau (high cardinality), làm bùng nổ số time series và khiến Prometheus cạn RAM.
- **Exercise 7.4 (Quan sát trên stack production với 2 instance, 30 users):**
  1. **p95 vs avg:** Trên Prometheus đo được `p95 = 297.5 ms` (Grafana live stat `296.08 ms`) và `avg = 256.6 ms` (Error rate `0.64%`–`0.77%`). Khoảng cách giữa `avg` và `p95`/`p99` (`~1.7s` trên biểu đồ) phản ánh trực tiếp nhóm ~3% slow tail requests từ LLM.
  2. **Phân tải giữa 2 instance:** Panel/PromQL `sum by (instance) (rate(http_requests_total{route="/ask"}[1m]))` ghi nhận `172.19.0.3:8000 = 8.97 req/s` và `172.19.0.2:8000 = 8.73 req/s` → Nginx chia đều gần như 50/50 theo round-robin.
  3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`:** Đo được `input = 1365.8 tok/s` vs `output = 714.1 tok/s` (~1.91 lần) vì ở agent v2, input prompt bao gồm `SYSTEM_PROMPT` + tài liệu context lấy từ bước RAG retrieval + câu hỏi người dùng, trong khi câu trả lời output ngắn gọn hơn.
  4. **`curl -i http://localhost:8080/metrics` trả về gì và vì sao:** Trả về **`HTTP/1.1 404 Not Found`** vì trong `nginx/nginx.conf` có khối `location = /metrics { return 404; }`. `/metrics` chỉ dành cho Prometheus scrape nội bộ trong Docker network `obs_net`, không public ra ngoài Internet để tránh lộ thông tin nội bộ (route, lưu lượng, model, chi phí).

### 4.1 Screenshot

- [x] [Dashboard Grafana khi đang có tải (4 Golden Signals, Latency & Traffic, LLM)](screenshots/grafana-dashboard.png)
- [x] [Trace chậm trong Jaeger (span `chat mock-llm-small` chiếm 98.5% thời gian)](screenshots/jaeger-slow-trace.png)
- [x] [Trace lỗi trong Jaeger (HTTP 503, event `exception` mở rộng)](screenshots/jaeger-error-trace.png)
- [x] [Trang Alerts của Prometheus với 3 alert đang `FIRING` đồng thời + 1 alert `PENDING`](screenshots/prometheus-alert-firing.png)

*(Đã chạy unit test alert rules `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.)*

### 4.2 Thí nghiệm "phá hệ thống" (Exercise 7.6)

Chạy dưới tải Locust 30 users, đo thời điểm chuyển trạng thái `PENDING` → `FIRING` qua Prometheus `/api/v1/alerts`:

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
| --- | --- | --- | --- | --- |
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, giá trị `20.5%`–`21.45%` > 5%) | ~70s (~1m 10s sau khi có tải; `PENDING` ở +15s) | Golden Signals → **Error rate** (đỏ) & Requests/s theo status code (503 tăng mạnh) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, giá trị `1.92s`–`1.95s` > 1s) | ~130s (~2m 10s sau khi có tải; `PENDING` ở +15s) | Golden Signals → **Latency p95** & Latency `/ask` p50/p95/p99 |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, giá trị `\$14.56/giờ` > \$2/giờ) | ~162s (~2m 42s; `PENDING` ở +45s khi burn rate vượt \$2/giờ) | LLM → **Cost burn rate (USD/giờ)** & LLM latency p95 theo model |
| D | `docker pause k5-day14-observability-agent-2` | `AgentInstanceDown` (`for: 30s`, `up == 0`) | **41.7s** (`PENDING` ở +16.6s) | Golden Signals → **Instances up** giảm; Locust ghi nhận `34` lỗi `504 Gateway Time-out` từ Nginx |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không firing | Panel **Retrieval hit ratio** mất (v1 không RAG), `tokens/s` giảm, bảng `agent_info` đổi sang `v1` |

**Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**
Alert hạ tầng (error rate, latency, CPU, instance up) chỉ phát hiện lỗi kỹ thuật ở mức HTTP/container, không hiểu nội dung câu trả lời đúng hay sai — thậm chí chuyển sang `v1` còn làm latency nhanh hơn và chi phí rẻ hơn nên mọi panel hạ tầng đều xanh. Để phát hiện sự cố suy giảm chất lượng trong production cần:
1. **CI/CD Eval Quality Gate:** Bắt buộc chạy `eval/run_eval.py` trên golden dataset trước mọi bản release để chặn regression ngay trước khi deploy.
2. **Online Quality Monitoring:** Lấy mẫu traffic thật (sampling) để chấm tự động bằng LLM-as-a-judge, theo dõi **retrieval hit ratio** (cảnh báo khi tụt đột ngột về 0), và đo phản hồi người dùng (thumbs up/down, retry rate).

**Vì sao 34 lỗi `504 Gateway Time-out` trong thí nghiệm D hiện ở Locust nhưng không hiện trên panel Error rate của agent?**
Khi `agent-2` bị `docker pause`, Nginx chuyển request vào container đang bị đóng băng và chờ hết `proxy_read_timeout 10s` rồi tự trả `504` cho client; bản thân `agent-2` chưa bao giờ hoàn tất xử lý để ghi nhận counter `http_requests_total{status="504"}`. Do đó cần giám sát thêm metrics ở tầng Load Balancer/Nginx hoặc chạy synthetic probes từ bên ngoài.

### 4.3 Debug bằng trace (Exercise 7.5)

Trace chậm nhất tìm được trong Jaeger (`http://localhost:16686/trace/ef657a568dadf3422625b4eed7cb23ef`):

- **`trace_id`:** `ef657a568dadf3422625b4eed7cb23ef`
- **Tổng thời gian (`POST /ask`):** `1724.2 ms` (hiển thị trên Jaeger UI: `1.7s`)
- **Span chiếm nhiều thời gian nhất:** `chat mock-llm-small` (`1698.4 ms`, chiếm **98.5%** tổng thời gian; trong khi `agent.retrieve_context` chỉ mất `24.3 ms`). Điều này chứng minh nút thắt nằm ở lời gọi LLM upstream chứ không phải logic xử lý hay retrieval của agent.
- **Dòng log JSON tương ứng (grep từ `docker compose -p k5-day14-observability logs agent` theo `trace_id`):**

```json
{"ts": "2026-11-25T14:44:04.724521+00:00", "level": "INFO", "service": "observable-agent", "instance": "5f39f4edb2a8", "event": "llm_call", "trace_id": "ef657a568dadf3422625b4eed7cb23ef", "span_id": "50d518c8b2ae802d", "request_id": "0ec190b41bf6", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1698.4}
{"ts": "2026-11-25T14:44:04.724881+00:00", "level": "INFO", "service": "observable-agent", "instance": "5f39f4edb2a8", "event": "http_request", "trace_id": "ef657a568dadf3422625b4eed7cb23ef", "span_id": "50d518c8b2ae802d", "request_id": "0ec190b41bf6", "method": "POST", "route": "/ask", "status": 200, "ms": 1724.2}
```

Trace lỗi đã kiểm tra trong Jaeger (`http://localhost:16686/trace/7767201b13083842f1d33e421065d12b`, HTTP 503, `637 ms`, event `exception` tại span `chat mock-llm-small`):
```json
{"ts": "2026-11-25T14:44:06.019140+00:00", "level": "INFO", "service": "observable-agent", "instance": "5f39f4edb2a8", "event": "llm_error", "trace_id": "7767201b13083842f1d33e421065d12b", "span_id": "959c0af9a97eafe3", "request_id": "47e9786f6a34", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu lấy trực tiếp từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`:

### Bảng 5.1 — Endpoint `POST /ask`

| Số instance | Requests | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 (`scale_1_stats.csv`) | 7,148 | 59.84 | 190 | 230 | 1700 | 68 (0.95%) |
| 3 (`scale_3_stats.csv`) | 7,230 | 60.55 | 190 | 230 | 1700 | 67 (0.93%) |

### Bảng 5.2 — Tổng hợp `Aggregated` (`/ask` + `/health`)

| Số instance | Requests | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 (`scale_1_stats.csv`) | 7,860 | 65.80 | 190 | 230 | 1700 | 68 (0.87%) |
| 3 (`scale_3_stats.csv`) | 7,920 | 66.33 | 190 | 220 | 1700 | 67 (0.85%) |

**Giải thích kết quả:** Scale từ 1 lên 3 instance **gần như không làm thay đổi p95** (`230 ms` → `230 ms` ở `/ask`; `230 ms` → `220 ms` ở Aggregated) và RPS chỉ nhích nhẹ (`59.84` → `60.55 req/s`). Nguyên nhân:
1. **Nút thắt nằm ở LLM upstream latency (I/O-bound):** Mỗi request mất ~190 ms (hoặc ~1.7s ở tail) chờ LLM trả lời; thêm container agent không thể làm LLM provider chạy nhanh hơn.
2. **Tải sinh ra bị giới hạn bởi `wait_time` của 100 Locust users:** Mỗi user chờ ngẫu nhiên giữa các request nên 1 instance FastAPI bất đồng bộ đã xử lý dư sức ~60 req/s mà chưa bão hoà CPU. Scale ngang lên 3 instance phát huy tác dụng khi tải vượt ngưỡng chịu đựng của 1 process (như ở mục 2.1 khi concurrency=100 không có `wait_time`) và mang lại tính sẵn sàng cao (High Availability — khi 1 instance gặp sự cố, 2 instance còn lại vẫn phục vụ).

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Percentile quan trọng hơn average:** Average che giấu tail latency; SLO phải đặt theo `p95`/`p99` và đo bằng load test đủ lớn thay vì mẫu nhỏ của eval.
  2. **Observability hạ tầng không thay thế được Eval chất lượng:** Hệ thống có thể xanh toàn bộ Golden Signals nhưng vẫn trả lời sai hoàn toàn (thí nghiệm E với `v1`); bắt buộc kết hợp cả Metrics + Traces + Logs với Eval Quality Gate trong CI.
  3. **Liên kết 3 trụ cột giúp root-cause nhanh:** Grafana phát hiện bất thường → Jaeger chỉ chính xác span chậm/lỗi (`chat mock-llm-small` chiếm 98.5%) → `trace_id` truy ngược ngay dòng JSON log chi tiết.
- **Nếu đưa agent này lên production thật, các metric / alert nên bổ sung:**
  - **Nginx / Load Balancer metrics:** Tỉ lệ lỗi `502`/`504` ở tầng gateway (bắt các lỗi mà agent metric không thấy khi container treo).
  - **RAG & Quality metrics:** Alert `RetrievalHitRatioLow` (khi hit ratio tụt bất thường, phát hiện lỗi index/vector DB hoặc regression như thí nghiệm E), cùng metric `agent_llm_ttft_seconds` (Time To First Token cho streaming).
  - **Security & Quota metrics:** Đếm số request bị chặn `401` (dò tìm API key), `429` (rate limit), `402` (cost guard) và kết nối Alertmanager gửi cảnh báo về Slack/PagerDuty.

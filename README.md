# Real-Time Network Anomaly Detection (Kafka × FastAPI × PostgreSQL × Streamlit)

End-to-end pipeline for **real-time network anomaly detection**: ingest → infer → persist → monitor.  
It combines classic/statistical detectors (**Random Forest**, **ADWIN**, **KL/L1 divergence**) with a production-minded data stack (**Kafka**, **FastAPI**, **PostgreSQL**, **Docker Compose**) and a **Streamlit** dashboard.

[![Watch the demo](assets/anomaly_detection.png)](https://youtu.be/XSlEOjZ624Y "Watch the 60s demo on YouTube")  
> 60s demo: ingest → score → store → dashboard (burst alert)

---

## Highlights

- **Streaming**: Kafka producer → FastAPI inference → PostgreSQL storage  
- **Detection**: RF for online scoring, **ADWIN** for concept drift, **KL/L1** for data drift  
- **Operations**: burst detection, thresholding, optional Slack alerts  
- **Monitoring**: fast WebGL-backed charts; filters & guardrails for large windows

---

## Architecture

![real-time-anomaly-diagram](assets/diagram-8-13.png)

---

## Tech Stack

- **Realtime**: Apache Kafka  
- **Serving**: FastAPI (Python), model artifacts (RandomForest + thresholds/encoders)  
- **Storage**: PostgreSQL (connection pool, indices)  
- **UI**: Streamlit + Plotly (WebGL)  
- **Container**: Docker Compose  
- **Drift/Anomaly**: ADWIN (concept), KL/L1 (data: proto/state/service distributions)

---

## Repository Layout

```bash
.
├─ dashboard/             # Streamlit dashboard
├─ serving/               # FastAPI app (scoring, alerts)
├─ kafka/                 # Sample producer / simulator
├─ db/                    # Schema & DB utilities
├─ model/                 # Local model artifacts (ignored in git)
├─ stream/                # (optional) stream simulator
├─ etl/                   # (optional) batch utilities
├─ docker-compose.yml
└─ .env.example
```

> **Important:** Large **data/model files are not tracked in git**.  
> Host artifacts on GitHub Releases / Hugging Face Hub / S3 / DVC remote, and provide a `scripts/download_data.sh`.

---

## Quick Start (Docker)

### 0) Prereqs
- Docker & Docker Compose
- Create and fill `.env` from template:
```bash
cp .env.example .env
# Edit DB/KAFKA/SLACK vars as needed
```

### 1) Bring the stack up
```bash
docker compose up -d --build
```

### 2) Initialize DB schema (if not auto-applied)
```bash
docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB -f /app/db/init.sql
```

### 3) Start streaming
```bash
# Publish sample events to Kafka
python kafka/stream_producer.py
# or use stream/stream_simulator.py
```

### 4) Open the apps
- **API docs**: http://localhost:8000/docs  
- **Dashboard**: http://localhost:8501

---

## Local Development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Run API
uvicorn serving.api_server:app --reload --port 8000
# Run dashboard
streamlit run dashboard/app.py
```

---

## Environment Variables (`.env`)

```ini
# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=anomaly
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# Kafka
KAFKA_BROKERS=localhost:9092
KAFKA_TOPIC=network-log

# Alerts (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

`db/db_config.py` reads these and builds `DB_CONFIG`.

---

## Data & Model

- **Model**: RandomForest produces a probability-like **score**; thresholding yields a **label** (0/1).  
- **Concept drift (ADWIN)**: monitors streaming metrics (e.g., score time-series) to detect regime shifts.  
- **Data drift (KL/L1)**: compares categorical distributions (e.g., `proto`, `state`, `service`) across windows.  
- **Burst detection**: if ≥ *N* anomalies within the last *W* minutes → raise alert.

> For reproducibility, host artifacts externally and provide `scripts/download_data.sh`.  
> Consider **DVC** for data/model versioning with an S3/GDrive remote.

---

## Database

- **Table**: `public.anomaly_scores` (example)
- **Columns** (typical):  
  `stime TIMESTAMPTZ, source TEXT, score FLOAT, label INT, proto TEXT, state TEXT, service TEXT, sload/dload FLOAT, spkts/dpkts INT, sjit/djit FLOAT, sttl/dttl INT, dur FLOAT, tcprtt FLOAT, synack FLOAT, ackdat FLOAT, ct_state_ttl INT ...`
- **Indexes**:
```sql
CREATE INDEX IF NOT EXISTS idx_anomaly_scores_stime ON public.anomaly_scores(stime);
-- add partial/time-based partitioning for scale if needed
```

---

## API (examples)

- `GET /healthz` — health probe  
- `POST /predict` — online scoring (single/batch)  
  - **Input**: JSON record(s) shaped like UNSW-NB15 fields (subset ok)  
  - **Output**: `{"score": 0.87, "label": 1}` (plus optional metadata)
- `POST /alert-test` — send a test Slack message (optional)

Open http://localhost:8000/docs for the live OpenAPI spec.

---

## Dashboard (Streamlit)

- **Controls**: time window, auto-refresh interval, score threshold, burst window & min hits  
- **Filters**: `proto`, `service`, `state`; row cap; EMA smoothing  
- **Views**:
  - **Anomaly score timeline** with threshold & hit markers  
  - **RAW KPIs**: sload/dload (dual axis), spkts/dpkts, jitter, TCP handshake (tcprtt/synack/ackdat)  
  - **Distributions**: protocol/state percent stacks (Normal vs Anomaly, Top-K + “Other”)  
  - **Heatmap**: `ct_state_ttl` grouped buckets over time  
  - **Recent anomalies & Top-10** tables with **CSV download**  

Built-in optimizations: caching (`@st.cache_resource`, `@st.cache_data`), connection pooling, WebGL rendering.

---

## Demo

- **Full video (YouTube)**: https://youtu.be/XSlEOjZ624Y  

<details>
  <summary>GIF preview (click to expand)</summary>

  ![Real-time demo](assets/anomaly_detection.png)

</details>

---

## Alerts & Notifications

- **Trigger**: score ≥ `threshold` **OR** ≥ `N` anomalies within `W` minutes (burst).  
- **Channel**: Slack webhook (optional, set `SLACK_WEBHOOK_URL` in `.env`).

**Example Slack message:**

![Slack alert screenshot](assets/slack-message.png)

Payload snippet:
```json
{
  "type": "burst",
  "hits_in_window": 12,
  "window_min": 5,
  "top_context": {"proto":"tcp", "state":"CON", "service":"http"},
  "threshold": 0.5
}
```

---

## Performance Metrics (fill with your measurements)

| Metric                         | Value     | Notes                         |
|-------------------------------|----------:|-------------------------------|
| End-to-end latency (median)   | **XXX ms**| Producer → DB → Dashboard     |
| p95 latency                   | **XXX ms**|                               |
| Throughput (EPS)              | **XXX/s** |                               |
| FPR @ threshold=0.5           | **X.XX%** | validation window             |
| Burst detection delay         | **XXX ms**|                               |

> Add a small load script to reproduce numbers; include graphs/screenshots if possible.

---

## Tests (recommended)

- **Unit**
  - KL/L1: expected value ranges on known distributions  
  - ADWIN: assert a trigger after a deliberate distribution shift
- **Integration**
  - Send a fake event → `/predict` → verify row upserted in DB and 200 OK

Example files: `tests/test_divergence.py`, `tests/test_adwin.py`, `tests/test_ingest.py`.

---

## Operations & Scaling

- **DB**
  - Index on `stime`; consider **partitioning** by day/hour for large volumes  
  - Only fetch required columns; conservative defaults for time window; enforce a row cap
- **Pooling & health**
  - `psycopg2.SimpleConnectionPool(min=1, max=8)`; add `/healthz` and graceful shutdown
- **Logging/metrics**
  - Structured logs; (optional) Prometheus/StatsD for API latency, DB query time, Kafka lag
- **Alerts**
  - Slack/webhook on threshold/burst; include recent context (proto/state/service) in the payload

---

## Large Files & Data Management

Keep the repo **code-only** + small samples. Exclude:
```gitignore
data/
models/
checkpoints/
*.pkl
*.parquet
*.zip
.ipynb_checkpoints/
__pycache__/
.DS_Store
```

Host large artifacts on **Releases / HF Hub / S3 / DVC remote**.  
If you accidentally committed large files, rewrite history:
```bash
git filter-repo --strip-blobs-bigger-than 100M
git push --force
```

---

## Handy Commands

```bash
# Clear notebook outputs (before commit)
jupyter nbconvert --clear-output --inplace **/*.ipynb

# Lint/format (if configured)
ruff check . && ruff format .

# Compose up
docker compose up -d --build
```

---

## Roadmap

- [ ] `/metrics` (Prometheus) endpoint  
- [ ] Stronger input validation (pydantic models)  
- [ ] Table partitioning & TTL/archiving job  
- [ ] CI: lint + tests + Docker build (GitHub Actions)  
- [ ] 60-sec demo video + Slack alert screenshot in README

---

## License & Data

- Code license: **MIT** (change as you wish)  
- Datasets (e.g., UNSW-NB15) follow their original licenses; this repo **does not** include large data files.

---

## Contributing

Issues and PRs are welcome. Please include reproducible steps (env, inputs, expected results).

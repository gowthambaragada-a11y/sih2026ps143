# OILTRACE-AI

> Automated, evidence-based oil-spill *origin* estimation and *vessel attribution*
> from satellite SAR + AIS, built for **SIH 2026 · Problem Statement 143 (NTRO)**.

Oil slicks do not carry a signature — but the vessels around them do. OILTRACE-AI
reverses the physics: it **detects the slick** in SAR imagery, **drifts it
backward in time** through wind/current fields to a probable **origin region**,
then **correlates historical AIS tracks** against that space-time window and
produces a **probabilistic, evidence-grounded vessel ranking** — never a verdict.

The entire stack runs offline on synthetic-but-physically-plausible reference
events, with trained ML models, a persisted audit trail, and a web dashboard.

---

## 1. What it does

| Stage | Input | Output |
|---|---|---|
| **Detection** | SAR scene | Slick polygon + centroid + confidence (U-Net segmentation, look-alike rejection) |
| **Drift reconstruction** | Slick + met-ocean fields | Backward & forward Lagrangian ensembles with uncertainty |
| **Origin estimation** | Backward ensemble | Probability-weighted origin region + release-time hypotheses (XGBoost + SAR age prior) |
| **AIS correlation** | AIS history + origin window | Candidate vessels with spatial / temporal / trajectory evidence |
| **Attribution** | Evidence + vessel metadata + anomaly scores | Ranked vessels with per-evidence flags (XGBoost fused with engineered scores) |

The output is a timestamped, non-accusatory **investigation report** (JSON +
Markdown) whose content is protected by a SHA-256 provenance hash in the audit log.

### Probability, not guilt
Every score is a probability / evidence strength. A high ranking means *"most
consistent with the observed slick, given drift and AIS uncertainty"* — it is
explicitly **not** a determination of responsibility. Gaps in AIS coverage
produce *"AIS coverage gap — requires verification"* flags, never a negative
inference.

---

## 2. Architecture

```
                        ┌──────────────────────────────────────────────┐
   SAR scene ─────────► │ DETECTION            detection.py → unet-v1    │
                        │   segment → polygon→ centroid, conf, warnings │
                        └────────────┬─────────────────────────────────┘
                                     │ slick centroid
                        ┌────────────▼─────────────────────────────────┐
   wind / current ─────► │ DRIFT                 engine(backward/forward)│
                        │   Lagrangian ensemble n_members; uncertainty  │
                        └────────────┬─────────────────────────────────┘
                                     │ mean backward trajectory
                        ┌────────────▼─────────────────────────────────┐
                        │ ORIGIN      candidate offsets 6..48h          │
                        │   XGBoost prob. (SAR age prior); region       │
                        └────────────┬─────────────────────────────────┘
                                     │ origin candidates (lat/lon/time)
                        ┌────────────▼─────────────────────────────────┐
   AIS history ────────► │ AIS correlation  proximity, time-window,     │
                        │   trajectory alignment, anomaly detection     │
                        └────────────┬─────────────────────────────────┘
                                     │ per-vessel evidence
                        ┌────────────▼─────────────────────────────────┐
                        │ ATTRIBUTION  evidence scores + ML fusion →     │
                        │   ranked vessels + evidence flags              │
                        └────────────┬─────────────────────────────────┘
                                     │
                  ┌──────────────────┼──────────────────────┐
                  ▼                   ▼                      ▼
            FastAPI + store      Report (json/md)       MapLibre dashboard
                  │                   │                      │
            SQLite/PostGIS      SHA-256 audit log     layers + ranking UI
```

## 3. Repository layout

```
.
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI: state cache, routers (health, events,
│   │   │                   #           detection, drift, origins, ais,
│   │   │                   #           attribution, report, store)
│   │   ├── core/           # config, geo kernels, logging
│   │   ├── models/         # Pydantic schemas
│   │   └── services/
│   │       ├── pipeline.py         # orchestrator (run_analysis)
│   │       ├── demo.py             # synthetic reference scenario generator
│   │       ├── evaluation.py       # event-level metric harness
│   │       ├── report.py           # JSON+Markdown report generator
│   │       ├── store.py            # SQLAlchemy persistence + audit log
│   │       ├── detection/          # U-Net model, inference, training
│   │       ├── drift/              # Lagrangian drift engine + met-ocean fields
│   │       ├── origin/             # XGBoost origin model
│   │       ├── attribution/        # XGBoost + evidence score fusion
│   │       └── ais/                # synthetic AIS loader, anomaly scoring
│   ├── db/schema.sql      # PostGIS production DDL (mirrors store.py)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/               # Vite + React + TypeScript + MapLibre dashboard
│   ├── src/components/     # MapView, VesselPanel, OriginPanel, Summary, toggles
│   ├── nginx.conf          # reverse proxy /api → backend for the built bundle
│   └── Dockerfile
├── models/                 # trained artifacts (see §5)
├── notebooks/  scripts/  docs/  datasets/
└── docker-compose.yml      # api + web (optional PostGIS service included)
```

## 4. Quickstart

### Backend (Python)

```bash
cd backend
python -m pip install -r requirements.txt
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu  # CPU locals
uvicorn app.main:app --port 8000
```

### Dashboard (Node 20+)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api → :8000)
```

### Run a full analysis

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/analyze
curl  http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/detection
curl  http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/drift/backward
curl  http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/origins
curl  http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/ais/vessels
curl  http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/attribution
curl -X POST http://127.0.0.1:8000/api/v1/events/SIH-2026-SPILL-001/report/persist
```

### One-command stack (Docker)

```bash
docker compose up --build
# dashboard → http://localhost:8080   API → http://localhost:8000
```

### Training / evaluation CLI

```bash
python -m app.services.model_training --stage detection        # also: origin, attribution, anomaly
python -m app.services.evaluation --seeds 1 3 5 7 11 --n-members 12 16 20
```

## 5. Trained models

| Model | Artifact | Purpose |
|---|---|---|
| U-Net segmentation | `models/oil_segmentation/oil_segmentation.pt` | slick/look-alike masks; val Dice 0.943 |
| Origin XGBoost | `models/origin_xgboost/origin_model.pkl` | candidate probability incl. SAR age prior; AUC 0.89 |
| Attribution XGBoost | `models/vessel_xgboost/vessel_model.pkl` | evidence fusion; trained on scenario fleets |
| AIS IsolationForest | `models/ais_isolation_forest/ais_model.pkl` | behavioural anomaly scoring |

## 6. Measured behaviour (15-event sweep)

| Metric | Value |
|---|---|
| Truth-vessel at rank #1 (top-1 hit rate) | **100 %** (15/15, seeds {1,3,5,7,11} × n_members {12,16,20}) |
| Mean score margin to next-ranked vessel | +2.1 pts |
| Best origin hypothesis distance error | 3.5 ± 1.0 km |
| Release-time error (n_members ≥ 16) | 0–6 h (vs 6 h candidate discretization) |

Raw per-event numbers: `backend/artifacts/evaluation/eval_15events.json`.

## 7. Spec coverage

- SS01 Synchroscan/floodfill-like slick mask, look-alike handling ✓
- SS09 Drift-based backward/forward reconstruction (OpenDrift slot + fallback engine) ✓
- SS13 Geophysical/hydrological time-series fields + ensemble uncertainty ✓
- SS14 As-Built / prior-analysis hyperlinked reports ✓ (report + provenance hash)
- SS18 Legal-aware per-vessel correlation, provenance audit trail ✓
- Guardrails: probabilistic output, uncertainty surfaced in every stage,
  coverage-gap flags, synthetic-data labels, no fabricated metrics.

## 8. Honest limitations

- **Synthetic reference data only** until validated against real SAR/AIS.
- Origin release-time is **discretized to 6 h bins**; fine-grained (<6h) timing
  error should not be over-interpreted. With small ensembles (n_members=12) the
  top candidate can shift bins (~12 h error) — the default n_members=16 wheels
  mitigate this.
- Detection accuracy is tied to the synthetic scene template (constant ~5 km
  centroid offset in the harness).
- The drift engine is a simplified Lagrangian model; OpenDrift/GNOME integration
  is the production path (`engine="opendrift"`).

---

*Built for SIH 2026 · PS143 · NTRO. All scenarios are synthetic; nothing in this
repository should be treated as real vessel incrimination.*
# OILTRACE-AI Analysis Report

- **Event**: FINAL-CHECK
- **Generated (UTC)**: 2026-09-08T12:36:02Z
- **Models**: {"detection": "unet-v1", "origin": "v1", "attribution": "v1", "anomaly": "isoforest-v1", "drift_engine": "fallback"}

## 1. Detection
- Status: **detected**  (confidence 0.70)
- Area: **4.902 km²**  at (20.235, 60.001)

## 2. Drift Reconstruction
- Backward uncertainty: **13.31 km** (16 member trajectories)
- Forward forecast uncertainty: **11.38 km**

## 3. Origin Estimation
- Region confidence: **0.67**, uncertainty **13.31 km**

| Candidate | Lat | Lon | Release (h) | Duration (h) | Prob |
|---|---|---|---|---|---|
| O2 | 20.016 | 59.958 | 1970-01-02 01:00 | 18 | 0.272 |
| O3 | 19.948 | 59.959 | 1970-01-01 19:00 | 24 | 0.214 |
| O0 | 20.160 | 59.980 | 1970-01-02 13:00 | 6 | 0.199 |
| O1 | 20.085 | 59.963 | 1970-01-02 07:00 | 12 | 0.140 |
| O4 | 19.785 | 59.965 | 1970-01-01 07:00 | 36 | 0.091 |
| O5 | 19.628 | 59.979 | 1969-12-31 19:00 | 48 | 0.085 |

## 4. Candidate Vessel Ranking

| Rank | Vessel | Type | Overall | Spatial | Temporal | Trajectory | Suitability |
|---|---|---|---|---|---|---|---|
| 1 | MV DEMO-000000 | tanker | 75.2 | 98.1 | 61.6 | 22.1 | 100.0 |
| 2 | MV DEMO-000002 | tanker | 72.6 | 98.2 | 49.2 | 21.5 | 100.0 |
| 3 | MV DEMO-000001 | cargo | 63.9 | 98.1 | 23.8 | 22.3 | 40.0 |

### Evidence detail

**1. MV DEMO-000000** (score 75.2)
- `positive` Entered probable origin region — min distance 1.0 km
- `positive` Present during estimated spill window — time difference 2.3 h
- `positive` Trajectory intersects origin probability zone
- `positive` Heading compatible with reconstructed movement — heading diff 40 deg

**2. MV DEMO-000002** (score 72.6)
- `positive` Entered probable origin region — min distance 0.9 km
- `positive` Present during estimated spill window — time difference 2.3 h
- `positive` Trajectory intersects origin probability zone
- `positive` Heading compatible with reconstructed movement — heading diff 41 deg

**3. MV DEMO-000001** (score 63.9)
- `positive` Entered probable origin region — min distance 1.0 km
- `positive` Present during estimated spill window — time difference 2.3 h
- `positive` Trajectory intersects origin probability zone
- `positive` Heading compatible with reconstructed movement — heading diff 39 deg

## 5. Uncertainties & Warnings


> This analysis is evidence-based and probabilistic.  A high ranking is not a determination of responsibility; it identifies the vessel most consistent with the observed slick subject to drift and AIS uncertainty. Ground truth linking requires supplementary investigation.
-- ============================================================================
-- OILTRACE-AI production persistence schema  (PostgreSQL + PostGIS target)
-- ----------------------------------------------------------------------------
-- Mirrors app/services/store.py (SQLite fallback) for offline demo runs.
-- Run with:  psql "$DATABASE_URL" -f db/schema.sql
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- 1. Spill events (master record, SS18 provenance: source + ingested_at)
CREATE TABLE IF NOT EXISTS spill_events (
    event_id          TEXT PRIMARY KEY,
    date              DATE,
    time              TIME,
    location          GEOMETRY(Point, 4326),
    status            TEXT,
    source            TEXT NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_detection   TEXT,
    model_origin      TEXT,
    model_attribution TEXT,
    model_anomaly     TEXT,
    model_drift       TEXT
);

-- 2. Detection records
CREATE TABLE IF NOT EXISTS detections (
    id               BIGSERIAL PRIMARY KEY,
    spill_id         TEXT NOT NULL REFERENCES spill_events(event_id),
    area_km2         DOUBLE PRECISION NOT NULL,
    confidence       DOUBLE PRECISION NOT NULL,
    centroid         GEOMETRY(Point, 4326) NOT NULL,
    polygon          GEOMETRY(Polygon, 4326) NOT NULL,
    metadata_json    JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_detections_spill ON detections(spill_id);

-- 3. Drift ensembles (one row per direction)
CREATE TABLE IF NOT EXISTS drift_ensembles (
    id                        BIGSERIAL PRIMARY KEY,
    spill_id                  TEXT NOT NULL REFERENCES spill_events(event_id),
    direction                 TEXT NOT NULL CHECK (direction IN ('backward','forward')),
    n_members                 INTEGER NOT NULL,
    uncertainty_km            DOUBLE PRECISION NOT NULL,
    mean_trajectory           GEOMETRY(LineString, 4326),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_drift_spill ON drift_ensembles(spill_id, direction);

-- 4. Origin hypotheses (probability per candidate)
CREATE TABLE IF NOT EXISTS origin_hypotheses (
    id               BIGSERIAL PRIMARY KEY,
    spill_id         TEXT NOT NULL REFERENCES spill_events(event_id),
    candidate_id     TEXT NOT NULL,
    location         GEOMETRY(Point, 4326) NOT NULL,
    release_time     DOUBLE PRECISION NOT NULL,          -- seconds since scene epoch
    probability      DOUBLE PRECISION NOT NULL,
    distance_km      DOUBLE PRECISION NOT NULL,
    drift_duration_h DOUBLE PRECISION NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_origin_spill ON origin_hypotheses(spill_id);

-- 5. Vessel registry
CREATE TABLE IF NOT EXISTS vessels (
    mmsi   TEXT PRIMARY KEY,
    imo    TEXT,
    name   TEXT,
    type   TEXT,
    length DOUBLE PRECISION,
    width  DOUBLE PRECISION,
    draft  DOUBLE PRECISION,
    cargo  TEXT,
    source TEXT NOT NULL
);

-- 6. AIS fixes (spatial index)
CREATE TABLE IF NOT EXISTS ais_fixes (
    id        BIGSERIAL PRIMARY KEY,
    mmsi      TEXT NOT NULL REFERENCES vessels(mmsi),
    timestamp DOUBLE PRECISION NOT NULL,
    location  GEOMETRY(Point, 4326) NOT NULL,
    sog       DOUBLE PRECISION,
    cog       DOUBLE PRECISION,
    heading   DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_ais_mmsi_t ON ais_fixes(mmsi, timestamp);
CREATE INDEX IF NOT EXISTS idx_ais_loc ON ais_fixes USING GIST(location);

-- 7. Attribution rows (one per candidate vessel per event)
CREATE TABLE IF NOT EXISTS attributions (
    id                 BIGSERIAL PRIMARY KEY,
    spill_id           TEXT NOT NULL REFERENCES spill_events(event_id),
    mmsi               TEXT NOT NULL REFERENCES vessels(mmsi),
    rank               INTEGER NOT NULL,
    overall            DOUBLE PRECISION NOT NULL,
    spatial            DOUBLE PRECISION NOT NULL,
    temporal           DOUBLE PRECISION NOT NULL,
    trajectory         DOUBLE PRECISION NOT NULL,
    vessel_suitability DOUBLE PRECISION NOT NULL,
    behaviour          DOUBLE PRECISION NOT NULL,
    ais_evidence       DOUBLE PRECISION NOT NULL,
    anomaly_score      DOUBLE PRECISION NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (spill_id, mmsi)
);
CREATE INDEX IF NOT EXISTS idx_attr_spill ON attributions(spill_id, rank);

-- 8. Attribution evidence flags
CREATE TABLE IF NOT EXISTS attribution_evidence (
    id       BIGSERIAL PRIMARY KEY,
    spill_id TEXT NOT NULL REFERENCES spill_events(event_id),
    mmsi     TEXT NOT NULL,
    label    TEXT NOT NULL,
    flag     TEXT NOT NULL,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_ev_spill ON attribution_evidence(spill_id, mmsi);

-- 9. Reports with SHA-256 provenance hash
CREATE TABLE IF NOT EXISTS reports (
    report_id     TEXT PRIMARY KEY,
    spill_id      TEXT NOT NULL REFERENCES spill_events(event_id),
    generated_utc TIMESTAMPTZ NOT NULL,
    sha256        TEXT NOT NULL,
    report_json   JSONB NOT NULL,
    report_md     TEXT NOT NULL
);

-- 10. Audit log (SS18 legal provenance chain)
CREATE TABLE IF NOT EXISTS audit_log (
    id           BIGSERIAL PRIMARY KEY,
    spill_id     TEXT NOT NULL REFERENCES spill_events(event_id),
    action       TEXT NOT NULL,
    detail       TEXT,
    payload_hash TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_spill ON audit_log(spill_id);

-- convenience view: slim event-level summary
CREATE OR REPLACE VIEW vw_event_summary AS
SELECT e.event_id, e.status, e.ingested_at,
       d.area_km2, d.confidence,
       o.top_origin_prob,
       a.top_vessel_mmsi, a.top_vessel_score
FROM spill_events e
LEFT JOIN LATERAL (
    SELECT area_km2, confidence FROM detections
    WHERE spill_id = e.event_id ORDER BY created_at DESC LIMIT 1
) d ON true
LEFT JOIN LATERAL (
    SELECT COALESCE(MAX(probability), 0) AS top_origin_prob
    FROM origin_hypotheses WHERE spill_id = e.event_id
) o ON true
LEFT JOIN LATERAL (
    SELECT mmsi AS top_vessel_mmsi, overall AS top_vessel_score
    FROM attributions WHERE spill_id = e.event_id ORDER BY rank LIMIT 1
) a ON true;
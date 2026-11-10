-- Roam Transit OS: production schema target (PostgreSQL 15+, PostGIS, h3-pg).
-- The MVP runs on the in-memory store (roam/store.py) which enforces the same contract.
-- Multi-tenancy: every tenant-owned row carries tenant_id and is protected by row-level
-- security. Application sessions set `app.tenant_ids` (comma list) or `app.role = 'ops'`.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS h3;          -- h3-pg
CREATE EXTENSION IF NOT EXISTS h3_postgis;

CREATE TABLE tenant (
  id                 text PRIMARY KEY,
  name               text NOT NULL,
  type               text NOT NULL CHECK (type IN ('city','county','transit_agency','community_org')),
  region             jsonb NOT NULL,
  timezone           text NOT NULL,
  contract_terms     jsonb NOT NULL DEFAULT '{}',
  data_export_policy text NOT NULL DEFAULT 'full_export_any_time_no_exit_fee',
  config             jsonb NOT NULL,          -- the tenant config file, versioned below
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE service_zone (
  id        text PRIMARY KEY,
  tenant_id text NOT NULL REFERENCES tenant(id),
  name      text,
  mode      text NOT NULL CHECK (mode IN ('paratransit','microtransit','av_network')),
  geom      geometry(MultiPolygon, 4326) NOT NULL,
  h3_cells  h3index[] NOT NULL DEFAULT '{}'
);
CREATE INDEX ON service_zone USING gist (geom);

CREATE TABLE service_policy (
  id                text PRIMARY KEY,
  tenant_id         text NOT NULL REFERENCES tenant(id),
  version           int  NOT NULL,
  hours             jsonb NOT NULL,
  fares             jsonb NOT NULL,
  eligibility_rules jsonb NOT NULL,
  booking_rules     jsonb NOT NULL,
  ada_rules         jsonb,
  effective_from    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, version)               -- service-change requests create new versions
);

CREATE TABLE rider (                         -- minimal personal data by design
  id                  text PRIMARY KEY,
  tenant_id           text NOT NULL REFERENCES tenant(id),
  contact             jsonb NOT NULL DEFAULT '{}',   -- encrypt at rest (pgcrypto / KMS); HIPAA when medical trips
  accessibility_needs text[] NOT NULL DEFAULT '{}',
  eligibility_status  text NOT NULL DEFAULT 'none',
  eligibility_expires date,
  saved_places        jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE funding_source (
  id          text PRIMARY KEY,
  tenant_id   text NOT NULL REFERENCES tenant(id),
  type        text NOT NULL CHECK (type IN ('city','county','institution','grant','medicaid_nemt')),
  name        text,
  account_ref text,
  rules       jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE vehicle (
  id                   text PRIMARY KEY,
  tenant_id            text NOT NULL REFERENCES tenant(id),
  adapter_kind         text NOT NULL CHECK (adapter_kind IN ('human_driver','av_partner','simulator')),
  seats                int  NOT NULL,
  wheelchair_positions int  NOT NULL,
  max_range_km         numeric,
  lease_ref            text,
  odd_zone_ids         text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE driver (
  id               text PRIMARY KEY,
  tenant_id        text NOT NULL REFERENCES tenant(id),
  operator_partner text,
  certifications   text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE shift (
  id           text PRIMARY KEY,
  tenant_id    text NOT NULL REFERENCES tenant(id),
  vehicle_id   text NOT NULL REFERENCES vehicle(id),
  driver_id    text REFERENCES driver(id),   -- NULL for driverless
  service_date date NOT NULL,
  starts_at    timestamptz NOT NULL,
  ends_at      timestamptz NOT NULL
);

CREATE TABLE trip_request (
  id                text PRIMARY KEY,
  tenant_id         text NOT NULL REFERENCES tenant(id),
  rider_id          text NOT NULL REFERENCES rider(id),
  mode              text NOT NULL,
  channel           text NOT NULL CHECK (channel IN ('app','web','ivr','agent')),
  origin            geometry(Point, 4326) NOT NULL,
  destination       geometry(Point, 4326) NOT NULL,
  service_date      date NOT NULL,
  requested_time    timestamptz NOT NULL,
  time_type         text NOT NULL DEFAULT 'pickup',
  window_start      timestamptz,
  window_end        timestamptz,
  funding_source_id text REFERENCES funding_source(id),
  standing_order_id text,
  status            text NOT NULL,
  status_reason     text,
  vehicle_id        text REFERENCES vehicle(id),
  pickup_arrival    timestamptz,
  actual_pickup     timestamptz,
  actual_dropoff    timestamptz,
  fare              numeric(8,2)
);
CREATE INDEX ON trip_request (tenant_id, service_date, status);

CREATE TABLE run  (id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenant(id), shift_id text NOT NULL REFERENCES shift(id), status text NOT NULL);
CREATE TABLE stop (
  id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenant(id), run_id text NOT NULL REFERENCES run(id),
  trip_request_id text REFERENCES trip_request(id), type text NOT NULL, seq int NOT NULL,
  eta timestamptz, actual timestamptz, status text NOT NULL
);

CREATE TABLE event (                          -- append-only; partition by month in production
  id         text PRIMARY KEY,
  tenant_id  text NOT NULL REFERENCES tenant(id),
  vehicle_id text,
  type       text NOT NULL,
  ts         timestamptz NOT NULL,
  location   geometry(Point, 4326),
  payload    jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON event (tenant_id, ts);

CREATE TABLE incident (
  id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenant(id), event_ids text[], severity int NOT NULL,
  summary text, parties text[], injuries boolean, notifications jsonb, status text NOT NULL, close_out text
);

CREATE TABLE invoice (
  id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenant(id), period text NOT NULL, vehicles int,
  platform_fee numeric(12,2), revenue_hours numeric(12,2), ops_fee numeric(12,2), performance_adj numeric(12,2),
  performance_detail jsonb, total numeric(12,2)
);

CREATE TABLE kpi_snapshot (tenant_id text NOT NULL REFERENCES tenant(id), period text NOT NULL, metrics jsonb NOT NULL, PRIMARY KEY (tenant_id, period));

-- ------------------------------------------------------------------ row-level security
CREATE OR REPLACE FUNCTION app_can_see(t text) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT current_setting('app.role', true) = 'ops'
      OR t = ANY (string_to_array(coalesce(current_setting('app.tenant_ids', true), ''), ','))
$$;

DO $$
DECLARE tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['service_zone','service_policy','rider','funding_source','vehicle','driver','shift',
                             'trip_request','run','stop','event','incident','invoice','kpi_snapshot']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (app_can_see(tenant_id)) WITH CHECK (app_can_see(tenant_id))', tbl);
  END LOOP;
END $$;
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON tenant USING (app_can_see(id));

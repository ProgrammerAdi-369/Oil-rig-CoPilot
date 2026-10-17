-- Raw tables mirror the dataset files. Everything derived (producing, downtime, real spill) lives in views
-- so corrections and rule overrides flow into every answer without rewriting raw rows.

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS teams (team_id TEXT PRIMARY KEY, name TEXT, lead_user_id TEXT);
CREATE TABLE IF NOT EXISTS areas (area_id TEXT PRIMARY KEY, name TEXT, team_id TEXT, lat REAL, lon REAL);
CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT, team_id TEXT);

CREATE TABLE IF NOT EXISTS wells (
  asset_id TEXT PRIMARY KEY, name TEXT, well_type TEXT, area_id TEXT, team_id TEXT, in_charge_user_id TEXT,
  lat REAL, lon REAL, installed_on TEXT, recorded_status TEXT, last_inspection_id TEXT,
  status TEXT, decommissioned_on TEXT);  -- status 'plugged_and_abandoned' = permanently closed (test data)
CREATE TABLE IF NOT EXISTS equipment (
  equipment_id TEXT PRIMARY KEY, asset_id TEXT, kind TEXT, model TEXT);

-- a well's type / team over time; when a well has no history its current wells.well_type / team_id apply
CREATE TABLE IF NOT EXISTS well_type_history (asset_id TEXT, well_type TEXT, from_date TEXT, to_date TEXT);
CREATE TABLE IF NOT EXISTS well_team_history (asset_id TEXT, team_id TEXT, from_date TEXT, to_date TEXT);
CREATE INDEX IF NOT EXISTS ix_th_asset ON well_type_history(asset_id);

CREATE TABLE IF NOT EXISTS inspections (
  inspection_id TEXT PRIMARY KEY, asset_id TEXT, inspected_at TEXT, inspector_user_id TEXT, method TEXT,
  ambient_temp_c REAL, wellhead_temp_c REAL, spill_detected INTEGER, spill_area_pct REAL,
  spill_est_volume_bbl REAL, notes TEXT, recorded_at TEXT);  -- recorded_at: set when an inspection was entered late
CREATE INDEX IF NOT EXISTS ix_ins_asset_time ON inspections(asset_id, inspected_at);

CREATE TABLE IF NOT EXISTS maintenance (
  maintenance_id TEXT PRIMARY KEY, asset_id TEXT, started_at TEXT, completed_at TEXT, maintenance_type TEXT,
  equipment_kind TEXT, issue TEXT, action_taken TEXT, technician_user_id TEXT, contractor TEXT,
  downtime_hours REAL, cost_labor REAL, cost_parts REAL, cost_total REAL,
  triggered_by_inspection_id TEXT, report_file TEXT, root_cause TEXT,
  recorded_at TEXT, cost_original REAL, cost_revised_on TEXT, cost_revision_reason TEXT);  -- cost_total is the revised amount
CREATE INDEX IF NOT EXISTS ix_mnt_asset_start ON maintenance(asset_id, started_at);

-- facts extracted from a repair report's text (extract.parse_report); interim reports describe work still in progress
CREATE TABLE IF NOT EXISTS report_facts (
  maintenance_id TEXT PRIMARY KEY, interim INTEGER, pump_model TEXT, pump_serial TEXT, pump_lot TEXT,
  followup_days INTEGER, followup_text TEXT, soil_samples_lab INTEGER, h2s_ppm REAL,
  extra_days INTEGER, extra_days_expected INTEGER, delay_reason TEXT, delay_text TEXT, root_cause_category TEXT);

-- operator notes classified by extract.classify_note (gas_odor, bypass_in, bypass_out, shut_in, restart, delay_*, anomalies, routine)
CREATE TABLE IF NOT EXISTS note_events (note_id TEXT PRIMARY KEY, asset_id TEXT, ts TEXT, kind TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_ne_asset_ts ON note_events(asset_id, ts);
CREATE INDEX IF NOT EXISTS ix_ne_kind ON note_events(kind, ts);

-- fleet documents: management-of-change memos, supplier recall notices, regulator letters
CREATE TABLE IF NOT EXISTS moc (moc_id TEXT, well_id TEXT, effective_from TEXT, expires TEXT, extends TEXT, title TEXT, PRIMARY KEY (moc_id, well_id));
CREATE TABLE IF NOT EXISTS recalls (ref TEXT, model TEXT, lot TEXT, notice_date TEXT, deadline TEXT, PRIMARY KEY (ref, lot));
CREATE TABLE IF NOT EXISTS regulator_letters (
  ref TEXT PRIMARY KEY, date TEXT, areas TEXT, since TEXT, due TEXT, min_bbl REAL, required_sentence TEXT, source TEXT);

-- facts users tell the copilot about an asset (e.g. "the recalled pump was swapped"); first-hand statements apply,
-- second-hand ones are kept as 'hearsay' and never applied. Visible to everyone, always attributed.
CREATE TABLE IF NOT EXISTS asset_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT, kind TEXT, author_user_id TEXT, source_user_id TEXT,
  status TEXT, text TEXT, created_at TEXT);
-- private presentation preferences ("sort by area, costs in thousands"): applied only for that user
CREATE TABLE IF NOT EXISTS user_prefs (user_id TEXT, key TEXT, value TEXT, created_at TEXT, PRIMARY KEY (user_id, key));

-- one row per protocol line of a report's "Compliance check" table; containment_hours parsed from the SR-02 row
CREATE TABLE IF NOT EXISTS report_compliance (
  maintenance_id TEXT, protocol_id TEXT, result TEXT, detail TEXT, containment_hours REAL,
  PRIMARY KEY (maintenance_id, protocol_id));

CREATE TABLE IF NOT EXISTS regulatory_events (
  event_id TEXT PRIMARY KEY, asset_id TEXT, date TEXT, agency TEXT, event_type TEXT, protocol_id TEXT,
  related_inspection_id TEXT, hours_to_report REAL, detail TEXT, fine_usd REAL, status TEXT);

-- human notes: dataset notes (status 'confirmed') and runtime feedback (status confirmed|unconfirmed|disputed)
CREATE TABLE IF NOT EXISTS notes (
  note_id TEXT PRIMARY KEY, asset_id TEXT, created_at TEXT, author_user_id TEXT, note_type TEXT,
  inspection_id TEXT, text TEXT, valid_from TEXT, valid_to TEXT, status TEXT DEFAULT 'confirmed');

-- structured meaning of a runtime note: 1 = says the well is running, 0 = says it is stopped/shut in
CREATE TABLE IF NOT EXISTS note_claims (note_id TEXT PRIMARY KEY, claims_producing INTEGER);

-- private memory: always read with a hard user_id filter
CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, chat_id TEXT, ts TEXT, role TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS conversation_entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, chat_id TEXT, ts TEXT, label TEXT, well_ids TEXT);

-- the structured answer (visual, rows, evidence, trace) shown for an assistant turn, so a reloaded chat looks identical
CREATE TABLE IF NOT EXISTS chat_payloads (conversation_id INTEGER PRIMARY KEY, payload TEXT);

-- overrides of a raw value; the original stays in its raw table and in original_value here
CREATE TABLE IF NOT EXISTS corrections (
  correction_id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT, target_id TEXT, field TEXT,
  original_value REAL, corrected_value REAL, author_user_id TEXT, reason TEXT,
  scope TEXT DEFAULT 'inspection', scope_value TEXT, created_at TEXT, status TEXT DEFAULT 'active',
  source_note_id TEXT UNIQUE);

-- thresholds and deadlines from manuals/SOPs; scope well_type beats global; source cites the document or user
CREATE TABLE IF NOT EXISTS rules (
  scope TEXT, scope_value TEXT, key TEXT, value REAL, unit TEXT, source TEXT, section TEXT, created_by TEXT,
  created_at TEXT, PRIMARY KEY (scope, scope_value, key, source));

-- searchable text: manual/SOP sections, report sections, notes
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY, doc_type TEXT, ref_id TEXT, asset_id TEXT, well_type TEXT, title TEXT, text TEXT,
  embedding BLOB);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, title, text);

CREATE INDEX IF NOT EXISTS ix_corr_target ON corrections(target_id, field, status);
CREATE INDEX IF NOT EXISTS ix_rules_key ON rules(key, scope, scope_value);

-- every inspection with corrections applied and the producing rule of the well type IN FORCE on that date
DROP VIEW IF EXISTS inspection_eff;
CREATE VIEW inspection_eff AS
WITH base AS (
  SELECT i.inspection_id, i.asset_id, i.inspected_at, i.inspector_user_id, i.method, i.ambient_temp_c,
         i.wellhead_temp_c, i.spill_area_pct, i.notes, w.area_id,
    COALESCE((SELECT h.well_type FROM well_type_history h WHERE h.asset_id=i.asset_id AND h.from_date <= date(i.inspected_at)
              AND (h.to_date IS NULL OR h.to_date = '' OR date(i.inspected_at) <= h.to_date) ORDER BY h.from_date DESC LIMIT 1),
             w.well_type) AS well_type,
    COALESCE((SELECT c.corrected_value FROM corrections c WHERE c.status='active' AND c.target_type='inspection'
              AND c.target_id=i.inspection_id AND c.field='wellhead_temp_c' ORDER BY c.correction_id DESC LIMIT 1),
             i.wellhead_temp_c) AS wh_temp_c,
    COALESCE((SELECT c.corrected_value FROM corrections c WHERE c.status='active' AND c.target_type='inspection'
              AND c.target_id=i.inspection_id AND c.field='spill_detected' ORDER BY c.correction_id DESC LIMIT 1),
             i.spill_detected) AS spill_real,
    i.spill_detected AS spill_detected_raw,
    COALESCE((SELECT c.corrected_value FROM corrections c WHERE c.status='active' AND c.target_type='inspection'
              AND c.target_id=i.inspection_id AND c.field='spill_est_volume_bbl' ORDER BY c.correction_id DESC LIMIT 1),
             i.spill_est_volume_bbl) AS spill_bbl,
    i.asset_id AS _a
  FROM inspections i JOIN wells w USING (asset_id)),
lim AS (
  SELECT b.*, (SELECT value FROM rules r WHERE r.key='producing_delta_c' AND r.scope='well_type' AND r.scope_value=b.well_type
                ORDER BY r.created_at DESC LIMIT 1) AS delta_limit_c FROM base b)
SELECT *, wh_temp_c - ambient_temp_c AS delta_c,
       CASE WHEN wh_temp_c - ambient_temp_c >= delta_limit_c THEN 1 ELSE 0 END AS producing
FROM lim;

-- OPS-3: the current status is the most recent of (a) the latest inspection reading and (b) the latest operator note that says
-- the well was shut in or restarted. A newer shut-in note => shut_in; a newer restart note => producing_unconfirmed.
DROP VIEW IF EXISTS well_status_now;
CREATE VIEW well_status_now AS
SELECT li.asset_id, li.inspection_id, li.inspected_at, li.producing AS insp_producing, li.delta_c, li.delta_limit_c, li.well_type, li.area_id,
       n.note_id, n.ts AS note_ts, n.kind AS note_kind,
       CASE WHEN n.ts IS NOT NULL AND n.ts > li.inspected_at THEN (CASE n.kind WHEN 'shut_in' THEN 'shut_in' ELSE 'producing_unconfirmed' END)
            WHEN li.producing = 1 THEN 'producing' ELSE 'not_producing' END AS status
FROM inspection_eff li
LEFT JOIN note_events n ON n.note_id = (SELECT x.note_id FROM note_events x WHERE x.asset_id = li.asset_id AND x.kind IN ('shut_in','restart')
                                        ORDER BY x.ts DESC, x.note_id DESC LIMIT 1)
WHERE li.inspected_at = (SELECT max(inspected_at) FROM inspections WHERE asset_id = li.asset_id);

-- each non-producing inspection = 7 days; sum over a window by filtering inspected_at
DROP VIEW IF EXISTS downtime_weeks;
CREATE VIEW downtime_weeks AS
SELECT asset_id, area_id, well_type, inspection_id, inspected_at, 7 AS days FROM inspection_eff WHERE producing = 0;

DROP VIEW IF EXISTS spills_real;
CREATE VIEW spills_real AS
SELECT e.inspection_id, e.asset_id, e.area_id, e.well_type, e.inspected_at, e.spill_area_pct, e.spill_bbl,
       w.lat, w.lon,
       CASE WHEN e.spill_bbl >= (SELECT value FROM rules WHERE key='spill_major_bbl' AND scope='global') THEN 'major'
            WHEN e.spill_bbl >= (SELECT value FROM rules WHERE key='spill_reportable_bbl' AND scope='global') THEN 'reportable'
            WHEN e.spill_bbl >= (SELECT value FROM rules WHERE key='spill_moderate_bbl' AND scope='global') THEN 'moderate'
            ELSE 'minor' END AS spill_class
FROM inspection_eff e JOIN wells w USING (asset_id) WHERE e.spill_real = 1;

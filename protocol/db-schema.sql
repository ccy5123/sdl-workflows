-- SDL case database schema (SQLite). Draft, see protocol/db-design.md.
-- The database is a build artefact: build_db.py recreates it from the coding JSON files and collection CSVs.
PRAGMA foreign_keys = ON;

-- Build metadata ------------------------------------------------------------------------------------------
CREATE TABLE db_build (
  build_id        INTEGER PRIMARY KEY CHECK (build_id = 1),
  schema_version  TEXT NOT NULL,
  built_at        TEXT NOT NULL,             -- ISO 8601 UTC
  build_script_sha256 TEXT NOT NULL,
  taxonomy_version TEXT NOT NULL REFERENCES taxonomy_version(version)
);
CREATE TABLE source_file (
  path            TEXT PRIMARY KEY,          -- workspace-relative
  sha256          TEXT NOT NULL,
  role            TEXT NOT NULL              -- coding_json, candidates_csv, screening_csv, bib, taxonomy, ...
);

-- Taxonomy ------------------------------------------------------------------------------------------------
CREATE TABLE taxonomy_version (
  version         TEXT PRIMARY KEY,          -- v1
  frozen_on       TEXT NOT NULL,
  source_sha256   TEXT NOT NULL              -- sha256 of protocol/taxonomy-<version>.json
);
CREATE TABLE uo_family (
  family          TEXT PRIMARY KEY           -- plan, prepare, mix, react, separate, form, measure, analyze, handle
);
CREATE TABLE unit_operation (
  unit_operation  TEXT PRIMARY KEY,          -- includes 'unmapped'
  family          TEXT NOT NULL REFERENCES uo_family(family)
);
CREATE TABLE module_type (
  module_type     TEXT PRIMARY KEY           -- includes 'unmapped'
);
CREATE TABLE transfer_mode (
  transfer_mode   TEXT PRIMARY KEY,          -- includes 'unmapped'
  is_material     INTEGER NOT NULL CHECK (is_material IN (0, 1))   -- data_transfer = 0
);
CREATE TABLE field_tag (
  field_tag       TEXT PRIMARY KEY           -- includes 'unmapped'
);

-- Literature and screening --------------------------------------------------------------------------------
CREATE TABLE candidate (
  cand_id         TEXT PRIMARY KEY,          -- C0001 ...
  doi             TEXT,
  arxiv_id        TEXT,
  first_author    TEXT,
  year            INTEGER,
  title           TEXT,
  venue           TEXT
);
CREATE TABLE screening (
  cand_id         TEXT NOT NULL REFERENCES candidate(cand_id),
  stage           TEXT NOT NULL CHECK (stage IN ('title', 'abstract', 'fulltext')),
  round           INTEGER NOT NULL DEFAULT 1,  -- 1 = sdl-db-01 collection; 2 = sdl-db-02 expansion (a later round supersedes)
  decision        TEXT NOT NULL,             -- e.g. include / exclude / unclear / fulltext / eligible / ineligible / unobtainable
  reason_code     TEXT,
  decided_by      TEXT NOT NULL,             -- model id or 'researcher'
  record_ref      TEXT,                      -- Evidence id or source file that holds the decision
  PRIMARY KEY (cand_id, stage, round)
);
CREATE TABLE paper (
  paper_id        TEXT PRIMARY KEY,          -- sci-adk bibkey
  cand_id         TEXT UNIQUE REFERENCES candidate(cand_id),
  doi             TEXT,
  pub_year        INTEGER,
  first_public_year INTEGER,                 -- earliest year over linked versions; used for the chronological split
  year_basis      TEXT NOT NULL              -- candidate_year | override:<basis> | unknown
);
CREATE TABLE paper_version_link (
  cand_id         TEXT NOT NULL REFERENCES candidate(cand_id),
  other_cand_id   TEXT NOT NULL REFERENCES candidate(cand_id),
  relation        TEXT NOT NULL CHECK (relation IN ('preprint_of', 'duplicate_version')),
  PRIMARY KEY (cand_id, other_cand_id)
);
-- Samples and gold set ------------------------------------------------------------------------------------
CREATE TABLE sample_draw (
  draw_id         TEXT PRIMARY KEY,          -- e.g. goldset-2026-10-20, sdl-db-02-expansion
  seed            INTEGER NOT NULL,
  evidence_id     TEXT NOT NULL,             -- sci-adk Evidence that recorded the draw
  description     TEXT NOT NULL
);
CREATE TABLE sample_member (
  draw_id         TEXT NOT NULL REFERENCES sample_draw(draw_id),
  cand_id         TEXT NOT NULL REFERENCES candidate(cand_id),
  stratum         TEXT,
  draw_order      INTEGER,
  PRIMARY KEY (draw_id, cand_id)
);
CREATE TABLE gold_membership (
  paper_id        TEXT PRIMARY KEY REFERENCES paper(paper_id),
  gold_set        TEXT NOT NULL CHECK (gold_set IN ('dev', 'test')),
  recode          INTEGER NOT NULL CHECK (recode IN (0, 1)),
  human_spotcheck INTEGER NOT NULL CHECK (human_spotcheck IN (0, 1))
);

-- Codings -------------------------------------------------------------------------------------------------
CREATE TABLE coding (
  coding_id       TEXT PRIMARY KEY,          -- <paper_id>|<role>|<prompt_version>
  paper_id        TEXT NOT NULL REFERENCES paper(paper_id),
  role            TEXT NOT NULL CHECK (role IN ('extractor_a', 'extractor_b', 'reference', 'recode', 'human')),
  coder_label     TEXT NOT NULL,             -- the 'coder' field of the JSON
  model_id        TEXT,                      -- claude-opus-5-5, claude-fable-5-1, NULL for a human
  prompt_path     TEXT,
  prompt_sha256   TEXT,
  taxonomy_version TEXT NOT NULL REFERENCES taxonomy_version(version),
  source_path     TEXT NOT NULL REFERENCES source_file(path),
  notes           TEXT,                      -- paper.notes of the JSON (coder's own words, no quotations)
  hardware_location TEXT CHECK (hardware_location IN ('main', 'SI', 'both')),
  sw_autonomy     INTEGER CHECK (sw_autonomy IN (1, 2, 3)),
  hw_autonomy     INTEGER CHECK (hw_autonomy IN (1, 2, 3)),
  UNIQUE (paper_id, role, prompt_sha256)
);

CREATE TABLE coding_field_tag (
  coding_id       TEXT NOT NULL REFERENCES coding(coding_id),
  field_tag       TEXT NOT NULL REFERENCES field_tag(field_tag),   -- includes 'unmapped'
  position        INTEGER NOT NULL,          -- order as coded; position 1 is the first tag
  PRIMARY KEY (coding_id, field_tag)
);

-- Coded items (keys: coding_id + hierarchical id) ---------------------------------------------------------
CREATE TABLE platform (
  coding_id       TEXT NOT NULL REFERENCES coding(coding_id),
  platform_id     TEXT NOT NULL,             -- <paper_id>/P<n>
  name            TEXT,
  commercial_integrated INTEGER NOT NULL CHECK (commercial_integrated IN (0, 1)),
  campaigns       TEXT,
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  PRIMARY KEY (coding_id, platform_id)
);
CREATE TABLE module (
  coding_id       TEXT NOT NULL,
  module_id       TEXT NOT NULL,             -- <paper_id>/P<n>/M<k>
  platform_id     TEXT NOT NULL,
  module_type     TEXT NOT NULL REFERENCES module_type(module_type),
  name_in_paper   TEXT,
  on_platform     INTEGER NOT NULL CHECK (on_platform IN (0, 1)),
  unmapped_note   TEXT,
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  PRIMARY KEY (coding_id, module_id),
  FOREIGN KEY (coding_id, platform_id) REFERENCES platform(coding_id, platform_id),
  CHECK (module_type <> 'unmapped' OR length(coalesce(unmapped_note, '')) > 0)
);
CREATE TABLE step (
  coding_id       TEXT NOT NULL,
  step_id         TEXT NOT NULL,             -- <paper_id>/P<n>/S<k>
  platform_id     TEXT NOT NULL,
  step_order      INTEGER NOT NULL,          -- k of S<k>: execution order within the platform
  unit_operation  TEXT NOT NULL REFERENCES unit_operation(unit_operation),
  performed_by    TEXT NOT NULL CHECK (performed_by IN ('robot', 'human', 'software')),
  unmapped_note   TEXT,
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  PRIMARY KEY (coding_id, step_id),
  UNIQUE (coding_id, platform_id, step_order),
  FOREIGN KEY (coding_id, platform_id) REFERENCES platform(coding_id, platform_id),
  CHECK (unit_operation <> 'unmapped' OR length(coalesce(unmapped_note, '')) > 0)
);
CREATE TABLE step_module (
  coding_id       TEXT NOT NULL,
  step_id         TEXT NOT NULL,
  module_id       TEXT NOT NULL,
  position        INTEGER NOT NULL,          -- order in module_ids; position 1 is the primary module
  PRIMARY KEY (coding_id, step_id, module_id),
  FOREIGN KEY (coding_id, step_id) REFERENCES step(coding_id, step_id),
  FOREIGN KEY (coding_id, module_id) REFERENCES module(coding_id, module_id)
);
CREATE TABLE connection (
  coding_id       TEXT NOT NULL,
  edge_id         TEXT NOT NULL,             -- <paper_id>/P<n>/E<k>
  platform_id     TEXT NOT NULL,
  from_module     TEXT NOT NULL,
  to_module       TEXT NOT NULL,
  transfer_mode   TEXT NOT NULL REFERENCES transfer_mode(transfer_mode),
  stated          INTEGER NOT NULL CHECK (stated IN (0, 1)),   -- 1 = stated, 0 = inferred
  unmapped_note   TEXT,
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  PRIMARY KEY (coding_id, edge_id),
  FOREIGN KEY (coding_id, platform_id) REFERENCES platform(coding_id, platform_id),
  FOREIGN KEY (coding_id, from_module) REFERENCES module(coding_id, module_id),
  FOREIGN KEY (coding_id, to_module) REFERENCES module(coding_id, module_id),
  CHECK (transfer_mode <> 'unmapped' OR length(coalesce(unmapped_note, '')) > 0)
);

-- Derived (computed by the build, never edited) -----------------------------------------------------------
CREATE TABLE item_flag (
  coding_id       TEXT NOT NULL REFERENCES coding(coding_id),   -- the extractor_a coding
  item_id         TEXT NOT NULL,             -- step_id or edge_id
  item_kind       TEXT NOT NULL CHECK (item_kind IN ('step', 'connection')),
  flag            TEXT NOT NULL CHECK (flag IN ('uncertain')),
  compared_with   TEXT NOT NULL REFERENCES coding(coding_id),   -- the extractor_b coding
  rule            TEXT NOT NULL,             -- e.g. 'pairing=spec-v3-r1fam; unpaired-or-label-differs'
  PRIMARY KEY (coding_id, item_id, flag)
);
CREATE TABLE platform_identity (
  identity_id     TEXT PRIMARY KEY,
  canonical_name  TEXT NOT NULL,
  group_ref       TEXT                       -- e.g. OpenAlex author id of the corresponding group
);
CREATE TABLE platform_identity_member (
  identity_id     TEXT NOT NULL REFERENCES platform_identity(identity_id),
  coding_id       TEXT NOT NULL,
  platform_id     TEXT NOT NULL,
  rule            TEXT NOT NULL CHECK (rule IN ('a_stated_reuse', 'b_name_and_group', 'singleton')),
  decided_by      TEXT NOT NULL,             -- 'build-rule' or a model id
  evidence        TEXT,
  PRIMARY KEY (coding_id, platform_id),
  FOREIGN KEY (coding_id, platform_id) REFERENCES platform(coding_id, platform_id)
);

-- Process information for sdl-db-03 (extraction/process-v1.md; quantities defined by the sdl-db-03 Spec) -------
CREATE TABLE process_extraction (
  process_id      TEXT PRIMARY KEY,          -- <paper_id>|process-<role>|<prompt sha256[:12]>
  paper_id        TEXT NOT NULL REFERENCES paper(paper_id),
  role            TEXT NOT NULL CHECK (role IN ('extractor', 'reference')),   -- Opus 5.5 / Fable 5.1
  coder_label     TEXT NOT NULL,             -- the 'coder' field of the JSON
  model_id        TEXT NOT NULL,
  prompt_path     TEXT NOT NULL,
  prompt_sha256   TEXT NOT NULL,
  record_coding_id TEXT NOT NULL REFERENCES coding(coding_id),   -- the DB-record coding given as input
  source_path     TEXT NOT NULL REFERENCES source_file(path),
  notes           TEXT,                      -- the extractor's own words, no quotations
  UNIQUE (paper_id, role, prompt_sha256)
);
CREATE TABLE step_process (
  process_id      TEXT NOT NULL REFERENCES process_extraction(process_id),
  coding_id       TEXT NOT NULL,             -- the DB-record coding that holds step_id
  step_id         TEXT NOT NULL,
  quantity        TEXT NOT NULL CHECK (quantity IN ('duration', 'duration_batch_size')),
  value           REAL NOT NULL,
  unit            TEXT NOT NULL,
  qualifier       TEXT NOT NULL,             -- bounds, 'approximately', 'covers <step ids>' (process-v1.md)
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  PRIMARY KEY (process_id, step_id, quantity),
  FOREIGN KEY (coding_id, step_id) REFERENCES step(coding_id, step_id)
);
CREATE TABLE process_item (
  process_id      TEXT NOT NULL REFERENCES process_extraction(process_id),
  coding_id       TEXT NOT NULL REFERENCES coding(coding_id),   -- the DB-record coding that holds target_id
  target_kind     TEXT NOT NULL CHECK (target_kind IN ('platform', 'module', 'connection')),
  target_id       TEXT NOT NULL,             -- platform_id, module_id or edge_id; existence checked by the build
  quantity        TEXT NOT NULL,
  value           REAL NOT NULL,
  unit            TEXT NOT NULL,
  qualifier       TEXT NOT NULL,
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  PRIMARY KEY (process_id, target_kind, target_id, quantity, qualifier)
);

-- Views ---------------------------------------------------------------------------------------------------
CREATE VIEW db_record_coding AS
  SELECT c.paper_id, c.coding_id
  FROM coding c
  WHERE c.role = 'extractor_a'
    AND c.prompt_path = 'extraction/prompt-v1.md';

CREATE VIEW db_process_extraction AS
  SELECT x.paper_id, x.process_id, x.record_coding_id
  FROM process_extraction x
  WHERE x.role = 'extractor'
    AND x.prompt_path = 'extraction/process-v1.md';

CREATE VIEW v_era AS
  SELECT p.paper_id, p.first_public_year,
         CASE WHEN p.first_public_year IS NULL THEN NULL
              WHEN p.first_public_year <= 2023 THEN 'train'
              ELSE 'test' END AS era
  FROM paper p;

CREATE VIEW v_step AS
  SELECT r.paper_id, s.coding_id, s.platform_id, s.step_id, s.step_order,
         s.unit_operation, u.family, s.performed_by,
         sm.module_id AS primary_module_id, m.module_type AS primary_module_type, m.on_platform,
         e.first_public_year, e.era,
         (SELECT tag.field_tag FROM coding_field_tag tag
           WHERE tag.coding_id = r.coding_id AND tag.position = 1) AS first_field_tag,
         EXISTS (SELECT 1 FROM item_flag f WHERE f.coding_id = s.coding_id AND f.item_id = s.step_id) AS uncertain
  FROM db_record_coding r
  JOIN step s ON s.coding_id = r.coding_id
  JOIN unit_operation u ON u.unit_operation = s.unit_operation
  LEFT JOIN step_module sm ON sm.coding_id = s.coding_id AND sm.step_id = s.step_id AND sm.position = 1
  LEFT JOIN module m ON m.coding_id = sm.coding_id AND m.module_id = sm.module_id
  JOIN v_era e ON e.paper_id = r.paper_id;

CREATE VIEW v_connection AS
  SELECT r.paper_id, c.coding_id, c.platform_id, c.edge_id, c.from_module, c.to_module,
         c.transfer_mode, t.is_material, c.stated,
         mf.module_type AS from_module_type, mt.module_type AS to_module_type,
         e.first_public_year, e.era,
         EXISTS (SELECT 1 FROM item_flag f WHERE f.coding_id = c.coding_id AND f.item_id = c.edge_id) AS uncertain
  FROM db_record_coding r
  JOIN connection c ON c.coding_id = r.coding_id
  JOIN transfer_mode t ON t.transfer_mode = c.transfer_mode
  JOIN module mf ON mf.coding_id = c.coding_id AND mf.module_id = c.from_module
  JOIN module mt ON mt.coding_id = c.coding_id AND mt.module_id = c.to_module
  JOIN v_era e ON e.paper_id = r.paper_id;

CREATE VIEW v_paper_integration AS
  SELECT r.paper_id,
         CASE COUNT(DISTINCT CASE WHEN t.is_material = 1 THEN c.transfer_mode END)
              WHEN 0 THEN 'none'
              WHEN 1 THEN MAX(CASE WHEN t.is_material = 1 THEN c.transfer_mode END)
              ELSE 'mixed' END AS integration_mode
  FROM db_record_coding r
  LEFT JOIN connection c ON c.coding_id = r.coding_id
  LEFT JOIN transfer_mode t ON t.transfer_mode = c.transfer_mode
  GROUP BY r.paper_id;

CREATE VIEW v_fulltext_latest AS
  SELECT s.* FROM screening s
  WHERE s.stage = 'fulltext'
    AND s.round = (SELECT MAX(round) FROM screening t WHERE t.cand_id = s.cand_id AND t.stage = 'fulltext');

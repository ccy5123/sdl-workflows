-- sdl-workflows: schema of the SQLite file and of the CSV and Parquet tables. Data CC BY 4.0, code MIT.
-- Every release is exported by a script from one recorded database build (release.source_build_digest);
-- nothing in it is edited by hand. Each paper has one coding. Item ids are hierarchical:
-- <paper_id>/P<n> for a platform, and /M<k>, /S<k>, /E<k> below it for its modules, steps and connections.
-- Column descriptions: the comment on a column's line, or an '@column table.column:' line ('*': any table).
PRAGMA foreign_keys = ON;

-- Columns found in several tables (a note on the table itself takes precedence).
-- @column *.paper_id: Citation key of the paper (see paper).
-- @column *.cand_id: Candidate id from the literature search (see candidate).
-- @column *.platform_id: Platform the row belongs to, <paper_id>/P<n> (see platform).
-- @column *.definition: Definition of the class or code.
-- @column *.unmapped_note: Coder's note on what did not fit the taxonomy; required when the class is 'unmapped'.
-- @column *.uncertain: 1 if a second, independent extraction of the same paper had no matching item with this label; 0 otherwise.
-- @column *.ev_doc: Document that describes the item: main (the article) or SI<k> (the k-th supplement the coder read as text); paper_document gives its file hash, version and page basis.
-- @column *.ev_page: Page in that document: the PDF page, or the supplement's own page number for a docx supplement (paper_document.page_basis).
-- @column *.ev_locator: Figure, table, section or paragraph on that page (a location, never a quotation).
-- @column *.field_tags: The paper's field tags in coded order, ';'-separated.
-- @column *.doi: DOI of the paper (paper.doi).
-- @column *.identity_id: Physical platform (platform_identity).
-- @column *.step_id: Step id, <paper_id>/P<n>/S<k>.
-- @column *.unit_operation: Unit-operation class (unit_operation).
-- @column *.family: Unit-operation family (uo_family).
-- @column *.transfer_mode: Transfer mode of the connection (transfer_mode).
-- @column *.reason_code: Exclusion reason (screening_reason) of an exclude, ineligible or unobtainable decision; empty otherwise.
-- @column *.integration_mode: How material moves between the modules of the paper's platforms: the one material transfer mode used (which may be 'unmapped'), 'mixed' when several are used, 'none' when no material connection is coded.

-- Release metadata ----------------------------------------------------------------------------------------
-- @column release.n_papers: Number of papers in the release.
CREATE TABLE release (
  release_version     TEXT PRIMARY KEY,          -- semantic version: MAJOR.MINOR.PATCH
  released_on         TEXT NOT NULL,             -- release date, ISO 8601
  source_build_digest TEXT NOT NULL,             -- SHA-256 content digest of the database build exported
  taxonomy_version    TEXT NOT NULL,             -- taxonomy version (v1)
  license             TEXT NOT NULL,             -- licences of data and code
  zenodo_doi          TEXT,                      -- Zenodo DOI of this version
  n_papers            INTEGER NOT NULL
);

-- Taxonomy (mode: taxonomy) -------------------------------------------------------------------------------
-- @column uo_family.family: Unit-operation family: plan, prepare, mix, react, separate, form, measure, analyze, handle, or unmapped.
CREATE TABLE uo_family (
  family              TEXT PRIMARY KEY,          -- plan, prepare, mix, react, separate, form, measure, analyze, handle, unmapped
  definition          TEXT NOT NULL
);
-- @column unit_operation.unit_operation: Unit-operation class of taxonomy v1; 'unmapped' for a step that fits no class.
-- @column unit_operation.family: Family of the unit operation (uo_family).
CREATE TABLE unit_operation (
  unit_operation      TEXT PRIMARY KEY,          -- includes 'unmapped'
  family              TEXT NOT NULL REFERENCES uo_family(family),
  definition          TEXT NOT NULL
);
-- @column module_type.module_type: Module class of taxonomy v1; 'unmapped' for a module that fits no class.
CREATE TABLE module_type (
  module_type         TEXT PRIMARY KEY,          -- includes 'unmapped'
  definition          TEXT NOT NULL
);
-- @column transfer_mode.transfer_mode: Transfer-mode class of taxonomy v1; 'unmapped' for a connection that fits no class.
-- @column transfer_mode.is_material: 1 if material moves; 0 for data_transfer.
CREATE TABLE transfer_mode (
  transfer_mode       TEXT PRIMARY KEY,          -- includes 'unmapped'
  is_material         INTEGER NOT NULL CHECK (is_material IN (0, 1)),   -- data_transfer = 0
  definition          TEXT NOT NULL
);
-- @column field_tag.field_tag: Application-field tag; 'unmapped' for a field that fits no tag.
CREATE TABLE field_tag (
  field_tag           TEXT PRIMARY KEY,          -- includes 'unmapped'
  definition          TEXT NOT NULL              -- stays within the tag name and the guideline's gloss
);
-- Correspondence of our classes to classes of other vocabularies, one row per correspondence. It was written
-- with taxonomy v1 and is not used for coding. modes/taxonomy/correspondence.csv holds the same rows, one line
-- per class with two columns per vocabulary.
-- @column taxonomy_correspondence.class_kind: Kind of our class: unit_operation, module_type, or transfer_mode.
-- @column taxonomy_correspondence.vocabulary: Other vocabulary: XDL (Mehr et al. 2020), WCSO (WeChemSynOntology, Schilling et al. 2026), Leong2022 (Leong et al. 2022), OntoLab_SAREF (Bai et al. 2024; module types only), Gottstein2026 (Gottstein et al. 2026).
CREATE TABLE taxonomy_correspondence (
  class_kind          TEXT NOT NULL CHECK (class_kind IN ('unit_operation', 'module_type', 'transfer_mode')),
  class               TEXT NOT NULL,             -- our class (of class_kind)
  vocabulary          TEXT NOT NULL CHECK (vocabulary IN ('XDL', 'WCSO', 'Leong2022', 'OntoLab_SAREF', 'Gottstein2026')),
  target              TEXT NOT NULL,             -- class in that vocabulary ('none' when there is none); for
                                                 -- Gottstein2026 one of its four orchestration objects
                                                 -- (primitive, unit_operation, unit_flow, workflow) or 'setup'
  match               TEXT NOT NULL CHECK (match IN ('exact', 'broader', 'narrower', 'none')),
                                                 -- exact; broader (the target is wider than our class);
                                                 -- narrower (the target is narrower; for Gottstein2026, one of
                                                 -- our items may span several of its objects); none
  source_ref          TEXT NOT NULL,             -- source key ; PDF page ; table, figure or section (README lists
                                                 -- the sources); a 'none' row gives the source searched
  PRIMARY KEY (class_kind, class, vocabulary, target),
  CHECK (vocabulary <> 'Gottstein2026'
         OR target IN ('primitive', 'unit_operation', 'unit_flow', 'workflow', 'setup', 'none'))
);

-- Literature and screening (mode: trends) -----------------------------------------------------------------
-- @column candidate.cand_id: Candidate id, C0001 onwards.
-- @column candidate.doi: DOI recorded for the candidate.
-- @column candidate.arxiv_id: arXiv identifier, for an arXiv record.
-- @column candidate.first_author: Surname of the first author.
-- @column candidate.year: Publication year recorded for the candidate; empty for some entries of the reviews' reference lists, for which no year was recorded.
-- @column candidate.title: Title (abstracts are not included); empty for some entries of the reviews' reference lists, for which no title was recorded.
-- @column candidate.venue: Journal, conference or repository.
CREATE TABLE candidate (
  cand_id             TEXT PRIMARY KEY,          -- C0001 onwards
  doi                 TEXT,
  arxiv_id            TEXT,
  first_author        TEXT,
  year                INTEGER,
  title               TEXT,                      -- title (abstracts are not included)
  venue               TEXT
);
-- @column screening_reason.reason_code: Exclusion reason code.
CREATE TABLE screening_reason (
  reason_code         TEXT PRIMARY KEY,          -- E_off_topic, E_review, E_open_loop, ...
  definition          TEXT NOT NULL
);
-- @column screening.stage: Screening stage: title, abstract, or fulltext.
-- @column screening.decision: Decision at that stage. title: likely, maybe or exclude; abstract: fulltext, unclear or exclude; fulltext: eligible, ineligible or unobtainable.
-- @column screening.reason_code: Exclusion reason (screening_reason) of an exclude, ineligible or unobtainable decision; empty otherwise.
-- @column screening.decided_by: researcher, or model (a language model screening under written instructions; see model_id).
CREATE TABLE screening (
  cand_id             TEXT NOT NULL REFERENCES candidate(cand_id),
  stage               TEXT NOT NULL CHECK (stage IN ('title', 'abstract', 'fulltext')),
  round               INTEGER NOT NULL,          -- a later round supersedes an earlier one for the same stage
  decision            TEXT NOT NULL,
  reason_code         TEXT REFERENCES screening_reason(reason_code),
  decided_by          TEXT NOT NULL CHECK (decided_by IN ('researcher', 'model')),
  model_id            TEXT,                      -- model that decided, where the screening record names it
  PRIMARY KEY (cand_id, stage, round),
  CHECK (decided_by = 'model' OR model_id IS NULL)
);
-- @column paper_version_link.cand_id: One candidate of a pair that are versions of the same study (preprint, journal or other-language version); the order of the pair carries no meaning, and at most one of the two is a paper of the release.
-- @column paper_version_link.other_cand_id: The other candidate of the pair.
-- @column paper_version_link.relation: duplicate_version (another version of the same study).
CREATE TABLE paper_version_link (
  cand_id             TEXT NOT NULL REFERENCES candidate(cand_id),
  other_cand_id       TEXT NOT NULL REFERENCES candidate(cand_id),
  relation            TEXT NOT NULL CHECK (relation IN ('preprint_of', 'duplicate_version')),
  PRIMARY KEY (cand_id, other_cand_id)
);

-- Papers --------------------------------------------------------------------------------------------------
-- @column paper.cand_id: Candidate id of the paper's record (see candidate).
-- @column paper.first_public_year: Earliest year over the linked versions of the paper; the year used by the chrono2023 benchmark split.
-- @column paper.year_basis: How first_public_year was set: candidate_year (the year recorded for the candidate), override:<basis>, or unknown.
-- @column paper.hardware_location: Where the paper describes the hardware: main, SI, or both.
-- @column paper.sw_autonomy: Software autonomy category of Tom et al. 2024: 1 one experiment from a data-driven design; 2 closed-loop iteration in which results choose the next experiment; 3 closed-loop iteration over an algorithm-generated search space.
-- @column paper.hw_autonomy: Hardware autonomy category of Tom et al. 2024: 1 a device doing one kind of task; 2 a workflow joining several tasks; 3 a fully automated laboratory running varied experiments without human intervention.
CREATE TABLE paper (
  paper_id            TEXT PRIMARY KEY,          -- citation key, stable across releases (e.g. Aand2024)
  cand_id             TEXT NOT NULL UNIQUE REFERENCES candidate(cand_id),
  doi                 TEXT NOT NULL,             -- bibliographic DOI (journal version where one exists)
  first_public_year   INTEGER,                   -- earliest year over linked versions
  year_basis          TEXT NOT NULL,             -- candidate_year, override:<basis>, or unknown
  hardware_location   TEXT CHECK (hardware_location IN ('main', 'SI', 'both')),
  sw_autonomy         INTEGER CHECK (sw_autonomy IN (1, 2, 3)),
  hw_autonomy         INTEGER CHECK (hw_autonomy IN (1, 2, 3))
);
-- Which file each evidence document label (main, SI1, SI2, ...) refers to, which version it is and what its
-- page numbers count. The hash lets a user check that their copy is the one the page numbers refer to.
-- No file is distributed.
-- @column paper_document.doc: Document label used in the ev_doc columns: main or SI<k>.
-- @column paper_document.file_format: File format of the document: pdf or docx.
-- @column paper_document.sha256: SHA-256 of the file the coder read; compare it with your copy before using page numbers.
-- @column paper_document.version: Version of the main text: journal, accepted_manuscript, preprint, or repository_copy (a repository deposit that does not state its version); empty for supplements.
CREATE TABLE paper_document (
  paper_id            TEXT NOT NULL REFERENCES paper(paper_id),
  doc                 TEXT NOT NULL CHECK (doc = 'main' OR doc GLOB 'SI[0-9]*'),
  file_format         TEXT NOT NULL,             -- pdf or docx
  sha256              TEXT NOT NULL,
  version             TEXT CHECK (version IN ('journal', 'accepted_manuscript', 'preprint', 'repository_copy')),
                      -- repository_copy: a repository deposit that does not state its version
  source_doi          TEXT,                      -- DOI of this version when it has one (a preprint DOI for preprints)
  source_url          TEXT,                      -- where an open-access copy was downloaded, when recorded
  page_basis          TEXT NOT NULL CHECK (page_basis IN ('pdf_page', 'si_internal_page')),
                      -- pdf_page: PDF page; si_internal_page: a docx supplement has no PDF pages, so the
                      -- coder used the supplement's own page numbers
  PRIMARY KEY (paper_id, doc),
  CHECK (doc <> 'main' OR version IS NOT NULL)
);
-- @column paper_field_tag.field_tag: Field tag (field_tag).
CREATE TABLE paper_field_tag (
  paper_id            TEXT NOT NULL REFERENCES paper(paper_id),
  field_tag           TEXT NOT NULL REFERENCES field_tag(field_tag),
  position            INTEGER NOT NULL,          -- order as coded; position 1 is the first tag
  PRIMARY KEY (paper_id, field_tag),
  UNIQUE (paper_id, position)
);

-- Platforms -----------------------------------------------------------------------------------------------
-- @column platform_identity.identity_id: Id of one physical platform; papers that use the same platform share it. I<n> for a platform found in several papers; for a platform found in one paper, its platform id.
-- @column platform_identity.canonical_name: Name of the physical platform: for a platform found in several papers, the name chosen for the group; for a platform found in one paper, the name that paper gives (empty if it gives none).
CREATE TABLE platform_identity (
  identity_id         TEXT PRIMARY KEY,          -- one id per physical platform across papers
  canonical_name      TEXT,
  group_ref           TEXT                       -- OpenAlex author id(s) of the corresponding group, ';'-separated
);
-- @column platform.name: Name the paper gives the platform; empty if it gives none.
-- @column platform.commercial_integrated: 1 if the platform is a commercial integrated system whose internal configuration is not disclosed.
-- @column platform.campaigns: Coder's summary of the closed-loop campaigns run on the platform.
-- @column platform.identity_id: Physical platform (platform_identity).
-- @column platform.identity_rule: How the identity was decided: a_stated_reuse (one paper states it reuses the other's platform), b_name_and_group (same platform name and a shared corresponding group), or singleton (no other paper).
CREATE TABLE platform (
  platform_id         TEXT PRIMARY KEY,          -- <paper_id>/P<n>
  paper_id            TEXT NOT NULL REFERENCES paper(paper_id),
  name                TEXT,                      -- name the paper gives the platform
  commercial_integrated INTEGER NOT NULL CHECK (commercial_integrated IN (0, 1)),
  campaigns           TEXT,                      -- coder's summary of the campaigns (no quotation)
  identity_id         TEXT NOT NULL REFERENCES platform_identity(identity_id),
  identity_rule       TEXT NOT NULL CHECK (identity_rule IN ('a_stated_reuse', 'b_name_and_group', 'singleton')),
  reuse_stated_in     TEXT REFERENCES paper(paper_id),   -- a_stated_reuse: the paper that states the reuse
  reuse_of            TEXT REFERENCES paper(paper_id),   -- a_stated_reuse: the paper whose platform is reused
  shared_group_ref    TEXT,                      -- b_name_and_group: OpenAlex author id(s) shared
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  CHECK (identity_rule <> 'a_stated_reuse' OR (reuse_stated_in IS NOT NULL AND reuse_of IS NOT NULL)),
  CHECK (identity_rule <> 'b_name_and_group' OR shared_group_ref IS NOT NULL)
);

-- Coded items ---------------------------------------------------------------------------------------------
-- @column module.module_id: Module id, <paper_id>/P<n>/M<k>.
-- @column module.module_type: Module class (module_type).
-- @column module.name_in_paper: Name or model the paper gives the module.
-- @column module.on_platform: 1 if the module is part of the platform; 0 for equipment outside it that the loop uses.
CREATE TABLE module (
  module_id           TEXT PRIMARY KEY,          -- <paper_id>/P<n>/M<k>
  platform_id         TEXT NOT NULL REFERENCES platform(platform_id),
  module_type         TEXT NOT NULL REFERENCES module_type(module_type),
  name_in_paper       TEXT,
  on_platform         INTEGER NOT NULL CHECK (on_platform IN (0, 1)),
  unmapped_note       TEXT,
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  CHECK (module_type <> 'unmapped' OR length(coalesce(unmapped_note, '')) > 0)
);
-- @column step.step_id: Step id, <paper_id>/P<n>/S<k>; k is the order within one cycle.
-- @column step.unit_operation: Unit-operation class (unit_operation).
-- @column step.performed_by: robot, human, or software.
CREATE TABLE step (
  step_id             TEXT PRIMARY KEY,          -- <paper_id>/P<n>/S<k>
  platform_id         TEXT NOT NULL REFERENCES platform(platform_id),
  step_order          INTEGER NOT NULL,          -- k of S<k>: execution order within the platform
  unit_operation      TEXT NOT NULL REFERENCES unit_operation(unit_operation),
  performed_by        TEXT NOT NULL CHECK (performed_by IN ('robot', 'human', 'software')),
  unmapped_note       TEXT,
  uncertain           INTEGER NOT NULL CHECK (uncertain IN (0, 1)),
                      -- 1 = a second, independent extraction of the paper had no matching item with this label
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  UNIQUE (platform_id, step_order),
  CHECK (unit_operation <> 'unmapped' OR length(coalesce(unmapped_note, '')) > 0)
);
-- @column step_module.step_id: Step (see step).
-- @column step_module.module_id: Module that carries out the step; a step may use several.
CREATE TABLE step_module (
  step_id             TEXT NOT NULL REFERENCES step(step_id),
  module_id           TEXT NOT NULL REFERENCES module(module_id),
  position            INTEGER NOT NULL,          -- position 1 is the primary module
  PRIMARY KEY (step_id, module_id),
  UNIQUE (step_id, position)
);
-- @column connection.edge_id: Connection id, <paper_id>/P<n>/E<k>.
-- @column connection.from_module: Module the material or data leaves.
-- @column connection.to_module: Module it arrives at.
-- @column connection.transfer_mode: How it moves (transfer_mode).
CREATE TABLE connection (
  edge_id             TEXT PRIMARY KEY,          -- <paper_id>/P<n>/E<k>
  platform_id         TEXT NOT NULL REFERENCES platform(platform_id),
  from_module         TEXT NOT NULL REFERENCES module(module_id),
  to_module           TEXT NOT NULL REFERENCES module(module_id),
  transfer_mode       TEXT NOT NULL REFERENCES transfer_mode(transfer_mode),
  stated              INTEGER NOT NULL CHECK (stated IN (0, 1)),   -- 1 = stated in the paper, 0 = inferred
  unmapped_note       TEXT,
  uncertain           INTEGER NOT NULL CHECK (uncertain IN (0, 1)),
  ev_doc TEXT, ev_page INTEGER, ev_locator TEXT,
  CHECK (transfer_mode <> 'unmapped' OR length(coalesce(unmapped_note, '')) > 0)
);

-- Benchmark (mode: benchmark) -----------------------------------------------------------------------------
-- Task definitions, the same as modes/benchmark/tasks/*.json. The reference values are those of the authors'
-- recorded evaluation (recorded_in); modes/benchmark/evaluate.py reproduces them from the release files.
CREATE TABLE benchmark_task (
  task_id             TEXT PRIMARY KEY,          -- chrono2023-module_type or chrono2023-transfer_mode
  benchmark_id        TEXT NOT NULL,             -- chrono2023 (see benchmark_split)
  target              TEXT NOT NULL,             -- module_type (of a step's primary module) or transfer_mode (of a material connection)
  item_rule           TEXT NOT NULL,             -- which steps or connections are items, and how a connection attaches to steps
  inputs              TEXT NOT NULL,             -- what a model may use to predict the label
  metric              TEXT NOT NULL,             -- how predictions are scored
  baseline_rule       TEXT NOT NULL,             -- how the baseline predicts
  baseline_top1       REAL NOT NULL,             -- baseline top-1 accuracy on the test items
  reference_model     TEXT NOT NULL,             -- how the reference model predicts
  reference_model_top1 REAL NOT NULL,            -- reference model top-1 accuracy on the test items
  diff_ci95_low       REAL NOT NULL,             -- 95% interval of reference_model_top1 - baseline_top1
  diff_ci95_high      REAL NOT NULL,             -- (paper-level paired cluster bootstrap, see metric)
  n_test_items        INTEGER NOT NULL,          -- number of test items
  n_test_papers       INTEGER NOT NULL,          -- number of test papers with at least one item
  recorded_in         TEXT NOT NULL              -- id of the recorded evaluation in the authors' research record
);
-- @column benchmark_split.benchmark_id: Benchmark: chrono2023 trains on papers first public in 2023 or earlier and tests on papers first public in 2024 or later.
-- @column benchmark_split.split: train, test, or excluded (see exclusion_reason).
-- @column benchmark_split.exclusion_reason: Why a test-year paper is left out: it was used to develop the extraction instructions.
CREATE TABLE benchmark_split (
  benchmark_id        TEXT NOT NULL,
  paper_id            TEXT NOT NULL REFERENCES paper(paper_id),
  split               TEXT NOT NULL CHECK (split IN ('train', 'test', 'excluded')),
  exclusion_reason    TEXT,                      -- set only when split = excluded
  PRIMARY KEY (benchmark_id, paper_id),
  CHECK ((split = 'excluded') = (exclusion_reason IS NOT NULL))
);

-- Views: builder mode -------------------------------------------------------------------------------------
CREATE VIEW paper_field_tags AS
  SELECT paper_id, group_concat(field_tag, ';') AS field_tags
  FROM (SELECT paper_id, field_tag FROM paper_field_tag ORDER BY paper_id, position)
  GROUP BY paper_id;

-- @column builder_platform.title: Title of the screened candidate record of the paper (candidate.title); for the one paper whose DOI names a later version, the screened version's title.
-- @column builder_platform.platform_name: Name the paper gives the platform.
-- @column builder_platform.n_modules: Number of modules of the platform.
-- @column builder_platform.n_modules_off_platform: Of these, modules outside the platform (on_platform = 0).
-- @column builder_platform.n_steps: Number of steps in one cycle.
-- @column builder_platform.n_steps_human: Of these, steps performed by a person.
-- @column builder_platform.module_types: Module types used on the platform, ','-separated.
-- @column builder_platform.material_transfer_modes: Transfer modes of the platform's material connections, ','-separated.
CREATE VIEW builder_platform AS
  SELECT pl.platform_id, pl.paper_id, p.doi, c.title, p.first_public_year, ft.field_tags,
         pl.name AS platform_name, pl.commercial_integrated, pl.campaigns, pl.identity_id,
         (SELECT COUNT(*) FROM module m WHERE m.platform_id = pl.platform_id) AS n_modules,
         (SELECT COUNT(*) FROM module m WHERE m.platform_id = pl.platform_id AND m.on_platform = 0) AS n_modules_off_platform,
         (SELECT COUNT(*) FROM step s WHERE s.platform_id = pl.platform_id) AS n_steps,
         (SELECT COUNT(*) FROM step s WHERE s.platform_id = pl.platform_id AND s.performed_by = 'human') AS n_steps_human,
         (SELECT group_concat(DISTINCT m.module_type) FROM module m WHERE m.platform_id = pl.platform_id) AS module_types,
         (SELECT group_concat(DISTINCT e.transfer_mode) FROM connection e
           JOIN transfer_mode t ON t.transfer_mode = e.transfer_mode
           WHERE e.platform_id = pl.platform_id AND t.is_material = 1) AS material_transfer_modes,
         pl.ev_doc, pl.ev_page, pl.ev_locator
  FROM platform pl
  JOIN paper p ON p.paper_id = pl.paper_id
  JOIN candidate c ON c.cand_id = p.cand_id
  LEFT JOIN paper_field_tags ft ON ft.paper_id = pl.paper_id;

-- @column builder_step.primary_module_id: First listed module of the step (step_module position 1).
-- @column builder_step.primary_module_type: Module type of the primary module.
-- @column builder_step.primary_module_name: Name of the primary module in the paper.
-- @column builder_step.other_module_ids: Further modules of the step, ';'-separated.
CREATE VIEW builder_step AS
  SELECT s.step_id, s.platform_id, pl.paper_id, p.doi, s.step_order, s.unit_operation, u.family,
         s.performed_by, sm.module_id AS primary_module_id, m.module_type AS primary_module_type,
         m.name_in_paper AS primary_module_name, m.on_platform,
         (SELECT group_concat(x.module_id, ';') FROM step_module x
           WHERE x.step_id = s.step_id AND x.position > 1) AS other_module_ids,
         s.unmapped_note, s.uncertain, s.ev_doc, s.ev_page, s.ev_locator
  FROM step s
  JOIN platform pl ON pl.platform_id = s.platform_id
  JOIN paper p ON p.paper_id = pl.paper_id
  JOIN unit_operation u ON u.unit_operation = s.unit_operation
  LEFT JOIN step_module sm ON sm.step_id = s.step_id AND sm.position = 1
  LEFT JOIN module m ON m.module_id = sm.module_id;

-- @column builder_connection.from_module_type: Module type of the source module.
-- @column builder_connection.from_module_name: Name of the source module in the paper.
-- @column builder_connection.to_module_type: Module type of the target module.
-- @column builder_connection.to_module_name: Name of the target module in the paper.
CREATE VIEW builder_connection AS
  SELECT e.edge_id, e.platform_id, pl.paper_id, p.doi,
         e.from_module, mf.module_type AS from_module_type, mf.name_in_paper AS from_module_name,
         e.to_module, mt.module_type AS to_module_type, mt.name_in_paper AS to_module_name,
         e.transfer_mode, t.is_material, e.stated, e.unmapped_note, e.uncertain,
         e.ev_doc, e.ev_page, e.ev_locator
  FROM connection e
  JOIN platform pl ON pl.platform_id = e.platform_id
  JOIN paper p ON p.paper_id = pl.paper_id
  JOIN transfer_mode t ON t.transfer_mode = e.transfer_mode
  JOIN module mf ON mf.module_id = e.from_module
  JOIN module mt ON mt.module_id = e.to_module;

-- Views: trends mode --------------------------------------------------------------------------------------
-- Integration mode of a paper: its one material transfer mode, 'mixed', or 'none'.
CREATE VIEW paper_integration AS
  SELECT p.paper_id,
         CASE COUNT(DISTINCT CASE WHEN t.is_material = 1 THEN e.transfer_mode END)
              WHEN 0 THEN 'none'
              WHEN 1 THEN MAX(CASE WHEN t.is_material = 1 THEN e.transfer_mode END)
              ELSE 'mixed' END AS integration_mode
  FROM paper p
  LEFT JOIN platform pl ON pl.paper_id = p.paper_id
  LEFT JOIN connection e ON e.platform_id = pl.platform_id
  LEFT JOIN transfer_mode t ON t.transfer_mode = e.transfer_mode
  GROUP BY p.paper_id;

-- @column trends_paper.title: Title of the screened candidate record (candidate.title). When the paper's DOI names a later version of that record (one paper: a preprint screened, its journal article cited), it is the screened version's title.
-- @column trends_paper.venue: Venue of the screened candidate record (candidate.venue); see title for the one paper whose DOI names a later version.
-- @column trends_paper.first_field_tag: First field tag of the paper.
-- @column trends_paper.n_platforms: Number of platforms coded for the paper.
-- @column trends_paper.n_platforms_shared_with_other_papers: Of these, platforms that the identity rules link to a platform of another paper.
-- @column trends_paper.n_modules: Number of modules over the paper's platforms.
-- @column trends_paper.n_steps: Number of steps over the paper's platforms.
-- @column trends_paper.n_steps_human: Of these, steps performed by a person.
-- @column trends_paper.n_material_connections: Number of material connections (any transfer mode except data_transfer).
-- @column trends_paper.n_human_transfer: Connections with transfer mode human_transfer.
-- @column trends_paper.n_robot_arm_gantry: Connections with transfer mode robot_arm_gantry.
-- @column trends_paper.n_mobile_robot: Connections with transfer mode mobile_robot.
-- @column trends_paper.n_fixed_tubing: Connections with transfer mode fixed_tubing.
CREATE VIEW trends_paper AS
  SELECT p.paper_id, p.doi, c.title, c.venue, p.first_public_year,
         (SELECT f.field_tag FROM paper_field_tag f WHERE f.paper_id = p.paper_id AND f.position = 1) AS first_field_tag,
         ft.field_tags, i.integration_mode, p.sw_autonomy, p.hw_autonomy, p.hardware_location,
         (SELECT COUNT(*) FROM platform pl WHERE pl.paper_id = p.paper_id) AS n_platforms,
         (SELECT COUNT(*) FROM platform pl WHERE pl.paper_id = p.paper_id
           AND pl.identity_rule <> 'singleton') AS n_platforms_shared_with_other_papers,
         (SELECT COUNT(*) FROM module m JOIN platform pl ON pl.platform_id = m.platform_id
           WHERE pl.paper_id = p.paper_id) AS n_modules,
         (SELECT COUNT(*) FROM step s JOIN platform pl ON pl.platform_id = s.platform_id
           WHERE pl.paper_id = p.paper_id) AS n_steps,
         (SELECT COUNT(*) FROM step s JOIN platform pl ON pl.platform_id = s.platform_id
           WHERE pl.paper_id = p.paper_id AND s.performed_by = 'human') AS n_steps_human,
         (SELECT COUNT(*) FROM connection e JOIN platform pl ON pl.platform_id = e.platform_id
           JOIN transfer_mode t ON t.transfer_mode = e.transfer_mode
           WHERE pl.paper_id = p.paper_id AND t.is_material = 1) AS n_material_connections,
         (SELECT COUNT(*) FROM connection e JOIN platform pl ON pl.platform_id = e.platform_id
           WHERE pl.paper_id = p.paper_id AND e.transfer_mode = 'human_transfer') AS n_human_transfer,
         (SELECT COUNT(*) FROM connection e JOIN platform pl ON pl.platform_id = e.platform_id
           WHERE pl.paper_id = p.paper_id AND e.transfer_mode = 'robot_arm_gantry') AS n_robot_arm_gantry,
         (SELECT COUNT(*) FROM connection e JOIN platform pl ON pl.platform_id = e.platform_id
           WHERE pl.paper_id = p.paper_id AND e.transfer_mode = 'mobile_robot') AS n_mobile_robot,
         (SELECT COUNT(*) FROM connection e JOIN platform pl ON pl.platform_id = e.platform_id
           WHERE pl.paper_id = p.paper_id AND e.transfer_mode = 'fixed_tubing') AS n_fixed_tubing
  FROM paper p
  JOIN candidate c ON c.cand_id = p.cand_id
  LEFT JOIN paper_field_tags ft ON ft.paper_id = p.paper_id
  JOIN paper_integration i ON i.paper_id = p.paper_id;

CREATE VIEW trends_screening_latest AS
  SELECT s.* FROM screening s
  WHERE s.round = (SELECT MAX(t.round) FROM screening t WHERE t.cand_id = s.cand_id AND t.stage = s.stage);

-- Benchmark items with their inputs. A material connection is an item only when it attaches to a pair of
-- steps of its platform (benchmark_task.item_rule); that rule is not a plain view, so the items are a table.
-- @column benchmark_item.task_id: Benchmark task (benchmark_task).
-- @column benchmark_item.split: Split of the item's paper (benchmark_split).
-- @column benchmark_item.unit_operation: module_type task: unit operation of the step; empty for transfer_mode items.
-- @column benchmark_item.prev_unit_operation: module_type task: unit operation of the previous step of the platform in step order; START for the first step.
-- @column benchmark_item.next_unit_operation: module_type task: unit operation of the next step; END for the last step.
-- @column benchmark_item.from_unit_operation: transfer_mode task: unit operation of the step the connection is attached to on its source side; empty for module_type items.
-- @column benchmark_item.to_unit_operation: transfer_mode task: unit operation of the step on the target side.
-- @column benchmark_item.from_family: transfer_mode task: family of the source-side step.
-- @column benchmark_item.to_family: transfer_mode task: family of the target-side step.
-- @column benchmark_item.uncertain: Copy of step.uncertain or connection.uncertain for the item.
CREATE TABLE benchmark_item (
  task_id             TEXT NOT NULL REFERENCES benchmark_task(task_id),
  item_id             TEXT NOT NULL,             -- step_id (module_type task) or edge_id (transfer_mode task)
  paper_id            TEXT NOT NULL REFERENCES paper(paper_id),
  platform_id         TEXT NOT NULL REFERENCES platform(platform_id),
  split               TEXT NOT NULL CHECK (split IN ('train', 'test', 'excluded')),
  label               TEXT NOT NULL,             -- the target: a module_type or a transfer_mode
  field_tag           TEXT NOT NULL,             -- first field tag of the paper ('' when none)
  -- module_type task: the step and its neighbours in step_order (START / END at the ends)
  unit_operation      TEXT REFERENCES unit_operation(unit_operation),
  prev_unit_operation TEXT,
  next_unit_operation TEXT,
  -- transfer_mode task: the step pair the connection is attached to
  from_unit_operation TEXT REFERENCES unit_operation(unit_operation),
  to_unit_operation   TEXT REFERENCES unit_operation(unit_operation),
  from_family         TEXT REFERENCES uo_family(family),
  to_family           TEXT REFERENCES uo_family(family),
  uncertain           INTEGER NOT NULL CHECK (uncertain IN (0, 1)),
  PRIMARY KEY (task_id, item_id)
);

-- Views: taxonomy mode ------------------------------------------------------------------------------------
-- @column taxonomy_class.class_kind: Kind of class: unit_operation, module_type, transfer_mode, or field_tag.
-- @column taxonomy_class.family: Family of a unit operation; empty for the other kinds.
CREATE VIEW taxonomy_class AS
  SELECT 'unit_operation' AS class_kind, unit_operation AS class, family, definition FROM unit_operation
  UNION ALL SELECT 'module_type', module_type, NULL, definition FROM module_type
  UNION ALL SELECT 'transfer_mode', transfer_mode, NULL, definition FROM transfer_mode
  UNION ALL SELECT 'field_tag', field_tag, NULL, definition FROM field_tag;

# HANDOFF: Behavioral Analytics Platform (read this first)

## 1. What the project is
A MERN website (React + Express + MongoDB) with a Python analysis engine. It must be GENERIC, not tied to one dataset.

**Module A: Graphical analysis (any tabular data).** Drag-and-drop or browse CSV/XLSX -> auto-profile (types, nulls,
distributions, correlations, category counts, trends) + a chart builder (choose chart type, X, Y, group-by).

**Module B: Behavioral analysis (only for data with the right shape).** Pipeline, in this order:
1. entity x behavior MATRIX (e.g. student x activity_type, values = clicks)
2. Min-Max scaling, then pairwise COSINE SIMILARITY
3. Threshold (tau) -> edges -> similarity GRAPH (isolated nodes removed). kNN graph offered as alternative.
4. COMMUNITY detection (Louvain primary; Leiden and Label Propagation for benchmark: modularity + NMI)
5. Per-community AVERAGE total activity
6. Communities sorted by that average and split into 3 TIERS (High / Moderate / Low-At-Risk) by quantile or custom cut-offs.
Every entity inherits its community's tier.

Data needs 3 ingredients: ENTITY ID, BEHAVIOR CATEGORY, MAGNITUDE (count/amount). Optional: lookup file that maps an ID
to a behavior category (OULAD: studentVle.id_site -> vle.activity_type); optional label column (OULAD: final_result) for NMI.
The site must run an ELIGIBILITY CHECK and explain why a dataset is unsuitable. Target: 3 datasets supported.
Dataset 1 = OULAD. Datasets 2 and 3 = TBD (candidates: UCI Online Retail II customer x product category x quantity;
MovieLens user x genre x rating count; Instacart user x department x orders). Third should require a lookup join.

## 2. Source material (original research notebook, Colab)
Dataset: Open University Learning Analytics Dataset (OULAD). studentVle.csv (453 MB, 10,655,280 rows, 26,074 students),
vle.csv (id_site -> activity_type), studentInfo.csv (final_result: Pass/Fail/Distinction/Withdrawn).
Notebook settings: sample 300 students (pandas sample random_state=42), tau=0.85, Louvain seed 42.
Notebook results: 297 connected nodes, 2544 edges, 15 communities. Louvain modularity 0.588501 NMI 0.054727.
NMI is low (0.05-0.09): communities reflect behavior PATTERN, not pass/fail. The UI should say this honestly.
Known weaknesses to surface as diagnostics: 4 communities have <=2 members; only the sampled/connected slice is tiered;
cosine similarity ignores magnitude while tiers use magnitude.

## 3. STATUS
- [x] STEP 1 DONE and TESTED: Python engine in `analysis/` (this zip). Reproduces the notebook EXACTLY on real OULAD
      (297 nodes, 2544 edges, 15 communities, modularity 0.588501, NMI 0.054727). 6.5 s end to end. 8 pytest tests pass.
- [ ] STEP 2: Express API (chunked uploads, MongoDB models, BullMQ + Redis job queue, routes calling the engine)
- [x] STEP 3 DONE: React client upload (drag/drop + browse) + Module A (auto charts + chart builder)
- [x] STEP 4 DONE: Module B wizard + results dashboard (Cytoscape). UI verified by build + jsdom smoke tests only; NEVER viewed in a real browser.
- [~] STEP 5 PARTIAL: presets for OULAD and MovieLens (filename-matched). Real MovieLens file not tested (synthetic only). Third dataset still TBD.
- [ ] STEP 6: Docker Compose, error handling, polish, docs

Known differences vs original notebook (intentional): Leiden uses leidenalg directly (15 communities vs 16 in notebook),
LPA is seeded + weighted (21 vs 22). Louvain identical.

## 4. Architecture (decided)
```
React (Vite) -> Express API -> MongoDB (metadata, mappings, jobs, result summaries)
                   |-> file storage (shared volume DATA_DIR)
                   |-> BullMQ + Redis queue -> Python FastAPI engine (pandas/DuckDB, sklearn, networkx, leidenalg)
```
- Browser never talks to Python. Express orchestrates.
- Raw big files NEVER go through Node memory or the browser: chunked/streamed upload to DATA_DIR; DuckDB aggregates in Python.
- Browser receives only aggregated results (graph JSON, tables, histograms).
- Frontend: React + Vite, react-dropzone, Plotly or ECharts, Cytoscape.js (sigma.js if >2k nodes).
- Engine only reads files inside DATA_DIR (path-traversal guard already implemented). Express and engine must share DATA_DIR.
- Planned folders: client/ server/ analysis/ datasets/ docker-compose.yml

## 5. Engine API CONTRACT (implemented, FastAPI on :8000)
POST /profile {path} -> {rows, columns[{name,type,numeric,nulls_in_sample,approx_distinct,min,max,mean,std,top_values}],
  preview[], behavioral_suggestion{entity_col,behavior_col,value_col,confidence,note}}
POST /behavioral/check {mapping} -> {ok, errors[], warnings[], stats{entities,behaviors,sparsity,varying_behaviors,behavior_names,preview}}
POST /behavioral/run {mapping, params, out_dir} -> {status: ok|ineligible|empty_graph|error, eligibility, summary, similarity{bins,counts,percentiles},
  benchmark[{algorithm,key,num_communities,modularity,nmi}], communities[{community_id,size,avg_total_activity,top_behavior,tier}],
  graph{nodes[{id,community,tier,total}],edges[{source,target,weight}],truncated}, macro_graph{nodes,edges}, diagnostics[{level,text}],
  outputs{classified_csv}}
Mapping: {path, format: long|wide, entity_col, behavior_col, value_col, agg: sum|count|mean|max, feature_cols, lookup{path,source_key,lookup_key}, label{path,entity_col,label_col}}
Params: {sample_size(300; null=all, max 5000), random_state(42), graph_method: threshold|knn, threshold(0.85), knn_k(10),
  algorithms[louvain,leiden,lpa], primary_algorithm: louvain|leiden|lpa|best_modularity, tier_method: quantile|thresholds,
  tier_labels[low,mid,high], low_cut, high_cut, min_community_size(1), max_edges_returned(20000)}
Engine run is currently SYNCHRONOUS (about 6 s on OULAD). Express/BullMQ wraps it as an async job with status polling.
Errors: 422 with a human-readable message for bad mappings; 400 path outside DATA_DIR; 404 missing file.

## 6. Step specs for the remaining work
STEP 2 (Express): Node 18+, ES modules. Routes: POST /api/uploads (chunked, resumable, up to ~500 MB, stream to DATA_DIR/<datasetId>/),
GET/DELETE /api/datasets, POST /api/datasets/:id/profile (calls engine /profile, caches in Mongo), POST /api/behavioral/check,
POST /api/jobs (create behavioral job -> BullMQ), GET /api/jobs/:id (status, progress, result), GET /api/jobs/:id/download (classified CSV).
Mongo models: Dataset{name,files[],profile,createdAt}, Job{datasetId,mapping,params,status,result,error,timings}.
Validation with zod. Helmet, CORS, rate limit, upload size caps. Mongo stores result SUMMARIES; full graph JSON on disk or GridFS if large.
STEP 3: dropzone page, dataset list, profile view, auto charts + chart builder (Module A).
STEP 4: wizard (1 pick files incl. optional lookup/label, 2 column mapping prefilled from behavioral_suggestion, 3 eligibility,
4 params with similarity histogram to choose tau + presets, 5 run with progress, 6 dashboard: matrix preview, similarity histogram,
Cytoscape graph colored by tier, community macro-graph, community table, algorithm benchmark, diagnostics panel, CSV/JSON export).
STEP 5: mapping presets for OULAD + 2 more datasets, "load demo" button.
STEP 6: docker-compose (mongo, redis, server, client, analysis), health checks, README, tests.

## 7. Preferences
- User is on macOS (Apple Silicon or Intel unknown). Give Mac / Terminal / Homebrew steps.
- Give COMPLETE file contents, one step at a time, tested where possible; explain what each step does.
- Act like a senior product developer: sensible defaults, honest diagnostics, no dataset-specific hard-coding.
- User is a student doing a major project; wants working end-to-end site and report-ready explanations.

## 8. PROMPT TO PASTE INTO THE NEW CHAT
(see the section below, also reproduced in the assistant's last message)

---
I am building a major project: a generic MERN website for "behavioral analysis" of student/user activity data, with a Python analysis engine.
I have attached a zip with the project so far plus a HANDOFF.md. READ HANDOFF.md FIRST: it contains the full concept, the pipeline, decisions, the engine API contract and the plan.

Current status: Step 1 (Python/FastAPI analysis engine in analysis/) is DONE and tested. It reproduces my original notebook exactly on the OULAD dataset
(297 nodes, 2544 edges, 15 communities, Louvain modularity 0.588501, NMI 0.054727).

Please continue from STEP 2 (Express API with chunked uploads, MongoDB, BullMQ + Redis job queue, calling the engine), then Step 3 (React upload + Module A graphical analysis),
Step 4 (React behavioral analysis wizard + results dashboard), Step 5 (two more datasets + demo presets), Step 6 (Docker Compose + polish).
Build and test the code yourself, then give me the complete files. I use a Mac, so give Mac Terminal/Homebrew steps. Keep it generic (not OULAD-specific).
Work step by step, and tell me exactly which commands to run to verify each step before moving on.
Unzip the attachment first, run `pytest -q` in analysis/ to confirm Step 1 works, then begin Step 2.

## UPDATE after Steps 2-4 (read this)
New engine endpoints: POST /charts/auto, /charts/query, /convert (xlsx->csv). Lookup spec gained `split_delimiter`. /behavioral/check now also returns `similarity` histogram (40 bins).
Server API: POST/GET/DELETE /api/datasets, POST /api/datasets/:id/files, GET .../files/:fid/profile, POST .../files/:fid/charts/auto|query,
POST /api/datasets/:id/behavioral/check, POST /api/datasets/:id/jobs, GET /api/datasets/:id/jobs, GET /api/jobs/:id, GET /api/jobs/:id/download, GET /api/health.
Verified: server e2e test reproduces OULAD (297 nodes / 2544 edges / 15 communities) through HTTP; 12 engine tests; 6 UI tests.
Known gaps / next: (a) run in a real browser and fix visual issues, (b) test MongoDB path, (c) real MovieLens + choose a 3rd dataset and add preset,
(d) Dockerfiles + full docker-compose, (e) optional BullMQ/Redis, chunked uploads, auth, larger-graph rendering (sigma.js), PDF/JSON report export.

## UPDATE 2 (bug fixes + zip)
- FIXED: MongoDB store crashed on create ("Cast to ObjectId failed") because `_id: String` was in schema options instead of the schema fields. Reproduced offline and fixed; real MongoDB write path still not run against a live mongod by me.
- NEW: .zip upload (engine POST /unzip; zip-slip safe, size capped). Zip contents become separate dataset files.
- CHANGED: OULAD preset only needs studentVle.csv + vle.csv; studentInfo.csv (label) optional.
- Tests now: engine 13, UI 7, server e2e incl. real OULAD zip.

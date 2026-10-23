import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import result from './oulad-result.json';

// jsdom has no canvas/ResizeObserver: stub the graph + chart sizing, test everything else for real
vi.mock('cytoscape', () => ({ default: () => ({ on() {}, destroy() {} }) }));
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };

vi.mock('../api.js', () => {
  const files = [
    { id: 'f1', originalName: 'studentVle.csv', size: 1e8 }, { id: 'f2', originalName: 'vle.csv', size: 1e5 },
    { id: 'f3', originalName: 'studentInfo.csv', size: 1e6 },
  ];
  const prof = (cols) => ({ rows: 100, columns: cols.map((c) => ({ name: c, type: 'BIGINT', numeric: c !== 'activity_type', approx_distinct: 5, nulls_in_sample: 0, min: 0, max: 9, mean: 4 })),
    preview: [{ a: 1 }], behavioral_suggestion: { entity_col: cols[0], behavior_col: null, value_col: cols[1] } });
  return { api: {
    health: vi.fn().mockResolvedValue({ server: 'ok', engine: true, store: 'json-file' }),
    datasets: vi.fn().mockResolvedValue([{ id: 'd1', name: 'OULAD', createdAt: new Date().toISOString(), files }]),
    dataset: vi.fn().mockResolvedValue({ id: 'd1', name: 'OULAD', files }),
    profile: vi.fn((id, fid) => Promise.resolve(prof(fid === 'f1' ? ['id_student', 'sum_click', 'id_site'] : fid === 'f2' ? ['id_site', 'activity_type'] : ['id_student', 'final_result']))),
    autoCharts: vi.fn().mockResolvedValue({ rows_analysed: 10, partial: false, charts: [
      { id: 'h', title: 'Distribution of x', kind: 'histogram', rows: [{ x: '0', value: 3 }, { x: '1', value: 5 }] },
      { id: 'c', title: 'Correlation', kind: 'correlation', columns: ['a', 'b'], matrix: [[1, 0.5], [0.5, 1]] }] }),
    jobs: vi.fn().mockResolvedValue([]),
    job: vi.fn().mockResolvedValue({ id: 'j1', status: 'done', params: { tier_labels: ['Low Engagement / At-Risk', 'Moderate Engagement', 'High Engagement'] }, result }),
    check: vi.fn(), createJob: vi.fn(), downloadUrl: (id) => `/api/jobs/${id}/download`,
  } };
});

import Home from '../pages/Home.jsx';
import Dataset from '../pages/Dataset.jsx';
import Results from '../behavioral/Results.jsx';
import { toMapping, toParams, mappingReady, guessLabel } from '../behavioral/Wizard.jsx';
import { alignColors, layoutClusters } from '../behavioral/viz.js';
import { PRESETS } from '../presets.js';

beforeEach(cleanup);

describe('pages render without crashing', () => {
  it('Home lists datasets and shows the dropzone', async () => {
    render(<MemoryRouter><Home /></MemoryRouter>);
    expect(screen.getByText(/click to browse/i)).toBeTruthy();
    await waitFor(() => expect(screen.getByText('OULAD')).toBeTruthy());
  });

  it('Results dashboard shows the real OULAD numbers', async () => {
    render(<Results jobId="j1" />);
    await waitFor(() => expect(screen.getByText('Results')).toBeTruthy());
    expect(screen.getByText('297')).toBeTruthy();                       // connected nodes
    expect(screen.getByText('2,544')).toBeTruthy();                     // edges
    expect(screen.getAllByText('High Engagement').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Louvain').length).toBeGreaterThan(0);
    expect(screen.getByText(/Download classified CSV/)).toBeTruthy();
  });

  it('Results dashboard has community-detection graphs, modularity and NMI for all three algorithms', async () => {
    render(<Results jobId="j1" />);
    await waitFor(() => expect(screen.getByText('Results')).toBeTruthy());
    expect(screen.getByText('Community detection graphs')).toBeTruthy();
    expect(screen.getAllByText('Leiden').length).toBeGreaterThan(0);          // Leiden is present (graph panel + tables)
    expect(screen.getAllByText('Modularity').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/0\.5905|0\.59048/).length).toBeGreaterThan(0); // Leiden modularity is visible
    expect(screen.getAllByText(/0\.0536/).length).toBeGreaterThan(0);          // Leiden NMI is visible
  });

  it('Dataset page: overview, graphical tab, behavioral wizard with OULAD preset', async () => {
    render(<MemoryRouter initialEntries={['/d/d1']}><Routes><Route path="/d/:id" element={<Dataset />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Columns')).toBeTruthy());
    fireEvent.click(screen.getByText('Graphical analysis'));
    await waitFor(() => expect(screen.getByText('Distribution of x')).toBeTruthy());
    expect(screen.getByText('Community detection graphs')).toBeTruthy();       // also shown in the graphical analysis tab
    expect(screen.getByText('Chart builder')).toBeTruthy();
    fireEvent.click(screen.getByText('Behavioral analysis'));
    await waitFor(() => expect(screen.getByText(/Recognised/)).toBeTruthy());
    fireEvent.click(screen.getByText('Apply preset'));
    await waitFor(() => expect(screen.getByText(/Check if this data is suitable/).disabled).toBe(false));
  });
});

describe('mapping logic', () => {
  const files = [{ id: 'f1', originalName: 'studentVle.csv' }, { id: 'f2', originalName: 'vle.csv' }, { id: 'f3', originalName: 'studentInfo.csv' }];
  it('OULAD preset becomes the exact request body the server expects', () => {
    const b = PRESETS[0].build(files);
    expect(mappingReady(b.mapping)).toBe(true);
    expect(toMapping(b.mapping)).toEqual({
      mainFileId: 'f1', format: 'long', entity_col: 'id_student', behavior_col: 'activity_type', value_col: 'sum_click', agg: 'sum',
      feature_cols: null, lookup: { fileId: 'f2', source_key: 'id_site', lookup_key: 'id_site', split_delimiter: null },
      label: { fileId: 'f3', entity_col: 'id_student', label_col: 'final_result' } });
  });
  it('OULAD preset works with only 2 files (label file optional)', () => {
    const two = files.slice(0, 2);
    expect(PRESETS[0].match(two)).toBeTruthy();
    const m = PRESETS[0].build(two).mapping;
    expect(mappingReady(m)).toBe(true);
    expect(toMapping(m).label).toBeNull();
  });
  it('MovieLens preset uses count + genre split', () => {
    const f = [{ id: 'a', originalName: 'ratings.csv' }, { id: 'b', originalName: 'movies.csv' }];
    expect(PRESETS[1].match(f)).toBeTruthy();
    const m = toMapping(PRESETS[1].build(f).mapping);
    expect(m.agg).toBe('count'); expect(m.value_col).toBeNull(); expect(m.lookup.split_delimiter).toBe('|');
  });
  it('incomplete mappings are rejected and params are coerced to numbers', () => {
    expect(mappingReady({ mainFileId: 'f1', format: 'long', entity_col: 'u', behavior_col: '', agg: 'sum', value_col: '', useLookup: false, useLabel: false, feature_cols: [] })).toBe(false);
    const p = toParams({ sample_size: '300', graph_method: 'threshold', threshold: '0.85', knn_k: '10', algorithms: ['louvain'], primary_algorithm: 'louvain', tier_method: 'quantile', tier_labels: ['a', 'b', 'c'], low_cut: '', high_cut: '', min_community_size: '1' });
    expect(p.sample_size).toBe(300); expect(p.threshold).toBe(0.85);
  });
});

describe('community graph helpers', () => {
  it('guessLabel finds final_result in another file without a preset', () => {
    const files = [{ id: 'f1' }, { id: 'f2' }, { id: 'f3' }];
    const col = (name, numeric, d) => ({ name, numeric, approx_distinct: d });
    const profiles = {
      f1: { columns: [col('id_student', true, 500), col('sum_click', true, 80)] },
      f2: { columns: [col('id_site', true, 6000), col('activity_type', false, 20)] },
      f3: { columns: [col('id_student', true, 32000), col('gender', false, 2), col('final_result', false, 4)] },
    };
    expect(guessLabel(files, profiles, 'id_student', 'f1')).toEqual({ fileId: 'f3', entity_col: 'id_student', label_col: 'final_result' });
    expect(guessLabel(files.slice(0, 2), profiles, 'id_student', 'f1')).toBeNull();
  });

  it('alignColors keeps the colour of the same group across algorithms', () => {
    const ref = [0, 0, 0, 1, 1, 2];
    const other = [5, 5, 5, 3, 3, 4];                 // same groups, different ids
    const { colorOf: a } = alignColors(null, ref);
    const { colorOf: b } = alignColors(ref, [2, 2, 2, 1, 1, 0]);
    expect(b[2]).toBe(a[0]); expect(b[1]).toBe(a[1]); expect(b[0]).toBe(a[2]);
    expect(other.length).toBe(6);
  });

  it('layoutClusters gives every node a position and keeps communities apart', () => {
    const nodes = Array.from({ length: 60 }, (_, i) => ({ id: String(i), total: i }));
    const membership = nodes.map((_, i) => Math.floor(i / 20));
    const pos = layoutClusters(nodes, membership, [{ source: '0', target: '25', weight: 1 }]);
    expect(pos.size).toBe(60);
    const c = (g) => { const p = [...Array(20).keys()].map((k) => pos.get(String(g * 20 + k))); return { x: p.reduce((s, q) => s + q.x, 0) / 20, y: p.reduce((s, q) => s + q.y, 0) / 20 }; };
    const d = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    expect(d(c(0), c(1))).toBeGreaterThan(40); expect(d(c(1), c(2))).toBeGreaterThan(40);
  });
});
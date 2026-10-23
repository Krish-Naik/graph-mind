import { describe, expect, test } from 'vitest';
import { guessLookup, guessLabel } from '../behavioral/Wizard.jsx';

const col = (name, approx_distinct, numeric = false) => ({ name, approx_distinct, numeric });
// profile shapes copied from the real OULAD files
const files = [
  { id: 'svle', originalName: 'studentVle.csv' }, { id: 'vle', originalName: 'vle.csv' }, { id: 'info', originalName: 'studentInfo.csv' },
];
const profiles = {
  svle: { rows: 10655280, columns: [col('code_module', 1), col('code_presentation', 2), col('id_student', 703, true), col('id_site', 370, true), col('date', 287, true), col('sum_click', 91, true)] },
  vle: { rows: 6364, columns: [col('id_site', 6330, true), col('code_module', 7), col('code_presentation', 4), col('activity_type', 20), col('week_from', 31), col('week_to', 31)] },
  info: { rows: 32593, columns: [col('code_module', 7), col('id_student', 28473, true), col('region', 12), col('final_result', 4)] },
};

describe('automatic mapping (no preset needed)', () => {
  test('finds the vle.csv lookup join and the activity_type behavior', () => {
    const g = guessLookup(files, profiles, 'svle', 'id_student');
    expect(g).toMatchObject({ fileId: 'vle', key: 'id_site', behavior: 'activity_type' });
  });
  test('finds the final_result label', () => {
    expect(guessLabel(files, profiles, 'id_student', 'svle')).toMatchObject({ fileId: 'info', label_col: 'final_result' });
  });
  test('proposes nothing when there is no lookup-like file', () => {
    expect(guessLookup(files.slice(0, 1), profiles, 'svle', 'id_student')).toBeNull();
  });
});
// One-click mappings for known datasets. Matched by file names; generic mapping still works for everything else.
const find = (files, name) => files.find((f) => f.originalName.toLowerCase() === name.toLowerCase());

// MOOC action log: file names may be .tsv or .csv, with or without a prefix (e.g. "mooc_actions.tsv")
const findLike = (files, re) => files.find((f) => re.test(f.originalName));
const MOOC_ACTIONS = /^(?!\.)(.*[^a-z])?mooc_actions\.(tsv|csv|txt)$/i;   // not the hidden "._mooc_actions.tsv" copies macOS makes

export const PRESETS = [
  {
    id: 'oulad',
    name: 'OULAD (Open University)',
    description: 'students x VLE activity type, summed clicks (final_result used for NMI if studentInfo.csv is present)',
    match: (files) => find(files, 'studentVle.csv') && find(files, 'vle.csv'),   // studentInfo.csv is optional (only for NMI)
    build: (files) => ({
      mapping: {
        mainFileId: find(files, 'studentVle.csv').id, format: 'long', entity_col: 'id_student', behavior_col: 'activity_type',
        value_col: 'sum_click', agg: 'sum', feature_cols: [],
        useLookup: true, lookup: { fileId: find(files, 'vle.csv').id, source_key: 'id_site', lookup_key: 'id_site', split_delimiter: '' },
        useLabel: !!find(files, 'studentInfo.csv'),
        label: { fileId: find(files, 'studentInfo.csv')?.id || '', entity_col: 'id_student', label_col: 'final_result' },
      },
      params: { sample_size: 300, threshold: 0.85 },
    }),
  },
  {
    id: 'mooc',
    name: 'MOOC actions (act-mooc)',
    description: 'users x course activity (TARGETID), number of actions; the other mooc_* files are not needed',
    match: (files) => !!findLike(files, MOOC_ACTIONS),
    build: (files) => ({
      mapping: {
        mainFileId: findLike(files, MOOC_ACTIONS).id, format: 'long', entity_col: 'USERID', behavior_col: 'TARGETID',
        value_col: '', agg: 'count', feature_cols: [],
        useLookup: false, lookup: { fileId: '', source_key: '', lookup_key: '', split_delimiter: '' },
        // the label file of this dataset marks single ACTIONS (dropout yes/no), not users, so it cannot be used for NMI
        useLabel: false, label: { fileId: '', entity_col: '', label_col: '' },
      },
      // 97 activity types give sparse behavior vectors: tau 0.85 would leave most users unconnected, 0.7 connects ~90%
      params: { sample_size: 300, threshold: 0.7 },
    }),
  },
  {
    id: 'movielens',
    name: 'MovieLens (ml-latest-small style)',
    description: 'users x movie genre, number of ratings; genres split on "|"',
    match: (files) => find(files, 'ratings.csv') && find(files, 'movies.csv'),
    build: (files) => ({
      mapping: {
        mainFileId: find(files, 'ratings.csv').id, format: 'long', entity_col: 'userId', behavior_col: 'genres',
        value_col: '', agg: 'count', feature_cols: [],
        useLookup: true, lookup: { fileId: find(files, 'movies.csv').id, source_key: 'movieId', lookup_key: 'movieId', split_delimiter: '|' },
        useLabel: false, label: { fileId: '', entity_col: '', label_col: '' },
      },
      params: { sample_size: 300, threshold: 0.85, tier_labels: ['Light viewers', 'Regular viewers', 'Heavy viewers'] },
    }),
  },
];

import axios from 'axios';

const http = axios.create({ baseURL: '/api' });
// surface the server's readable message instead of "Request failed with status code 422"
http.interceptors.response.use((r) => r, (e) => {
  e.message = e.response?.data?.error || (e.code === 'ERR_NETWORK' ? 'Cannot reach the server. Is it running?' : e.message);
  return Promise.reject(e);
});
const data = (p) => p.then((r) => r.data);

function form(files, name) {
  const fd = new FormData();
  if (name) fd.append('name', name);
  files.forEach((f) => fd.append('files', f));
  return fd;
}

export const api = {
  health: () => data(http.get('/health')),
  datasets: () => data(http.get('/datasets')),
  dataset: (id) => data(http.get(`/datasets/${id}`)),
  createDataset: (files, name, onProgress) =>
    data(http.post('/datasets', form(files, name), { onUploadProgress: (e) => onProgress?.(e.total ? e.loaded / e.total : 0) })),
  addFiles: (id, files, onProgress) =>
    data(http.post(`/datasets/${id}/files`, form(files), { onUploadProgress: (e) => onProgress?.(e.total ? e.loaded / e.total : 0) })),
  deleteDataset: (id) => data(http.delete(`/datasets/${id}`)),
  profile: (id, fid) => data(http.get(`/datasets/${id}/files/${fid}/profile`)),
  autoCharts: (id, fid) => data(http.post(`/datasets/${id}/files/${fid}/charts/auto`)),
  chartQuery: (id, fid, spec) => data(http.post(`/datasets/${id}/files/${fid}/charts/query`, spec)),
  check: (id, mapping, sampleSize) => data(http.post(`/datasets/${id}/behavioral/check`, { mapping, sampleSize })),
  createJob: (id, mapping, params) => data(http.post(`/datasets/${id}/jobs`, { mapping, params })),
  job: (jobId) => data(http.get(`/jobs/${jobId}`)),
  jobs: (id) => data(http.get(`/datasets/${id}/jobs`)),
  downloadUrl: (jobId) => `/api/jobs/${jobId}/download`,
};

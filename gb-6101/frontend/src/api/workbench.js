import { request } from "./http.js";

export const api = {
  config: () => request("/workbench"),
  login: data => request("/auth/login", {method: "POST", data}),
  cases: () => request("/cases"),
  createCase: data => request("/cases", {method: "POST", data}),
  runs: () => request("/runs"),
  run: (id, signal) => request(`/runs/${id}`, {signal}),
  enqueue: (id, data) => request(`/cases/${id}/runs`, {method: "POST", data}),
  review: id => request(`/runs/${id}/review`),
  submitReview: (id, data) => request(`/runs/${id}/review`, {method: "POST", data}),
  export: id => request(`/runs/${id}/export`, {raw: true}),
  audit: () => request("/audit", {signal: AbortSignal.timeout(5000)}),

  // Drill copies: anonymised practice batches for outsourced teams.
  drills: () => request("/drills"),
  drill: (id, signal) => request(`/drills/${id}`, {signal}),
  createDrill: data => request("/drills", {method: "POST", data}),
  appendDrill: (id, data) => request(`/drills/${id}/batches`, {method: "POST", data}),
  drillRuns: (sessionId, batchId, signal) =>
    request(`/drills/${sessionId}/batches/${batchId}/runs`, {signal}),
  drillRun: (sessionId, batchId, runId, signal) =>
    request(`/drills/${sessionId}/batches/${batchId}/runs/${runId}`, {signal}),
  rerunDrill: (sessionId, batchId) =>
    request(`/drills/${sessionId}/batches/${batchId}/runs`, {method: "POST"}),
  exportDrill: (sessionId, batchId, runId) =>
    request(`/drills/${sessionId}/batches/${batchId}/runs/${runId}/export`, {raw: true}),
};

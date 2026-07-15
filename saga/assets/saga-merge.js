// Pure reconciliation of two comment envelopes — the embedded file state and
// the localStorage draft buffer — by per-record updatedAt, with tombstones.
//
// Kept dependency-free and DOM-free so it loads in the page (as SagaMerge) and
// runs unchanged under node for unit tests (module.exports). See saga.js for
// how the served/static runtime drives it.

(function (root) {
  function ts(rec) {
    return (rec && rec.updatedAt) || 0;
  }

  // Union of two record lists keyed by id; the greater updatedAt wins, and a
  // tie favours b (the local buffer — an offline draft is never clobbered by an
  // older file copy). A deletedAt counts as an update, so it rides along on the
  // record with the greater updatedAt like any other change.
  function mergeLists(a, b) {
    const byId = new Map();
    (a || []).forEach((r) => byId.set(r.id, r));
    (b || []).forEach((r) => {
      const prev = byId.get(r.id);
      if (!prev || ts(r) >= ts(prev)) byId.set(r.id, r);
    });
    return [...byId.values()];
  }

  // The singleton overall comment: greater updatedAt wins (tie favours b).
  function mergeOverall(a, b) {
    if (!a) return b || null;
    if (!b) return a;
    return ts(b) >= ts(a) ? b : a;
  }

  function recomputeUpdatedAt(env) {
    let max = 0;
    if (env.overall) max = Math.max(max, ts(env.overall));
    (env.file || []).forEach((r) => (max = Math.max(max, ts(r))));
    (env.inline || []).forEach((r) => (max = Math.max(max, ts(r))));
    env.updatedAt = max;
    return env;
  }

  // Merge the file's embedded envelope with the localStorage buffer (which may
  // be absent). The result carries the given sagaId and a recomputed updatedAt.
  function mergeEnvelope(fileState, buffer, sagaId) {
    const f = fileState || {};
    const merged = {
      schema: 1,
      sagaId: sagaId,
      overall: buffer
        ? mergeOverall(f.overall || null, buffer.overall || null)
        : f.overall || null,
      file: buffer ? mergeLists(f.file, buffer.file) : f.file || [],
      inline: buffer ? mergeLists(f.inline, buffer.inline) : f.inline || [],
      updatedAt: 0,
    };
    return recomputeUpdatedAt(merged);
  }

  const api = { mergeLists, mergeOverall, mergeEnvelope, recomputeUpdatedAt };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.SagaMerge = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

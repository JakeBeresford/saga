// PR saga: chapter-based review of one change set.
//
// Standalone static build: the saga payload is inlined into the page as
// window.__sagaData (verdict + chapters, each with its reconstructed diff), and
// the review comments live in an embedded JSON block (#saga-comments) that is
// the durable source of truth. This file renders the saga — a table of contents
// and a chapter reader — tracks per-chapter mark-as-read, and lets a reviewer
// leave inline / per-file / overall comments.
//
// Two runtime modes via progressive enhancement:
//   * Served  (origin http://127.0.0.1:PORT, `saga serve` reachable): edits
//     autosave into the file over the API, and Publish/Read are live buttons.
//   * Static  (file://, no server): drafting still works and buffers in
//     localStorage; Publish/Read are hidden and a banner nudges the reviewer to
//     reopen through `saga serve`.
// Reading persisted comments never needs the server — the page always hydrates
// from the embedded block on load.

(function () {
  const data = window.__sagaData || {chapters: [], verdict: null, branch: ''};
  const readSlug = data.branch || 'saga';
  const CONFIG = {
    drawFileList: false, matching: 'lines',
    outputFormat: 'line-by-line', highlight: true, colorScheme: 'dark',
  };

  let chapters = [];
  let current = 0;

  const $ = (id) => document.getElementById(id);

  // --- theme (light/dark) --------------------------------------------
  // Follows the OS unless the reader forces a choice via the header toggle,
  // stored globally (not per-saga) so the preference sticks across files.

  const THEME_KEY = 'saga-theme';

  function effectiveTheme() {
    const forced = document.documentElement.getAttribute('data-theme');
    if (forced === 'light' || forced === 'dark') return forced;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light' : 'dark';
  }

  function setThemeIcon() {
    const btn = $('saga-theme');
    if (btn) btn.textContent = effectiveTheme() === 'dark' ? '☀' : '☾';
  }

  function initTheme() {
    const btn = $('saga-theme');
    if (!btn) return;
    setThemeIcon();
    btn.addEventListener('click', () => {
      const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      setThemeIcon();
      // Re-draw the open chapter so diff2html's own colour-scheme class
      // (and the residual diff colours our CSS doesn't override) match.
      if (!$('saga-reader').hidden) openChapter(current);
    });
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // --- mark-as-read (localStorage) -----------------------------------

  function readKey() { return 'saga-read:' + readSlug; }
  function readSet() {
    try { return new Set(JSON.parse(localStorage.getItem(readKey()) || '[]')); }
    catch (e) { return new Set(); }
  }
  function isRead(id) { return readSet().has(id); }
  function setRead(id, read) {
    const s = readSet();
    if (read) s.add(id); else s.delete(id);
    localStorage.setItem(readKey(), JSON.stringify([...s]));
  }

  // --- comment store (embedded block + localStorage buffer) ----------
  // The envelope is the merge of the file's embedded block and this origin's
  // localStorage draft (see saga-merge.js). Every mutation stamps updatedAt,
  // writes the buffer synchronously (immediate durability), and — when served —
  // schedules a debounced save into the file.

  let sagaId = '';
  let env = {schema: 1, sagaId: '', updatedAt: 0, overall: null, file: [], inline: []};

  function now() { return Date.now(); }
  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'c' + now().toString(16) + Math.random().toString(16).slice(2);
  }

  function parseEmbedded() {
    const el = $('saga-comments');
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  function bufferKey() { return 'saga:' + sagaId + ':comments'; }
  function loadBuffer() {
    try { return JSON.parse(localStorage.getItem(bufferKey()) || 'null'); }
    catch (e) { return null; }
  }
  function saveBuffer() {
    try { localStorage.setItem(bufferKey(), JSON.stringify(env)); } catch (e) {}
  }

  // Live (non-tombstoned) accessors used for display.
  function liveInline(path, line, side) {
    return env.inline.filter((c) => !c.deletedAt &&
      c.path === path && c.line === line && c.side === side);
  }
  function liveFileComment(path) {
    return env.file.find((f) => !f.deletedAt && f.path === path) || null;
  }
  function liveOverall() {
    return env.overall && !env.overall.deletedAt ? env.overall : null;
  }

  function commentCount() {
    let n = env.inline.filter((c) => !c.deletedAt).length;
    n += env.file.filter((f) => !f.deletedAt).length;
    const o = liveOverall();
    if (o && o.body && o.body.trim()) n += 1;
    return n;
  }
  function updateCount() {
    const el = $('saga-cmt-count');
    if (!el) return;
    const n = commentCount();
    el.textContent = n === 1 ? '1 comment' : n + ' comments';
  }

  // Every edit funnels through here: recompute the roll-up timestamp, persist
  // the buffer, refresh the count, and (served) schedule a save into the file.
  function onChange() {
    SagaMerge.recomputeUpdatedAt(env);
    saveBuffer();
    updateCount();
    if (mode === 'served') scheduleSync();
  }

  function addInline(path, line, side, body) {
    env.inline.push({id: uid(), path: path, line: line, side: side,
                     body: body, updatedAt: now(), deletedAt: null});
    onChange();
  }
  function deleteRecord(rec) {
    rec.deletedAt = now();
    rec.updatedAt = now();
    onChange();
  }
  function setFileComment(path, body, anchor) {
    const rec = liveFileComment(path);
    if (body) {
      if (rec) { rec.body = body; rec.updatedAt = now(); }
      else env.file.push({id: uid(), path: path, line: anchor.line, side: anchor.side,
                          body: body, updatedAt: now(), deletedAt: null});
    } else if (rec) {
      rec.deletedAt = now();
      rec.updatedAt = now();
    }
    onChange();
  }
  function setOverall(body) {
    if (body) {
      if (env.overall && !env.overall.deletedAt) {
        env.overall.body = body; env.overall.updatedAt = now();
      } else {
        env.overall = {body: body, updatedAt: now(), deletedAt: null};
      }
    } else if (env.overall) {
      env.overall.deletedAt = now();
      env.overall.updatedAt = now();
    }
    onChange();
  }

  // --- connection controller (served ⇄ buffering) --------------------
  // GET /api/session is the mode probe, token source, and heartbeat, unified.
  // The UI is driven off the last write's real outcome, never a one-shot probe.

  let mode = 'static';        // 'served' | 'static'
  let token = null;
  let syncTimer = null;
  let reconnectTimer = null;

  function setStatus(state) {
    const el = $('saga-status');
    if (!el) return;
    const labels = {
      saved: 'Saved', saving: 'Saving…',
      reconnecting: 'Reconnecting…', draft: 'Draft (this browser only)',
    };
    el.textContent = labels[state] || '';
    el.dataset.state = state;
  }

  function scheduleSync() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(sync, 500);
  }

  function sync() {
    setStatus('saving');
    return fetch('/api/comments', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json', 'X-Saga-Token': token},
      body: JSON.stringify(env),
    }).then((res) => {
      if (!res.ok) throw new Error('PUT ' + res.status);
      setStatus('saved');
    }).catch(() => { enterBuffering(); });
  }

  // On a failed write, keep buffering to localStorage and poll the session
  // endpoint; a restart mints a new token, so refresh it before flushing.
  function enterBuffering() {
    setStatus('reconnecting');
    if (reconnectTimer) return;
    reconnectTimer = setInterval(() => {
      fetch('/api/session').then((res) => {
        if (!res.ok) throw new Error('session ' + res.status);
        return res.json();
      }).then((s) => {
        if (s.sagaId !== sagaId) return;
        token = s.token;
        clearInterval(reconnectTimer);
        reconnectTimer = null;
        sync();
      }).catch(() => {});
    }, 3000);
  }

  function detectMode() {
    return fetch('/api/session').then((res) => {
      if (!res.ok) throw new Error('session ' + res.status);
      return res.json();
    }).then((s) => {
      if (s.sagaId !== sagaId) throw new Error('sagaId mismatch');
      token = s.token;
      mode = 'served';
      applyMode();
      // Reconcile the file with the merged (possibly newer) buffer on load.
      sync();
    }).catch(() => {
      mode = 'static';
      applyMode();
    });
  }

  // Toggle the served-only controls and the static banner, and seed the pill.
  function applyMode() {
    const served = mode === 'served';
    const banner = $('saga-static-banner');
    if (banner) banner.hidden = served;
    const publish = $('saga-publish');
    const exportBtn = $('saga-export');
    if (publish) publish.hidden = !served;
    if (exportBtn) exportBtn.hidden = !served;
    setStatus(served ? 'saved' : 'draft');
  }

  function notify(message, isError) {
    const el = $('saga-notice');
    if (!el) return;
    el.innerHTML = '';
    const box = document.createElement('div');
    box.className = isError ? 'saga-error' : 'saga-flash';
    box.textContent = message;
    el.appendChild(box);
    if (!isError) setTimeout(() => { if (box.parentNode) box.remove(); }, 6000);
  }

  // --- publish / read (served only) ----------------------------------

  function publishGithub(btn) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Publishing…';
    fetch('/api/publish', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Saga-Token': token},
      body: JSON.stringify({mode: 'github'}),
    }).then((res) => res.json().then((j) => ({ok: res.ok, j}))).then(({ok, j}) => {
      if (!ok) throw new Error(j.error || 'publish failed');
      notify(j.summary || 'Created a pending review on GitHub.');
    }).catch((e) => notify('Publish failed: ' + e.message, true))
      .finally(() => { btn.textContent = label; btn.disabled = false; });
  }

  function exportForAgent(btn) {
    const label = btn.textContent;
    btn.disabled = true;
    fetch('/api/publish', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Saga-Token': token},
      body: JSON.stringify({mode: 'agent'}),
    }).then((res) => res.json().then((j) => ({ok: res.ok, j}))).then(({ok, j}) => {
      if (!ok) throw new Error(j.error || 'read failed');
      return copyText(JSON.stringify(j.comments, null, 2));
    }).then(() => {
      btn.textContent = 'Copied ✓';
      notify('Comments copied as JSON for a coding agent.');
      setTimeout(() => { btn.textContent = label; }, 1500);
    }).catch((e) => notify('Read failed: ' + e.message, true))
      .finally(() => { btn.disabled = false; });
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
    return Promise.resolve();
  }

  // --- inline comment threads ----------------------------------------

  // Read (file, line, side) from a diff2html line-by-line row. Added/context
  // lines anchor to the new-file number (RIGHT); pure deletions to the old
  // number (LEFT). Hunk-header / spacer rows have no number and return null.
  function lineAnchor(tr) {
    const cell = tr.querySelector('td.d2h-code-linenumber');
    if (!cell) return null;
    const n1 = cell.querySelector('.line-num1');
    const n2 = cell.querySelector('.line-num2');
    const l2 = n2 && n2.textContent.trim();
    const l1 = n1 && n1.textContent.trim();
    if (l2) return {line: parseInt(l2, 10), side: 'RIGHT'};
    if (l1) return {line: parseInt(l1, 10), side: 'LEFT'};
    return null;
  }
  function firstAnchor(fw) {
    let anchor = null;
    fw.querySelectorAll('tr').forEach((tr) => {
      if (!anchor) anchor = lineAnchor(tr);
    });
    return anchor || {line: 1, side: 'RIGHT'};
  }

  // Render the comment thread for one line into its cell. The composer is only
  // shown when showComposer is true, so a line with saved comments displays them
  // on their own — clicking the line number again reveals the composer to add more.
  function renderThread(td, path, line, side, row, showComposer) {
    td.innerHTML = '';
    liveInline(path, line, side).forEach((c) => {
      const item = document.createElement('div');
      item.className = 'saga-cmt';
      const body = document.createElement('div');
      body.className = 'saga-cmt-body';
      body.innerHTML = renderMarkdown(c.body);
      const del = document.createElement('button');
      del.className = 'saga-cmt-del';
      del.textContent = '✕';
      del.title = 'Delete comment';
      del.addEventListener('click', () => {
        deleteRecord(c);
        if (!liveInline(path, line, side).length) row.remove();
        else renderThread(td, path, line, side, row, false);
      });
      item.appendChild(body);
      item.appendChild(del);
      td.appendChild(item);
    });
    if (!showComposer) return null;
    const composer = document.createElement('div');
    composer.className = 'saga-cmt-composer';
    const ta = document.createElement('textarea');
    ta.className = 'saga-cmt-input';
    ta.placeholder = 'Comment on line ' + line + ' (' + side + ')…';
    const save = document.createElement('button');
    save.className = 'saga-btn saga-cmt-save';
    save.textContent = 'Comment';
    save.addEventListener('click', () => {
      const v = ta.value.trim();
      if (!v) return;
      addInline(path, line, side, v);
      renderThread(td, path, line, side, row, false);
    });
    const cancel = document.createElement('button');
    cancel.className = 'saga-btn saga-cmt-cancel';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', () => {
      if (!liveInline(path, line, side).length) row.remove();
      else renderThread(td, path, line, side, row, false);
    });
    composer.appendChild(ta);
    composer.appendChild(save);
    composer.appendChild(cancel);
    td.appendChild(composer);
    ta.focus();
    return ta;
  }

  function insertComposerRow(tr, path, line, side) {
    const next = tr.nextSibling;
    if (next && next.classList && next.classList.contains('saga-cmt-row') &&
        next.dataset.line === String(line) && next.dataset.side === side) {
      // Row already exists (from a prior comment or the initial load); reveal the
      // composer so the reviewer can add another comment on the same line.
      renderThread(next.querySelector('td'), path, line, side, next, true);
      return;
    }
    const row = document.createElement('tr');
    row.className = 'saga-cmt-row';
    row.dataset.line = String(line);
    row.dataset.side = side;
    const td = document.createElement('td');
    td.colSpan = tr.children.length;
    td.className = 'saga-cmt-cell';
    row.appendChild(td);
    tr.parentNode.insertBefore(row, tr.nextSibling);
    // A brand-new row with existing saved comments comes from the initial load
    // pass; show those comments without a composer. A click on a bare line opens
    // the composer to write the first comment.
    renderThread(td, path, line, side, row, !liveInline(path, line, side).length);
  }

  // Per-file comment control injected into a diff2html file header. The panel
  // re-renders after every save/delete so the reviewer gets the same visible
  // feedback an inline thread does — the saved note shows above the editor, and
  // the header button reflects whether a comment exists.
  function wireFileComment(fw, path) {
    const header = fw.querySelector('.d2h-file-header');
    if (!header) return;
    const btn = document.createElement('button');
    btn.className = 'saga-file-cmt-btn';
    header.appendChild(btn);
    const panel = document.createElement('div');
    panel.className = 'saga-file-cmt-panel';
    header.parentNode.insertBefore(panel, header.nextSibling);

    function refreshBtn() {
      const rec = liveFileComment(path);
      btn.textContent = rec ? '💬 File comment ✓' : '💬 File comment';
      btn.classList.toggle('saga-has-comment', !!rec);
    }

    function render() {
      panel.innerHTML = '';
      const rec = liveFileComment(path);
      if (rec) {
        const item = document.createElement('div');
        item.className = 'saga-cmt';
        const body = document.createElement('div');
        body.className = 'saga-cmt-body';
        body.innerHTML = renderMarkdown(rec.body);
        const del = document.createElement('button');
        del.className = 'saga-cmt-del';
        del.textContent = '✕';
        del.title = 'Delete file comment';
        del.addEventListener('click', () => {
          deleteRecord(rec);
          render();
          refreshBtn();
        });
        item.appendChild(body);
        item.appendChild(del);
        panel.appendChild(item);
      }
      const composer = document.createElement('div');
      composer.className = 'saga-cmt-composer';
      const ta = document.createElement('textarea');
      ta.className = 'saga-cmt-input';
      ta.placeholder = 'Comment on the whole file…';
      ta.value = rec ? rec.body : '';
      const save = document.createElement('button');
      save.className = 'saga-btn';
      save.textContent = rec ? 'Update file comment' : 'Save file comment';
      save.addEventListener('click', () => {
        const v = ta.value.trim();
        if (!v && !rec) return;
        setFileComment(path, v, firstAnchor(fw));
        render();
        refreshBtn();
      });
      composer.appendChild(ta);
      composer.appendChild(save);
      panel.appendChild(composer);
    }

    refreshBtn();
    render();
    panel.hidden = !liveFileComment(path);
    btn.addEventListener('click', () => { panel.hidden = !panel.hidden; });
  }

  // Build a link for a diff file path — a local editor/file URL or a GitHub blob
  // URL, per data.file_links — or null when there is nothing to link to.
  function fileURL(path) {
    const fl = data.file_links;
    if (!fl) return null;
    // diff2html shows renames as "old → new"; link the new path.
    const rel = path.split(' → ').pop().trim();
    if (fl.type === 'github') {
      return fl.base + '/' + rel.split('/').map(encodeURIComponent).join('/');
    }
    const abs = fl.root.replace(/\/+$/, '') + '/' + rel;
    return (fl.scheme === 'file' ? 'file://' : fl.scheme + '://file') + encodeURI(abs);
  }

  // Turn a diff2html file name into a link that opens the file (editor/GitHub).
  function linkifyFileName(fw, path) {
    const url = fileURL(path);
    if (!url) return;
    const nameEl = fw.querySelector('.d2h-file-name');
    if (!nameEl || nameEl.querySelector('a.saga-file-link')) return;
    const a = document.createElement('a');
    a.className = 'saga-file-link';
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.title = 'Open ' + path;
    a.textContent = nameEl.textContent;
    nameEl.textContent = '';
    nameEl.appendChild(a);
  }

  // After a chapter's diff is drawn, make its lines and files commentable.
  function wireComments(container) {
    container.querySelectorAll('.d2h-file-wrapper').forEach((fw) => {
      const nameEl = fw.querySelector('.d2h-file-name');
      const path = nameEl ? nameEl.textContent.trim() : '';
      if (!path) return;
      linkifyFileName(fw, path);
      wireFileComment(fw, path);
      fw.querySelectorAll('tr').forEach((tr) => {
        const lnCell = tr.querySelector('td.d2h-code-linenumber');
        if (!lnCell) return;
        const anchor = lineAnchor(tr);
        if (!anchor) return;
        lnCell.classList.add('saga-linenum');
        lnCell.title = 'Comment on this line';
        lnCell.addEventListener('click', () => insertComposerRow(tr, path, anchor.line, anchor.side));
        if (liveInline(path, anchor.line, anchor.side).length) {
          insertComposerRow(tr, path, anchor.line, anchor.side);
        }
      });
    });
  }

  // --- entry ----------------------------------------------------------

  function show() {
    chapters = data.chapters || [];
    const fileState = parseEmbedded() ||
      {schema: 1, sagaId: '', updatedAt: 0, overall: null, file: [], inline: []};
    sagaId = fileState.sagaId || readSlug;
    env = SagaMerge.mergeEnvelope(fileState, loadBuffer(), sagaId);
    // A merge may have pulled in a newer buffer than the file — persist it.
    saveBuffer();
    initTheme();
    renderHead();
    renderVerdict(data.verdict, data.stats);
    renderTOC();
    detectMode();
  }

  // --- header (title, summary, provenance) ----------------------------

  function renderHead() {
    if (data.title) $('saga-title').textContent = data.title;
    const sum = $('saga-summary');
    if (sum && data.summary) { sum.textContent = data.summary; sum.hidden = false; }
    const meta = $('saga-meta');
    if (meta) {
      const parts = [];
      if (data.commit_sha) parts.push(data.commit_sha.slice(0, 7));
      const rel = relativeTime(data.generated_at);
      if (rel) parts.push('generated ' + rel);
      meta.textContent = parts.join(' · ');
    }
  }

  function relativeTime(iso) {
    if (!iso) return '';
    const then = new Date(iso).getTime();
    if (isNaN(then)) return '';
    const secs = Math.round((Date.now() - then) / 1000);
    if (secs < 60) return 'just now';
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800],
                   ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [name, size] of units) {
      const n = Math.floor(secs / size);
      if (n >= 1) return n + ' ' + name + (n === 1 ? '' : 's') + ' ago';
    }
    return 'just now';
  }

  // --- verdict line --------------------------------------------------

  function renderVerdict(v, stats) {
    if (!v) return;
    // Scope segments read neutral; attention flags echo the amber rail so a
    // reviewer can spot what needs a look. All text is generated (no user
    // content), so building innerHTML here is injection-safe.
    const seg = [{ t: v.chapters + (v.chapters === 1 ? ' chapter' : ' chapters') }];
    if (stats && stats.files) seg.push({ t: stats.files + (stats.files === 1 ? ' file' : ' files') });
    if (stats && (stats.added || stats.removed)) {
      seg.push({ html: '<span class="saga-add">+' + (stats.added || 0) + '</span> ' +
                       '<span class="saga-del">−' + (stats.removed || 0) + '</span>' });
    }
    if (v.deviations > 0) seg.push({ t: v.deviations + (v.deviations === 1 ? ' differs from plan' : ' differ from plan'), flag: true });
    if (v.low_confidence > 0) seg.push({ t: v.low_confidence + (v.low_confidence === 1 ? ' needs a closer look' : ' need a closer look'), flag: true });
    $('saga-verdict').innerHTML = seg
      .map((s) => (s.html ? s.html : s.flag ? '<span class="saga-flag">' + s.t + '</span>' : s.t))
      .join(' · ');
    // Two-tier status rail: amber when anything is flagged, else green.
    const rail = $('saga-rail');
    if (rail) {
      rail.classList.remove('saga-rail-ok', 'saga-rail-attn');
      if (v.deviations > 0 || v.low_confidence > 0) rail.classList.add('saga-rail-attn');
      else rail.classList.add('saga-rail-ok');
    }
  }

  // --- table of contents ---------------------------------------------

  function badges(ch, read) {
    const out = [];
    if (ch.plan_step) out.push('<span class="saga-badge saga-plan">' + esc(ch.plan_step) + '</span>');
    if (ch.deviation) out.push('<span class="saga-badge saga-dev">Differs from plan</span>');
    if (ch.confidence === 'low') out.push('<span class="saga-badge saga-low">Needs a closer look</span>');
    if (ch.qa) out.push('<span class="saga-badge saga-qa">⚠ QA</span>');
    if (read) out.push('<span class="saga-badge saga-read">✓ Read</span>');
    return out.join('');
  }

  function renderTOC() {
    const toc = $('saga-toc');
    $('saga-reader').hidden = true;
    toc.hidden = false;
    const rd = readSet();
    const bannerText = 'Drafting in this browser only — open with ' +
      '<code>saga serve ./saga.html</code> to save into the file and publish to GitHub.';
    let html =
      '<div class="saga-review">' +
      '<h2 class="saga-toc-title">Review</h2>' +
      '<div id="saga-static-banner" class="saga-banner" hidden>' + bannerText + '</div>' +
      '<textarea id="saga-overall" class="saga-cmt-input saga-overall" placeholder="Overall review comment…"></textarea>' +
      '<div class="saga-review-actions">' +
      '<span class="saga-cmt-count" id="saga-cmt-count"></span>' +
      '<span class="saga-status-pill" id="saga-status"></span>' +
      '<button class="saga-btn" id="saga-export" data-label="Copy for agent" hidden>Copy for agent</button>' +
      '<button class="saga-btn saga-btn-primary" id="saga-publish" hidden>Publish to GitHub</button>' +
      '</div>' +
      '</div>' +
      '<h2 class="saga-toc-title">Chapters</h2>';
    chapters.forEach((ch, i) => {
      html +=
        '<button class="saga-toc-item" data-i="' + i + '">' +
        '<div class="saga-toc-head"><span class="saga-num">' + (i + 1) + '</span>' +
        '<span class="saga-toc-titletext">' + esc(ch.title) + '</span></div>' +
        '<div class="saga-toc-summary">' + esc(ch.summary) + '</div>' +
        '<div class="saga-badges">' + badges(ch, rd.has(ch.id)) + '</div>' +
        '</button>';
    });
    toc.innerHTML = html;
    toc.querySelectorAll('.saga-toc-item').forEach((b) => {
      b.addEventListener('click', () => openChapter(parseInt(b.dataset.i, 10)));
    });
    const overall = $('saga-overall');
    if (overall) {
      const o = liveOverall();
      overall.value = o ? o.body : '';
      overall.addEventListener('input', () => setOverall(overall.value.trim()));
    }
    const publish = $('saga-publish');
    if (publish) publish.addEventListener('click', () => publishGithub(publish));
    const exportBtn = $('saga-export');
    if (exportBtn) exportBtn.addEventListener('click', () => exportForAgent(exportBtn));
    updateCount();
    applyMode();
  }

  // --- chapter reader ------------------------------------------------

  function openChapter(i) {
    current = i;
    const ch = chapters[i];
    if (!ch) return;
    $('saga-toc').hidden = true;
    const reader = $('saga-reader');
    reader.hidden = false;

    const devBanner = ch.deviation
      ? '<div class="saga-deviation"><strong>Differs from the plan.</strong> ' + esc(ch.deviation) + ' Worth confirming this was intentional.</div>'
      : '';
    const lowBanner = ch.confidence === 'low'
      ? '<div class="saga-lowconf"><strong>Needs a closer look.</strong> The walkthrough is unsure here — read the diff rather than just trusting the summary.</div>'
      : '';
    const qaLine = ch.qa
      ? '<div class="saga-qanote">⚠ Manual QA: ' + esc(ch.qa) + '</div>'
      : '';

    // Class-based (not id-based) so the same nav can render at top and bottom.
    const navRow = (place) =>
      '<div class="saga-reader-nav ' + place + '">' +
      '<button class="saga-btn saga-toc-link">☰ Contents</button>' +
      '<span class="saga-progress">Chapter ' + (i + 1) + ' of ' + chapters.length + '</span>' +
      '<span class="saga-nav-spacer"></span>' +
      '<button class="saga-btn saga-prev"' + (i === 0 ? ' disabled' : '') + '>← Prev</button>' +
      '<button class="saga-btn saga-next"' + (i === chapters.length - 1 ? ' disabled' : '') + '>Next →</button>' +
      '</div>';

    reader.innerHTML =
      navRow('saga-nav-top') +
      '<div class="saga-chapter-head">' +
      '<span class="saga-num">' + (i + 1) + '</span>' +
      '<h2 class="saga-chapter-title">' + esc(ch.title) + '</h2>' +
      '<div class="saga-badges">' + badges(ch, isRead(ch.id)) + '</div>' +
      '</div>' +
      devBanner + lowBanner +
      '<div class="saga-narration">' + renderMarkdown(ch.narration) + '</div>' +
      qaLine +
      '<label class="saga-readmark"><input type="checkbox" id="saga-read-cb"' +
      (isRead(ch.id) ? ' checked' : '') + '> Mark chapter as read</label>' +
      '<div id="saga-chapter-diff" class="saga-chapter-diff"></div>' +
      navRow('saga-nav-bottom');

    reader.querySelectorAll('.saga-toc-link').forEach((b) => b.addEventListener('click', renderTOC));
    reader.querySelectorAll('.saga-prev').forEach((b) => b.addEventListener('click', () => openChapter(i - 1)));
    reader.querySelectorAll('.saga-next').forEach((b) => b.addEventListener('click', () => openChapter(i + 1)));
    $('saga-read-cb').addEventListener('change', (e) => setRead(ch.id, e.target.checked));

    renderChapterDiff(ch);
    window.scrollTo(0, 0);
  }

  function renderMarkdown(text) {
    if (window.marked && text) return window.marked.parse(text);
    return esc(text || '');
  }

  function renderChapterDiff(ch) {
    const container = $('saga-chapter-diff');
    if (!ch.diff || !ch.diff.trim()) {
      container.innerHTML = '<div class="saga-empty">No diff hunks in this chapter.</div>';
      return;
    }
    CONFIG.colorScheme = effectiveTheme();
    const ui = new Diff2HtmlUI(container, ch.diff, CONFIG);
    ui.draw();
    ui.highlightCode();
    wireComments(container);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', show);
  } else {
    show();
  }
})();

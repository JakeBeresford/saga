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

  // Move focus to a swapped-in view's heading so keyboard and screen-reader
  // users land in the new content instead of being dropped on <body>.
  function focusHeading(el) {
    if (!el) return;
    el.tabIndex = -1;
    el.focus({preventScroll: true});
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

  function emptyEnv() {
    return {schema: 1, sagaId: '', updatedAt: 0, overall: null, file: [], inline: []};
  }

  let sagaId = '';
  let env = emptyEnv();
  let dirtyOnLoad = false;    // the merged buffer differs from the file on disk

  // A content signature of an envelope's comments, order-independent, used to
  // tell whether a merge actually changed anything the file already holds.
  function envSignature(e) {
    const rec = (r) => JSON.stringify(
      [r.id, r.path, r.line, r.side, r.body, r.updatedAt, r.deletedAt]);
    const arr = (a) => (a || []).map(rec).sort().join('|');
    const o = e.overall;
    const overall = o ? JSON.stringify([o.body, o.updatedAt, o.deletedAt]) : 'null';
    return overall + '#' + arr(e.file) + '#' + arr(e.inline);
  }

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
  function updateRecord(rec, body) {
    rec.body = body;
    rec.updatedAt = now();
    onChange();
  }
  // Add or update the file comment for a path (callers guarantee a non-empty
  // body; deletion goes through deleteRecord).
  function setFileComment(path, body, anchor) {
    const rec = liveFileComment(path);
    if (rec) { rec.body = body; rec.updatedAt = now(); }
    else env.file.push({id: uid(), path: path, line: anchor.line, side: anchor.side,
                        body: body, updatedAt: now(), deletedAt: null});
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
  let pendingWrite = false;   // an edit is buffered but not yet confirmed in the file

  // Authoring is served-only. Over file:// (or any page that never reached the
  // server) the review is read-only: existing comments still render, but nothing
  // new can be drafted — a comment authored here could never leave the browser
  // (localStorage is origin-scoped, so `saga serve` can't see it), so we don't
  // let one be written in the first place.
  function canComment() { return mode === 'served'; }

  function setStatus(state) {
    const el = $('saga-status');
    if (!el) return;
    const labels = {
      saved: 'Saved', saving: 'Saving…',
      reconnecting: 'Reconnecting…', draft: 'Read-only (open with saga serve)',
    };
    el.textContent = labels[state] || '';
    el.dataset.state = state;
  }

  function scheduleSync() {
    pendingWrite = true;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(sync, 500);
  }

  function sync(opts) {
    clearTimeout(syncTimer);
    setStatus('saving');
    return fetch('/api/comments', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json', 'X-Saga-Token': token},
      body: JSON.stringify(env),
      // On tab-close we flush with keepalive so the browser completes the
      // request as the page unloads (sendBeacon can't set the token header).
      keepalive: !!(opts && opts.keepalive),
    }).then((res) => {
      if (!res.ok) throw new Error('PUT ' + res.status);
      pendingWrite = false;
      setStatus('saved');
    }).catch(() => { enterBuffering(); });
  }

  // Flush a debounced edit immediately when the tab is hidden or closing, so a
  // close inside the 500ms debounce window still reaches the file (the buffer
  // already holds it; this stops the file from silently lagging).
  function flushPending() {
    if (mode === 'served' && pendingWrite) sync({keepalive: true});
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
        if (s.sagaId !== sagaId) {
          // This origin now serves a different saga (a reused port). Retrying
          // can never recover our file, so stop polling and fall back to
          // buffer-only drafts instead of looping forever.
          clearInterval(reconnectTimer);
          reconnectTimer = null;
          mode = 'static';
          applyMode();
          notify('This address now serves a different saga; comments are ' +
                 'saved in this browser only.', true);
          return;
        }
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
      // Reconcile only when the merged buffer is actually newer than the file —
      // a plain open with no pending draft must not rewrite the file.
      if (dirtyOnLoad) sync();
    }).catch(() => {
      mode = 'static';
      applyMode();
    });
  }

  // Toggle the served-only controls and the static banner, and seed the pill.
  function applyModeControls() {
    const served = mode === 'served';
    const banner = $('saga-static-banner');
    if (banner) banner.hidden = served;
    const publish = $('saga-publish');
    const exportBtn = $('saga-export');
    if (publish) publish.hidden = !served;
    if (exportBtn) exportBtn.hidden = !served;
    setStatus(served ? 'saved' : 'draft');
  }

  // Apply the controls and, because the mode is settled asynchronously (a served
  // page renders as static until /api/session answers), re-render whichever view
  // is open so its comment affordances match the confirmed mode. The reader has
  // no such controls to seed, so it only needs the re-render.
  function applyMode() {
    applyModeControls();
    if (!$('saga-reader').hidden) openChapter(current);
    else if (!$('saga-review-view').hidden) openReview();
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

  // POST a publish mode and resolve with the parsed JSON, rejecting on a non-OK
  // response so both callers share one error path.
  function postPublish(mode) {
    return fetch('/api/publish', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Saga-Token': token},
      body: JSON.stringify({mode: mode}),
    }).then((res) => res.json().then((j) => {
      if (!res.ok) throw new Error(j.error || 'request failed');
      return j;
    }));
  }

  function publishGithub(btn) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Publishing…';
    postPublish('github')
      .then((j) => notify(j.summary || 'Created a pending review on GitHub.'))
      .catch((e) => notify('Publish failed: ' + e.message, true))
      .finally(() => { btn.textContent = label; btn.disabled = false; });
  }

  function exportForAgent(btn) {
    const label = btn.textContent;
    btn.disabled = true;
    postPublish('agent')
      .then((j) => copyText(JSON.stringify(j.comments, null, 2)))
      .then(() => {
        btn.textContent = 'Copied ✓';
        notify('Comments copied as JSON for a coding agent.');
        setTimeout(() => { btn.textContent = label; }, 1500);
      })
      .catch((e) => notify('Read failed: ' + e.message, true))
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
    for (const tr of fw.querySelectorAll('tr')) {
      const anchor = lineAnchor(tr);
      if (anchor) return anchor;
    }
    return {line: 1, side: 'RIGHT'};
  }

  // Render the comment thread for one line into its cell. The composer is only
  // shown when showComposer is true, so a line with saved comments displays them
  // on their own — clicking the line number again reveals the composer to add more.
  // A rendered comment: its (sanitized) markdown body plus edit and delete
  // buttons. Edit swaps the body in place for a prefilled composer; Save routes
  // the new text through onSave, Cancel restores the read view untouched.
  function commentItem(rec, delLabel, onDelete, onSave) {
    const item = document.createElement('div');

    function showView() {
      item.className = 'saga-cmt';
      item.innerHTML = '';
      const body = document.createElement('div');
      body.className = 'saga-cmt-body';
      body.innerHTML = renderMarkdown(rec.body);
      item.appendChild(body);
      // Read-only views (file://) show the comment without edit/delete controls.
      if (!canComment()) return;
      const edit = document.createElement('button');
      edit.className = 'saga-cmt-edit';
      edit.textContent = '✎';
      edit.title = 'Edit comment';
      edit.setAttribute('aria-label', 'Edit comment');
      edit.addEventListener('click', showEditor);
      const del = document.createElement('button');
      del.className = 'saga-cmt-del';
      del.textContent = '✕';
      del.title = delLabel;
      del.setAttribute('aria-label', delLabel);
      del.addEventListener('click', onDelete);
      item.appendChild(edit);
      item.appendChild(del);
    }

    // Edit turns this element into the composer itself (not a composer nested
    // inside the rendered-comment box), so the input matches the new-comment UI
    // exactly — same class, same full width, same position.
    function showEditor() {
      item.className = 'saga-cmt-composer';
      item.innerHTML = '';
      const ta = document.createElement('textarea');
      ta.className = 'saga-cmt-input';
      ta.value = rec.body;
      const save = document.createElement('button');
      save.className = 'saga-btn saga-cmt-save';
      save.textContent = 'Update';
      save.addEventListener('click', () => {
        const v = ta.value.trim();
        if (!v) return;
        onSave(v);
      });
      const cancel = document.createElement('button');
      cancel.className = 'saga-btn saga-cmt-cancel';
      cancel.textContent = 'Cancel';
      cancel.addEventListener('click', showView);
      item.appendChild(ta);
      item.appendChild(save);
      item.appendChild(cancel);
      ta.focus();
    }

    showView();
    return item;
  }

  function renderThread(td, path, line, side, row, showComposer) {
    td.innerHTML = '';
    liveInline(path, line, side).forEach((c) => {
      td.appendChild(commentItem(c, 'Delete comment', () => {
        deleteRecord(c);
        if (!liveInline(path, line, side).length) row.remove();
        else renderThread(td, path, line, side, row, false);
      }, (body) => {
        updateRecord(c, body);
        renderThread(td, path, line, side, row, false);
      }));
    });
    if (!showComposer || !canComment()) return null;
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
  // feedback an inline thread does — a saved note shows on its own with edit and
  // delete controls (no lingering composer), the composer appears only when no
  // note exists yet, and the header button reflects whether a comment exists.
  function wireFileComment(fw, path) {
    const header = fw.querySelector('.d2h-file-header');
    if (!header) return;
    // Read-only (file://): only surface the control when a saved note exists to
    // display — there is nothing to author.
    if (!canComment() && !liveFileComment(path)) return;
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
        // A saved note stands on its own — edit/delete in place, no composer
        // trailing below (that stray second editor was the file-comment bug).
        panel.appendChild(commentItem(rec, 'Delete file comment', () => {
          deleteRecord(rec);
          render();
          refreshBtn();
        }, (body) => {
          setFileComment(path, body, firstAnchor(fw));
          render();
          refreshBtn();
        }));
        return;
      }
      const composer = document.createElement('div');
      composer.className = 'saga-cmt-composer';
      const ta = document.createElement('textarea');
      ta.className = 'saga-cmt-input';
      ta.placeholder = 'Comment on the whole file…';
      const save = document.createElement('button');
      save.className = 'saga-btn';
      save.textContent = 'Save file comment';
      save.addEventListener('click', () => {
        const v = ta.value.trim();
        if (!v) return;
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
    const rel = newPath(path);
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

  // diff2html renders a rename as "old → new"; comments and links key off the
  // new path so a stored anchor matches the file GitHub knows.
  function newPath(display) { return display.split(' → ').pop().trim(); }

  // After a chapter's diff is drawn, make its lines and files commentable.
  function wireComments(container) {
    container.querySelectorAll('.d2h-file-wrapper').forEach((fw) => {
      const nameEl = fw.querySelector('.d2h-file-name');
      const path = nameEl ? newPath(nameEl.textContent) : '';
      if (!path) return;
      linkifyFileName(fw, path);
      wireFileComment(fw, path);
      fw.querySelectorAll('tr').forEach((tr) => {
        const lnCell = tr.querySelector('td.d2h-code-linenumber');
        if (!lnCell) return;
        const anchor = lineAnchor(tr);
        if (!anchor) return;
        // Only served pages can author, so only they make the gutter a comment
        // target; read-only pages still render any saved thread below.
        if (canComment()) {
          lnCell.classList.add('saga-linenum');
          lnCell.title = 'Comment on this line';
          // A line-number cell is a button for keyboard and screen-reader users,
          // not just a click target.
          lnCell.tabIndex = 0;
          lnCell.setAttribute('role', 'button');
          lnCell.setAttribute('aria-label', 'Comment on line ' + anchor.line);
          const openComposer = () => insertComposerRow(tr, path, anchor.line, anchor.side);
          lnCell.addEventListener('click', openComposer);
          lnCell.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openComposer(); }
          });
        }
        if (liveInline(path, anchor.line, anchor.side).length) {
          insertComposerRow(tr, path, anchor.line, anchor.side);
        }
      });
    });
  }

  // --- entry ----------------------------------------------------------

  function show() {
    chapters = data.chapters || [];
    const fileState = parseEmbedded() || emptyEnv();
    sagaId = fileState.sagaId || readSlug;
    env = SagaMerge.mergeEnvelope(fileState, loadBuffer(), sagaId);
    // A merge may have pulled in a newer buffer than the file — persist it, and
    // remember whether it differs so the on-load reconcile only writes if needed.
    dirtyOnLoad = envSignature(env) !== envSignature(fileState);
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
    $('saga-review-view').hidden = true;
    toc.hidden = false;
    const rd = readSet();
    let html = '<h2 class="saga-toc-title">Chapters</h2>';
    chapters.forEach((ch, i) => {
      html +=
        '<button class="saga-toc-item" data-i="' + i + '">' +
        '<div class="saga-toc-head"><span class="saga-num">' + (i + 1) + '</span>' +
        '<span class="saga-toc-titletext">' + esc(ch.title) + '</span></div>' +
        '<div class="saga-toc-summary">' + esc(ch.summary) + '</div>' +
        '<div class="saga-badges">' + badges(ch, rd.has(ch.id)) + '</div>' +
        '</button>';
    });
    html +=
      '<button class="saga-toc-item saga-wrapup-item" id="saga-wrapup-item">' +
      '<div class="saga-toc-head"><span class="saga-num">✓</span>' +
      '<span class="saga-toc-titletext">Wrap up →</span></div>' +
      '<div class="saga-toc-summary">Leave an overall comment, then publish or copy for an agent.</div>' +
      '</button>';
    toc.innerHTML = html;
    toc.querySelectorAll('.saga-toc-item[data-i]').forEach((b) => {
      b.addEventListener('click', () => openChapter(parseInt(b.dataset.i, 10)));
    });
    $('saga-wrapup-item').addEventListener('click', openReview);
    focusHeading(toc.querySelector('.saga-toc-title'));
  }

  // The wrap-up page: overall comment + publish/export controls. Reached from the
  // "Wrap up" nav button (any chapter) or the index card — no longer front-loaded
  // on the index. It owns the review element IDs, so it is the only live copy.
  function openReview() {
    $('saga-toc').hidden = true;
    $('saga-reader').hidden = true;
    const view = $('saga-review-view');
    view.hidden = false;
    const bannerText = 'Read-only — open with ' +
      '<code>saga serve ./saga.html</code> to leave comments and publish to GitHub.';
    const nav =
      '<div class="saga-reader-nav saga-nav-top">' +
      '<button class="saga-btn saga-toc-link">☰ Contents</button>' +
      '<span class="saga-progress">Wrap up</span>' +
      '<span class="saga-nav-spacer"></span>' +
      '<button class="saga-btn saga-prev"' + (chapters.length ? '' : ' disabled') + '>← Prev</button>' +
      '</div>';
    view.innerHTML =
      nav +
      '<div class="saga-review">' +
      '<h2 class="saga-toc-title">Wrap up</h2>' +
      '<div id="saga-static-banner" class="saga-banner" hidden>' + bannerText + '</div>' +
      '<textarea id="saga-overall" class="saga-cmt-input saga-overall" placeholder="Overall review comment…"></textarea>' +
      '<div class="saga-review-actions">' +
      '<span class="saga-cmt-count" id="saga-cmt-count"></span>' +
      '<span class="saga-status-pill" id="saga-status" role="status" aria-live="polite"></span>' +
      '<button class="saga-btn" id="saga-export" data-label="Copy for agent" hidden>Copy for agent</button>' +
      '<button class="saga-btn saga-btn-primary" id="saga-publish" hidden>Publish to GitHub</button>' +
      '</div>' +
      '</div>';
    view.querySelectorAll('.saga-toc-link').forEach((b) => b.addEventListener('click', renderTOC));
    view.querySelectorAll('.saga-prev').forEach((b) =>
      b.addEventListener('click', () => openChapter(chapters.length - 1)));
    const overall = $('saga-overall');
    if (overall) {
      const o = liveOverall();
      overall.value = o ? o.body : '';
      if (canComment()) {
        overall.addEventListener('input', () => setOverall(overall.value.trim()));
      } else {
        overall.readOnly = true;
        if (!o) overall.placeholder = 'Open with saga serve to leave a comment.';
      }
    }
    const publish = $('saga-publish');
    if (publish) publish.addEventListener('click', () => publishGithub(publish));
    const exportBtn = $('saga-export');
    if (exportBtn) exportBtn.addEventListener('click', () => exportForAgent(exportBtn));
    updateCount();
    applyModeControls();
    focusHeading(view.querySelector('.saga-toc-title'));
    window.scrollTo(0, 0);
  }

  // --- chapter reader ------------------------------------------------

  function openChapter(i) {
    current = i;
    const ch = chapters[i];
    if (!ch) return;
    const isLast = i === chapters.length - 1;
    $('saga-toc').hidden = true;
    $('saga-review-view').hidden = true;
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
      (isLast ? '' : '<button class="saga-btn saga-next">Next →</button>') +
      '<button class="saga-btn saga-wrapup">Wrap up →</button>' +
      '</div>';

    const roBanner = canComment() ? '' :
      '<div class="saga-banner">Read-only — open with ' +
      '<code>saga serve ./saga.html</code> to leave comments.</div>';

    reader.innerHTML =
      navRow('saga-nav-top') + roBanner +
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
    reader.querySelectorAll('.saga-wrapup').forEach((b) => b.addEventListener('click', openReview));
    $('saga-read-cb').addEventListener('change', (e) => setRead(ch.id, e.target.checked));

    renderChapterDiff(ch);
    focusHeading(reader.querySelector('.saga-chapter-title'));
    window.scrollTo(0, 0);
  }

  function renderMarkdown(text) {
    if (!text) return '';
    // Narration and comment bodies reach innerHTML, so marked's HTML must be
    // sanitized — narration is LLM output derived from the branch under review.
    // With DOMPurify unavailable, escape the raw text rather than emit unsafe HTML.
    if (window.marked && window.DOMPurify) {
      return window.DOMPurify.sanitize(window.marked.parse(text));
    }
    return esc(text);
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

  // Flush a pending debounced write before the tab is backgrounded or closed.
  // visibilitychange is the reliable signal on mobile; pagehide covers close.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushPending();
  });
  window.addEventListener('pagehide', flushPending);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', show);
  } else {
    show();
  }
})();

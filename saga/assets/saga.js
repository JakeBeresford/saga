// PR saga: chapter-based review of one change set.
//
// Standalone static build: the saga payload is inlined into the page as
// window.__sagaData (verdict + chapters, each with its reconstructed
// diff). This file renders it — a table of contents (the entry point) and a
// chapter reader — tracks per-chapter mark-as-read in localStorage, and lets a
// reviewer leave inline / per-file / overall comments (also drafted in
// localStorage) that Export downloads as a saga.comments.json sidecar. No
// server, no fetch.

(function () {
  const data = window.__sagaData || {chapters: [], verdict: null, branch: ''};
  const slug = data.branch || 'saga';
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

  function readKey() { return 'saga-read:' + slug; }
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

  // --- comments (localStorage draft, exported as a sidecar) ----------

  let comments = {files: {}, overall: ''};

  function commentsKey() { return 'saga-comments:' + slug; }
  function loadComments() {
    try {
      const c = JSON.parse(localStorage.getItem(commentsKey()) || '{}');
      if (!c.files || typeof c.files !== 'object') c.files = {};
      if (typeof c.overall !== 'string') c.overall = '';
      return c;
    } catch (e) { return {files: {}, overall: ''}; }
  }
  function persist() {
    localStorage.setItem(commentsKey(), JSON.stringify(comments));
    updateCount();
  }
  function fileEntry(path) {
    if (!comments.files[path]) comments.files[path] = {file_comment: '', file_anchor: null, inline: []};
    return comments.files[path];
  }
  function inlineFor(path, line, side) {
    const e = comments.files[path];
    if (!e || !e.inline) return [];
    return e.inline.filter((c) => c.line === line && c.side === side);
  }
  function commentCount() {
    let n = 0;
    Object.values(comments.files).forEach((f) => {
      n += (f.inline ? f.inline.length : 0);
      if (f.file_comment && f.file_comment.trim()) n += 1;
    });
    if (comments.overall && comments.overall.trim()) n += 1;
    return n;
  }
  function updateCount() {
    const el = $('saga-cmt-count');
    if (!el) return;
    const n = commentCount();
    el.textContent = n === 1 ? '1 comment' : n + ' comments';
  }

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

  // Render the comment thread + composer for one line into its cell.
  function renderThread(td, path, line, side, row) {
    td.innerHTML = '';
    inlineFor(path, line, side).forEach((c) => {
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
        const e = fileEntry(path);
        e.inline.splice(e.inline.indexOf(c), 1);
        persist();
        renderThread(td, path, line, side, row);
      });
      item.appendChild(body);
      item.appendChild(del);
      td.appendChild(item);
    });
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
      fileEntry(path).inline.push({line: line, side: side, body: v});
      persist();
      renderThread(td, path, line, side, row);
    });
    const cancel = document.createElement('button');
    cancel.className = 'saga-btn saga-cmt-cancel';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', () => {
      if (!inlineFor(path, line, side).length) row.remove();
      else ta.value = '';
    });
    composer.appendChild(ta);
    composer.appendChild(save);
    composer.appendChild(cancel);
    td.appendChild(composer);
    return ta;
  }

  function insertComposerRow(tr, path, line, side) {
    const next = tr.nextSibling;
    if (next && next.classList && next.classList.contains('saga-cmt-row') &&
        next.dataset.line === String(line) && next.dataset.side === side) {
      const ta = next.querySelector('.saga-cmt-input');
      if (ta) ta.focus();
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
    renderThread(td, path, line, side, row);
  }

  // Per-file comment control injected into a diff2html file header.
  function wireFileComment(fw, path) {
    const header = fw.querySelector('.d2h-file-header');
    if (!header) return;
    const btn = document.createElement('button');
    btn.className = 'saga-file-cmt-btn';
    btn.textContent = '💬 File comment';
    header.appendChild(btn);
    const panel = document.createElement('div');
    panel.className = 'saga-file-cmt-panel';
    const ta = document.createElement('textarea');
    ta.className = 'saga-cmt-input';
    ta.placeholder = 'Comment on the whole file…';
    const entry = comments.files[path];
    ta.value = entry && entry.file_comment ? entry.file_comment : '';
    const save = document.createElement('button');
    save.className = 'saga-btn';
    save.textContent = 'Save file comment';
    save.addEventListener('click', () => {
      const v = ta.value.trim();
      const e = fileEntry(path);
      e.file_comment = v;
      if (v && !e.file_anchor) e.file_anchor = firstAnchor(fw);
      if (!v) e.file_anchor = null;
      persist();
    });
    panel.appendChild(ta);
    panel.appendChild(save);
    panel.hidden = !(entry && entry.file_comment);
    header.parentNode.insertBefore(panel, header.nextSibling);
    btn.addEventListener('click', () => { panel.hidden = !panel.hidden; });
  }

  // After a chapter's diff is drawn, make its lines and files commentable.
  function wireComments(container) {
    container.querySelectorAll('.d2h-file-wrapper').forEach((fw) => {
      const nameEl = fw.querySelector('.d2h-file-name');
      const path = nameEl ? nameEl.textContent.trim() : '';
      if (!path) return;
      wireFileComment(fw, path);
      fw.querySelectorAll('tr').forEach((tr) => {
        const lnCell = tr.querySelector('td.d2h-code-linenumber');
        if (!lnCell) return;
        const anchor = lineAnchor(tr);
        if (!anchor) return;
        lnCell.classList.add('saga-linenum');
        lnCell.title = 'Comment on this line';
        lnCell.addEventListener('click', () => insertComposerRow(tr, path, anchor.line, anchor.side));
        if (inlineFor(path, anchor.line, anchor.side).length) {
          insertComposerRow(tr, path, anchor.line, anchor.side);
        }
      });
    });
  }

  function exportComments() {
    const files = {};
    Object.keys(comments.files).forEach((p) => {
      const e = comments.files[p];
      const inline = (e.inline || []).filter((c) => c.body && c.body.trim());
      const fc = (e.file_comment || '').trim();
      if (!inline.length && !fc) return;
      const out = {};
      if (fc) {
        out.file_comment = fc;
        if (e.file_anchor) out.file_anchor = e.file_anchor;
      }
      if (inline.length) out.inline = inline;
      files[p] = out;
    });
    const sidecar = {
      branch: data.branch || '',
      base: data.base || '',
      generated_at: new Date().toISOString(),
      overall: (comments.overall || '').trim(),
      files: files,
    };
    const blob = new Blob([JSON.stringify(sidecar, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'saga.comments.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // --- entry ----------------------------------------------------------

  function show() {
    chapters = data.chapters || [];
    comments = loadComments();
    initTheme();
    renderHead();
    renderVerdict(data.verdict, data.stats);
    renderTOC();
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
    let html =
      '<div class="saga-review">' +
      '<h2 class="saga-toc-title">Review</h2>' +
      '<textarea id="saga-overall" class="saga-cmt-input saga-overall" placeholder="Overall review comment…"></textarea>' +
      '<div class="saga-review-actions">' +
      '<span class="saga-cmt-count" id="saga-cmt-count"></span>' +
      '<button class="saga-btn" id="saga-export">Export comments</button>' +
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
      overall.value = comments.overall || '';
      overall.addEventListener('input', () => { comments.overall = overall.value; persist(); });
    }
    const exp = $('saga-export');
    if (exp) exp.addEventListener('click', exportComments);
    updateCount();
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

    const videoEl = ch.video
      ? '<video class="saga-chapter-video" src="' + esc(ch.video) + '" autoplay muted loop controls playsinline></video>'
      : '';

    reader.innerHTML =
      navRow('saga-nav-top') +
      '<div class="saga-chapter-head">' +
      '<span class="saga-num">' + (i + 1) + '</span>' +
      '<h2 class="saga-chapter-title">' + esc(ch.title) + '</h2>' +
      '<div class="saga-badges">' + badges(ch, isRead(ch.id)) + '</div>' +
      '</div>' +
      devBanner + lowBanner +
      videoEl +
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

// PR saga: chapter-based review of one change set.
//
// Standalone static build: the saga payload is inlined into the page as
// window.__sagaData (verdict + chapters, each with its reconstructed
// diff). This file only renders it — a table of contents (the entry point) and
// a chapter reader — and tracks per-chapter mark-as-read in localStorage. No
// server, no fetch, no commenting.

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

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // --- mark-as-read (localStorage) -----------------------------------

  function readKey() { return 'otto-saga-read:' + slug; }
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

  // --- entry ----------------------------------------------------------

  function show() {
    chapters = data.chapters || [];
    renderVerdict(data.verdict);
    renderTOC();
  }

  // --- verdict line --------------------------------------------------

  function renderVerdict(v) {
    if (!v) return;
    const parts = [
      v.chapters + (v.chapters === 1 ? ' chapter' : ' chapters'),
      v.deviations + (v.deviations === 1 ? ' deviation' : ' deviations'),
      v.low_confidence + ' low-confidence',
    ];
    if (v.qa && v.qa !== 'n/a') parts.push('QA ' + v.qa);
    $('saga-verdict').textContent = parts.join(' · ');
    // Shift the top status rail to the loudest state present:
    // deviation (red) > attention (amber) > clear (green).
    const rail = $('otto-rail');
    if (rail) {
      rail.classList.remove('otto-rail-ok', 'otto-rail-attn', 'otto-rail-dev');
      if (v.deviations > 0) rail.classList.add('otto-rail-dev');
      else if (v.low_confidence > 0 || v.qa === 'attention') rail.classList.add('otto-rail-attn');
      else rail.classList.add('otto-rail-ok');
    }
  }

  // --- table of contents ---------------------------------------------

  function badges(ch, read) {
    const out = [];
    if (ch.plan_step) out.push('<span class="saga-badge saga-plan">' + esc(ch.plan_step) + '</span>');
    if (ch.deviation) out.push('<span class="saga-badge saga-dev">⚠ Deviation</span>');
    if (ch.confidence === 'low') out.push('<span class="saga-badge saga-low">Low confidence</span>');
    if (ch.qa && ch.qa.status === 'green') out.push('<span class="saga-badge saga-qa">✓ QA</span>');
    if (read) out.push('<span class="saga-badge saga-read">✓ Read</span>');
    return out.join('');
  }

  function renderTOC() {
    const toc = $('saga-toc');
    $('saga-reader').hidden = true;
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
    toc.innerHTML = html;
    toc.querySelectorAll('.saga-toc-item').forEach((b) => {
      b.addEventListener('click', () => openChapter(parseInt(b.dataset.i, 10)));
    });
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
      ? '<div class="saga-deviation"><strong>⚠ Deviation from plan.</strong> ' + esc(ch.deviation) + '</div>'
      : '';
    const lowBanner = ch.confidence === 'low'
      ? '<div class="saga-lowconf">Low confidence — this chapter needs close review.</div>'
      : '';
    const qaLine = ch.qa && ch.qa.note
      ? '<div class="saga-qanote">' + (ch.qa.status === 'green' ? '✓ ' : '') + esc(ch.qa.note) + '</div>'
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
    const ui = new Diff2HtmlUI(container, ch.diff, CONFIG);
    ui.draw();
    ui.highlightCode();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', show);
  } else {
    show();
  }
})();

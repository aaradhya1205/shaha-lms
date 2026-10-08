// Small progressive enhancements shared by all pages. Everything still works without JS.
(function () {
  // Click anywhere on a table row to open it (links/inputs inside keep their own behaviour).
  document.addEventListener('click', e => {
    const row = e.target.closest('tr[data-href]');
    if (!row || e.target.closest('a, button, input, label, select')) return;
    if (e.metaKey || e.ctrlKey) window.open(row.dataset.href, '_blank');
    else location.href = row.dataset.href;
  });

  // Filter dropdowns apply immediately.
  document.querySelectorAll('[data-autosubmit]').forEach(el =>
    el.addEventListener('change', () => el.form && el.form.submit()));

  // Flash messages fade after a while.
  setTimeout(() => document.querySelectorAll('.flash.success').forEach(f => {
    f.style.transition = 'opacity .6s'; f.style.opacity = '0';
    setTimeout(() => f.remove(), 700);
  }), 6000);
})();

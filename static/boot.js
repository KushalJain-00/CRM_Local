/* Pre-paint boot for CRM Local: applies the stored theme + sidebar collapse
   before first paint (no flash of wrong theme). Density is initialized later
   by app.js (it needs the DOM). Runs before the stylesheet loads. */
(function () {
  try {
    var mode = localStorage.getItem('crm-theme-mode') || localStorage.getItem('crm-theme') || 'system';
    if (mode !== 'light' && mode !== 'dark') mode = 'system';
    var resolved = mode === 'system'
      ? (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : mode;
    document.documentElement.setAttribute('data-theme', resolved);
    document.documentElement.setAttribute('data-theme-mode', mode);
    if (localStorage.getItem('crm-sb-collapsed') === '1') {
      document.documentElement.classList.add('sb-collapsed');
    }
  } catch (e) { /* localStorage unavailable -> defaults */ }
})();

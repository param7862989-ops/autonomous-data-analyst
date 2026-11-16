// Applies the saved colour theme before the first paint, so dark-mode users never see a flash
// of the light theme. Loaded synchronously from <head>; kept in sync with src/lib/theme.ts.
(function () {
  try {
    var saved = window.localStorage.getItem("ada-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.dataset.theme = saved;
    }
  } catch {
    // Storage can be blocked (private mode, site-data settings): fall back to the OS setting.
  }
})();

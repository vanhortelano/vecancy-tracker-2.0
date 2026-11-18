/* api-base.js — finds the app server.
   Normally the Python server also serves this page, so the API is at the same address.
   In a preview tool (VS Code Live Server, Live Preview, ...) the page comes from a different port,
   so the local test server on this computer is used instead: http://127.0.0.1:8080
   (start it with START-LOCAL.bat or the VS Code task "Start Vacancy Tracker"). */
(function(){
  window.VT_API_BASE = "";
  if (window.VT_LOCAL_MODE === undefined && /^(localhost|127\.0\.0\.1)$/.test(location.hostname)){
    window.VT_API_BASE = "http://127.0.0.1:8080";
    document.write('<script src="' + window.VT_API_BASE + '/mode.js"><\/script>');
  }
})();

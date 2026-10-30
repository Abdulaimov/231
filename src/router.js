// Маршруты старого сайта (#prices, #smm, #rent, #p-said …). Встраивается в <head> при сборке:
// нужная «страница» показывается до первой отрисовки и переключается даже без основного скрипта.
// Где браузер умеет View Transitions, смена «страницы» идёт шторкой (оформление — в стилях).
(function (d, w) {
  var V = __VIEWS__, A = __ALIAS__, lastMain = null, mainY = null;
  w.__lastMain = null;
  function go(init) {
    var h = location.hash.slice(1);
    try { h = decodeURIComponent(h); } catch (e) {}
    if (A[h]) { h = A[h]; history.replaceState(null, "", "#" + h); }
    var v = V.indexOf(h) > -1 ? h : "main", prev = d.getAttribute("data-view"), back = lastMain;
    function apply() {
      d.setAttribute("data-view", v);
      if (!init && v !== prev) {
        if (v === "main" && mainY !== null && h === back) { w.scrollTo(0, mainY); }
        else {
          var el = v === "main" && h && h !== "top" && h.indexOf("case-") ? document.getElementById(h) : null;
          if (el) { el.scrollIntoView(); } else { w.scrollTo(0, 0); }
        }
      }
      if (!init) { w.dispatchEvent(new CustomEvent("route", { detail: { view: v, prev: prev, hash: h } })); }
    }
    if (!init && v !== prev && prev === "main") { mainY = w.scrollY; }
    if (v === "main" && h.indexOf("case-") !== 0) { lastMain = h; w.__lastMain = h; }
    if (!init && v !== prev && document.startViewTransition && !w.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      document.startViewTransition(apply);
    } else { apply(); }
  }
  d.classList.add("js");
  // интро с логотипом — один раз за сессию и только при заходе на главную
  try {
    if (!location.hash && !sessionStorage.getItem("231intro") && !w.matchMedia("(prefers-reduced-motion: reduce)").matches) { d.classList.add("intro-on"); }
  } catch (e) {}
  go(true);
  w.addEventListener("hashchange", function () { go(false); });
})(document.documentElement, window);

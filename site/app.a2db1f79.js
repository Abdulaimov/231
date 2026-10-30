/* 231inc — поведение сайта.
   Маршруты (#prices, #rent, #p-said …) переключает короткий скрипт в <head>, поэтому страницы работают и без этого файла.
   Здесь: интро, меню, лайтбокс, референсы и сборщик заявки, калькулятор аренды, копирование контактов, видео по нажатию,
   лента избранного, след из кадров, появление блоков, тон «комнаты», таймкод, бегущая строка, часы,
   курсор-подсказка, превью за курсором, наклон карточек и «магнитные» кнопки. */
(() => {
  "use strict";

  const doc = document.documentElement;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const DATA = JSON.parse($("#site-data").textContent);
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const canDialog = typeof HTMLDialogElement === "function" && typeof HTMLDialogElement.prototype.showModal === "function";
  const live = $("#live");
  const say = (text) => { live.textContent = ""; setTimeout(() => { live.textContent = text; }, 40); };
  const plainClick = (e) => !(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0);
  const extOf = (url) => ((url || "").match(/\.(avif|webp|jpg)(?:$|\?)/) || [])[1] || null;
  // какой формат браузер выбрал для фото на странице — им же грузим превью, ленту и соседние кадры
  const loadedFormat = () => extOf(($$("picture img").find((i) => i.currentSrc) || {}).currentSrc);
  const plural = (n, one, few, many) => {
    const a = n % 10;
    const b = n % 100;
    if (a === 1 && b !== 11) return one;
    if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
    return many;
  };
  const money = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const smallSrc = (m, fmt) => (!fmt || fmt === "jpg" ? `${m.base}-${m.jw[0]}.jpg` : `${m.base}-${m.ws[0]}.${fmt}`);
  doc.classList.add("app-on");
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
  }

  /* ---------- интро «231» (первый заход за сессию) ---------- */
  if (doc.classList.contains("intro-on")) {
    try { sessionStorage.setItem("231intro", "1"); } catch { /* приватный режим */ }
    const intro = $(".intro");
    const finish = () => { doc.style.setProperty("--intro", "0s"); intro?.remove(); };
    const skip = () => {
      if (doc.classList.contains("intro-skip") || !intro?.isConnected) return;
      doc.style.setProperty("--intro", "0s");
      doc.classList.add("intro-skip");
      setTimeout(() => intro?.remove(), 500);
    };
    intro?.addEventListener("click", skip);
    addEventListener("keydown", skip, { once: true });
    setTimeout(finish, 4200);
  }

  /* ---------- диалоги (в старых браузерах без <dialog> — простой оверлей) ---------- */
  let opener = null;
  function openDialog(dlg, from) {
    if (!dlg || dlg.open) return;
    opener = from || document.activeElement;
    if (canDialog) dlg.showModal(); else dlg.setAttribute("open", "");
    doc.classList.add("modal-open");
  }
  function closeDialog(dlg) {
    if (!dlg || !dlg.open) return;
    if (canDialog) dlg.close(); else { dlg.removeAttribute("open"); dlg.dispatchEvent(new Event("close")); }
  }
  $$("dialog").forEach((dlg) => dlg.addEventListener("close", () => {
    if (!$$("dialog").some((d) => d.open)) doc.classList.remove("modal-open");
    if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
    opener = null;
  }));
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-close]");
    if (btn) closeDialog(btn.closest("dialog"));
  });
  if (!canDialog) document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDialog($$("dialog").find((d) => d.open));
  });

  /* ---------- шапка: линия под шапкой и полоса прокрутки ---------- */
  const hdr = $("#hdr");
  const scrollTimeline = typeof CSS !== "undefined" && CSS.supports && CSS.supports("animation-timeline: scroll()");
  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      hdr.classList.toggle("scrolled", scrollY > 8);
      if (!scrollTimeline) {
        const max = doc.scrollHeight - innerHeight;
        hdr.style.setProperty("--p", max > 0 ? (scrollY / max).toFixed(4) : 0);
      }
      ticking = false;
    });
  };
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- меню на телефоне ---------- */
  const menu = $("#menu");
  $$(".menu-btn").forEach((btn) => btn.addEventListener("click", (e) => {
    if (!menu || !plainClick(e)) return;
    e.preventDefault();
    openDialog(menu, btn);
  }));
  menu?.addEventListener("click", (e) => {
    if (e.target.closest("a[href^='#']:not([data-req])")) { opener = null; closeDialog(menu); }
  });

  /* ---------- «страницы»: подсветка меню, заголовок вкладки, фокус, «Назад» ---------- */
  const baseTitle = document.title;
  const viewHeading = (view) => (view === "main" ? null : document.getElementById(view)?.querySelector("h1"));
  let measureStrip = null;
  function markNav(view) {
    $$("[data-nav]").forEach((a) => {
      const on = view !== "main" && a.dataset.nav.split("|").some((k) => k && (k.endsWith("-") ? view.startsWith(k) : view === k));
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  function onRoute(view, prev, hash, init) {
    markNav(view);
    const h1 = viewHeading(view);
    document.title = h1 ? `${h1.textContent.trim()} — 231inc` : baseTitle;
    if (!init && h1 && view !== prev) h1.focus({ preventScroll: true });
    if (hash.startsWith("case-")) openCase(hash.slice(5));
    else if (caseDlg?.open) closeDialog(caseDlg);
    if (view === "main" && measureStrip) measureStrip();
  }
  addEventListener("route", (e) => onRoute(e.detail.view, e.detail.prev, e.detail.hash, false));

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-back]");
    if (!a || !plainClick(e)) return;
    const last = window.__lastMain;
    if (last === null || last === undefined) return; // пришли сразу на эту страницу — обычная ссылка
    e.preventDefault();
    if (last) location.hash = "#" + last;
    else {
      history.pushState(null, "", location.pathname + location.search);
      dispatchEvent(new HashChangeEvent("hashchange"));
    }
  });

  /* ---------- референсы: понравившиеся кадры (хранятся только в этом браузере) ---------- */
  const REF_KEY = "231refs";
  let refs = [];
  try {
    const saved = JSON.parse(localStorage.getItem(REF_KEY) || "[]");
    refs = Array.isArray(saved) ? saved.filter((r) => DATA.media[r]) : [];
  } catch { refs = []; }
  const saveRefs = () => { try { localStorage.setItem(REF_KEY, JSON.stringify(refs)); } catch { /* хранилище недоступно */ } };
  function refInfo(ref) {
    for (const p of DATA.people) {
      const items = DATA.galleries[p.id]?.items || [];
      const i = items.indexOf(ref);
      if (i > -1) return { who: p.name, n: i + 1, total: items.length };
    }
    const st = DATA.galleries.studio?.items || [];
    const j = st.indexOf(ref);
    return j > -1 ? { who: "Студия", n: j + 1, total: st.length } : { who: "", n: 0, total: 0 };
  }

  /* ---------- сборщик заявки: текст для WhatsApp или Telegram, отправляет сам человек ---------- */
  const req = $("#req");
  const form = $("[data-req-form]");
  let reqTried = false;
  function buildMessage() {
    if (!form) return { text: "", valid: false };
    const svc = $$("input[name=svc]:checked", form).map((i) => i.value);
    const note = form.note.value.trim();
    const lines = ["Здравствуйте! Пишу с сайта 231inc."];
    if (svc.length) lines.push(`Интересует: ${svc.join(", ")}.`);
    if (form.author.value) lines.push(`Автор: ${form.author.value}.`);
    if (form.date.value) lines.push(`Дата: ${new Date(form.date.value + "T12:00").toLocaleDateString("ru-RU")}.`);
    if (form.name.value.trim()) lines.push(`Меня зовут ${form.name.value.trim()}.`);
    if (note) lines.push(`Комментарий: ${note}`);
    if (refs.length) {
      lines.push("Референсы с сайта:");
      refs.forEach((r) => {
        const inf = refInfo(r);
        const full = DATA.media[r]?.alt || "";
        const alt = full.length > 70 ? `${full.slice(0, 70).replace(/\s+\S*$/, "")}…` : full;
        lines.push(`— ${inf.who}${inf.n ? `, кадр ${inf.n} из ${inf.total}` : ""}${alt ? ` (${alt})` : ""}`);
      });
    }
    if (DATA.url) lines.push(DATA.url);
    return { text: lines.join("\n"), valid: svc.length > 0 || refs.length > 0 || note.length > 0 };
  }
  function renderReq() {
    if (!form) return;
    $("[data-refs-list]", form).replaceChildren(...refs.map((r) => {
      const m = DATA.media[r];
      const li = document.createElement("li");
      const img = new Image();
      img.alt = m.alt || "";
      img.decoding = "async";
      img.loading = "lazy";
      img.src = m.type === "video" ? m.poster : smallSrc(m, loadedFormat());
      const rm = document.createElement("button");
      rm.type = "button";
      rm.dataset.ref = r;
      rm.setAttribute("aria-label", `Убрать из референсов: ${m.alt || "кадр"}`);
      rm.textContent = "×";
      li.append(img, rm);
      return li;
    }));
    $("[data-refs-empty]", form).hidden = refs.length > 0;
    const { text, valid } = buildMessage();
    $("[data-req-text]", form).textContent = text;
    $("[data-req-wa]", form).href = `${DATA.wa}?text=${encodeURIComponent(text)}`;
    $("[data-req-error]", form).hidden = !reqTried || valid;
  }
  function guard(e) {
    if (buildMessage().valid) return true;
    e.preventDefault();
    reqTried = true;
    renderReq();
    $("input[name=svc]", form)?.focus();
    return false;
  }
  if (form) {
    form.addEventListener("input", renderReq);
    form.addEventListener("change", renderReq);
    form.addEventListener("submit", (e) => e.preventDefault());
    $("[data-req-wa]", form).addEventListener("click", guard);
    $("[data-req-tg]", form).addEventListener("click", (e) => {
      if (!guard(e)) return;
      copyText(buildMessage().text).then((ok) => say(ok ? "Текст скопирован: вставьте его в чат Telegram" : "Скопируйте текст из поля «Сообщение»"));
    });
    $("[data-req-copy]", form).addEventListener("click", async (e) => {
      if (!guard(e)) return;
      const btn = e.currentTarget;
      const ok = await copyText(buildMessage().text);
      btn.textContent = ok ? "Скопировано" : "Не получилось — выделите текст выше";
      setTimeout(() => { btn.textContent = "Скопировать текст"; }, 2000);
    });
  }
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-req]");
    if (!t || !req || !plainClick(e)) return;
    e.preventDefault();
    if (menu?.open) { opener = null; closeDialog(menu); }
    reqTried = false;
    renderReq();
    openDialog(req, t);
  });

  /* ---------- лайтбокс: кадр «вылетает» из сетки, приближается кликом, сохраняется в референсы ---------- */
  const lb = $("#lb");
  const stage = $("#lb-stage");
  const cap = $("#lb-cap");
  const bar = $(".lb-progress i");
  const lbHeart = $("[data-lb-heart]");
  let list = [];
  let idx = 0;
  let label = "";
  let lastPointer = "mouse";

  function updateLbHeart() {
    if (!lbHeart || !list.length) return;
    const on = refs.includes(list[idx]);
    lbHeart.setAttribute("aria-pressed", String(on));
    $("[data-lb-heart-t]", lbHeart).textContent = on ? "В референсах" : "В референсы";
  }
  function syncRefs(added) {
    $$("[data-ref]").forEach((b) => b.setAttribute("aria-pressed", String(refs.includes(b.dataset.ref))));
    $$("[data-refs-count]").forEach((el) => { el.textContent = refs.length; });
    const pill = $(".refs-pill");
    if (pill) {
      pill.hidden = refs.length === 0;
      pill.dataset.n = refs.length;
      if (added) { pill.classList.remove("bump"); void pill.offsetWidth; pill.classList.add("bump"); }
    }
    updateLbHeart();
    renderReq();
  }
  function toggleRef(ref) {
    const on = !refs.includes(ref);
    refs = on ? [...refs, ref] : refs.filter((r) => r !== ref);
    saveRefs();
    syncRefs(on);
    say(on ? `Кадр сохранён в референсы. Всего: ${refs.length}` : `Кадр убран из референсов. Всего: ${refs.length}`);
  }
  const pop = (el) => { el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); };
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ref]");
    if (!b) return;
    e.preventDefault();
    toggleRef(b.dataset.ref);
    pop(b);
  });

  function fitWidth(m) {
    const vw = innerWidth - (innerWidth < 768 ? 32 : 208);
    const vh = innerHeight - (innerWidth < 768 ? 160 : 100);
    return Math.max(200, Math.round(Math.min(vw, vh * m.w / m.h)));
  }
  function bigSrcset(m, fmt) {
    return fmt === "jpg" || !fmt ? m.jw.map((w) => `${m.base}-${w}.jpg ${w}w`).join(", ")
      : m.ws.map((w) => `${m.base}-${w}.${fmt} ${w}w`).join(", ");
  }
  const widthOf = (url) => Number(((url || "").match(/-(\d+)\.(?:avif|webp|jpg)/) || [])[1] || 0);
  function mediaFor(ref, thumb) {
    const m = DATA.media[ref];
    if (!m) return document.createTextNode("");
    if (m.type === "video") {
      const v = document.createElement("video");
      Object.assign(v, { controls: true, playsInline: true, preload: "metadata", poster: m.poster, src: m.src });
      v.className = "lb-media";
      v.setAttribute("aria-label", m.alt);
      return v;
    }
    const img = document.createElement("img");
    Object.assign(img, { alt: m.alt, width: m.w, height: m.h, decoding: "async" });
    img.className = "lb-media";
    img.style.backgroundColor = m.c;
    const fmt = extOf(thumb && thumb.currentSrc) || loadedFormat();
    const sizes = fitWidth(m) + "px";
    if (thumb && thumb.currentSrc) {
      // сразу показываем уже загруженный кадр из сетки, крупный подменяем, когда догрузится
      img.src = thumb.currentSrc;
      const hi = new Image();
      hi.decoding = "async";
      hi.sizes = sizes;
      hi.srcset = bigSrcset(m, fmt);
      hi.onload = () => {
        const big = hi.currentSrc || hi.src;
        if (img.isConnected && widthOf(big) > widthOf(img.currentSrc || img.src)) img.src = big;
      };
    } else {
      img.sizes = sizes;
      img.srcset = bigSrcset(m, fmt);
      img.src = `${m.base}-${m.jw[m.jw.length - 1]}.jpg`;
    }
    return img;
  }
  function preload(i) {
    const m = DATA.media[list[(i + list.length) % list.length]];
    if (!m || m.type === "video") return;
    const img = new Image();
    img.decoding = "async";
    img.sizes = fitWidth(m) + "px";
    img.srcset = bigSrcset(m, loadedFormat());
  }
  function show(i, dir, thumb) {
    stage.querySelector("video")?.pause();
    idx = (i + list.length) % list.length;
    const el = mediaFor(list[idx], thumb);
    if (dir && el.classList) el.classList.add(dir > 0 ? "slide-r" : "slide-l");
    stage.replaceChildren(el);
    cap.textContent = list.length > 1 ? `${label} · ${idx + 1} / ${list.length}` : label;
    lb.classList.toggle("lb-single", list.length < 2);
    if (bar) bar.style.transform = `scaleX(${(idx + 1) / list.length})`;
    updateLbHeart();
    const v = stage.querySelector("video");
    if (v) v.play().catch(() => {});
    if (list.length > 1) { preload(idx + 1); preload(idx - 1); }
  }
  function flipFrom(thumb) {
    const img = stage.querySelector("img.lb-media");
    if (!img) return;
    const a = thumb.getBoundingClientRect();
    requestAnimationFrame(() => {
      const b = img.getBoundingClientRect();
      if (!a.width || !b.width) return;
      // равномерный масштаб по ширине, центр по высоте: кадр не искажается, даже если превью было кадрировано
      const k = a.width / b.width;
      img.style.transform = `translate(${a.left - b.left}px,${a.top + a.height / 2 - b.height * k / 2 - b.top}px) scale(${k})`;
      img.getBoundingClientRect();
      img.style.transition = "transform .6s cubic-bezier(.2,.7,.2,1)";
      img.style.transform = "";
      img.addEventListener("transitionend", () => { img.style.transition = ""; }, { once: true });
    });
  }
  function openLb(gallery, i, from) {
    const g = DATA.galleries[gallery];
    if (!lb || !g || !g.items.length) return false;
    list = g.items;
    label = g.label;
    const thumb = from?.querySelector("img");
    show(i, 0, thumb);
    openDialog(lb, from);
    if (thumb && !reduceMotion) flipFrom(thumb);
    return true;
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-lb]");
    if (!a || !plainClick(e)) return;
    if (openLb(a.dataset.lb, Number(a.dataset.i) || 0, a)) e.preventDefault();
  });
  if (lb) {
    $(".lb-prev", lb).addEventListener("click", () => show(idx - 1, -1));
    $(".lb-next", lb).addEventListener("click", () => show(idx + 1, 1));
    lbHeart?.addEventListener("click", () => { toggleRef(list[idx]); pop(lbHeart); });
    lb.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); show(idx - 1, -1); }
      if (e.key === "ArrowRight") { e.preventDefault(); show(idx + 1, 1); }
    });
    // клик мышью по кадру — приблизить, движение мыши — рассмотреть детали
    const originAt = (img, e) => {
      const r = stage.getBoundingClientRect();
      img.style.transformOrigin = `${((e.clientX - r.left) / r.width * 100).toFixed(1)}% ${((e.clientY - r.top) / r.height * 100).toFixed(1)}%`;
    };
    stage.addEventListener("click", (e) => {
      const img = e.target.closest("img.lb-media");
      if (!img) { if (e.target === stage) closeDialog(lb); return; }
      if (lastPointer !== "mouse") return;
      if (img.classList.contains("zoomed")) { img.classList.replace("zoomed", "unzoom"); return; }
      originAt(img, e);
      img.classList.remove("unzoom");
      img.classList.add("zoomed");
      const m = DATA.media[list[idx]];
      if (m && !img.dataset.big) {
        img.dataset.big = "1";
        const fmt = loadedFormat();
        const hi = new Image();
        hi.decoding = "async";
        hi.src = !fmt || fmt === "jpg" ? `${m.base}-${m.jw[m.jw.length - 1]}.jpg` : `${m.base}-${m.ws[m.ws.length - 1]}.${fmt}`;
        hi.onload = () => { if (img.isConnected) img.src = hi.src; };
      }
    });
    stage.addEventListener("pointermove", (e) => {
      const img = stage.querySelector("img.lb-media.zoomed");
      if (img && e.pointerType === "mouse") originAt(img, e);
    });
    // свайп пальцем: влево — следующий кадр, вправо — предыдущий
    let sx = null;
    let sy = 0;
    stage.addEventListener("pointerdown", (e) => {
      lastPointer = e.pointerType;
      if (e.pointerType !== "mouse" && e.isPrimary) { sx = e.clientX; sy = e.clientY; }
    });
    stage.addEventListener("pointerup", (e) => {
      if (sx === null) return;
      const dx = e.clientX - sx;
      const dy = e.clientY - sy;
      sx = null;
      if (list.length > 1 && Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.4) show(idx + (dx < 0 ? 1 : -1), dx < 0 ? 1 : -1);
    });
    stage.addEventListener("pointercancel", () => { sx = null; });
    lb.addEventListener("close", () => {
      stage.querySelector("video")?.pause();
      stage.replaceChildren();
    });
  }

  /* ---------- видео по нажатию: файл грузится только после клика ---------- */
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-video]");
    if (!a || !plainClick(e)) return;
    const m = DATA.media[a.dataset.video];
    if (!m) return;
    e.preventDefault();
    const v = document.createElement("video");
    Object.assign(v, { controls: true, playsInline: true, preload: "auto", poster: m.poster, src: m.src });
    v.setAttribute("aria-label", m.alt);
    a.closest(".ph-frame").append(v);
    a.hidden = true;
    v.focus({ preventScroll: true });
    v.play().catch(() => {});
  });

  /* ---------- копирование телефона и почты ---------- */
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const src = document.getElementById(btn.dataset.copy);
    if (!src) return;
    const text = src.textContent.trim();
    btn.dataset.label = btn.dataset.label || btn.textContent;
    if (await copyText(text)) {
      btn.textContent = "Скопировано";
      say(`Скопировано: ${text}`);
    } else {
      const range = document.createRange();
      range.selectNodeContents(src);
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      btn.textContent = "Выделено";
      say("Текст выделен, скопируйте его");
    }
    clearTimeout(btn._t);
    btn._t = setTimeout(() => { btn.textContent = btn.dataset.label; }, 1800);
  });

  /* ---------- калькулятор аренды ---------- */
  const calc = $("[data-calc]");
  if (calc) {
    calc.hidden = false;
    const r1 = Number(calc.dataset.r1);
    const r2 = Number(calc.dataset.r2) || r1;
    const from = Number(calc.dataset.r2from) || 2;
    const range = $("[data-range]", calc);
    const dateIn = $("[data-calc-date]", calc);
    const update = () => {
      const h = Number(range.value);
      const perHour = h >= from ? r2 : r1;
      const sum = perHour * h;
      const word = plural(h, "час", "часа", "часов");
      $("[data-hours]", calc).textContent = h;
      $("[data-hours-word]", calc).textContent = word;
      $("[data-total]", calc).textContent = money(sum);
      $("[data-rate]", calc).textContent = `· ${money(perHour)} сомони / час`;
      const day = dateIn.value ? `, ${new Date(dateIn.value + "T12:00").toLocaleDateString("ru-RU")}` : "";
      const text = `Здравствуйте! Хочу арендовать студию 231inc на ${h} ${word}${day}. По ставкам с сайта выходит ${money(sum)} сомони. Подскажите, есть ли свободное время?`;
      $("[data-calc-wa]", calc).href = `${DATA.wa}?text=${encodeURIComponent(text)}`;
    };
    range.addEventListener("input", update);
    dateIn.addEventListener("change", update);
    $$("[data-step]", calc).forEach((b) => b.addEventListener("click", () => {
      range.value = Math.min(Number(range.max), Math.max(Number(range.min), Number(range.value) + Number(b.dataset.step)));
      update();
    }));
    update();
  }

  /* ---------- проекты: фильтр и окно проекта (если проекты есть в content.json) ---------- */
  const caseDlg = $("#case-dlg");
  function openCase(id) {
    const tpl = document.getElementById("tpl-case-" + id);
    if (!caseDlg || !tpl) return;
    $("#case-in").replaceChildren(tpl.content.cloneNode(true));
    openDialog(caseDlg);
  }
  caseDlg?.addEventListener("close", () => {
    $$("video", caseDlg).forEach((v) => v.pause());
    if (location.hash.startsWith("#case-")) {
      const last = window.__lastMain;
      history.replaceState(null, "", location.pathname + location.search + (last ? "#" + last : ""));
    }
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".chips button");
    if (!b) return;
    $$("button", b.parentElement).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $$(".case").forEach((c) => { c.hidden = b.dataset.v !== "Все" && c.dataset.cat !== b.dataset.v; });
  });

  /* ---------- «расшифровка» подписей и счётчики цен при появлении ---------- */
  const GLYPHS = "0123456789/·—+";
  function scramble(el) {
    if (reduceMotion || el.children.length || el.dataset.scrambled) return;
    el.dataset.scrambled = "1";
    const final = el.textContent;
    const total = 20;
    let frame = 0;
    const step = () => {
      frame += 1;
      const open = Math.floor((frame / total) * final.length);
      let out = "";
      for (let k = 0; k < final.length; k += 1) {
        const ch = final[k];
        out += k < open || ch === " " || ch === "·" ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0];
      }
      el.textContent = frame < total ? out : final;
      if (frame < total) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function countUp(el) {
    if (reduceMotion || el.dataset.counted) return;
    const target = Number(el.textContent.replace(/\D/g, ""));
    if (!target) return;
    el.dataset.counted = "1";
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 900);
      el.textContent = money(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(step); else el.textContent = money(target);
    };
    requestAnimationFrame(step);
  }

  /* ---------- появление блоков и фото при прокрутке ---------- */
  if (!reduceMotion && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        en.target.classList.add("in");
        io.unobserve(en.target);
        if (en.target.matches(".kicker")) scramble(en.target);
      }
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    const vh = innerHeight;
    for (const el of $$("[data-rv]")) {
      const r = el.getBoundingClientRect();
      if (r.height && r.top < vh && r.bottom > 0) el.classList.add("in"); // уже на экране — без анимации
      else io.observe(el);
    }
    doc.classList.add("rv-on");
    const counter = new IntersectionObserver((entries) => {
      for (const en of entries) if (en.isIntersecting) { countUp(en.target); counter.unobserve(en.target); }
    }, { threshold: 0.6 });
    $$(".plan-price b, .rate b, .price-val b, .rates-inline b").forEach((el) => counter.observe(el));
  }

  /* ---------- тон «комнаты»: фон медленно меняется под автора или студию ---------- */
  if ("IntersectionObserver" in window) {
    const amb = new IntersectionObserver((entries) => {
      for (const en of entries) if (en.isIntersecting) doc.style.setProperty("--page", en.target.dataset.ambient);
    }, { rootMargin: "-48% 0px -48% 0px" });
    $$("[data-ambient]").forEach((el) => amb.observe(el));
  }

  /* ---------- таймкод в видоискателе (идёт, пока кадр на экране) ---------- */
  const tc = $("[data-tc]");
  if (tc && !reduceMotion && "IntersectionObserver" in window) {
    const pad = (n) => String(n).padStart(2, "0");
    const t0 = performance.now();
    let visible = false;
    let raf = 0;
    let last = -1;
    const tick = (now) => {
      const f = Math.floor((now - t0) / 1000 * 24);
      if (f !== last) {
        last = f;
        tc.textContent = `${pad(Math.floor(f / 86400))}:${pad(Math.floor(f / 1440) % 60)}:${pad(Math.floor(f / 24) % 60)}:${pad(f % 24)}`;
      }
      raf = visible ? requestAnimationFrame(tick) : 0;
    };
    new IntersectionObserver(([en]) => {
      visible = en.isIntersecting;
      if (visible && !raf) raf = requestAnimationFrame(tick);
    }).observe(tc.closest(".hero-frame"));
  }

  /* ---------- часы Душанбе ---------- */
  const clocks = $$("[data-clock]");
  if (clocks.length) {
    let fmt = null;
    try { fmt = new Intl.DateTimeFormat("ru-RU", { timeZone: "Asia/Dushanbe", hour: "2-digit", minute: "2-digit" }); } catch { fmt = null; }
    if (fmt) {
      const tickClock = () => { const t = fmt.format(new Date()); clocks.forEach((c) => { c.textContent = t; }); };
      tickClock();
      setInterval(tickClock, 15000);
    }
  }

  /* ---------- бегущая строка: сдвигается вместе с прокруткой ---------- */
  const track = $("[data-marquee]");
  if (track && !reduceMotion) {
    let half = 0;
    let raf = 0;
    const measure = () => { half = track.scrollWidth / 2; };
    const update = () => {
      raf = 0;
      if (half) track.style.setProperty("--mx", ((scrollY * 0.55) % half).toFixed(1));
    };
    measure();
    document.fonts?.ready.then(() => { measure(); update(); });
    addEventListener("resize", () => { measure(); update(); }, { passive: true });
    addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(update); }, { passive: true });
    update();
  }

  /* ---------- лента избранного: на компьютере едет вбок при прокрутке, на телефоне листается пальцем ---------- */
  const strip = $("[data-strip]");
  if (strip) {
    const film = $("[data-strip-track]", strip);
    const sbar = $("[data-strip-bar]", strip);
    const pin = $(".strip-pin", strip);
    const setBar = (p) => { if (sbar) sbar.style.transform = `scaleX(${Math.max(0.06, p).toFixed(3)})`; };
    if (matchMedia("(min-width: 960px)").matches && !reduceMotion) {
      strip.classList.add("strip-pinned");
      let travel = 0;
      let top = 0;
      let raf = 0;
      const hdrH = () => hdr.getBoundingClientRect().height;
      const update = () => {
        raf = 0;
        const p = travel ? Math.min(1, Math.max(0, (scrollY - (top - hdrH())) / travel)) : 0;
        film.style.transform = `translate3d(${(-p * travel).toFixed(1)}px,0,0)`;
        setBar(p);
      };
      measureStrip = () => {
        if (!strip.offsetParent) return;
        travel = Math.max(0, film.scrollWidth - film.clientWidth);
        strip.style.height = `${travel + pin.offsetHeight}px`;
        top = strip.getBoundingClientRect().top + scrollY;
        update();
      };
      measureStrip();
      document.fonts?.ready.then(measureStrip);
      addEventListener("load", measureStrip);
      addEventListener("resize", measureStrip, { passive: true });
      addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(update); }, { passive: true });
      // переход Tab к кадру за краем экрана прокручивает страницу так, чтобы кадр стал виден
      film.addEventListener("focusin", (e) => {
        const f = e.target.closest(".f35");
        if (!f || !travel) return;
        scrollTo(0, top - hdrH() + Math.min(travel, Math.max(0, f.offsetLeft - innerWidth * 0.3)));
      });
    } else {
      film.addEventListener("scroll", () => {
        const max = film.scrollWidth - film.clientWidth;
        setBar(max > 0 ? film.scrollLeft / max : 1);
      }, { passive: true });
    }
  }

  /* ---------- след из кадров за курсором или пальцем ---------- */
  const trail = $("[data-trail]");
  if (trail && !reduceMotion && DATA.trail?.length) {
    trail.classList.add("trail-on");
    const layer = $(".trail-layer", trail);
    const pool = DATA.trail.map((r) => DATA.media[r]).filter((m) => m && !m.type);
    let n = 0;
    let lx = null;
    let ly = null;
    let warmed = false;
    const warm = () => {
      if (warmed) return;
      warmed = true;
      const fmt = loadedFormat();
      pool.forEach((m) => { const im = new Image(); im.decoding = "async"; im.src = smallSrc(m, fmt); });
    };
    new IntersectionObserver(([en]) => { if (en.isIntersecting) warm(); }, { rootMargin: "400px 0px" }).observe(trail);
    const spawn = (x, y) => {
      const m = pool[n % pool.length];
      n += 1;
      const el = document.createElement("span");
      el.className = "trail-img";
      el.style.setProperty("--r", (m.w / m.h).toFixed(3));
      const img = new Image();
      img.alt = "";
      img.decoding = "async";
      img.src = smallSrc(m, loadedFormat());
      el.append(img);
      const box = trail.getBoundingClientRect();
      const w = Math.min(230, Math.max(130, innerWidth * 0.15));
      const h = w * m.h / m.w;
      el.style.transform = `translate3d(${(x - box.left - w / 2).toFixed(1)}px,${(y - box.top - h / 2).toFixed(1)}px,0) rotate(${(Math.random() * 16 - 8).toFixed(1)}deg)`;
      layer.append(el);
      setTimeout(() => {
        el.classList.add("out");
        el.addEventListener("animationend", () => el.remove(), { once: true });
      }, 700);
      while (layer.children.length > 14) layer.firstElementChild.remove();
    };
    trail.addEventListener("pointermove", (e) => {
      warm();
      if (lx === null) { lx = e.clientX; ly = e.clientY; return; }
      if (Math.hypot(e.clientX - lx, e.clientY - ly) > (e.pointerType === "mouse" ? 95 : 55)) {
        lx = e.clientX;
        ly = e.clientY;
        spawn(e.clientX, e.clientY);
      }
    }, { passive: true });
    trail.addEventListener("pointerleave", () => { lx = null; ly = null; });
    trail.addEventListener("pointerdown", (e) => {
      warm();
      if (e.pointerType !== "mouse") { lx = e.clientX; ly = e.clientY; spawn(e.clientX, e.clientY); }
    });
  }

  /* ---------- только мышь: параллакс обложки, курсор, превью, наклон, магниты, глитч ---------- */
  if (finePointer) {
    const follow = (el, k, onFrame) => {
      let x = 0;
      let y = 0;
      let tx = 0;
      let ty = 0;
      let raf = 0;
      const loop = () => {
        x += (tx - x) * k;
        y += (ty - y) * k;
        onFrame(x, y, tx - x);
        raf = Math.abs(tx - x) + Math.abs(ty - y) > 0.3 ? requestAnimationFrame(loop) : 0;
      };
      return {
        to(nx, ny, jump) {
          tx = nx; ty = ny;
          if (jump || reduceMotion) { x = nx; y = ny; onFrame(x, y, 0); return; }
          if (!raf) raf = requestAnimationFrame(loop);
        },
      };
    };

    // обложка чуть следует за мышью
    const heroEl = $("[data-hero]");
    if (heroEl && !reduceMotion) {
      let raf = 0;
      let px = 0;
      let py = 0;
      heroEl.addEventListener("pointermove", (e) => {
        const r = heroEl.getBoundingClientRect();
        px = ((e.clientX - r.left) / r.width) * 2 - 1;
        py = ((e.clientY - r.top) / r.height) * 2 - 1;
        if (!raf) raf = requestAnimationFrame(() => {
          raf = 0;
          heroEl.style.setProperty("--mx", px.toFixed(3));
          heroEl.style.setProperty("--my", py.toFixed(3));
        });
      });
      heroEl.addEventListener("pointerleave", () => { heroEl.style.setProperty("--mx", 0); heroEl.style.setProperty("--my", 0); });
    }

    // круг с подписью над фото и видео
    const cur = document.createElement("div");
    cur.className = "cursor";
    cur.setAttribute("aria-hidden", "true");
    const curLabel = document.createElement("span");
    cur.append(curLabel);
    document.body.append(cur);
    if (!reduceMotion) doc.classList.add("cursor-on");
    const curPos = follow(cur, 0.24, (x, y) => { cur.style.transform = `translate3d(${x}px,${y}px,0)`; });

    // превью работы автора за курсором (оглавление авторов, «Другие авторы»)
    const pic = document.createElement("div");
    pic.className = "hover-pic";
    pic.setAttribute("aria-hidden", "true");
    const picImg = document.createElement("img");
    picImg.alt = "";
    picImg.decoding = "async";
    pic.append(picImg);
    document.body.append(pic);
    const picPos = follow(pic, 0.16, (x, y, dx) => {
      const rot = reduceMotion ? 0 : Math.max(-9, Math.min(9, dx * 0.09));
      pic.style.transform = `translate3d(${x + 36}px,${y - pic.offsetHeight / 2}px,0) rotate(${rot}deg)`;
    });

    let mx = -100;
    let my = -100;
    let curOn = false;
    let pvRow = null;
    const probe = (target, jump) => {
      const c = target?.closest?.("[data-cursor]");
      const want = c && !reduceMotion ? c.dataset.cursor : "";
      if (want && curLabel.textContent !== want) curLabel.textContent = want;
      if (!!want !== curOn) {
        curOn = !!want;
        cur.classList.toggle("on", curOn);
        if (curOn) curPos.to(mx, my, true);
      }
      const row = target?.closest?.("[data-pv]") || null;
      if (row !== pvRow) {
        pvRow = row;
        if (row && row.dataset.pv) {
          const fmt = loadedFormat();
          picImg.src = !fmt || fmt === "jpg" ? `${row.dataset.pv}-960.jpg` : `${row.dataset.pv}-480.${fmt}`;
          picPos.to(mx, my, !pic.classList.contains("on") || jump);
          pic.classList.add("on");
        } else pic.classList.remove("on");
      }
    };
    addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse") return;
      mx = e.clientX;
      my = e.clientY;
      probe(e.target);
      if (curOn) curPos.to(mx, my);
      if (pvRow) picPos.to(mx, my);
    }, { passive: true });
    let probeRaf = 0;
    addEventListener("scroll", () => {
      if (probeRaf || mx < 0) return;
      probeRaf = requestAnimationFrame(() => { probeRaf = 0; probe(document.elementFromPoint(mx, my), true); });
    }, { passive: true });
    document.addEventListener("pointerleave", () => { probe(null); });
    addEventListener("route", () => probe(null));

    if (!reduceMotion) {
      // «магнитные» кнопки чуть тянутся к курсору
      $$("[data-magnet]").forEach((el) => {
        el.addEventListener("pointermove", (e) => {
          const r = el.getBoundingClientRect();
          el.style.transform = `translate3d(${(e.clientX - r.left - r.width / 2) * 0.28}px,${(e.clientY - r.top - r.height / 2) * 0.36}px,0)`;
        });
        el.addEventListener("pointerleave", () => { el.style.transform = ""; });
      });
      // карточки клиентов, тарифов и ставок наклоняются за курсором, по ним бежит блик
      $$(".client-card, .tariff, .rate").forEach((el) => {
        el.setAttribute("data-tilt", "");
        const glare = document.createElement("span");
        glare.className = "tilt-glare";
        glare.setAttribute("aria-hidden", "true");
        el.append(glare);
        el.addEventListener("pointermove", (e) => {
          const r = el.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width;
          const y = (e.clientY - r.top) / r.height;
          el.style.setProperty("--ry", `${((x - 0.5) * 10).toFixed(2)}deg`);
          el.style.setProperty("--rx", `${((0.5 - y) * 8).toFixed(2)}deg`);
          el.style.setProperty("--gx", `${(x * 100).toFixed(1)}%`);
          el.style.setProperty("--gy", `${(y * 100).toFixed(1)}%`);
          el.classList.add("tilting");
        });
        el.addEventListener("pointerleave", () => {
          el.style.removeProperty("--rx");
          el.style.removeProperty("--ry");
          el.classList.remove("tilting");
        });
      });
      // ролик ИИ-графики «сбоит» при наведении
      $$(".ph-video .ph-frame").forEach((frame) => {
        const fig = frame.closest(".ph-video");
        frame.addEventListener("pointerenter", () => {
          const src = $("picture img", frame)?.currentSrc;
          if (!src || $("video", frame)) return;
          if (!$(".gl", frame)) {
            ["gl-r", "gl-c"].forEach((cls) => {
              const span = document.createElement("span");
              span.className = `gl ${cls}`;
              const im = new Image();
              im.alt = "";
              im.src = src;
              span.append(im);
              frame.append(span);
            });
          }
          fig.classList.remove("glitching");
          void fig.offsetWidth;
          fig.classList.add("glitching");
        });
      });
    }
  }

  syncRefs(false);
  onRoute(doc.dataset.view || "main", null, decodeURIComponent(location.hash.slice(1)), true);
})();

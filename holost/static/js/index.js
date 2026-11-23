/* Головна сторінка: список усіх проектів. */
"use strict";

(() => {
  const { api, esc, toast, fail, ago, busy, $ } = H;
  let projects = [];
  const summaries = {};

  async function load() {
    try {
      const data = await api("/api/projects");
      projects = data.projects;
      fillStackFilter();
      render();
      loadSummaries();
    } catch (e) { fail(e); }
  }

  function fillStackFilter() {
    const sel = $("#stack-filter");
    const cur = sel.value;
    const all = [...new Set(projects.flatMap((p) => p.stack))].sort();
    sel.innerHTML = '<option value="">Усі технології</option>' +
      all.map((s) => `<option ${s === cur ? "selected" : ""}>${esc(s)}</option>`).join("");
  }

  function matches(p, q, stack) {
    if (stack && !p.stack.includes(stack)) return false;
    if (!q) return true;
    const hay = [p.name, p.short_desc, p.path, p.tags.join(" "), p.stack.join(" ")].join(" ").toLowerCase();
    return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
  }

  function gitBadges(s) {
    if (!s) return '<span class="muted">…</span>';
    if (!s.exists) return '<span class="badge badge-err">папку не знайдено</span>';
    const g = s.git || {};
    if (!g.is_repo) return '<span class="badge">без git</span>';
    let html = `<span class="badge" title="Гілка">⎇ ${esc(g.branch || "?")}</span>`;
    if (g.changed) html += ` <span class="badge badge-warn" title="Незакомічені зміни">✎ ${g.changed}</span>`;
    if (g.ahead) html += ` <span class="badge badge-accent" title="Не запушено">↑${g.ahead}</span>`;
    if (g.behind) html += ` <span class="badge badge-accent" title="Є нові коміти на сервері">↓${g.behind}</span>`;
    return html;
  }

  function render() {
    const q = $("#filter").value.trim();
    const stack = $("#stack-filter").value;
    const list = projects.filter((p) => matches(p, q, stack));
    $("#count").textContent = projects.length ? `${list.length} з ${projects.length}` : "";
    $("#empty").classList.toggle("hidden", projects.length > 0);
    $("#projects").innerHTML = list.map((p) => {
      const s = summaries[p.id];
      const last = s && s.git && s.git.last_commit;
      return `
      <a class="pcard ${p.exists ? "" : "missing"}" href="/projects/${p.id}">
        <button class="star ${p.favorite ? "on" : ""}" data-star="${p.id}" title="В обрані" type="button">⭐</button>
        <h3>${esc(p.name)}</h3>
        <div class="desc">${esc(p.short_desc) || '<span class="muted">Без опису</span>'}</div>
        <div class="badges">${p.stack.map((t) => `<span class="badge badge-accent">${esc(t)}</span>`).join("")}
          ${p.tags.map((t) => `<span class="badge">#${esc(t)}</span>`).join("")}</div>
        <div class="path mono" title="${esc(p.path)}">${esc(p.path)}</div>
        <div class="badges" data-summary="${p.id}">${gitBadges(s)}
          ${p.open_incidents ? `<span class="badge badge-err" title="Відкриті помилки">💥 ${p.open_incidents}</span>` : ""}</div>
        <div class="foot">
          <span>${last ? "Коміт " + esc(ago(last.date)) + ": " + esc(last.subject).slice(0, 60) : ""}</span>
          <span>${p.last_opened_at ? "відкр. " + esc(ago(p.last_opened_at)) : ""}</span>
        </div>
      </a>`;
    }).join("");
  }

  async function loadSummaries() {
    // Git-статус підтягуємо паралельно, але не більше 4 запитів одночасно.
    const queue = projects.filter((p) => p.exists).map((p) => p.id);
    projects.filter((p) => !p.exists).forEach((p) => { summaries[p.id] = { exists: false }; });
    const worker = async () => {
      while (queue.length) {
        const id = queue.shift();
        try { summaries[id] = await api(`/api/projects/${id}/summary`); } catch (e) { summaries[id] = { exists: true }; }
        render();
      }
    };
    await Promise.all([worker(), worker(), worker(), worker()]);
  }

  async function scan(btn) {
    await busy(btn, async () => {
      const res = await api("/api/scan", { method: "POST", body: {} });
      toast(`Знайдено проектів: ${res.found}. Нових: ${res.added.length}`, "ok");
      await load();
    });
  }

  function openAdd() {
    const dlg = $("#dlg-add");
    $("#form-add").reset();
    dlg.showModal();
  }

  async function openRoots() {
    try {
      const s = await api("/api/settings");
      const form = $("#form-roots");
      form.roots.value = s.roots.join("\n");
      $("#roots-suggestions").innerHTML = s.suggestions.length
        ? "Знайдені папки: " + s.suggestions.map((x) => `<a href="#" data-sugg="${esc(x)}">${esc(x)}</a>`).join(", ")
        : "";
      $("#dlg-roots").showModal();
    } catch (e) { fail(e); }
  }

  $("#form-add").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    try {
      const res = await api("/api/projects", { method: "POST", body: { path: form.path.value, name: form.name.value } });
      $("#dlg-add").close();
      location.href = `/projects/${res.id}`;
    } catch (e) {
      if (e.status === 409 && e.data && e.data.id) { location.href = `/projects/${e.data.id}`; return; }
      fail(e);
    }
  });

  $("#form-roots").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const res = await api("/api/settings", { method: "PUT", body: { roots: ev.target.roots.value } });
      if (res.missing.length) toast("Не знайдено папки: " + res.missing.join(", "), "error");
      $("#dlg-roots").close();
      await scan($("#btn-scan"));
    } catch (e) { fail(e); }
  });

  $("#roots-suggestions").addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-sugg]");
    if (!a) return;
    ev.preventDefault();
    const ta = $("#form-roots").roots;
    const lines = ta.value.split("\n").filter(Boolean);
    if (!lines.includes(a.dataset.sugg)) lines.push(a.dataset.sugg);
    ta.value = lines.join("\n");
  });

  $("#projects").addEventListener("click", async (ev) => {
    const star = ev.target.closest("[data-star]");
    if (!star) return;
    ev.preventDefault();
    const p = projects.find((x) => x.id === +star.dataset.star);
    try {
      await api(`/api/projects/${p.id}`, { method: "PUT", body: { favorite: !p.favorite } });
      p.favorite = !p.favorite;
      render();
    } catch (e) { fail(e); }
  });

  $("#btn-scan").addEventListener("click", (ev) => scan(ev.currentTarget));
  $("#btn-add").addEventListener("click", openAdd);
  $("#btn-roots").addEventListener("click", openRoots);
  $("#empty").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-action]");
    if (b) (b.dataset.action === "add" ? openAdd : openRoots)();
  });
  $("#filter").addEventListener("input", render);
  $("#stack-filter").addEventListener("change", render);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      ev.preventDefault();
      $("#filter").focus();
    }
  });

  load();
})();

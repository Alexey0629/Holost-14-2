/* Сторінка проекту: кнопки-вкладки з усіма інструментами. */
"use strict";

(() => {
  const { api, esc, toast, fail, size, date, ago, md, diff, busy, copy, $, $$ } = H;
  const PID = window.PROJECT_ID;
  const base = `/api/projects/${PID}`;
  const rawUrl = (path) => `/projects/${PID}/raw?path=${encodeURIComponent(path)}`;
  const q = (path) => encodeURIComponent(path || "");

  let project = null;
  const loaded = {};
  const tabs = {};
  let activeTab = null;

  // ================================================================ утиліти

  function joinPath(a, b) {
    const out = [];
    for (const p of [...(a ? a.split("/") : []), ...String(b || "").split("/")]) {
      if (p === "..") out.pop();
      else if (p && p !== ".") out.push(p);
    }
    return out.join("/");
  }
  const dirname = (p) => (p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");
  const loadingHtml = '<p class="muted">Завантаження…</p>';
  const emptyHtml = (text) => `<p class="muted">${esc(text)}</p>`;

  function fileIcon(e) {
    if (e.type === "dir") return e.ignored ? "📦" : "📁";
    if (e.image) return "🖼️";
    const ext = (e.name.split(".").pop() || "").toLowerCase();
    if (["py"].includes(ext)) return "🐍";
    if (["js", "ts", "jsx", "tsx", "mjs", "vue"].includes(ext)) return "📜";
    if (["md", "txt", "rst"].includes(ext)) return "📝";
    if (["json", "yml", "yaml", "toml", "ini", "cfg", "env"].includes(ext)) return "⚙️";
    if (["sql", "db", "sqlite", "sqlite3"].includes(ext)) return "🗃️";
    if (["html", "htm", "css", "scss"].includes(ext)) return "🎨";
    if (["log"].includes(ext)) return "📋";
    return "📄";
  }

  /** Діалог з полями. Повертає об'єкт значень або null. */
  function ask(title, fields) {
    return new Promise((resolve) => {
      const dlg = $("#dlg-prompt");
      $("#prompt-title").textContent = title;
      $("#prompt-body").innerHTML = fields.map((f) => {
        let input;
        if (f.type === "textarea") {
          input = `<textarea class="input mono" name="${f.name}" rows="${f.rows || 6}" placeholder="${esc(f.placeholder || "")}">${esc(f.value || "")}</textarea>`;
        } else if (f.type === "select") {
          input = `<select class="input" name="${f.name}">${f.options.map((o) => `<option ${o === f.value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
        } else {
          input = `<input class="input" name="${f.name}" value="${esc(f.value || "")}" placeholder="${esc(f.placeholder || "")}">`;
        }
        return `<label>${esc(f.label)}${input}</label>`;
      }).join("");
      const onClose = () => {
        dlg.removeEventListener("close", onClose);
        if (dlg.returnValue !== "ok") return resolve(null);
        const values = {};
        fields.forEach((f) => { values[f.name] = dlg.querySelector(`[name="${f.name}"]`).value; });
        resolve(values);
      };
      dlg.addEventListener("close", onClose);
      dlg.returnValue = "";
      dlg.showModal();
      const first = dlg.querySelector("input, textarea, select");
      if (first) { first.focus(); if (first.select) first.select(); }
    });
  }

  function invalidate(...names) { names.forEach((n) => { loaded[n] = false; }); }

  // ================================================================ вкладки

  function activate(name) {
    if (!tabs[name]) name = "folders";
    activeTab = name;
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
    if (!loaded[name]) {
      loaded[name] = true;
      Promise.resolve().then(() => tabs[name].load()).catch((e) => { loaded[name] = false; fail(e); });
    }
    if (tabs[name].shown) tabs[name].shown();
  }

  $("#tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-tab]");
    if (b) activate(b.dataset.tab);
  });
  document.addEventListener("click", (ev) => {
    const r = ev.target.closest("[data-reload]");
    if (r) { invalidate(r.dataset.reload); activate(r.dataset.reload); }
    const t = ev.target.closest("[data-md-toggle]");
    if (t) {
      const id = t.dataset.mdToggle;
      const ta = document.getElementById(id);
      const pv = document.getElementById(id + "-preview");
      const preview = pv.classList.contains("hidden");
      if (preview) pv.innerHTML = md(ta.value) || emptyHtml("Порожньо");
      pv.classList.toggle("hidden", !preview);
      ta.classList.toggle("hidden", preview);
      t.textContent = preview ? "✏️ Редагувати" : "👁 Перегляд";
    }
    const open = ev.target.closest("[data-open]");
    if (open) { ev.preventDefault(); openInEditor(open.dataset.open, +open.dataset.line || 0); }
  });

  function setTabCount(name, n) {
    const tab = $(`.tab[data-tab="${name}"]`);
    let c = tab.querySelector(".count");
    if (!n) { if (c) c.remove(); return; }
    if (!c) { c = document.createElement("span"); c.className = "count"; tab.appendChild(c); }
    c.textContent = n;
  }

  // ================================================================ проект

  async function loadProject() {
    project = await api(base);
    $("#p-name").textContent = project.name;
    $("#crumb-name").textContent = project.name;
    document.title = project.name + " · Holost";
    $("#p-short").textContent = project.short_desc || "";
    $("#p-path").textContent = project.path;
    $("#p-stack").innerHTML = project.stack.map((s) => `<span class="badge badge-accent">${esc(s)}</span>`).join("");
    $("#missing").classList.toggle("hidden", project.exists);
    return project;
  }

  async function loadHeaderGit() {
    try {
      const s = await api(`${base}/summary`);
      const g = (s && s.git) || {};
      let html = "";
      if (g.is_repo) {
        html = `<span class="badge">⎇ ${esc(g.branch)}</span>`;
        if (g.changed) html += `<span class="badge badge-warn">✎ ${g.changed} змін</span>`;
        if (g.ahead) html += `<span class="badge badge-accent">↑${g.ahead}</span>`;
        if (g.behind) html += `<span class="badge badge-accent">↓${g.behind}</span>`;
        setTabCount("tests", g.changed || 0);
      } else if (s.exists) {
        html = '<span class="badge">без git</span>';
      }
      $("#p-git").innerHTML = html;
    } catch (e) { /* не критично */ }
  }

  $("#p-path").addEventListener("click", () => copy(project.path));

  // ================================================================ 📁 Папки

  let folderPath = "";
  let folderAbs = "";

  tabs.folders = { load: () => openFolder(folderPath) };

  async function openFolder(path) {
    const data = await api(`${base}/files?path=${q(path)}`);
    folderPath = data.path;
    folderAbs = data.abs_path;
    $("#fold-abs").textContent = data.abs_path;
    const parts = folderPath ? folderPath.split("/") : [];
    let crumbs = `<a data-folder="">📁 ${esc(project.name)}</a>`;
    parts.forEach((p, i) => { crumbs += ` / <a data-folder="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</a>`; });
    $("#fold-crumbs").innerHTML = crumbs;
    const rows = [];
    if (folderPath) rows.push(`<tr data-path="${esc(dirname(folderPath))}" data-type="dir"><td>⬆️ ..</td><td></td><td></td><td></td></tr>`);
    data.entries.forEach((e) => {
      rows.push(`<tr data-path="${esc(e.path)}" data-type="${e.type}" data-image="${e.image ? 1 : ""}" class="${e.ignored ? "dim" : ""}">
        <td>${fileIcon(e)} ${esc(e.name)}${e.symlink ? ' <span class="badge">link</span>' : ""}${e.ignored ? ' <span class="muted small">(залежності/кеш)</span>' : ""}</td>
        <td class="num muted">${e.type === "file" ? size(e.size) : ""}</td>
        <td class="muted small">${esc(date(e.mtime))}</td>
        <td class="num"><button class="btn btn-sm" data-act="rename" title="Перейменувати">✏️</button>
          <button class="btn btn-sm btn-danger" data-act="delete" title="Видалити">🗑</button></td></tr>`);
    });
    if (!data.entries.length) rows.push('<tr><td colspan="4" class="muted">Порожня папка</td></tr>');
    $("#fold-table tbody").innerHTML = rows.join("");
  }

  $("#fold-crumbs").addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-folder]");
    if (a) openFolder(a.dataset.folder).catch(fail);
  });

  $("#fold-table").addEventListener("click", async (ev) => {
    const tr = ev.target.closest("tr[data-path]");
    if (!tr) return;
    const path = tr.dataset.path;
    const act = ev.target.closest("[data-act]");
    if (act) {
      ev.stopPropagation();
      if (act.dataset.act === "rename") await renamePath(path);
      if (act.dataset.act === "delete") await deletePath(path, tr.dataset.type);
      return openFolder(folderPath).catch(fail);
    }
    if (tr.dataset.type === "dir") return openFolder(path).catch(fail);
    if (tr.dataset.image) return showImage(path);
    openInEditor(path);
  });

  $("#fold-open").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    await api(`${base}/open-folder`, { method: "POST", body: { path: folderPath } });
    toast("Відкрито в провіднику", "ok", 1500);
  }));
  $("#fold-copy").addEventListener("click", () => copy(folderAbs));
  $("#fold-newdir").addEventListener("click", () => createItem("dir", folderPath).then(() => openFolder(folderPath)).catch(fail));
  $("#fold-newfile").addEventListener("click", () => createItem("file", folderPath).catch(fail));

  async function createItem(type, inDir) {
    const v = await ask(type === "dir" ? "Нова папка" : "Новий файл", [
      { name: "path", label: "Шлях відносно кореня проекту", value: inDir ? inDir + "/" : "", placeholder: type === "dir" ? "src/utils" : "src/utils/helpers.py" },
    ]);
    if (!v || !v.path.trim()) return;
    const res = await api(`${base}/file`, { method: "POST", body: { path: v.path.trim(), type } });
    toast(type === "dir" ? "Папку створено" : "Файл створено", "ok", 1500);
    invalidate("history", "structure");
    refreshTree();
    if (type === "file") openInEditor(res.path);
    return res;
  }

  async function renamePath(path) {
    const v = await ask("Перейменувати / перемістити", [{ name: "path", label: "Новий шлях", value: path }]);
    if (!v || !v.path.trim() || v.path.trim() === path) return null;
    try {
      const res = await api(`${base}/rename`, { method: "POST", body: { path, new_path: v.path.trim() } });
      toast("Перейменовано", "ok", 1500);
      invalidate("history", "structure");
      refreshTree();
      return res.path;
    } catch (e) { fail(e); return null; }
  }

  async function deletePath(path, type) {
    if (!confirm(`Видалити ${type === "dir" ? "папку з усім вмістом" : "файл"} «${path}»?`)) return false;
    try {
      await api(`${base}/file?path=${q(path)}`, { method: "DELETE" });
      toast("Видалено", "ok", 1500);
      invalidate("history", "structure");
      refreshTree();
      if (current && (current.path === path || current.path.startsWith(path + "/"))) closeEditor();
      return true;
    } catch (e) { fail(e); return false; }
  }

  function showImage(path) {
    $("#img-title").textContent = path;
    $("#img-full").src = rawUrl(path);
    $("#dlg-image").showModal();
  }

  // ================================================================ 📝 Опис

  tabs.about = {
    load() {
      $("#about-short").value = project.short_desc;
      $("#about-tags").value = project.tags;
      $("#about-full").value = project.full_desc;
      renderReadme();
    },
  };

  function renderReadme() {
    const box = $("#about-readme");
    if (!project.readme) {
      box.innerHTML = emptyHtml("README не знайдено. Натисніть «Редагувати», щоб створити README.md.");
      return;
    }
    const dir = dirname(project.readme.path);
    box.innerHTML = /\.md$/i.test(project.readme.path)
      ? md(project.readme.content, { image: (u) => rawUrl(joinPath(dir, u)) })
      : `<pre class="output">${esc(project.readme.content)}</pre>`;
  }

  $("#about-save").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    const body = { short_desc: $("#about-short").value, tags: $("#about-tags").value, full_desc: $("#about-full").value };
    await api(base, { method: "PUT", body });
    Object.assign(project, body);
    $("#p-short").textContent = project.short_desc;
    invalidate("history");
    toast("Опис збережено", "ok");
  }));

  $("#about-readme-edit").addEventListener("click", async () => {
    if (project.readme) return openInEditor(project.readme.path);
    try {
      await api(`${base}/file`, { method: "POST", body: { path: "README.md", content: `# ${project.name}\n\n${project.short_desc || ""}\n` } });
    } catch (e) { if (e.status !== 400) return fail(e); }
    project.readme = { path: "README.md", content: "" };
    openInEditor("README.md");
  });

  // ================================================================ 💻 Код

  let cm = null;
  let current = null;
  let savedContent = "";
  let dirty = false;

  const MODES = {
    py: "python", pyw: "python", js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript",
    ts: { name: "javascript", typescript: true }, tsx: { name: "javascript", typescript: true },
    json: { name: "javascript", json: true }, html: "htmlmixed", htm: "htmlmixed", vue: "htmlmixed", svelte: "htmlmixed",
    jinja: "jinja2", jinja2: "jinja2", j2: "jinja2", xml: "xml", svg: "xml", css: "css", scss: "text/x-scss",
    less: "text/x-less", sql: "text/x-sql", md: "markdown", markdown: "markdown", sh: "shell", bash: "shell", zsh: "shell",
    yml: "yaml", yaml: "yaml", go: "go", rs: "rust", php: "application/x-httpd-php", c: "text/x-csrc", h: "text/x-csrc",
    cpp: "text/x-c++src", cc: "text/x-c++src", hpp: "text/x-c++src", java: "text/x-java", cs: "text/x-csharp",
    kt: "text/x-kotlin", scala: "text/x-scala", toml: "toml", ini: "properties", cfg: "properties", env: "properties",
    properties: "properties", diff: "diff", patch: "diff",
  };
  const TWO_SPACES = new Set(["js", "mjs", "cjs", "jsx", "ts", "tsx", "json", "html", "htm", "vue", "css", "scss", "less", "yml", "yaml", "md", "jinja", "jinja2", "svelte"]);

  function modeFor(path) {
    const name = path.split("/").pop();
    if (/^Dockerfile/i.test(name)) return "dockerfile";
    if (/^\.env/.test(name)) return "properties";
    if (name === "Makefile") return "shell";
    return MODES[(name.split(".").pop() || "").toLowerCase()] || null;
  }

  const isDark = () => {
    const t = document.documentElement.getAttribute("data-theme");
    return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  };

  function initEditor() {
    const ta = $("#code-editor");
    if (window.CodeMirror) {
      cm = CodeMirror.fromTextArea(ta, {
        lineNumbers: true, matchBrackets: true, autoCloseBrackets: true, styleActiveLine: true,
        indentUnit: 4, tabSize: 4, indentWithTabs: false, readOnly: "nocursor",
        theme: isDark() ? "material-darker" : "default",
        extraKeys: {
          "Ctrl-S": () => save(), "Cmd-S": () => save(),
          "Ctrl-/": "toggleComment", "Cmd-/": "toggleComment",
          "Alt-G": "jumpToLine",
          Tab: (ed) => (ed.somethingSelected() ? ed.indentSelection("add")
            : ed.replaceSelection(ed.getOption("indentWithTabs") ? "\t" : " ".repeat(ed.getOption("indentUnit")), "end")),
          "Shift-Tab": (ed) => ed.indentSelection("subtract"),
        },
      });
      cm.on("change", () => setDirty(cm.getValue() !== savedContent));
      document.addEventListener("holost:theme", () => cm.setOption("theme", isDark() ? "material-darker" : "default"));
    } else {
      ta.disabled = true;
      ta.addEventListener("input", () => setDirty(ta.value !== savedContent));
      ta.addEventListener("keydown", (ev) => {
        if ((ev.ctrlKey || ev.metaKey) && ev.key === "s") { ev.preventDefault(); save(); }
      });
    }
  }

  const getVal = () => (cm ? cm.getValue() : $("#code-editor").value);

  function setVal(text, path) {
    if (cm) {
      const ext = (path.split(".").pop() || "").toLowerCase();
      const unit = TWO_SPACES.has(ext) ? 2 : 4;
      const usesTabs = /^\t/m.test(text) && !/^ {2,}\S/m.test(text);
      cm.setOption("mode", modeFor(path));
      cm.setOption("indentUnit", unit);
      cm.setOption("tabSize", usesTabs ? 4 : unit);
      cm.setOption("indentWithTabs", usesTabs);
      cm.setOption("readOnly", false);
      cm.setValue(text);
      cm.clearHistory();
    } else {
      const ta = $("#code-editor");
      ta.disabled = false;
      ta.value = text;
    }
  }

  function setDirty(v) {
    dirty = v;
    $("#code-dirty").classList.toggle("hidden", !v);
    $("#code-save").disabled = !current;
  }

  tabs.code = {
    load: () => refreshTree(),
    shown() { if (cm) setTimeout(() => cm.refresh(), 0); },
  };

  function treeItem(e) {
    return `<li class="${e.ignored ? "ignored" : ""}" data-path="${esc(e.path)}" data-type="${e.type}" data-image="${e.image ? 1 : ""}">
      <div class="node" title="${esc(e.path)}">${fileIcon(e)} ${esc(e.name)}</div>${e.type === "dir" ? '<ul class="hidden" data-loaded=""></ul>' : ""}</li>`;
  }

  async function loadTreeDir(ul, path) {
    const data = await api(`${base}/files?path=${q(path)}`);
    ul.innerHTML = data.entries.map(treeItem).join("") || '<li class="muted small">порожньо</li>';
    ul.dataset.loaded = "1";
  }

  let treeReady = null;

  function refreshTree() {
    treeReady = (async () => {
      const root = $("#code-tree");
      const open = $$("li[data-type=dir] > ul:not(.hidden)", root).map((ul) => ul.parentElement.dataset.path);
      await loadTreeDir(root, "").catch(fail);
      for (const p of open) await expandDir(p).catch(() => {});
      if (current) markActive(current.path);
    })();
    return treeReady;
  }

  function findLi(path) {
    return $$("#code-tree li[data-path]").find((li) => li.dataset.path === path) || null;
  }

  async function expandDir(path) {
    const li = findLi(path);
    if (!li) return;
    const ul = li.querySelector(":scope > ul");
    if (!ul.dataset.loaded) await loadTreeDir(ul, path);
    ul.classList.remove("hidden");
  }

  async function revealInTree(path) {
    await (treeReady || refreshTree());
    const parts = path.split("/");
    for (let i = 1; i < parts.length; i++) await expandDir(parts.slice(0, i).join("/"));
    markActive(path);
  }

  function markActive(path) {
    $$("#code-tree .node.active").forEach((n) => n.classList.remove("active"));
    const li = findLi(path);
    if (li) { li.querySelector(".node").classList.add("active"); li.scrollIntoView({ block: "nearest" }); }
  }

  $("#code-tree").addEventListener("click", async (ev) => {
    const node = ev.target.closest(".node");
    if (!node) return;
    const li = node.parentElement;
    if (li.dataset.type === "dir") {
      const ul = li.querySelector(":scope > ul");
      if (!ul.dataset.loaded) await loadTreeDir(ul, li.dataset.path).catch(fail);
      ul.classList.toggle("hidden");
    } else if (li.dataset.image) {
      showImage(li.dataset.path);
    } else {
      openFile(li.dataset.path);
    }
  });

  function openInEditor(path, line) {
    activate("code");
    return openFile(path, line);
  }

  async function openFile(path, line) {
    if (dirty && current && current.path !== path &&
        !confirm(`У файлі «${current.path}» є незбережені зміни. Відкрити інший файл без збереження?`)) return;
    let f;
    try {
      f = await api(`${base}/file?path=${q(path)}`);
    } catch (e) { return fail(e); }
    current = { path: f.path, mtime: f.mtime, encoding: f.encoding };
    savedContent = f.content;
    setVal(f.content, f.path);
    setDirty(false);
    $("#code-file").textContent = f.path;
    $("#code-info").textContent = [f.language, size(f.size), f.encoding !== "utf-8" ? f.encoding : "", f.newline === "\r\n" ? "CRLF" : ""].filter(Boolean).join(" · ");
    ["#code-rename", "#code-delete", "#code-save", "#code-history"].forEach((s) => { $(s).disabled = false; });
    if (cm) {
      setTimeout(() => {
        cm.refresh();
        if (line) {
          cm.setCursor({ line: line - 1, ch: 0 });
          cm.scrollIntoView({ line: line - 1, ch: 0 }, 200);
          const h = cm.addLineClass(line - 1, "background", "CodeMirror-activeline-background");
          setTimeout(() => cm.removeLineClass(h, "background", "CodeMirror-activeline-background"), 2500);
        }
        cm.focus();
      }, 0);
    }
    revealInTree(f.path).catch(() => {});
  }

  function closeEditor() {
    current = null;
    savedContent = "";
    setVal("", "x.txt");
    if (cm) cm.setOption("readOnly", "nocursor");
    setDirty(false);
    $("#code-file").textContent = "Оберіть файл зліва";
    $("#code-info").textContent = "";
    ["#code-rename", "#code-delete", "#code-save", "#code-history"].forEach((s) => { $(s).disabled = true; });
  }

  async function save(force) {
    if (!current) return;
    const content = getVal();
    try {
      const r = await api(`${base}/file`, {
        method: "PUT",
        body: { path: current.path, content, mtime: force ? null : current.mtime, encoding: current.encoding },
      });
      current.mtime = r.mtime;
      current.encoding = r.encoding;
      savedContent = content;
      setDirty(false);
      invalidate("history", "structure", "db", "api", "usage");
      loadHeaderGit();
      toast("Збережено: " + current.path, "ok", 1500);
    } catch (e) {
      if (e.status === 409 && confirm(e.message + "\n\nПерезаписати файл вашою версією?")) return save(true);
      if (e.status !== 409) fail(e);
    }
  }

  $("#code-save").addEventListener("click", () => save());
  $("#code-refresh").addEventListener("click", () => refreshTree());
  $("#code-newfile").addEventListener("click", () => createItem("file", current ? dirname(current.path) : "").catch(fail));
  $("#code-newdir").addEventListener("click", () => createItem("dir", current ? dirname(current.path) : "").catch(fail));
  $("#code-rename").addEventListener("click", async () => {
    if (!current) return;
    if (dirty && !confirm("Є незбережені зміни. Продовжити?")) return;
    const newPath = await renamePath(current.path);
    if (newPath) { dirty = false; openFile(newPath); }
  });
  $("#code-delete").addEventListener("click", async () => {
    if (current) await deletePath(current.path, "file");
  });
  $("#code-history").addEventListener("click", () => {
    if (current) { activate("history"); historyForFile(current.path); }
  });

  window.addEventListener("beforeunload", (ev) => {
    if (dirty) { ev.preventDefault(); ev.returnValue = ""; }
  });

  // ================================================================ 🗄 Структура БД

  tabs.db = { load: loadDb };

  function tablesHtml(tables, dbPath) {
    if (!tables.length) return emptyHtml("Таблиць немає");
    return `<div class="db-tables">${tables.map((t) => `
      <div class="db-table">
        <header><span ${dbPath ? `class="copy" data-db-table="${esc(t.name)}" data-db="${esc(dbPath)}" title="Показати дані"` : ""}>${t.kind === "view" ? "👁" : "▦"} ${esc(t.name)}</span>
          <span class="muted small">${t.rows != null ? t.rows + " рядк." : ""}</span></header>
        <ul>${t.columns.map((c) => {
          const fk = t.foreign_keys.find((f) => f.from === c.name);
          return `<li><span>${c.pk ? "🔑 " : ""}${esc(c.name)}${fk ? ` <span class="fk">→ ${esc(fk.table)}${fk.to ? "." + esc(fk.to) : ""}</span>` : ""}</span>
            <span class="t" title="${esc(c.type)}">${esc(c.type)}${c.notnull ? " NOT NULL" : ""}</span></li>`;
        }).join("")}</ul>
        ${t.indexes.length ? `<footer>Індекси: ${t.indexes.map((i) => `${esc(i.name)} (${i.columns.map(esc).join(", ")})${i.unique ? " unique" : ""}`).join("; ")}</footer>` : ""}
      </div>`).join("")}</div>`;
  }

  async function loadDb() {
    const box = $("#db-content");
    box.innerHTML = loadingHtml;
    const d = await api(`${base}/db`);
    let html = "";
    d.sqlite.forEach((db) => {
      const first = db.tables.find((t) => t.kind === "table");
      html += `<div class="card"><h3>🗃️ ${esc(db.path)} <span class="badge">SQLite</span>
          <span class="badge">${db.tables.length} табл.</span></h3>
        ${db.error ? `<div class="alert alert-error">${esc(db.error)}</div>` : tablesHtml(db.tables, db.path)}
        <details><summary>SQL-консоль (тільки читання)</summary>
          <div class="db-console" data-db="${esc(db.path)}">
            <textarea class="input mono" rows="3">${esc(first ? `SELECT * FROM "${first.name}" LIMIT 50` : "SELECT name FROM sqlite_master")}</textarea>
            <div class="row end"><button class="btn btn-primary btn-sm" type="button" data-db-run>▶ Виконати</button></div>
            <div class="result-table"></div>
          </div>
        </details></div>`;
    });
    d.sql_files.forEach((f) => {
      html += `<div class="card"><h3>📄 <a href="#" data-open="${esc(f.path)}">${esc(f.path)}</a> <span class="badge">SQL-схема</span></h3>${tablesHtml(f.tables)}</div>`;
    });
    if (d.models.length) {
      html += `<div class="card"><h3>🧩 ORM-моделі <span class="badge">${d.models.length}</span></h3><div class="db-tables">${d.models.map((m) => `
        <div class="db-table">
          <header><span>${esc(m.class)}</span><span class="muted small">${m.table ? "▦ " + esc(m.table) : ""}</span></header>
          <ul>${m.fields.map((f) => `<li><span>${f.pk ? "🔑 " : ""}${esc(f.name)}${f.fk ? ` <span class="fk">→ ${esc(f.fk)}</span>` : ""}</span><span class="t" title="${esc(f.type)}">${esc(f.type)}</span></li>`).join("")}
            ${m.relationships.map((r) => `<li><span>↔ ${esc(r.name)}</span><span class="t fk">${esc(r.target)}</span></li>`).join("")}</ul>
          <footer><a href="#" data-open="${esc(m.file)}" data-line="${m.line}">${esc(m.file)}:${m.line}</a></footer>
        </div>`).join("")}</div></div>`;
    }
    if (d.migrations.length) {
      html += `<div class="card"><h3>📜 Міграції</h3><div class="chips">${d.migrations.map((m) => `<span class="badge">${esc(m)}</span>`).join("")}</div></div>`;
    }
    box.innerHTML = html || `<div class="empty"><div class="empty-icon">🗄️</div>
      <p>Не знайдено SQLite-баз, *.sql-схем чи ORM-моделей.</p>
      <p class="small">Підтримуються: файли .db/.sqlite/.sqlite3, CREATE TABLE у *.sql, моделі SQLAlchemy / Flask-SQLAlchemy / Django / SQLModel.</p></div>`;
  }

  async function runDbQuery(consoleEl) {
    const sql = consoleEl.querySelector("textarea").value;
    const out = consoleEl.querySelector(".result-table");
    out.innerHTML = loadingHtml;
    try {
      const r = await api(`${base}/db/query`, { method: "POST", body: { path: consoleEl.dataset.db, sql } });
      out.innerHTML = r.columns.length
        ? `<table class="table"><thead><tr>${r.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
          <tbody>${r.rows.map((row) => `<tr>${row.map((v) => `<td>${v === null ? '<span class="muted">NULL</span>' : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>
          <p class="muted small">${r.rows.length} рядк.${r.truncated ? " (показано перші 200)" : ""}</p>`
        : emptyHtml("Запит виконано, рядків немає");
    } catch (e) { out.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`; }
  }

  $("#db-content").addEventListener("click", (ev) => {
    const run = ev.target.closest("[data-db-run]");
    if (run) return runDbQuery(run.closest(".db-console"));
    const t = ev.target.closest("[data-db-table]");
    if (t) {
      const c = $$(".db-console", $("#db-content")).find((x) => x.dataset.db === t.dataset.db);
      if (!c) return;
      c.closest("details").open = true;
      c.querySelector("textarea").value = `SELECT * FROM "${t.dataset.dbTable}" LIMIT 50`;
      runDbQuery(c);
    }
  });

  // ================================================================ 🧭 Використання

  tabs.usage = {
    async load() {
      $("#usage-notes").value = project.usage_notes;
      const box = $("#usage-auto");
      box.innerHTML = loadingHtml;
      const u = await api(`${base}/usage`);
      const cmdRow = (label, cmd) => cmd
        ? `<dt>${esc(label)}</dt><dd><code class="copy" data-copy="${esc(cmd)}" title="Скопіювати">${esc(cmd)}</code></dd>` : "";
      let html = `<div class="card"><h3>▶ Команди</h3><dl class="kv">
        ${cmdRow("Встановлення", u.commands.install)}
        ${cmdRow("Запуск", project.run_cmd || u.commands.run)}
        ${cmdRow("Тести", project.test_cmd || u.commands.test)}
        </dl>${!u.commands.install && !u.commands.run && !u.commands.test ? emptyHtml("Не вдалося визначити автоматично — вкажіть у «Налаштуваннях».") : ""}</div>`;
      if (u.entry_points.length) {
        html += `<div class="card"><h3>🚪 Точки входу</h3><div class="chips">${u.entry_points.map((e) => `<a href="#" class="badge" data-open="${esc(e)}">${esc(e)}</a>`).join("")}</div></div>`;
      }
      if (u.scripts.length) {
        html += `<div class="card"><h3>📜 Скрипти</h3><table class="table small">${u.scripts.map((s) => `
          <tr><td><code class="copy" data-copy="${esc(s.name)}">${esc(s.name)}</code></td><td class="mono muted">${esc(s.command)}</td></tr>`).join("")}</table></div>`;
      }
      const deps = Object.entries(u.dependencies);
      if (deps.length) {
        html += `<div class="card"><h3>📦 Залежності</h3>${deps.map(([k, list]) => `
          <h4>${esc(k)} <span class="badge">${list.length}</span></h4><div class="chips">${list.map((d) => `<span class="badge">${esc(d)}</span>`).join("")}</div>`).join("")}</div>`;
      }
      const envFiles = Object.entries(u.env_files);
      if (envFiles.length || u.env_used.length) {
        html += `<div class="card"><h3>🔐 Змінні оточення</h3>
          ${envFiles.map(([f, keys]) => `<h4>${esc(f)}</h4><div class="chips">${keys.map((k) => `<span class="badge">${esc(k)}</span>`).join("") || '<span class="muted">порожньо</span>'}</div>`).join("")}
          ${u.env_used.length ? `<h4>Використовуються в коді</h4><div class="chips">${u.env_used.map((k) => `<span class="badge badge-accent">${esc(k)}</span>`).join("")}</div>` : ""}
          <p class="muted small">Значення змінних не показуються.</p></div>`;
      }
      if (u.config_files.length || u.ci.length || u.docker_services.length) {
        html += `<div class="card"><h3>🧰 Конфігурація</h3><div class="chips">${u.config_files.map((f) => `<a href="#" class="badge" data-open="${esc(f)}">${esc(f)}</a>`).join("")}</div>
          ${u.ci.length ? `<h4>CI</h4><div class="chips">${u.ci.map((f) => `<a href="#" class="badge" data-open="${esc(f)}">${esc(f)}</a>`).join("")}</div>` : ""}
          ${u.docker_services.length ? `<h4>Docker-сервіси</h4><div class="chips">${u.docker_services.map((s) => `<span class="badge badge-accent">🐳 ${esc(s)}</span>`).join("")}</div>` : ""}</div>`;
      }
      box.innerHTML = html;
    },
  };

  $("#usage-auto").addEventListener("click", (ev) => {
    const c = ev.target.closest("[data-copy]");
    if (c) copy(c.dataset.copy);
  });

  $("#usage-save").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    const usage_notes = $("#usage-notes").value;
    await api(base, { method: "PUT", body: { usage_notes } });
    project.usage_notes = usage_notes;
    invalidate("history");
    toast("Нотатки збережено", "ok");
  }));

  // ================================================================ 🔌 API

  let endpoints = [];
  let savedRequests = [];
  let currentRequestId = null;

  tabs.api = {
    async load() {
      $("#api-base").value = project.api_base_url;
      await Promise.all([loadSavedRequests(), loadEndpoints()]);
    },
  };

  async function loadEndpoints() {
    const tbody = $("#api-endpoints tbody");
    tbody.innerHTML = `<tr><td>${loadingHtml}</td></tr>`;
    endpoints = (await api(`${base}/endpoints`)).endpoints;
    renderEndpoints();
  }

  function renderEndpoints() {
    const f = $("#api-filter").value.toLowerCase();
    const list = endpoints.filter((e) => !f || (e.path + " " + e.handler + " " + e.file + " " + e.methods.join(" ")).toLowerCase().includes(f));
    $("#api-endpoints tbody").innerHTML = list.map((e) => `
      <tr data-ep="${endpoints.indexOf(e)}">
        <td>${e.methods.map((m) => `<span class="method m-${esc(m)}">${esc(m)}</span>`).join(" ")}</td>
        <td class="mono">${esc(e.path)}</td>
        <td class="muted">${esc(e.handler)}</td>
        <td><a href="#" data-open="${esc(e.file)}" data-line="${e.line}" class="small">${esc(e.file)}:${e.line}</a></td>
      </tr>`).join("") || `<tr><td class="muted">Ендпоінтів не знайдено (Flask, FastAPI, Django, Express, Go, Spring).</td></tr>`;
  }

  $("#api-filter").addEventListener("input", renderEndpoints);
  $("#api-endpoints").addEventListener("click", (ev) => {
    if (ev.target.closest("[data-open]")) return;
    const tr = ev.target.closest("[data-ep]");
    if (!tr) return;
    const e = endpoints[+tr.dataset.ep];
    newRequest();
    const m = e.methods.find((x) => x !== "ANY" && x !== "WS") || "GET";
    $("#api-method").value = m;
    $("#api-url").value = e.path;
    $("#api-name").value = `${m} ${e.path}`;
    $("#api-url").focus();
  });

  async function loadSavedRequests() {
    savedRequests = (await api(`${base}/requests`)).requests;
    $("#api-saved").innerHTML = savedRequests.map((r) => `
      <li data-req="${r.id}" class="${r.id === currentRequestId ? "active" : ""}">
        <span><span class="method m-${esc(r.method)}">${esc(r.method)}</span> ${esc(r.name)}<br><span class="muted small mono">${esc(r.url)}</span></span>
        <button class="btn btn-sm btn-danger" data-req-del="${r.id}" title="Видалити">🗑</button></li>`).join("")
      || '<li class="static muted">Збережених запитів немає. Напишіть запит ліворуч і натисніть «Зберегти запит».</li>';
  }

  function newRequest() {
    currentRequestId = null;
    ["#api-url", "#api-headers", "#api-body", "#api-notes", "#api-name"].forEach((s) => { $(s).value = ""; });
    $("#api-method").value = "GET";
    $("#api-response").innerHTML = "";
    $$("#api-saved li").forEach((li) => li.classList.remove("active"));
  }

  $("#api-saved").addEventListener("click", async (ev) => {
    const del = ev.target.closest("[data-req-del]");
    if (del) {
      ev.stopPropagation();
      if (!confirm("Видалити збережений запит?")) return;
      await api(`${base}/requests/${del.dataset.reqDel}`, { method: "DELETE" }).catch(fail);
      if (+del.dataset.reqDel === currentRequestId) newRequest();
      return loadSavedRequests().catch(fail);
    }
    const li = ev.target.closest("[data-req]");
    if (!li) return;
    const r = savedRequests.find((x) => x.id === +li.dataset.req);
    currentRequestId = r.id;
    $("#api-method").value = r.method;
    $("#api-url").value = r.url;
    $("#api-headers").value = r.headers;
    $("#api-body").value = r.body;
    $("#api-notes").value = r.notes;
    $("#api-name").value = r.name;
    $("#api-response").innerHTML = "";
    $$("#api-saved li").forEach((x) => x.classList.toggle("active", x === li));
  });

  $("#api-new").addEventListener("click", newRequest);

  $("#api-save").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    const body = {
      name: $("#api-name").value.trim() || `${$("#api-method").value} ${$("#api-url").value}`,
      method: $("#api-method").value, url: $("#api-url").value, headers: $("#api-headers").value,
      body: $("#api-body").value, notes: $("#api-notes").value,
    };
    const r = currentRequestId
      ? await api(`${base}/requests/${currentRequestId}`, { method: "PUT", body })
      : await api(`${base}/requests`, { method: "POST", body });
    currentRequestId = r.id;
    $("#api-name").value = r.name;
    await loadSavedRequests();
    toast("Запит збережено", "ok", 1500);
  }));

  $("#api-base").addEventListener("change", async () => {
    const api_base_url = $("#api-base").value.trim();
    try {
      await api(base, { method: "PUT", body: { api_base_url } });
      project.api_base_url = api_base_url;
    } catch (e) { fail(e); }
  });

  $("#api-send").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    const out = $("#api-response");
    out.innerHTML = loadingHtml;
    try {
      const r = await api(`${base}/http`, {
        method: "POST",
        body: { method: $("#api-method").value, url: $("#api-url").value, headers: $("#api-headers").value,
          body: $("#api-body").value, base_url: $("#api-base").value.trim() },
      });
      let bodyText = r.body;
      try { bodyText = JSON.stringify(JSON.parse(r.body), null, 2); } catch (e) { /* не JSON */ }
      const cls = r.status < 300 ? "badge-ok" : r.status < 400 ? "badge-accent" : r.status < 500 ? "badge-warn" : "badge-err";
      out.innerHTML = `<div class="row"><span class="badge ${cls}">${r.status} ${esc(r.reason)}</span>
          <span class="muted small">${r.time_ms} мс · ${size(r.body.length)}${r.truncated ? " (обрізано)" : ""}</span>
          <span class="muted small mono grow">${esc(r.url)}</span></div>
        <details><summary>Заголовки відповіді</summary><pre class="output">${esc(Object.entries(r.headers).map(([k, v]) => `${k}: ${v}`).join("\n"))}</pre></details>
        <pre class="output" style="margin-top:.5rem">${esc(bodyText) || '<span class="muted">(порожнє тіло)</span>'}</pre>`;
    } catch (e) {
      out.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }));

  // ================================================================ 🔍 Пошук

  tabs.search = { load() {}, shown() { setTimeout(() => $("#search-q").focus(), 0); } };

  $("#search-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const box = $("#search-results");
    const params = new URLSearchParams({
      q: $("#search-q").value, glob: $("#search-glob").value,
      case: $("#search-case").checked ? "1" : "0", regex: $("#search-regex").checked ? "1" : "0",
    });
    box.innerHTML = loadingHtml;
    try {
      const r = await api(`${base}/search?${params}`);
      const groups = new Map();
      r.matches.forEach((m) => { if (!groups.has(m.path)) groups.set(m.path, []); groups.get(m.path).push(m); });
      let html = `<p class="muted small">Знайдено ${r.matches.length}${r.truncated ? "+" : ""} збігів у ${groups.size} файлах (переглянуто ${r.files_scanned}).</p>`;
      if (r.files.length) {
        html += `<div class="card"><h4>Файли з такою назвою</h4><div class="chips">${r.files.map((f) => `<a href="#" class="badge" data-open="${esc(f)}">${esc(f)}</a>`).join("")}</div></div>`;
      }
      groups.forEach((list, path) => {
        html += `<div class="search-file card"><div class="fname"><a href="#" data-open="${esc(path)}">${esc(path)}</a> <span class="badge">${list.length}</span></div>
          ${list.map((m) => {
            const t = m.text;
            const hl = m.end > m.start ? esc(t.slice(0, m.start)) + "<mark>" + esc(t.slice(m.start, m.end)) + "</mark>" + esc(t.slice(m.end)) : esc(t);
            return `<div class="search-line" data-open="${esc(path)}" data-line="${m.line}"><span class="ln">${m.line}</span><span>${hl}</span></div>`;
          }).join("")}</div>`;
      });
      box.innerHTML = html;
    } catch (e) { box.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`; }
  });

  // ================================================================ 🖼 Візуал

  let images = [];
  tabs.visual = { load: loadImages };

  async function loadImages() {
    $("#visual-grid").innerHTML = loadingHtml;
    images = (await api(`${base}/images`)).images;
    renderImages();
  }

  function renderImages() {
    const f = $("#visual-filter").value.toLowerCase();
    const list = images.filter((i) => !f || i.path.toLowerCase().includes(f));
    $("#visual-grid").innerHTML = list.map((i) => `
      <figure data-img="${esc(i.path)}" title="${esc(i.path)}">
        <div class="thumb"><img src="${rawUrl(i.path)}" alt="${esc(i.name)}" loading="lazy"></div>
        <figcaption>${esc(i.name)} <span class="muted">· ${size(i.size)}</span></figcaption>
      </figure>`).join("") || emptyHtml("Картинок у проекті не знайдено. Завантажте скріншоти, макети чи схеми вище.");
  }

  $("#visual-filter").addEventListener("input", renderImages);
  $("#visual-grid").addEventListener("click", (ev) => {
    const fig = ev.target.closest("[data-img]");
    if (fig) showImage(fig.dataset.img);
  });
  $("#visual-upload").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = ev.target.querySelector("button[type=submit]");
    await busy(btn, async () => {
      const r = await api(`${base}/images`, { method: "POST", form: new FormData(ev.target) });
      toast("Завантажено: " + r.path, "ok");
      ev.target.file.value = "";
      invalidate("history", "structure");
      await loadImages();
    });
  });

  // ================================================================ ⬇ Оновлення з проду

  tabs.prod = {
    async load() {
      $$('input[name="prod-mode"]').forEach((r) => { r.checked = r.value === project.prod_mode; });
      $("#prod-remote").value = project.prod_remote;
      $("#prod-branch").value = project.prod_branch;
      $("#prod-cmd").value = project.prod_cmd;
      toggleProdFields();
      await Promise.all([loadProdRuns(), prodWarning()]);
    },
  };

  const prodMode = () => ($('input[name="prod-mode"]:checked') || {}).value || "git";

  function toggleProdFields() {
    const git = prodMode() === "git";
    $("#prod-git-fields").classList.toggle("hidden", !git);
    $("#prod-cmd-field").classList.toggle("hidden", git);
  }

  async function prodWarning() {
    const box = $("#prod-warning");
    box.innerHTML = "";
    if (prodMode() !== "git") return;
    const st = await api(`${base}/git/status`).catch(() => null);
    if (!st) return;
    if (!st.is_repo) {
      box.innerHTML = '<div class="alert alert-warn">Проект не є git-репозиторієм — оберіть «Своя команда» або ініціалізуйте git у вкладці «Тести + Git».</div>';
    } else if (!st.clean) {
      box.innerHTML = `<div class="alert alert-warn">Є ${st.files.length} незакомічених змін — pull може не пройти, якщо зміни конфліктують.</div>`;
    } else if (st.behind) {
      box.innerHTML = `<div class="alert alert-ok">На сервері ${st.behind} нових комітів.</div>`;
    }
  }

  async function loadProdRuns() {
    const runs = (await api(`${base}/runs?kind=prod`)).runs;
    $("#prod-runs").innerHTML = runs.map(runItem).join("") || '<li class="static muted">Оновлень ще не було</li>';
  }

  function runItem(r) {
    const ok = r.exit_code === 0;
    return `<li data-run="${r.id}"><span>${ok ? "✔️" : "❌"} <span class="mono small">${esc(r.command.slice(0, 80))}</span></span>
      <span class="meta">${esc(ago(r.started_at))} · ${r.duration}с</span></li>`;
  }

  function runOutput(r, extra = "") {
    const ok = r.exit_code === 0;
    return `<div class="card"><div class="row between"><span class="row">
        <span class="badge ${ok ? "badge-ok" : "badge-err"}">${ok ? "✔ Успішно" : "✘ Код " + esc(r.exit_code)}</span>${extra}
        <span class="muted small">${esc(date(r.started_at))} · ${r.duration} с${r.timed_out ? " · таймаут" : ""}</span></span>
        <code class="small">${esc(r.command)}</code></div>
      <pre class="output" style="margin-top:.5rem">${esc(r.output) || '<span class="muted">(немає виводу)</span>'}</pre></div>`;
  }

  $$('input[name="prod-mode"]').forEach((r) => r.addEventListener("change", () => { toggleProdFields(); prodWarning(); }));

  async function saveProd() {
    const body = { prod_mode: prodMode(), prod_remote: $("#prod-remote").value.trim(), prod_branch: $("#prod-branch").value.trim(), prod_cmd: $("#prod-cmd").value };
    await api(base, { method: "PUT", body });
    Object.assign(project, body);
  }

  $("#prod-save").addEventListener("click", (ev) => busy(ev.currentTarget, async () => { await saveProd(); toast("Збережено", "ok", 1500); }));
  $("#prod-run").addEventListener("click", (ev) => {
    if (!confirm("Оновити проект з проду?")) return;
    busy(ev.currentTarget, async () => {
      await saveProd();
      $("#prod-output").innerHTML = '<div class="card">' + loadingHtml + "</div>";
      try {
        const r = await api(`${base}/prod/update`, { method: "POST", body: {} });
        $("#prod-output").innerHTML = runOutput(r);
        toast(r.exit_code === 0 ? "Оновлено з проду" : "Оновлення завершилось з помилкою", r.exit_code === 0 ? "ok" : "error");
      } catch (e) {
        $("#prod-output").innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
      }
      invalidate("history", "tests", "structure", "code");
      loadHeaderGit();
      await Promise.all([loadProdRuns(), prodWarning()]);
    });
  });
  $("#prod-runs").addEventListener("click", async (ev) => {
    const li = ev.target.closest("[data-run]");
    if (!li) return;
    try { $("#prod-output").innerHTML = runOutput(await api(`${base}/runs/${li.dataset.run}`)); } catch (e) { fail(e); }
  });

  // ================================================================ 🕘 Історія змін

  const KIND_ICONS = { edit: "✏️", create: "➕", delete: "🗑", rename: "🔀", description: "📝", settings: "⚙️", git: "⎇", prod: "⬇️" };
  let historyPath = null;

  tabs.history = {
    async load() {
      await Promise.all([loadChanges(), loadCommits()]);
    },
  };

  async function loadChanges() {
    const list = (await api(`${base}/changes`)).changes;
    $("#hist-changes").innerHTML = list.map((c) => `
      <li data-change="${c.id}"><span>${KIND_ICONS[c.kind] || "•"} ${esc(c.summary)}${c.path ? ` <span class="mono small muted">${esc(c.path)}</span>` : ""}</span>
        <span class="meta" title="${esc(date(c.created_at))}">${esc(ago(c.created_at))}</span></li>`).join("")
      || '<li class="static muted">Змін через застосунок ще не було. Тут з\'являтимуться редагування файлів, коміти, оновлення з проду…</li>';
  }

  async function loadCommits() {
    const box = $("#hist-commits");
    const r = await api(`${base}/git/log?limit=200${historyPath ? "&path=" + q(historyPath) : ""}`);
    if (!r.is_repo) { box.innerHTML = '<li class="static muted">Проект не є git-репозиторієм.</li>'; return; }
    const head = historyPath ? `<li class="static"><span>Історія файлу <code>${esc(historyPath)}</code></span><button class="btn btn-sm" data-hist-clear>✕ Усі коміти</button></li>` : "";
    box.innerHTML = head + (r.commits.map((c) => `
      <li data-sha="${esc(c.sha)}"><span><code class="small">${esc(c.short)}</code> ${esc(c.subject)}<br><span class="muted small">${esc(c.author)}</span></span>
        <span class="meta" title="${esc(date(c.date))}">${esc(ago(c.date))}</span></li>`).join("") || '<li class="static muted">Комітів ще немає</li>');
  }

  function historyForFile(path) {
    historyPath = path;
    loaded.history = true;
    Promise.all([loadChanges(), loadCommits()]).catch(fail);
  }

  $("#hist-changes").addEventListener("click", async (ev) => {
    const li = ev.target.closest("[data-change]");
    if (!li) return;
    $$("#hist-changes li, #hist-commits li").forEach((x) => x.classList.toggle("active", x === li));
    try {
      const c = await api(`${base}/changes/${li.dataset.change}`);
      $("#hist-detail").innerHTML = `<div class="card"><h3>${KIND_ICONS[c.kind] || ""} ${esc(c.summary)} <span class="muted small">${esc(date(c.created_at))}</span></h3>
        ${c.path ? `<p><a href="#" data-open="${esc(c.path)}">${esc(c.path)}</a></p>` : ""}
        ${c.diff ? `<div class="diff">${diff(c.diff)}</div>` : emptyHtml("Без диффу")}</div>`;
      $("#hist-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { fail(e); }
  });

  $("#hist-commits").addEventListener("click", async (ev) => {
    if (ev.target.closest("[data-hist-clear]")) { historyPath = null; return loadCommits().catch(fail); }
    const li = ev.target.closest("[data-sha]");
    if (!li) return;
    $$("#hist-changes li, #hist-commits li").forEach((x) => x.classList.toggle("active", x === li));
    try {
      const r = await api(`${base}/git/show/${li.dataset.sha}`);
      $("#hist-detail").innerHTML = `<div class="card"><div class="diff">${diff(r.diff)}</div></div>`;
      $("#hist-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { fail(e); }
  });

  // ================================================================ 💥 Падіння, помилки

  let incidents = [];
  tabs.errors = {
    async load() {
      renderIngest();
      await Promise.all([loadIncidents(), loadLogs()]);
    },
  };

  async function loadIncidents() {
    const status = $("#err-status").value;
    incidents = (await api(`${base}/incidents?status=${status}`)).incidents;
    if (status === "open") setTabCount("errors", incidents.length);
    $("#err-list").innerHTML = incidents.map((i) => `
      <li data-inc="${i.id}"><span><span class="badge ${i.level === "warning" ? "badge-warn" : i.status === "resolved" ? "badge-ok" : "badge-err"}">${esc(i.level)}</span>
        ${esc(i.title)} ${i.occurrences > 1 ? `<span class="badge">×${i.occurrences}</span>` : ""}
        <br><span class="muted small">${esc({ manual: "вручну", api: "від проекту", log: "з логу" }[i.source] || i.source)}${i.status === "resolved" ? " · ✔ вирішено" : ""}</span></span>
        <span class="meta" title="${esc(date(i.last_seen_at))}">${esc(ago(i.last_seen_at))}</span></li>`).join("")
      || `<li class="static muted">${status === "open" ? "Відкритих помилок немає 🎉" : "Порожньо"}</li>`;
  }

  /** Рядки трейсбеку «File "...", line N» перетворюємо на посилання в редактор. */
  function tracebackHtml(tb) {
    const root = project.path.replace(/\\/g, "/").replace(/\/$/, "") + "/";
    return esc(tb).replace(/File &quot;([^&]+?)&quot;, line (\d+)/g, (m, file, line) => {
      const norm = file.replace(/\\/g, "/");
      let rel = null;
      if (norm.startsWith(root)) rel = norm.slice(root.length);
      else if (!norm.startsWith("/") && !/^[A-Za-z]:/.test(norm)) rel = norm;
      return rel ? `File &quot;<a href="#" data-open="${esc(rel)}" data-line="${line}">${file}</a>&quot;, line ${line}` : m;
    });
  }

  function showIncident(i) {
    $("#err-detail").innerHTML = `<div class="card">
      <div class="row between"><h3>${esc(i.title)}</h3><span class="row">
        ${i.status === "open" ? '<button class="btn btn-sm btn-primary" data-inc-status="resolved">✔ Вирішено</button>' : '<button class="btn btn-sm" data-inc-status="open">↺ Знову відкрити</button>'}
        <button class="btn btn-sm btn-danger" data-inc-delete>🗑</button></span></div>
      <dl class="kv"><dt>Рівень</dt><dd>${esc(i.level)}</dd><dt>Джерело</dt><dd>${esc(i.source)}</dd>
        <dt>Разів</dt><dd>${i.occurrences}</dd><dt>Вперше</dt><dd>${esc(date(i.created_at))}</dd>
        <dt>Востаннє</dt><dd>${esc(date(i.last_seen_at))}</dd>${i.resolved_at ? `<dt>Вирішено</dt><dd>${esc(date(i.resolved_at))}</dd>` : ""}</dl>
      ${i.message ? `<h4>Повідомлення</h4><pre class="output">${esc(i.message)}</pre>` : ""}
      ${i.traceback ? `<h4>Traceback</h4><pre class="output">${tracebackHtml(i.traceback)}</pre>` : ""}
      <h4>Нотатки (причина, як виправлено)</h4>
      <textarea class="input" rows="3" data-inc-notes>${esc(i.notes)}</textarea>
      <div class="row end"><button class="btn btn-sm" data-inc-save>💾 Зберегти нотатки</button></div>
    </div>`;
    $("#err-detail").dataset.inc = i.id;
    $("#err-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  $("#err-status").addEventListener("change", () => loadIncidents().catch(fail));
  $("#err-list").addEventListener("click", (ev) => {
    const li = ev.target.closest("[data-inc]");
    if (!li) return;
    $$("#err-list li").forEach((x) => x.classList.toggle("active", x === li));
    showIncident(incidents.find((i) => i.id === +li.dataset.inc));
  });

  $("#err-detail").addEventListener("click", async (ev) => {
    const id = $("#err-detail").dataset.inc;
    if (!id) return;
    try {
      const st = ev.target.closest("[data-inc-status]");
      if (st || ev.target.closest("[data-inc-save]")) {
        const body = { notes: $("[data-inc-notes]").value };
        if (st) body.status = st.dataset.incStatus;
        const i = await api(`${base}/incidents/${id}`, { method: "PUT", body });
        toast("Збережено", "ok", 1500);
        await loadIncidents();
        if (st) $("#err-detail").innerHTML = ""; else showIncident(i);
      }
      if (ev.target.closest("[data-inc-delete]") && confirm("Видалити інцидент?")) {
        await api(`${base}/incidents/${id}`, { method: "DELETE" });
        $("#err-detail").innerHTML = "";
        await loadIncidents();
      }
    } catch (e) { fail(e); }
  });

  $("#err-add").addEventListener("click", async () => {
    const v = await ask("Нова помилка / падіння", [
      { name: "title", label: "Заголовок", placeholder: "Бот падає при /start" },
      { name: "level", label: "Рівень", type: "select", options: ["error", "critical", "warning"], value: "error" },
      { name: "message", label: "Опис", type: "textarea", rows: 3 },
      { name: "traceback", label: "Traceback / лог (необов'язково)", type: "textarea", rows: 6 },
    ]);
    if (!v) return;
    try {
      const i = await api(`${base}/incidents`, { method: "POST", body: v });
      $("#err-status").value = "open";
      await loadIncidents();
      showIncident(i);
    } catch (e) { fail(e); }
  });

  async function loadLogs() {
    const files = (await api(`${base}/logs`)).files;
    $("#err-logs").innerHTML = files.map((f) => `
      <li data-log="${esc(f.path)}"><span class="mono small">📋 ${esc(f.path)}</span><span class="meta">${size(f.size)} · ${esc(ago(f.mtime))}</span></li>`).join("")
      || '<li class="static muted">Лог-файлів (*.log, logs/*.txt) не знайдено</li>';
  }

  let currentLog = null;
  $("#err-logs").addEventListener("click", async (ev) => {
    const li = ev.target.closest("[data-log]");
    if (!li) return;
    $$("#err-logs li").forEach((x) => x.classList.toggle("active", x === li));
    try {
      currentLog = await api(`${base}/logs/view?path=${q(li.dataset.log)}`);
      renderLog(false);
    } catch (e) { fail(e); }
  });

  function renderLog(onlyErrors) {
    const l = currentLog;
    const lines = onlyErrors ? l.lines.filter((x) => x.level) : l.lines;
    $("#err-detail").dataset.inc = "";
    $("#err-detail").innerHTML = `<div class="card">
      <div class="row between"><h3 class="mono">${esc(l.path)}</h3>
        <span class="row"><span class="badge badge-err">${l.errors} помилок</span><span class="badge badge-warn">${l.warnings} попереджень</span>
        <label class="check small"><input type="checkbox" data-log-only ${onlyErrors ? "checked" : ""}> лише проблеми</label></span></div>
      ${l.partial ? '<p class="muted small">Показано кінець файлу (останні 512 КБ).</p>' : ""}
      ${l.tracebacks.length ? `<h4>Трейсбеки (${l.tracebacks.length})</h4>${l.tracebacks.map((t, n) => `
        <details><summary>${esc(t.title)} <span class="muted">· рядок ${t.line}</span></summary>
          <pre class="output">${tracebackHtml(t.text)}</pre>
          <div class="row end"><button class="btn btn-sm" data-tb="${n}">➕ Створити інцидент</button></div></details>`).join("")}` : ""}
      <h4>Лог</h4>
      <div class="output log-view">${lines.map((x) => `<div class="${x.level ? "lvl-" + x.level : ""}"><span class="ln">${x.n}</span>${esc(x.text)}</div>`).join("") || '<span class="muted">порожньо</span>'}</div>
    </div>`;
    const view = $("#err-detail .log-view");
    view.scrollTop = view.scrollHeight;
  }

  $("#err-detail").addEventListener("change", (ev) => {
    if (ev.target.matches("[data-log-only]")) renderLog(ev.target.checked);
  });
  $("#err-detail").addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-tb]");
    if (!b || !currentLog) return;
    const t = currentLog.tracebacks[+b.dataset.tb];
    try {
      await api(`${base}/incidents`, { method: "POST", body: { title: t.title, traceback: t.text, source: "log", message: `${currentLog.path}, рядок ${t.line}` } });
      toast("Інцидент створено", "ok");
      await loadIncidents();
    } catch (e) { fail(e); }
  });

  function renderIngest() {
    const url = project.ingest_url;
    const py = `import json, sys, traceback, urllib.request

HOLOST_URL = "${url}"

def report_error(exc, level="error"):
    data = {
        "title": f"{type(exc).__name__}: {exc}",
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "level": level,
    }
    req = urllib.request.Request(HOLOST_URL, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass  # Holost не запущений — не заважаємо програмі

# Автоматично надсилати всі необроблені винятки:
def _hook(t, e, tb):
    report_error(e, "critical")
    sys.__excepthook__(t, e, tb)

sys.excepthook = _hook`;
    const curl = `curl -X POST ${url} \\
  -H "Content-Type: application/json" \\
  -d '{"title": "Щось впало", "message": "деталі", "level": "error"}'`;
    $("#err-ingest").innerHTML = `
      <p class="muted">Однакові помилки групуються (лічильник ×N), вирішена помилка відкривається знову, якщо повториться.</p>
      <h4>Python</h4><pre class="output copy" data-copy-pre>${esc(py)}</pre>
      <h4>curl / будь-яка мова</h4><pre class="output copy" data-copy-pre>${esc(curl)}</pre>
      <p class="muted small">Натисніть на код, щоб скопіювати.</p>`;
  }
  $("#err-ingest").addEventListener("click", (ev) => {
    const pre = ev.target.closest("[data-copy-pre]");
    if (pre) copy(pre.textContent);
  });

  // ================================================================ 🌳 Структура проекту

  const LANG_COLORS = ["#3b5bdb", "#e67700", "#2b8a3e", "#c2255c", "#1098ad", "#7048e8", "#f08c00", "#5c940d", "#868e96", "#d6336c"];

  tabs.structure = {
    async load() {
      $("#struct-stats").innerHTML = loadingHtml;
      const [s, t] = await Promise.all([api(`${base}/stats`), api(`${base}/tree`)]);
      const langs = s.languages.filter((l) => l.lines > 0);
      const total = langs.reduce((a, l) => a + l.lines, 0) || 1;
      $("#struct-stats").innerHTML = `
        <div class="stats">
          <div class="stat"><div class="v">${s.files}${s.truncated ? "+" : ""}</div><div class="l">файлів</div></div>
          <div class="stat"><div class="v">${s.dirs}</div><div class="l">папок</div></div>
          <div class="stat"><div class="v">${s.lines.toLocaleString("uk-UA")}</div><div class="l">рядків коду й тексту</div></div>
          <div class="stat"><div class="v">${size(s.size)}</div><div class="l">розмір (без залежностей)</div></div>
          <div class="stat"><div class="v">${s.languages.length}</div><div class="l">мов / форматів</div></div>
        </div>
        ${langs.length ? `<div class="card"><h3>Мови</h3>
          <div class="lang-bar">${langs.map((l, i) => `<span style="width:${(l.lines / total) * 100}%;background:${LANG_COLORS[i % LANG_COLORS.length]}" title="${esc(l.language)}"></span>`).join("")}</div>
          <div class="lang-legend">${langs.map((l, i) => `<span><span class="dot" style="background:${LANG_COLORS[i % LANG_COLORS.length]}"></span>${esc(l.language)} <span class="muted">${((l.lines / total) * 100).toFixed(1)}% · ${l.files} ф. · ${l.lines} р.</span></span>`).join("")}</div>
          ${s.key_files.length ? `<h4>Ключові файли</h4><div class="chips">${s.key_files.map((f) => `<a href="#" class="badge" data-open="${esc(f)}">${esc(f)}</a>`).join("")}</div>` : ""}
        </div>` : ""}`;
      $("#struct-largest tbody").innerHTML = s.largest.map((f) => `
        <tr><td><a href="#" data-open="${esc(f.path)}" class="mono">${esc(f.path)}</a></td><td class="num">${size(f.size)}</td></tr>`).join("");
      $("#struct-tree").innerHTML = treeHtml(t.tree, 0) + (t.truncated ? '<p class="muted">… дерево обрізано</p>' : "");
    },
  };

  function treeHtml(node, depth) {
    if (node.type === "file") return `<div class="file" data-open="${esc(node.path)}">${fileIcon({ type: "file", name: node.name, image: /\.(png|jpe?g|gif|svg|webp|ico|bmp)$/i.test(node.name) })} ${esc(node.name)} <span class="muted">${size(node.size)}</span></div>`;
    if (node.ignored) return `<div class="muted">📦 ${esc(node.name)}/ <span class="small">(пропущено)</span></div>`;
    const kids = node.children || [];
    return `<details ${depth < 1 ? "open" : ""}><summary>📁 ${esc(node.name)}/ <span class="muted small">${kids.length}</span></summary>
      <div class="children">${kids.map((c) => treeHtml(c, depth + 1)).join("")}</div></details>`;
  }

  // ================================================================ ✅ Тести + Git

  tabs.tests = {
    async load() {
      $("#tests-cmd").value = project.test_cmd || (project.detected && project.detected.test_cmd) || "";
      await Promise.all([loadTestHistory(), loadGit()]);
    },
  };

  async function loadTestHistory() {
    const runs = (await api(`${base}/runs?kind=test`)).runs;
    $("#tests-history").innerHTML = runs.map(runItem).join("") || '<li class="static muted">Тести ще не запускались</li>';
  }

  function summaryBadges(s) {
    if (!s) return "";
    return Object.entries(s).map(([k, v]) => `<span class="badge ${k === "failed" || k === "error" ? "badge-err" : k === "passed" ? "badge-ok" : ""}">${esc(k)}: ${v}</span>`).join(" ");
  }

  $("#tests-run").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    const command = $("#tests-cmd").value.trim();
    $("#tests-result").innerHTML = '<p class="muted">Тести виконуються…</p>';
    try {
      const r = await api(`${base}/tests/run`, { method: "POST", body: { command, save: $("#tests-save").checked } });
      if ($("#tests-save").checked) project.test_cmd = r.command;
      $("#tests-cmd").value = r.command;
      $("#tests-result").innerHTML = runOutput(r, summaryBadges(r.summary));
      toast(r.exit_code === 0 ? "Тести пройшли ✔" : "Тести впали ✘", r.exit_code === 0 ? "ok" : "error");
    } catch (e) {
      $("#tests-result").innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
    await loadTestHistory();
  }));

  $("#tests-history").addEventListener("click", async (ev) => {
    const li = ev.target.closest("[data-run]");
    if (!li) return;
    try { $("#tests-result").innerHTML = runOutput(await api(`${base}/runs/${li.dataset.run}`)); } catch (e) { fail(e); }
  });

  const STATUS_NAMES = { M: "змінено", A: "додано", D: "видалено", R: "перейменовано", C: "скопійовано", U: "конфлікт", "?": "новий" };

  async function loadGit() {
    const box = $("#git-content");
    const st = await api(`${base}/git/status`);
    if (!st.is_repo) {
      box.innerHTML = `<p class="muted">Цей проект ще не під git.</p><button class="btn btn-primary" data-git="init" type="button">Ініціалізувати git-репозиторій</button>`;
      return;
    }
    const br = st.branches;
    const options = br.local.map((b) => `<option value="${esc(b)}" ${b === br.current ? "selected" : ""}>${esc(b)}</option>`).join("") +
      (br.remote.length ? `<optgroup label="Віддалені">${br.remote.map((b) => `<option value="${esc(b)}">${esc(b)}</option>`).join("")}</optgroup>` : "");
    box.innerHTML = `
      <div class="row wrap">
        <label class="grow">Гілка <select class="input" id="git-branch">${options || `<option>${esc(st.branch)}</option>`}</select></label>
        <button class="btn btn-sm" type="button" id="git-newbranch">➕ Нова гілка</button>
      </div>
      <div class="row wrap small">
        ${st.upstream ? `<span class="badge">↔ ${esc(st.upstream)}</span>` : '<span class="badge badge-warn">без upstream</span>'}
        ${st.ahead ? `<span class="badge badge-accent">↑ ${st.ahead} не запушено</span>` : ""}
        ${st.behind ? `<span class="badge badge-accent">↓ ${st.behind} нових на сервері</span>` : ""}
        ${br.remotes.map((r) => `<span class="badge" title="${esc(r.url)}">${esc(r.name)}</span>`).join("")}
      </div>
      <h4 class="row between">Зміни (${st.files.length}) ${st.files.length ? '<button class="btn btn-sm" type="button" data-git-diff="">Весь дифф</button>' : ""}</h4>
      <ul class="list">${st.files.map((f) => {
        const code = f.untracked ? "?" : (f.index !== " " ? f.index : f.worktree);
        return `<li data-git-diff="${esc(f.path)}"><span class="mono small">${esc(f.path)}</span>
          <span class="badge ${code === "D" ? "badge-err" : code === "?" || code === "A" ? "badge-ok" : "badge-warn"}">${esc(STATUS_NAMES[code] || code)}</span></li>`;
      }).join("") || '<li class="static muted">Робоча копія чиста ✔</li>'}</ul>
      ${st.files.length ? `<h4>Коміт</h4>
        <textarea class="input" id="git-message" rows="2" placeholder="Що змінено…"></textarea>
        <div class="row end"><button class="btn btn-primary" type="button" id="git-commit">✔ Закомітити все</button></div>` : ""}`;
    setTabCount("tests", st.files.length);
  }

  async function gitAction(action, body = {}, btn = null) {
    return busy(btn, async () => {
      const r = await api(`${base}/git/${action}`, { method: "POST", body });
      toast(r.output || "Готово", "ok", 5000);
      invalidate("history", "prod", "code", "structure");
      await loadGit();
      loadHeaderGit();
      return r;
    });
  }

  $("#git-content").addEventListener("change", async (ev) => {
    if (ev.target.id !== "git-branch") return;
    let branch = ev.target.value;
    const remote = branch.includes("/") && $$("#git-branch optgroup option").some((o) => o.value === branch);
    if (remote) branch = branch.split("/").slice(1).join("/");
    if (!confirm(`Перейти на гілку «${branch}»?`)) { loadGit(); return; }
    await gitAction("checkout", { branch });
    refreshTree();
  });

  $("#git-content").addEventListener("click", async (ev) => {
    const d = ev.target.closest("[data-git-diff]");
    if (d) {
      try {
        const path = d.dataset.gitDiff;
        const r = await api(`${base}/git/diff${path ? "?path=" + q(path) : ""}`);
        $("#git-diff").innerHTML = `<div class="card"><h3 class="row between"><span class="mono">${esc(path || "Усі зміни")}</span>
          ${path ? `<a href="#" data-open="${esc(path)}">Відкрити в редакторі</a>` : ""}</h3><div class="diff">${diff(r.diff)}</div></div>`;
        $("#git-diff").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) { fail(e); }
      return;
    }
    if (ev.target.id === "git-commit") {
      const message = $("#git-message").value.trim();
      if (!message) return toast("Напишіть повідомлення коміту", "error");
      await gitAction("commit", { message }, ev.target);
      $("#git-diff").innerHTML = "";
    }
    if (ev.target.id === "git-newbranch") {
      const v = await ask("Нова гілка", [{ name: "branch", label: "Назва гілки", placeholder: "feature/new-thing" }]);
      if (v && v.branch.trim()) await gitAction("checkout", { branch: v.branch.trim(), create: true });
    }
  });

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-git]");
    if (!b) return;
    const action = b.dataset.git;
    if (action === "push" && !confirm("Відправити коміти на сервер (git push)?")) return;
    await gitAction(action, {}, b);
  });

  // ================================================================ ⚙ Налаштування

  tabs.settings = {
    load() {
      $("#set-name").value = project.name;
      $("#set-path").value = project.path;
      $("#set-run").value = project.run_cmd;
      $("#set-run").placeholder = (project.detected && project.detected.run_cmd) || "напр. python app.py";
      $("#set-test").value = project.test_cmd;
      $("#set-test").placeholder = (project.detected && project.detected.test_cmd) || "напр. python -m pytest";
      $("#set-api").value = project.api_base_url;
      $("#set-fav").checked = !!project.favorite;
      $("#set-key").textContent = project.ingest_key;
    },
  };

  $("#set-save").addEventListener("click", (ev) => busy(ev.currentTarget, async () => {
    const body = { name: $("#set-name").value.trim(), run_cmd: $("#set-run").value.trim(), test_cmd: $("#set-test").value.trim(),
      api_base_url: $("#set-api").value.trim(), favorite: $("#set-fav").checked };
    await api(base, { method: "PUT", body });
    await loadProject();
    invalidate("tests", "usage", "api");
    toast("Налаштування збережено", "ok");
  }));

  $("#set-key-new").addEventListener("click", async () => {
    if (!confirm("Створити новий ключ? Старий перестане працювати.")) return;
    try {
      project = await api(`${base}/ingest-key`, { method: "POST", body: {} });
      $("#set-key").textContent = project.ingest_key;
      invalidate("errors");
    } catch (e) { fail(e); }
  });

  $("#set-remove").addEventListener("click", async () => {
    if (!confirm(`Прибрати «${project.name}» зі списку? Файли на диску залишаться.`)) return;
    try {
      await api(base, { method: "DELETE" });
      location.href = "/";
    } catch (e) { fail(e); }
  });

  // ================================================================ старт

  initEditor();
  loadProject().then(() => {
    activate((location.hash || "#folders").slice(1));
    loadHeaderGit();
    api(`${base}/incidents?status=open`).then((r) => setTabCount("errors", r.incidents.length)).catch(() => {});
  }).catch(fail);
})();

/* Спільні утиліти: запити до API, тости, форматування, markdown, дифф. */
"use strict";

const H = (() => {
  const token = document.querySelector('meta[name="csrf-token"]').content;

  async function api(url, { method = "GET", body, form } = {}) {
    const opts = { method, headers: { "X-CSRF-Token": token, Accept: "application/json" } };
    if (form) {
      opts.body = form;
    } else if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      throw new Error("Сервер недоступний. Чи запущено «Всі проекти» (python run.py)?");
    }
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("json") ? await res.json() : { error: (await res.text()).slice(0, 500) };
    if (!res.ok) {
      const err = new Error((data && data.error) || res.statusText);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);

  function toast(msg, type = "info", ms = 4000) {
    const box = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = "toast " + type;
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => el.remove(), type === "error" ? Math.max(ms, 7000) : ms);
  }

  const fail = (e) => toast(e.message || String(e), "error");

  function size(n) {
    if (n == null) return "";
    const u = ["Б", "КБ", "МБ", "ГБ"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + " " + u[i];
  }

  function date(v) {
    if (!v) return "";
    const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
    if (isNaN(d)) return String(v);
    return d.toLocaleString("uk-UA", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function ago(v) {
    if (!v) return "";
    const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
    const s = (Date.now() - d.getTime()) / 1000;
    if (isNaN(s)) return "";
    if (s < 60) return "щойно";
    if (s < 3600) return Math.floor(s / 60) + " хв тому";
    if (s < 86400) return Math.floor(s / 3600) + " год тому";
    if (s < 86400 * 30) return Math.floor(s / 86400) + " дн тому";
    return date(v);
  }

  const unsafeUrl = (u) => /^\s*(javascript|data|vbscript):/i.test(u);

  function inline(s, opts) {
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    s = esc(s);
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, url) => {
      if (unsafeUrl(url)) return alt;
      const src = /^https?:/i.test(url) || !opts.image ? url : opts.image(url);
      return `<img alt="${alt}" src="${src}" loading="lazy">`;
    });
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, t, url) =>
      unsafeUrl(url) ? t : `<a href="${url}" target="_blank" rel="noopener">${t}</a>`);
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    s = s.replace(/\u0000(\d+)\u0000/g, (_, n) => "<code>" + esc(codes[+n]) + "</code>");
    return s;
  }

  /** Мінімальний безпечний markdown → HTML (усе екранується). */
  function md(src, opts = {}) {
    const lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let para = [], list = null, i = 0;
    const flushPara = () => { if (para.length) { out.push("<p>" + inline(para.join(" "), opts) + "</p>"); para = []; } };
    const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*```/.test(line)) {
        flushPara(); flushList();
        const buf = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
        i++;
        out.push("<pre><code>" + esc(buf.join("\n")) + "</code></pre>");
        continue;
      }
      const hm = line.match(/^(#{1,6})\s+(.*)$/);
      if (hm) { flushPara(); flushList(); out.push(`<h${hm[1].length}>${inline(hm[2], opts)}</h${hm[1].length}>`); i++; continue; }
      const ul = line.match(/^\s*[-*+]\s+(.*)$/);
      const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if ((ul || ol) && !/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
        flushPara();
        const type = ul ? "ul" : "ol";
        if (list !== type) { flushList(); out.push(`<${type}>`); list = type; }
        out.push("<li>" + inline((ul || ol)[1], opts) + "</li>");
        i++;
        continue;
      }
      if (/^\s*>/.test(line)) { flushPara(); flushList(); out.push("<blockquote>" + inline(line.replace(/^\s*>\s?/, ""), opts) + "</blockquote>"); i++; continue; }
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flushPara(); flushList(); out.push("<hr>"); i++; continue; }
      if (!line.trim()) { flushPara(); flushList(); i++; continue; }
      flushList();
      para.push(line.trim());
      i++;
    }
    flushPara(); flushList();
    return out.join("\n");
  }

  /** Unified diff → кольоровий HTML. */
  function diff(text) {
    if (!text) return '<div class="muted">(немає змін)</div>';
    return text.split("\n").map((l) => {
      let cls = "";
      if (/^(diff |index |--- |\+\+\+ |commit |Author:|AuthorDate:|Commit:|CommitDate:|Date:)/.test(l)) cls = "meta";
      else if (l.startsWith("@@")) cls = "hunk";
      else if (l.startsWith("+")) cls = "add";
      else if (l.startsWith("-")) cls = "del";
      return `<div class="${cls}">${esc(l) || " "}</div>`;
    }).join("");
  }

  async function busy(btn, fn) {
    if (btn) { btn.classList.add("loading"); btn.disabled = true; }
    try {
      return await fn();
    } catch (e) {
      fail(e);
      return undefined;
    } finally {
      if (btn) { btn.classList.remove("loading"); btn.disabled = false; }
    }
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Скопійовано", "ok", 1500);
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("Скопійовано", "ok", 1500);
    }
  }

  // Кнопки «Скасувати» / «✕» у діалогах
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-close]");
    if (b && b.closest("dialog")) b.closest("dialog").close("");
  });

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // Перемикач теми
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("allprojects-theme", next); } catch (e) { /* ігноруємо */ }
    document.dispatchEvent(new CustomEvent("allprojects:theme", { detail: next }));
  });

  return { api, esc, toast, fail, size, date, ago, md, diff, busy, copy, $, $$ };
})();

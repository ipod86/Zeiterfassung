"use strict";

function fmtHMS(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = String(Math.floor(sec / 3600)).padStart(2, "0");
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Fehler");
  return data;
}

document.addEventListener("DOMContentLoaded", () => {
  const grid = document.getElementById("grid");
  if (grid) initBookingPage(grid);
  const custList = document.getElementById("cust-list");
  if (custList) initOverviewPage(custList);
  initRecurringPicker();
  initBudgetAlerts();
  initHelp();
  initFeedback();
});

// --- feedback (bug / feature) modal with check-off list ---
function escHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function initFeedback() {
  const dlg = document.getElementById("feedback-modal");
  const btn = document.getElementById("feedback-btn");
  if (!dlg || !btn) return;
  const list = dlg.querySelector("#fb-list");
  const count = dlg.querySelector("#fb-count");
  const typeSel = dlg.querySelector("#fb-type");
  const msgIn = dlg.querySelector("#fb-message");
  const note = dlg.querySelector("#fb-msg");

  function render(items) {
    const open = items.filter((i) => !i.done).length;
    count.textContent = items.length ? `· ${open} offen / ${items.length} gesamt` : "";
    if (!items.length) { list.innerHTML = '<p class="muted">Noch keine Meldungen.</p>'; return; }
    list.innerHTML = items.map((i) => {
      const badge = i.type === "WUNSCH" ? "wunsch" : "bug";
      const label = i.type === "WUNSCH" ? "💡 Wunsch" : "🐞 Bug";
      return `<label class="fb-item${i.done ? " done" : ""}">
        <input type="checkbox" data-id="${i.id}" ${i.done ? "checked" : ""}>
        <span class="fb-text">
          <span class="fb-badge ${badge}">${label}</span>
          <span class="fb-meta">${escHtml(i.ts)} · ${escHtml(i.user)}</span>
          <span class="fb-body">${escHtml(i.message)}</span>
        </span></label>`;
    }).join("");
  }

  async function load() {
    try {
      const res = await fetch("/api/feedback");
      const data = await res.json();
      render(data.items || []);
    } catch { list.innerHTML = '<p class="muted">Konnte Liste nicht laden.</p>'; }
  }

  btn.addEventListener("click", () => { note.textContent = ""; dlg.showModal(); load(); });
  dlg.querySelectorAll(".fb-close").forEach((b) =>
    b.addEventListener("click", () => dlg.close()));
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

  dlg.querySelector("#fb-save").addEventListener("click", async () => {
    const message = msgIn.value.trim();
    if (!message) { note.textContent = "Bitte eine Beschreibung eingeben."; return; }
    try {
      await post("/api/feedback", { type: typeSel.value, message });
      msgIn.value = "";
      note.textContent = "Danke! Meldung gespeichert.";
      load();
    } catch (e) { note.textContent = e.message || "Fehler beim Speichern."; }
  });

  list.addEventListener("change", async (e) => {
    const cb = e.target.closest("input[type=checkbox][data-id]");
    if (!cb) return;
    try {
      await post(`/api/feedback/${cb.dataset.id}/toggle`, { done: cb.checked });
      load();
    } catch { cb.checked = !cb.checked; }
  });
}

// --- help / instructions modal (? button in the top bar) ---
function initHelp() {
  const dlg = document.getElementById("help-modal");
  const btn = document.getElementById("help-btn");
  if (!dlg || !btn) return;
  btn.addEventListener("click", () => dlg.showModal());
  dlg.querySelectorAll(".help-close").forEach((b) =>
    b.addEventListener("click", () => dlg.close()));
  // click on the backdrop closes the dialog
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
}

// --- acknowledgeable budget threshold warning (modal on load / after stop) ---
function initBudgetAlerts() {
  const dlg = document.getElementById("budget-alert");
  if (!dlg) return;
  let acked = {};
  try { acked = JSON.parse(localStorage.getItem("budgetAck") || "{}"); } catch { acked = {}; }
  const items = [...dlg.querySelectorAll("li[data-key]")];
  const pending = [];
  items.forEach((li) => {
    if (acked[li.dataset.key]) li.classList.add("hidden");
    else pending.push(li.dataset.key);
  });
  if (!pending.length) return;
  dlg.showModal();
  document.getElementById("ba-ok")?.addEventListener("click", () => {
    pending.forEach((k) => { acked[k] = 1; });
    try { localStorage.setItem("budgetAck", JSON.stringify(acked)); } catch {}
  });
}

// --- recurring-task picker (▾ next to a task input) ---
function initRecurringPicker() {
  const menu = document.getElementById("rectask-menu");
  if (!menu) return;
  let activeInput = null;
  const close = () => { menu.classList.add("hidden"); activeInput = null; };

  document.addEventListener("click", (ev) => {
    const pick = ev.target.closest(".task-pick");
    if (pick) {
      ev.preventDefault();
      const cell = pick.closest(".task-cell");
      const input = cell && cell.querySelector("input");
      if (!input) return;
      if (activeInput === input && !menu.classList.contains("hidden")) { close(); return; }
      activeInput = input;
      // Move the menu into the same dialog (top layer) so it shows above a modal.
      (input.closest("dialog") || document.body).appendChild(menu);
      menu.classList.remove("hidden");
      const r = pick.getBoundingClientRect();
      const w = menu.offsetWidth;
      menu.style.top = (r.bottom + 4) + "px";
      menu.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + "px";
      return;
    }
    const li = ev.target.closest("#rectask-menu li");
    if (li) {
      if (activeInput) {
        activeInput.value = li.dataset.text;
        activeInput.dispatchEvent(new Event("input", { bubbles: true }));
        activeInput.focus();
      }
      close();
      return;
    }
    if (!ev.target.closest("#rectask-menu")) close();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}

function initOverviewPage(custList) {
  const sections = [...custList.querySelectorAll("section.cust")];
  const noResult = document.getElementById("cust-noresult");

  // --- search across customer + project names ---
  const search = document.getElementById("cust-search");
  search?.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    let visible = 0;
    sections.forEach((sec) => {
      const ok = (sec.dataset.search || "").includes(q);
      sec.classList.toggle("hidden", !ok);
      if (ok) visible++;
    });
    if (noResult) noResult.classList.toggle("hidden", visible !== 0);
  });

  // --- expand/collapse a project's bookings ---
  custList.addEventListener("click", (ev) => {
    const tg = ev.target.closest(".proj-toggle");
    if (!tg) return;
    const row = document.getElementById(tg.dataset.target);
    if (row) {
      const hidden = row.classList.toggle("hidden");
      tg.classList.toggle("open", !hidden);
    }
  });

  // --- delete a booking ---
  custList.addEventListener("click", async (ev) => {
    const del = ev.target.closest(".btn-del-entry");
    if (del) {
      if (!confirm("Buchung wirklich löschen?")) return;
      try {
        await post(`/api/entry/${del.dataset.id}/delete`, {});
        const tr = del.closest("tr");
        if (tr) tr.remove();  // row disappears in place; list stays expanded
      } catch (e) { alert(e.message); }
      return;
    }
    const edit = ev.target.closest(".btn-edit-entry");
    if (edit) openEditEntry(edit.dataset);
  });

  // --- edit a booking ---
  const dlg = document.getElementById("edit-entry");
  let editId = null;
  function openEditEntry(d) {
    editId = d.id;
    document.getElementById("ee-date").value = d.date;
    document.getElementById("ee-start").value = d.start;
    document.getElementById("ee-end").value = d.end;
    document.getElementById("ee-pause").value = d.pause || 0;
    document.getElementById("ee-task").value = d.task || "";
    const rs = document.getElementById("ee-rate");
    let matched = false;
    for (const o of rs.options) {
      if (o.value === d.rate) { rs.value = d.rate; matched = true; break; }
    }
    if (!matched) {
      const o = new Option(`${d.rate} (individuell)`, d.rate, true, true);
      rs.add(o, 0);
    }
    dlg.showModal();
  }
  document.getElementById("ee-save")?.addEventListener("click", async () => {
    try {
      await post(`/api/entry/${editId}/edit`, {
        date: document.getElementById("ee-date").value,
        start: document.getElementById("ee-start").value,
        end: document.getElementById("ee-end").value,
        pause: document.getElementById("ee-pause").value,
        rate: document.getElementById("ee-rate").value,
        task: document.getElementById("ee-task").value,
      });
      dlg.close();
      location.reload();
    } catch (e) { alert(e.message); }
  });
}

function initBookingPage(grid) {
  const warnPct = Number(grid.dataset.warnPct) || 80;

  // --- budget mini-bar (consumed budget for the selected/running project) ---
  function renderBudgetMini(tr) {
    const mini = tr.querySelector(".budget-mini");
    if (!mini) return;
    let budgetH = 0, usedSecs = 0;
    if (tr.classList.contains("running")) {
      budgetH = Number(mini.dataset.budget) || 0;
      usedSecs = Number(mini.dataset.used) || 0;
    } else {
      const opt = tr.querySelector(".project-select")?.selectedOptions[0];
      if (opt) {
        budgetH = Number(opt.dataset.budget) || 0;
        usedSecs = Number(opt.dataset.used) || 0;
      }
    }
    if (!budgetH || budgetH <= 0) { mini.classList.add("hidden"); return; }
    const usedH = usedSecs / 3600;
    const pct = budgetH > 0 ? (usedH / budgetH) * 100 : 0;
    const fill = mini.querySelector(".bar > span");
    const label = mini.querySelector(".bm-label");
    if (fill) {
      fill.style.width = Math.min(pct, 100) + "%";
      fill.className = pct >= 100 ? "over" : (pct >= warnPct ? "warn" : "okbar");
    }
    if (label) label.textContent = `${usedH.toFixed(1)}/${budgetH.toFixed(1)} h`;
    mini.classList.remove("hidden");
  }
  grid.querySelectorAll("tbody tr.entry-row").forEach(renderBudgetMini);

  // --- live ticking ---
  setInterval(() => {
    // paused timers freeze: skip rows/chips flagged data-paused="1"
    document.querySelectorAll(
      ".entry-row.running:not([data-paused='1']) .elapsed, .chip-time:not([data-paused='1'])"
    ).forEach((el) => {
      el.dataset.elapsed = Number(el.dataset.elapsed) + 1;
      el.textContent = fmtHMS(el.dataset.elapsed);
    });
    // live-grow the consumed budget on running (non-paused) rows
    document.querySelectorAll(".entry-row.running:not([data-paused='1'])").forEach((tr) => {
      const mini = tr.querySelector(".budget-mini");
      if (mini && mini.dataset.budget) {
        mini.dataset.used = Number(mini.dataset.used) + 1;
        renderBudgetMini(tr);
      }
    });
  }, 1000);

  // --- per-column search (customer / project / task) ---
  const searchInputs = grid.querySelectorAll(".search-row input[data-col]");
  function applyFilter() {
    const terms = {};
    searchInputs.forEach((i) => (terms[i.dataset.col] = i.value.trim().toLowerCase()));
    grid.querySelectorAll("tbody tr.entry-row").forEach((tr) => {
      const task = (tr.querySelector(".task-input")?.value || "").toLowerCase();
      const ok =
        (tr.dataset.customer || "").includes(terms.customer || "") &&
        (tr.dataset.projects || "").includes(terms.project || "") &&
        task.includes(terms.task || "");
      tr.classList.toggle("hidden", !ok);
    });
  }
  searchInputs.forEach((i) => i.addEventListener("input", applyFilter));

  // --- preselect rate when a project is chosen ---
  function syncRate(tr) {
    const ps = tr.querySelector(".project-select");
    const rs = tr.querySelector(".rate-select");
    if (!ps || !rs) return;
    const opt = ps.selectedOptions[0];
    if (!opt || !opt.value || opt.value === "__new") return;
    const rateId = opt.dataset.rateId;
    const rateAmt = opt.dataset.rate;
    let matched = false;
    if (rateId) {
      for (const o of rs.options) {
        if (o.dataset.id === rateId) { rs.value = o.value; matched = true; break; }
      }
    }
    if (!matched && rateAmt) {
      for (const o of rs.options) {
        if (o.value === rateAmt) { rs.value = o.value; break; }
      }
    }
  }

  // --- new project dialog ---
  const npModal = document.getElementById("np-modal");
  let npCustomerId = null;
  function openNewProject(tr) {
    npCustomerId = Number(tr.dataset.customerId);
    document.getElementById("np-customer").textContent =
      "Kunde: " + tr.querySelector(".c-customer").childNodes[0].textContent.trim();
    document.getElementById("np-name").value = "";
    npModal.showModal();
  }
  document.getElementById("np-save")?.addEventListener("click", async () => {
    const name = document.getElementById("np-name").value.trim();
    if (!name) { alert("Projektname fehlt"); return; }
    const rateSel = document.getElementById("np-rate").selectedOptions[0];
    try {
      await post("/api/project/quick", {
        customer_id: npCustomerId,
        name,
        default_rate_id: rateSel ? Number(rateSel.dataset.id) : null,
      });
      location.reload();
    } catch (e) { alert(e.message); }
  });

  // --- manual entry dialog ---
  const modal = document.getElementById("manual-modal");
  let manualProject = null, manualRate = null;
  function openManual(tr) {
    const ps = tr.querySelector(".project-select");
    if (!ps || !ps.value || ps.value === "__new") {
      alert("Bitte zuerst ein Projekt in dieser Zeile wählen.");
      return;
    }
    manualProject = Number(ps.value);
    manualRate = tr.querySelector(".rate-select")?.value;
    document.getElementById("manual-project").textContent =
      tr.querySelector(".c-customer").childNodes[0].textContent.trim() + " / " +
      ps.selectedOptions[0].textContent.trim();
    document.getElementById("m-date").value = new Date().toISOString().slice(0, 10);
    document.getElementById("m-start").value = "09:00";
    document.getElementById("m-end").value = "10:00";
    document.getElementById("m-task").value = "";
    modal.showModal();
  }
  document.getElementById("m-save")?.addEventListener("click", async () => {
    try {
      await post("/api/entry/manual", {
        project_id: manualProject,
        rate: manualRate,
        date: document.getElementById("m-date").value,
        start: document.getElementById("m-start").value,
        end: document.getElementById("m-end").value,
        task: document.getElementById("m-task").value,
      });
      modal.close();
      location.reload();
    } catch (e) { alert(e.message); }
  });

  // --- row interactions ---
  grid.addEventListener("change", (ev) => {
    const ps = ev.target.closest(".project-select");
    if (!ps) return;
    const tr = ps.closest("tr.entry-row");
    if (ps.value === "__new") { ps.value = ""; openNewProject(tr); }
    else { syncRate(tr); renderBudgetMini(tr); }
  });

  // Re-render the whole (correctly-sorted) table body in place after an action
  // — no full reload, no scroll-to-top — and refresh the "Jetzt aktiv" banner.
  // Replacing the body reproduces the server's top-5 / alphabetical ordering, so
  // a started timer moves into the "Zuletzt"-Gruppe just like a fresh load.
  async function refreshGrid() {
    try {
      const data = await fetch("/api/grid").then((r) => r.json());
      if (!data || !data.ok) return;
      const body = document.getElementById("grid-body");
      if (body && data.html !== undefined) {
        body.innerHTML = data.html;
        body.querySelectorAll("tr.entry-row").forEach(renderBudgetMini);
      }
      const wrap = document.getElementById("active-banner-wrap");
      if (wrap && data.banner !== undefined) wrap.innerHTML = data.banner;
      applyFilter();
    } catch {}
  }

  grid.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const tr = btn.closest("tr.entry-row");
    const act = btn.dataset.act;
    try {
      if (act === "start") {
        const ps = tr.querySelector(".project-select");
        if (!ps.value || ps.value === "__new") {
          if (ps.value === "__new") { ps.value = ""; openNewProject(tr); }
          else alert("Bitte ein Projekt wählen (oder mit ＋ neu anlegen).");
          return;
        }
        await post("/api/timer/start", {
          project_id: Number(ps.value),
          rate: tr.querySelector(".rate-select").value,
          task: tr.querySelector(".task-input").value,
        });
        await refreshGrid();
      } else if (act === "stop") {
        await post("/api/timer/stop", { entry_id: Number(tr.dataset.entry) });
        await refreshGrid();
      } else if (act === "pause") {
        await post("/api/timer/pause", { entry_id: Number(tr.dataset.entry) });
        await refreshGrid();
      } else if (act === "resume") {
        await post("/api/timer/resume", { entry_id: Number(tr.dataset.entry) });
        await refreshGrid();
      } else if (act === "manual") {
        openManual(tr);
      }
    } catch (e) { alert(e.message); }
  });

  // --- poll others' activity ---
  setInterval(async () => {
    try {
      const st = await fetch("/api/state").then((r) => r.json());
      // Compare the exact set of running entry-IDs, not just the count, so a
      // timer started or stopped on another machine (same user) is detected
      // even when the running-count happens to stay the same.
      const local = new Set(
        [...document.querySelectorAll(".entry-row.running")].map(
          (tr) => String(tr.dataset.entry)
        )
      );
      const remote = new Set(st.mine.map((m) => String(m.id)));
      const sameSet =
        local.size === remote.size && [...local].every((id) => remote.has(id));
      if (!sameSet) location.reload();
    } catch {}
  }, 20000);
}

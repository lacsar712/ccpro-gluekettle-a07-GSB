import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  me: null,
  page: "bench",
  board: null,
  picked: null,
  peak: "96",
  stampData: null,
  submitNames: "worker, worker2",
  username: "admin",
  password: "123456",
  err: "",
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

async function refreshBoard() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  } else {
    state.picked = state.board.kettles[0];
  }
}

async function refreshStamps() {
  if (!state.picked) return;
  state.stampData = await api(`/api/kettles/${state.picked.id}/stamps`);
  state.picked = state.stampData.kettle;
}

function topBar() {
  const bar = el(`<header class="topbar">
    <div class="brand">骨巷熬胶坊</div>
    <nav>
      <button data-page="bench" class="${state.page === "bench" ? "on" : ""}">锅位作业台</button>
      <button data-page="stamps" class="${state.page === "stamps" ? "on" : ""}">押印台</button>
    </nav>
    <div class="who">${esc(state.me.username)} · ${state.me.role === "admin" ? "管理员" : "操作工"}
      <button id="logout">退出</button>
    </div>
  </header>`);
  bar.querySelectorAll("[data-page]").forEach((b) => {
    b.onclick = async () => {
      state.err = "";
      state.page = b.dataset.page;
      if (state.page === "stamps") {
        state.stampData = null;
        render();
        try {
          await refreshStamps();
        } catch (ex) { state.err = ex.message; }
      }
      render();
    };
  });
  bar.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
  };
  return bar;
}

function kettleRow() {
  const row = el(`<div class="row"></div>`);
  state.board.kettles.forEach((k) => {
    const n = (k.activeStampers || []).length;
    const btn = el(`<button class="kettle ${k.status} ${state.picked && state.picked.id === k.id ? "pick" : ""}">
      <strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span>
      <small>峰值 ${k.latestPeakC ?? "无"} · 印 ${n}</small>
    </button>`);
    btn.onclick = async () => {
      state.picked = k;
      state.err = "";
      if (state.page === "stamps") {
        state.stampData = null;
        render();
        try {
          await refreshStamps();
        } catch (ex) { state.err = ex.message; }
      }
      render();
    };
    row.append(btn);
  });
  return row;
}

function renderBench(box) {
  box.append(el(`<p>${state.board.alley} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃ 且两名不同人未撤回押印</p>`));
  box.append(kettleRow());
  const d = el(`<section class="drawer"></section>`);
  box.append(d);
  if (!state.picked) return;
  const k = state.picked;
  const names = k.activeStampers || [];
  d.innerHTML = `<h3>${esc(k.code)} · ${LABELS[k.status]}</h3>
    <p>最近峰值：${k.latestPeakC ?? "无"} ℃ · 煮胶 ${k.cookCount} 次</p>
    <p>未撤回押印（去重 ${names.length} 人）：${names.length ? esc(names.join("、")) : "<em>空名单</em>"}</p>
    <input id="peak" value="${esc(state.peak)}" />
    <button id="log">登记峰值</button>
    <div>
      <button data-s="cold">冷锅</button>
      <button data-s="boiling">熬煮中</button>
      <button data-s="drawn">已出胶</button>
    </div>`;
  d.querySelector("#log").onclick = async () => {
    state.err = "";
    state.peak = d.querySelector("#peak").value;
    try {
      state.picked = await api(`/api/kettles/${state.picked.id}/cooks`, {
        method: "POST",
        body: JSON.stringify({ peakTempC: Number(state.peak) }),
      });
      await renderAfterChange();
    } catch (ex) { fail(ex); }
  };
  d.querySelectorAll("[data-s]").forEach((b) => {
    b.onclick = async () => {
      state.err = "";
      try {
        state.picked = await api(`/api/kettles/${state.picked.id}/status`, {
          method: "POST",
          body: JSON.stringify({ status: b.dataset.s }),
        });
        await renderAfterChange();
      } catch (ex) { fail(ex); }
    };
  });
}

function stampRow(s) {
  const revoked = s.revokedAt != null;
  const tr = el(`<tr class="${revoked ? "revoked" : ""}">
    <td>${esc(state.stampData.kettle.code)}</td>
    <td>${esc(s.stamper)}</td>
    <td>${fmtTime(s.stampedAt)}</td>
    <td>${s.revokedAt ? fmtTime(s.revokedAt) : "—"}</td>
    <td class="act"></td>
  </tr>`);
  if (!revoked && state.me.role === "admin") {
    const btn = el(`<button class="revoke">撤印</button>`);
    btn.onclick = async () => {
      state.err = "";
      try {
        await api(`/api/stamps/${s.id}/revoke`, { method: "POST" });
        await renderAfterChange();
      } catch (ex) { fail(ex); }
    };
    tr.querySelector(".act").append(btn);
  }
  return tr;
}

function renderStamps(box) {
  box.append(el(`<p>按锅筛名单；操作工只能给自己加印，撤印归管理员。出胶须两名不同人的未撤回押印。</p>`));
  box.append(kettleRow());
  if (!state.picked || !state.stampData) return;
  const k = state.stampData.kettle;
  const names = k.activeStampers || [];
  const panel = el(`<section class="stamppanel">
    <h3>${esc(k.code)} · 未撤回押印 ${names.length} 人${names.length ? "：" + esc(names.join("、")) : "（空名单）"}</h3>
    <div class="stampactions">
      <button id="addstamp">我给自己加印（${esc(state.me.username)}）</button>
    </div>
    <table class="stamptable">
      <thead><tr><th>锅码</th><th>印人</th><th>加印时刻</th><th>撤回时刻</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </section>`);
  if (state.me.role === "admin") {
    const submit = el(`<div class="submitbook">
      <h4>主管交本（整本一次交入，至少两名不同人）</h4>
      <input id="names" value="${esc(state.submitNames)}" placeholder="两名印人，逗号分隔" />
      <button id="submitbook">交本</button>
    </div>`);
    submit.querySelector("#submitbook").onclick = async () => {
      state.err = "";
      state.submitNames = submit.querySelector("#names").value;
      const stampers = state.submitNames.split(/[,，、\s]+/).map((x) => x.trim()).filter(Boolean);
      try {
        await api(`/api/kettles/${state.picked.id}/stamp-books/submit`, {
          method: "POST",
          body: JSON.stringify({ stampers }),
        });
        await renderAfterChange();
      } catch (ex) { fail(ex); }
    };
    panel.querySelector(".stampactions").append(submit);
  }
  const tbody = panel.querySelector("tbody");
  state.stampData.stamps.forEach((s) => tbody.append(stampRow(s)));
  panel.querySelector("#addstamp").onclick = async () => {
    state.err = "";
    try {
      await api(`/api/kettles/${state.picked.id}/stamps/add`, { method: "POST" });
      await renderAfterChange();
    } catch (ex) { fail(ex); }
  };
  box.append(panel);
}

function fail(ex) {
  state.err = ex.message;
  render();
}

async function renderAfterChange() {
  await refreshBoard();
  if (state.page === "stamps") await refreshStamps();
  render();
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    const box = el(`<div class="wrap">
      <h1>骨巷熬胶坊</h1>
      <p>一排熬锅作业台，原生页面，无前端框架。</p>
      <form autocomplete="off">
        <label>用户名
          <input name="u" autocomplete="off" value="${esc(state.username)}" />
        </label>
        <label>密码
          <input name="p" type="password" autocomplete="off" value="${esc(state.password)}" />
        </label>
        <p class="hint">已预填 admin / 123456，另有 worker、worker2 / 123456</p>
        <button>登录</button>
      </form>
      <p class="err">${esc(state.err)}</p>
    </div>`);
    box.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      state.err = "";
      try {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: box.querySelector("[name=u]").value,
            password: box.querySelector("[name=p]").value,
          }),
        });
        localStorage.setItem(TOKEN_KEY, data.access_token);
        state.me = data.user;
        state.ready = true;
        await refreshBoard();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    app.append(box);
    return;
  }
  if (!state.board || !state.me) {
    app.append(el(`<div class="wrap">${state.err ? esc(state.err) : "装载…"}</div>`));
    return;
  }
  app.append(topBar());
  const box = el(`<main class="wrap">
    <h2>${state.page === "stamps" ? "押印台" : "锅位作业台"}</h2>
    <p class="err">${esc(state.err)}</p>
  </main>`);
  if (state.page === "bench") {
    renderBench(box);
  } else {
    if (state.stampData) renderStamps(box);
    else box.append(el(`<p>装载押印名单…</p>`));
  }
  app.append(box);
}

async function boot() {
  if (!state.ready) {
    render();
    return;
  }
  try {
    state.me = await api("/api/auth/me");
    await refreshBoard();
    await refreshStamps();
    render();
  } catch (e) {
    state.err = e.message;
    render();
  }
}

boot();

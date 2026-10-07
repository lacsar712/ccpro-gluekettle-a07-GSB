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
  view: location.hash === "#stamps" ? "stamps" : "bench",
  board: null,
  picked: null,
  peak: "96",
  stamps: null, // { kettleId, kettleCode, stamps[] }
  stampFilter: null,
  err: "",
  username: "admin",
  password: "123456",
};

window.addEventListener("hashchange", () => {
  state.view = location.hash === "#stamps" ? "stamps" : "bench";
  if (state.view === "stamps") loadStamps().catch(() => {});
  render();
});

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

const isAdmin = () => state.me?.role === "admin";

async function refresh() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
  render();
}

async function loadStamps() {
  const kid = state.stampFilter || state.picked?.id || state.board?.kettles?.[0]?.id;
  if (!kid) return;
  state.stampFilter = kid;
  state.stamps = await api(`/api/kettles/${kid}/stamps`);
  render();
}

function fmt(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  if (!state.me || !state.board) {
    app.append(el(`<div class="wrap">${state.err ? esc(state.err) : "装载…"}</div>`));
    return;
  }
  const box = el(`<div class="wrap">
    <header class="topbar">
      <h1>${esc(state.board.workshop)}</h1>
      <nav>
        <a href="#bench" class="${state.view === "bench" ? "on" : ""}">锅位作业台</a>
        <a href="#stamps" class="${state.view === "stamps" ? "on" : ""}">押印台</a>
      </nav>
      <div class="who">${esc(state.me.username)} · ${isAdmin() ? "管理员" : "操作工"}
        <button id="logout">退出</button>
      </div>
    </header>
    <p class="sub">${esc(state.board.alley)} · 出胶须最近峰值 ≥ 90℃，且未撤回押印去重后至少两名不同人</p>
    <div id="view"></div>
    <p class="err">${esc(state.err)}</p>
  </div>`);
  box.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
  };
  if (state.view === "stamps") renderStamps(box.querySelector("#view"));
  else renderBench(box.querySelector("#view"));
  app.append(box);
}

function renderLogin() {
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
      <p class="hint">已预填 admin / 123456，另有 worker / worker2 / 123456</p>
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
      state.ready = true;
      state.me = data.user;
      await refresh();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function renderBench(root) {
  const view = el(`<div>
    <div class="row"></div>
    <section class="drawer"></section>
  </div>`);
  const row = view.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const n = k.activeStamperNames.length;
    const btn = el(`<button class="kettle ${k.status} ${state.picked?.id === k.id ? "pick" : ""}">
      <strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span>
      <small>未撤回 ${n} 人${k.sealed ? " · 已封账" : ""}</small>
    </button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  if (state.picked) {
    const d = view.querySelector(".drawer");
    const k = state.picked;
    const names = k.activeStamperNames;
    const peakOk = k.latestPeakC != null && k.latestPeakC >= 90;
    const peopleOk = names.length >= 2;
    d.innerHTML = `
      <h3>${esc(k.code)} · ${LABELS[k.status]}${k.sealed ? " · 已封账" : ""}</h3>
      <p>最近峰值：${k.latestPeakC ?? "无"} ℃（<span class="${peakOk ? "ok" : "no"}">${peakOk ? "达标" : "不足 90℃"}</span>）
        · 煮胶 ${k.cookCount} 次</p>
      <p>未撤回押印去重后 <strong>${names.length}</strong> 人：
        <span class="${peopleOk ? "ok" : "no"}">${names.length ? esc(names.join("、")) : "空名单"}</span>
        （${peopleOk ? "满足两人" : "须至少两名不同人"}）</p>
      <input id="peak" value="${esc(state.peak)}" />
      <button id="log">登记峰值</button>
      <div class="statusbtns">
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button id="draw" class="${peakOk && peopleOk && !k.sealed ? "" : "blocked"}">已出胶</button>
      </div>`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.peak = d.querySelector("#peak").value;
      try {
        state.picked = await api(`/api/kettles/${k.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((b) => {
      b.onclick = async () => {
        state.err = "";
        try {
          state.picked = await api(`/api/kettles/${k.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: b.dataset.s }),
          });
          await refresh();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
    d.querySelector("#draw").onclick = async () => {
      state.err = "";
      try {
        state.picked = await api(`/api/kettles/${k.id}/status`, {
          method: "POST",
          body: JSON.stringify({ status: "drawn" }),
        });
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  }
  root.append(view);
}

function renderStamps(root) {
  const view = el(`<section class="stamps">
    <div class="filter">
      <label>按锅筛选
        <select id="kettle-select"></select>
      </label>
      <button id="addstamp">我给自己加印（${esc(state.me.username)}）</button>
      ${isAdmin() ? `<span class="hint">管理员可撤印、改印人</span>` : `<span class="hint">操作工只能给自己加印；撤印归管理员</span>`}
    </div>
    <table class="stamptable">
      <thead><tr><th>#</th><th>印人</th><th>加印时刻</th><th>撤回时刻</th><th>状态</th><th>操作</th></tr></thead>
      <tbody></tbody>
    </table>
  </section>`);
  const sel = view.querySelector("#kettle-select");
  state.board.kettles.forEach((k) => {
    const opt = el(`<option value="${k.id}">${esc(k.code)} · ${LABELS[k.status]}</option>`);
    if (k.id === state.stampFilter || (!state.stampFilter && state.picked?.id === k.id)) opt.selected = true;
    sel.append(opt);
  });
  if (!state.stampFilter) state.stampFilter = Number(sel.value);
  sel.onchange = async () => {
    state.stampFilter = Number(sel.value);
    state.err = "";
    try {
      await loadStamps();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  view.querySelector("#addstamp").onclick = async () => {
    state.err = "";
    try {
      await api(`/api/kettles/${state.stampFilter}/stamps`, { method: "POST" });
      await loadStamps();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  const tbody = view.querySelector("tbody");
  const rows = state.stamps?.stamps || [];
  if (!rows.length) {
    tbody.append(el(`<tr><td colspan="6" class="hint">该锅暂无押印（空名单）</td></tr>`));
  }
  rows.forEach((s) => {
    const withdrawn = s.withdrawnAt != null;
    const sealed = s.bookId != null;
    const tr = el(`<tr class="${withdrawn ? "withdrawn" : ""} ${sealed ? "sealed" : ""}">
      <td>${s.id}</td>
      <td class="stamper-cell"></td>
      <td>${fmt(s.stampedAt)}</td>
      <td>${fmt(s.withdrawnAt)}</td>
      <td>${sealed ? "已封账" : withdrawn ? "已撤回" : "有效"}</td>
      <td class="ops"></td>
    </tr>`);
    const cell = tr.querySelector(".stamper-cell");
    const ops = tr.querySelector(".ops");
    if (isAdmin() && !sealed) {
      const inp = el(`<input class="nameedit" value="${esc(s.stamper)}" />`);
      cell.append(inp);
      const save = el(`<button>改名</button>`);
      save.onclick = async () => {
        state.err = "";
        try {
          await api(`/api/stamps/${s.id}`, {
            method: "PATCH",
            body: JSON.stringify({ stamper: inp.value.trim() }),
          });
          await loadStamps();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
      cell.append(save);
      const toggle = el(
        `<button>${withdrawn ? "恢复" : "撤印"}</button>`
      );
      toggle.onclick = async () => {
        state.err = "";
        try {
          await api(`/api/stamps/${s.id}`, {
            method: "PATCH",
            body: JSON.stringify({ withdrawn: !withdrawn }),
          });
          await loadStamps();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
      ops.append(toggle);
    } else {
      cell.textContent = s.stamper;
      if (!isAdmin() && !withdrawn && !sealed) {
        ops.append(el(`<span class="hint">仅本人可加，撤印找管理员</span>`));
      }
    }
    tbody.append(tr);
  });
  root.append(view);
  if (!state.stamps) {
    loadStamps().catch((e) => {
      state.err = e.message;
      render();
    });
  }
}

async function boot() {
  if (state.ready) {
    try {
      state.me = await api("/api/auth/me");
      await refresh();
      if (state.view === "stamps") loadStamps().catch(() => {});
    } catch (e) {
      localStorage.removeItem(TOKEN_KEY);
      state.ready = false;
      state.err = e.message;
      render();
    }
  } else {
    render();
  }
}

boot();

/**
 * stock-selector レポートビューア(PWA)。
 * サーバー/APIなし。sync_report.py が置いた暗号化ファイルを
 * ブラウザ側でパスフレーズ復号して表示するだけの静的アプリ。
 */

const SESSION_KEY = "msd_passphrase_session";
const PERSIST_KEY = "msd_passphrase_persist";

const state = {
  passphrase: null,
  manifest: null, // { reports: [...] }
  reportCache: new Map(), // ts -> decrypted snapshot
};

const el = (id) => document.getElementById(id);

function currentPassphrase() {
  return (
    sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(PERSIST_KEY) || null
  );
}

function savePassphrase(passphrase, persist) {
  if (persist) {
    localStorage.setItem(PERSIST_KEY, passphrase);
  } else {
    sessionStorage.setItem(SESSION_KEY, passphrase);
  }
}

function clearPassphrase() {
  sessionStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(PERSIST_KEY);
}

function showLogin(message) {
  el("login-view").classList.remove("hidden");
  el("app-view").classList.add("hidden");
  el("login-error").textContent = message || "";
  el("password-input").focus();
}

function showApp() {
  el("login-view").classList.add("hidden");
  el("app-view").classList.remove("hidden");
}

async function tryUnlock(passphrase) {
  const manifest = await fetchAndDecrypt(passphrase, "reports/manifest.enc");
  state.passphrase = passphrase;
  state.manifest = manifest;
  return manifest;
}

async function boot() {
  const saved = currentPassphrase();
  if (saved) {
    try {
      await tryUnlock(saved);
      showApp();
      route();
      return;
    } catch (e) {
      clearPassphrase();
    }
  }
  showLogin();
}

el("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const passphrase = el("password-input").value;
  const persist = el("remember-device").checked;
  el("login-error").textContent = "";
  el("login-submit").disabled = true;
  try {
    await tryUnlock(passphrase);
    savePassphrase(passphrase, persist);
    showApp();
    route();
  } catch (e) {
    el("login-error").textContent =
      "パスワードが違うか、レポートがまだ同期されていません。";
  } finally {
    el("login-submit").disabled = false;
  }
});

el("logout-button").addEventListener("click", () => {
  clearPassphrase();
  state.passphrase = null;
  state.manifest = null;
  state.reportCache.clear();
  location.hash = "#/";
  showLogin();
});

/* ---------------- ルーティング ---------------- */

window.addEventListener("hashchange", route);

function route() {
  if (!state.manifest) return;
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/report\/(.+)$/);
  if (m) {
    renderDetail(m[1]);
  } else {
    renderList();
  }
}

/* ---------------- 表示ヘルパー ---------------- */

function formatTs(ts) {
  // "20260707_2134" -> "2026/07/07 21:34"
  const match = ts.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})$/);
  if (!match) return ts;
  const [, y, mo, d, h, mi] = match;
  return `${y}/${mo}/${d} ${h}:${mi}`;
}

function modeBadge(entry) {
  if (entry.sector_first) return `セクター先行(上位${entry.top_sectors ?? "?"})`;
  if (entry.universe === "sp500") return "SP500全体";
  return `${(entry.market || "us").toUpperCase()}通常`;
}

function completenessLabel(c, scoreVersion) {
  const price = c.has_price_data ? "P" : "P✗";
  // ファンダ指標の分母はスコアリングのバージョンで変わる(v1: 4指標, v2: 5指標)
  const fundMax = (scoreVersion || 1) >= 2 ? 5 : 4;
  return `${price} F${c.fundamental_metrics}/${fundMax} N${c.news_count}`;
}

/** Fable 5の出力(簡易的な#見出し・-箇条書きを含む)を最低限整形して表示する。 */
function renderFableText(text) {
  if (!text) return "";
  const lines = text.split("\n");
  let html = "";
  let inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      continue;
    }
    const heading = line.match(/^#{1,6}\s*(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (heading) {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<h3>${escapeHtml(heading[1])}</h3>`;
    } else if (bullet) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${escapeHtml(bullet[1])}</li>`;
    } else {
      if (inList) {
        html += "</ul>";
        inList = false;
      }
      html += `<p>${escapeHtml(line)}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/* ---------------- 一覧画面 ---------------- */

function renderList() {
  el("detail-view").classList.add("hidden");
  el("list-view").classList.remove("hidden");

  const container = el("report-list");
  container.innerHTML = "";

  const reports = state.manifest.reports || [];
  if (reports.length === 0) {
    container.innerHTML = `<p class="empty">同期済みのレポートがありません。sync_report.py を実行してください。</p>`;
    return;
  }

  for (const entry of reports) {
    const top = entry.top && entry.top[0];
    const card = document.createElement("a");
    card.className = "report-card";
    card.href = `#/report/${entry.ts}`;
    card.innerHTML = `
      <div class="row1">
        <span class="date">${formatTs(entry.ts)}</span>
        <span class="badge">${escapeHtml(modeBadge(entry))}</span>
      </div>
      <div class="top-line">
        <span>${
          top ? `Top: ${escapeHtml(top.code)} ${escapeHtml(top.name)}` : "評価銘柄なし"
        }</span>
        ${top ? `<span class="score">${top.total_score}</span>` : ""}
      </div>
      <div class="sub-line">評価${entry.evaluable}銘柄 ${
        entry.excluded ? `(評価不能${entry.excluded})` : ""
      }</div>
    `;
    container.appendChild(card);
  }
}

/* ---------------- 詳細画面 ---------------- */

async function renderDetail(ts) {
  el("list-view").classList.add("hidden");
  el("detail-view").classList.remove("hidden");
  const body = el("detail-body");
  body.innerHTML = `<p class="loading">読み込み中...</p>`;
  el("detail-title").textContent = formatTs(ts);

  try {
    let snapshot = state.reportCache.get(ts);
    if (!snapshot) {
      const entry = (state.manifest.reports || []).find((r) => r.ts === ts);
      if (!entry) throw new Error("レポートが見つかりません");
      snapshot = await fetchAndDecrypt(state.passphrase, `reports/${entry.file}`);
      state.reportCache.set(ts, snapshot);
    }
    body.innerHTML = buildDetailHtml(snapshot);
  } catch (e) {
    body.innerHTML = `<p class="empty">読み込みに失敗しました: ${escapeHtml(
      String(e.message || e)
    )}</p>`;
  }
}

function buildDetailHtml(snapshot) {
  const meta = snapshot.meta || {};
  const w = meta.weights || {};
  const candidates = snapshot.candidates || [];
  const excluded = snapshot.excluded || [];
  const sectorRanking = snapshot.sector_ranking || [];

  let html = "";

  html += `<div class="meta-block">
    <div><span class="k">実行日時</span> ${escapeHtml(meta.generated_at || "-")}</div>
    <div><span class="k">市場</span> ${escapeHtml(meta.market || "-")} &middot;
      <span class="k">ユニバース</span> ${escapeHtml(meta.universe || "-")}
      ${
        meta.sector_first
          ? ` &middot; sector-first 上位${meta.top_sectors ?? "?"}セクター`
          : ""
      }
    </div>
    <div><span class="k">重み</span> ファンダ${fmtWeight(w.fundamental)} / テクニカル${fmtWeight(
    w.technical
  )} / ニュース${fmtWeight(w.news)}</div>
    <div><span class="k">評価銘柄数</span> ${candidates.length}件(評価不能 ${
    excluded.length
  }件)</div>
  </div>`;

  if (sectorRanking.length > 0) {
    html += `<h2>セクター相対強度</h2>`;
    html += `<div class="table-scroll"><table class="data-table">
      <thead><tr><th>セクター</th><th>コード</th><th>リターン</th><th>比ベンチマーク</th></tr></thead>
      <tbody>`;
    for (const s of sectorRanking) {
      html += `<tr>
        <td>${escapeHtml(s.name)}</td>
        <td class="mono">${escapeHtml(s.code)}</td>
        <td class="${numClass(s.return_pct)}">${fmtPct(s.return_pct)}</td>
        <td class="${numClass(s.relative_strength_pct)}">${fmtPct(
        s.relative_strength_pct
      )}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;
  }

  html += `<h2>スコア一覧</h2>`;
  html += `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>#</th><th>コード</th><th>銘柄名</th><th>総合</th><th>F</th><th>T</th><th>N</th><th>データ</th></tr></thead>
    <tbody>`;
  for (const c of candidates) {
    html += `<tr>
      <td>${c.rank ?? ""}</td>
      <td class="mono">${escapeHtml(c.code)}</td>
      <td>${escapeHtml(c.name || "")}</td>
      <td class="total">${fmtNum(c.total_score)}</td>
      <td>${fmtNum(c.fundamental_score)}</td>
      <td>${fmtNum(c.technical_score)}</td>
      <td>${fmtNum(c.news_score)}</td>
      <td class="mono small">${escapeHtml(completenessLabel(c, meta.score_version))}</td>
    </tr>`;
  }
  html += `</tbody></table></div>`;

  if (excluded.length > 0) {
    html += `<h2>評価不能銘柄(価格データ取得不可)</h2><ul class="plain-list">`;
    for (const c of excluded) {
      html += `<li><span class="mono">${escapeHtml(c.code)}</span> ${escapeHtml(
        c.name || ""
      )}</li>`;
    }
    html += `</ul>`;
  }

  if (snapshot.fable_report) {
    html += `<h2>Fable 5による総合コメント</h2><div class="fable-block">${renderFableText(
      snapshot.fable_report
    )}</div>`;
  }

  html += `<p class="disclaimer">本レポートは投資助言ではありません。最終的な投資判断はご自身の責任で行ってください。</p>`;

  return html;
}

function fmtNum(v) {
  return typeof v === "number" ? v.toFixed(1) : "-";
}
function fmtWeight(v) {
  return typeof v === "number" ? v.toFixed(2) : "-";
}
function fmtPct(v) {
  return typeof v === "number" ? `${v > 0 ? "+" : ""}${v.toFixed(2)}%` : "-";
}
function numClass(v) {
  if (typeof v !== "number") return "";
  return v > 0 ? "pos" : v < 0 ? "neg" : "";
}

/* ---------------- 起動 ---------------- */

boot();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  });
}

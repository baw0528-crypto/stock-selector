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

function doLogout() {
  clearPassphrase();
  state.passphrase = null;
  state.manifest = null;
  state.reportCache.clear();
  location.hash = "#/";
  showLogin();
}
el("logout-button").addEventListener("click", doLogout);
el("logout-button-dash").addEventListener("click", doLogout);

/* ---------------- ルーティング ---------------- */

window.addEventListener("hashchange", route);

function route() {
  if (!state.manifest) return;
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/report\/(.+)$/);
  hideTooltip();
  if (m) {
    renderDetail(m[1]);
  } else if (hash === "#/dashboard") {
    renderDashboard();
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
  const v = scoreVersion || 1;
  const fundMax = v >= 3 ? 6 : v >= 2 ? 5 : 4;
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
  el("dashboard-view").classList.add("hidden");
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
  el("dashboard-view").classList.add("hidden");
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

/* ---------------- ダッシュボード ---------------- */

const TOP_N = 10; // 「上位」とみなす順位のしきい値

async function loadAllSnapshots(onProgress) {
  const entries = state.manifest.reports || [];
  const snapshots = [];
  let done = 0;
  for (const entry of entries) {
    let snap = state.reportCache.get(entry.ts);
    if (!snap) {
      try {
        snap = await fetchAndDecrypt(state.passphrase, `reports/${entry.file}`);
        state.reportCache.set(entry.ts, snap);
      } catch (e) {
        done++;
        continue; // 壊れた/未同期のファイルはスキップ
      }
    }
    snapshots.push({ ts: entry.ts, snap });
    done++;
    if (onProgress) onProgress(done, entries.length);
  }
  snapshots.sort((a, b) => (a.ts < b.ts ? -1 : 1)); // 古い順
  return snapshots;
}

function aggregate(snapshots) {
  const byCode = new Map(); // code -> {name, appearances, scores: Map(ts->score)}
  const versions = new Set();
  for (const { ts, snap } of snapshots) {
    versions.add((snap.meta && snap.meta.score_version) || 1);
    for (const c of snap.candidates || []) {
      if (c.rank == null || c.rank > TOP_N) continue;
      let rec = byCode.get(c.code);
      if (!rec) {
        rec = { code: c.code, name: c.name || c.code, appearances: 0, scores: new Map() };
        byCode.set(c.code, rec);
      }
      rec.appearances++;
      rec.scores.set(ts, c.total_score);
    }
  }
  const regulars = [...byCode.values()]
    .map((r) => ({
      ...r,
      avgScore: [...r.scores.values()].reduce((a, b) => a + b, 0) / r.scores.size,
    }))
    .sort((a, b) => b.appearances - a.appearances || b.avgScore - a.avgScore);

  // 最新のセクター相対強度(記録があるスナップショットのうち最新)
  let latestSectors = null;
  let latestSectorsTs = null;
  for (const { ts, snap } of snapshots) {
    if ((snap.sector_ranking || []).some((s) => s.market === "us")) {
      latestSectors = snap.sector_ranking.filter((s) => s.market === "us");
      latestSectorsTs = ts;
    }
  }
  return { regulars, versions: [...versions].sort(), latestSectors, latestSectorsTs };
}

/* ---- SVGチャート生成 ----
   マーク仕様: バー≤24px・データ端のみ4px角丸・基線側は直角、線2px丸端、
   端点マーカーr4.5+サーフェス2pxリング、グリッドはヘアライン実線。 */

function esc(s) {
  return escapeHtml(String(s));
}

/** 右端だけ4px角丸の横バーパス(基線=左端は直角) */
function barPath(x, y, w, h) {
  const r = Math.min(4, w);
  return `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} L${x},${y + h} Z`;
}

/** 左端だけ4px角丸(負値バー用、基線=右端は直角) */
function barPathLeft(x, y, w, h) {
  const r = Math.min(4, w);
  return `M${x + w},${y} L${x + r},${y} Q${x},${y} ${x},${y + r} L${x},${y + h - r} Q${x},${y + h} ${x + r},${y + h} L${x + w},${y + h} Z`;
}

/** 常連銘柄: 出現回数の横バー(単一色相=マグニチュード) */
function regularsChart(regulars, totalSnapshots) {
  const items = regulars.slice(0, 8);
  if (items.length === 0) return "";
  const W = 340, rowH = 30, labelW = 56, valW = 66;
  const H = items.length * rowH;
  const barMax = W - labelW - valW;
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="viz" role="img" aria-label="上位${TOP_N}入りの回数">`;
  items.forEach((r, i) => {
    const y = i * rowH + (rowH - 16) / 2;
    const w = Math.max(2, (r.appearances / totalSnapshots) * barMax);
    const tip = `${esc(r.code)} ${esc(r.name)}\n上位入り ${r.appearances}/${totalSnapshots}回 / 平均スコア ${r.avgScore.toFixed(1)}`;
    svg += `<text x="${labelW - 6}" y="${y + 12}" class="viz-label" text-anchor="end">${esc(r.code)}</text>`;
    svg += `<path d="${barPath(labelW, y, w, 16)}" class="viz-bar" data-tip="${tip}"></path>`;
    svg += `<text x="${labelW + w + 6}" y="${y + 12}" class="viz-value">${r.appearances}回 <tspan class="viz-sub">avg ${r.avgScore.toFixed(1)}</tspan></text>`;
  });
  svg += "</svg>";
  return svg;
}

/** スコア推移: 常連上位3銘柄の折れ線(カテゴリカル3系列) */
function trendChart(regulars, snapshots) {
  const series = regulars.filter((r) => r.scores.size >= 2).slice(0, 3);
  if (series.length === 0 || snapshots.length < 2) return null;
  const tsList = snapshots.map((s) => s.ts);
  const W = 340, H = 170, padL = 30, padR = 56, padT = 8, padB = 18;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  let lo = Infinity, hi = -Infinity;
  for (const s of series) for (const v of s.scores.values()) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  lo = Math.floor(lo / 5) * 5; hi = Math.ceil(hi / 5) * 5;
  if (hi === lo) hi = lo + 5;
  const x = (i) => padL + (tsList.length === 1 ? plotW / 2 : (i / (tsList.length - 1)) * plotW);
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * plotH;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="viz" role="img" aria-label="スコア推移">`;
  // 横グリッド(ヘアライン)+ y目盛り
  const step = (hi - lo) / 2 >= 10 ? 10 : 5;
  for (let v = lo; v <= hi; v += step) {
    svg += `<line x1="${padL}" y1="${y(v)}" x2="${W - padR}" y2="${y(v)}" class="viz-grid"></line>`;
    svg += `<text x="${padL - 5}" y="${y(v) + 3.5}" class="viz-tick" text-anchor="end">${v}</text>`;
  }
  // x軸ラベル(最初と最後の日付)
  const fmtD = (ts) => `${ts.slice(4, 6)}/${ts.slice(6, 8)}`;
  svg += `<text x="${padL}" y="${H - 4}" class="viz-tick">${fmtD(tsList[0])}</text>`;
  svg += `<text x="${W - padR}" y="${H - 4}" class="viz-tick" text-anchor="end">${fmtD(tsList[tsList.length - 1])}</text>`;

  // 各系列の折れ線 + 端点 + 直接ラベル(衝突時は縦にずらし、リーダー線で結ぶ)
  const endLabels = [];
  series.forEach((s, si) => {
    const pts = [];
    tsList.forEach((ts, i) => {
      const v = s.scores.get(ts);
      if (v != null) pts.push({ i, v });
    });
    const poly = pts.map((p) => `${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    svg += `<polyline points="${poly}" class="viz-line viz-s${si + 1}"></polyline>`;
    for (const p of pts) {
      const tip = `${esc(s.code)} ${fmtD(tsList[p.i])}\n総合スコア ${p.v.toFixed(1)}`;
      svg += `<circle cx="${x(p.i)}" cy="${y(p.v)}" r="11" class="viz-hit" data-tip="${tip}"></circle>`;
    }
    const last = pts[pts.length - 1];
    svg += `<circle cx="${x(last.i)}" cy="${y(last.v)}" r="4.5" class="viz-dot viz-s${si + 1}"></circle>`;
    endLabels.push({ si, code: s.code, x: x(last.i), y: y(last.v) });
  });
  // 端ラベルの衝突回避(最低12px間隔に押し広げる)
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    if (endLabels[i].labelY == null) endLabels[i - 1].labelY = endLabels[i - 1].labelY ?? endLabels[i - 1].y;
    const prev = endLabels[i - 1].labelY ?? endLabels[i - 1].y;
    endLabels[i].labelY = Math.max(endLabels[i].y, prev + 12);
  }
  for (const l of endLabels) {
    const ly = l.labelY ?? l.y;
    if (Math.abs(ly - l.y) > 2) {
      svg += `<line x1="${l.x + 5}" y1="${l.y}" x2="${l.x + 10}" y2="${ly}" class="viz-leader"></line>`;
    }
    svg += `<text x="${l.x + 12}" y="${ly + 3.5}" class="viz-label">${esc(l.code)}</text>`;
  }
  svg += "</svg>";
  return { svg, series, tsList };
}

/** セクター相対強度: 対SPY超過リターンのダイバージングバー */
function sectorChart(sectors) {
  const sorted = [...sectors].sort((a, b) => b.relative_strength_pct - a.relative_strength_pct);
  const W = 340, rowH = 24, labelW = 96, valW = 46;
  const H = sorted.length * rowH;
  const maxAbs = Math.max(...sorted.map((s) => Math.abs(s.relative_strength_pct)), 0.1);
  const plotW = W - labelW - valW;
  const cx = labelW + plotW / 2;
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="viz" role="img" aria-label="セクター相対強度">`;
  svg += `<line x1="${cx}" y1="0" x2="${cx}" y2="${H}" class="viz-baseline"></line>`;
  sorted.forEach((s, i) => {
    const y = i * rowH + (rowH - 14) / 2;
    const v = s.relative_strength_pct;
    const w = Math.max(1.5, (Math.abs(v) / maxAbs) * (plotW / 2 - 4));
    const tip = `${esc(s.name)}(${esc(s.code)})\n対SPY ${v > 0 ? "+" : ""}${v.toFixed(2)}% / リターン ${s.return_pct > 0 ? "+" : ""}${s.return_pct.toFixed(2)}%`;
    svg += `<text x="${labelW - 6}" y="${y + 11}" class="viz-label" text-anchor="end">${esc(s.name)}</text>`;
    if (v >= 0) {
      svg += `<path d="${barPath(cx, y, w, 14)}" class="viz-bar-pos" data-tip="${tip}"></path>`;
      svg += `<text x="${cx + w + 4}" y="${y + 11}" class="viz-value">+${v.toFixed(1)}</text>`;
    } else {
      svg += `<path d="${barPathLeft(cx - w, y, w, 14)}" class="viz-bar-neg" data-tip="${tip}"></path>`;
      svg += `<text x="${cx - w - 4}" y="${y + 11}" class="viz-value" text-anchor="end">${v.toFixed(1)}</text>`;
    }
  });
  svg += "</svg>";
  return svg;
}

function trendTable(series, tsList) {
  const fmtD = (ts) => `${ts.slice(4, 6)}/${ts.slice(6, 8)} ${ts.slice(9, 11)}:${ts.slice(11, 13)}`;
  let html = `<details class="viz-table"><summary>テーブルで見る</summary><div class="table-scroll"><table class="data-table"><thead><tr><th>実行</th>`;
  for (const s of series) html += `<th>${esc(s.code)}</th>`;
  html += `</tr></thead><tbody>`;
  for (const ts of tsList) {
    html += `<tr><td class="mono">${fmtD(ts)}</td>`;
    for (const s of series) {
      const v = s.scores.get(ts);
      html += `<td>${v != null ? v.toFixed(1) : "-"}</td>`;
    }
    html += `</tr>`;
  }
  html += `</tbody></table></div></details>`;
  return html;
}

async function renderDashboard() {
  el("list-view").classList.add("hidden");
  el("detail-view").classList.add("hidden");
  el("dashboard-view").classList.remove("hidden");
  const body = el("dashboard-body");
  const entries = state.manifest.reports || [];
  if (entries.length === 0) {
    body.innerHTML = `<p class="empty">同期済みのレポートがありません。</p>`;
    return;
  }
  body.innerHTML = `<p class="loading">レポートを復号中... (0/${entries.length})</p>`;
  const snapshots = await loadAllSnapshots((n, total) => {
    const p = body.querySelector(".loading");
    if (p) p.textContent = `レポートを復号中... (${n}/${total})`;
  });
  if (location.hash !== "#/dashboard") return; // 復号中に画面遷移した場合
  if (snapshots.length === 0) {
    body.innerHTML = `<p class="empty">読み込めるレポートがありませんでした。</p>`;
    return;
  }

  const { regulars, versions, latestSectors, latestSectorsTs } = aggregate(snapshots);
  const latest = snapshots[snapshots.length - 1];
  const latestTop = (latest.snap.candidates || []).find((c) => c.rank === 1);

  let html = "";

  // KPIタイル
  const fmtD = (ts) => `${ts.slice(4, 6)}/${ts.slice(6, 8)}`;
  html += `<div class="tile-row">
    <div class="tile">
      <div class="tile-label">集計対象レポート</div>
      <div class="tile-value">${snapshots.length}<span class="tile-unit">本</span></div>
      <div class="tile-sub">${fmtD(snapshots[0].ts)} 〜 ${fmtD(latest.ts)}</div>
    </div>
    <div class="tile">
      <div class="tile-label">最新トップ銘柄</div>
      <div class="tile-value">${latestTop ? esc(latestTop.code) : "-"}</div>
      <div class="tile-sub">${latestTop ? `スコア ${latestTop.total_score.toFixed(1)} ・ ${esc(latestTop.name)}` : ""}</div>
    </div>
  </div>`;

  // 常連銘柄
  html += `<section class="chart-card">
    <h2>よく上位に入る銘柄</h2>
    <p class="chart-note">各レポートで上位${TOP_N}位以内に入った回数(全${snapshots.length}本中)</p>
    ${regularsChart(regulars, snapshots.length)}
  </section>`;

  // スコア推移
  const trend = trendChart(regulars, snapshots);
  if (trend) {
    html += `<section class="chart-card">
      <h2>常連銘柄のスコア推移</h2>
      <div class="viz-legend">${trend.series
        .map((s, i) => `<span class="viz-key"><i class="viz-swatch viz-s${i + 1}"></i>${esc(s.code)}</span>`)
        .join("")}</div>
      ${trend.svg}
      ${trendTable(trend.series, trend.tsList)}
      ${versions.length > 1 ? `<p class="chart-note">※ スコア定義の異なるバージョン(v${versions.join("/v")})のレポートが混在しています</p>` : ""}
    </section>`;
  }

  // セクター相対強度
  if (latestSectors && latestSectors.length > 0) {
    html += `<section class="chart-card">
      <h2>セクター相対強度(対SPY・20営業日)</h2>
      <p class="chart-note">${formatTs(latestSectorsTs)} 時点</p>
      ${sectorChart(latestSectors)}
    </section>`;
  }

  html += `<p class="disclaimer">本ダッシュボードは投資助言ではありません。最終的な投資判断はご自身の責任で行ってください。</p>`;
  body.innerHTML = html;
}

/* ---- タップ/ホバーのツールチップ ---- */

function hideTooltip() {
  el("viz-tooltip").classList.add("hidden");
}

function showTooltip(target, text) {
  const tip = el("viz-tooltip");
  tip.textContent = "";
  text.split("\n").forEach((line, i) => {
    if (i > 0) tip.appendChild(document.createElement("br"));
    tip.appendChild(document.createTextNode(line));
  });
  tip.classList.remove("hidden");
  const r = target.getBoundingClientRect();
  const tr = tip.getBoundingClientRect();
  let left = r.left + r.width / 2 - tr.width / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tr.width - 8));
  let top = r.top - tr.height - 8;
  if (top < 8) top = r.bottom + 8;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

document.addEventListener("click", (ev) => {
  const t = ev.target.closest ? ev.target.closest("[data-tip]") : null;
  if (t) {
    showTooltip(t, t.getAttribute("data-tip"));
    ev.stopPropagation();
  } else {
    hideTooltip();
  }
});
document.addEventListener("scroll", hideTooltip, true);

/* ---------------- 起動 ---------------- */

boot();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  });
}

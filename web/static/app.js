/**
 * app.js — Sherlock Dashboard v4
 *
 * Features:
 *  - Auto-loads first available dataset from /api/blocks
 *  - Populates Dataset Information card (no dropdown)
 *  - Nav anchor bar supports smooth scroll
 *  - Charts: 2-col pie+donut, full-width heuristic bar
 *  - Clickable charts → filter TX Explorer
 *  - Heuristic tooltips on bar chart + TX chip hover
 *  - Block Explorer: paginated (20 per page), count label
 *  - TX Explorer: 50 per page, search + class + heuristic filter
 *  - Copy TXID button
 *  - Color-coded TX cards (flagged/coinjoin)
 */

"use strict";

/* ── Constants ────────────────────────────────────────────────────────── */
const TX_PAGE_SIZE    = 50;
const BLOCK_PAGE_SIZE = 20;

const HEURISTIC_DESCRIPTIONS = {
  cioh:                "Common Input Ownership — multiple inputs likely belong to the same wallet.",
  change_detection:    "Identifies outputs likely returning change to the sender.",
  coinjoin:            "Equal-value outputs from multiple inputs indicate privacy mixing.",
  consolidation:       "Many inputs merged into fewer outputs — typical UTXO cleanup.",
  address_reuse:       "Same scriptPubKey appears in both inputs and outputs.",
  round_number_payment:"Outputs with human-friendly BTC denominations.",
  batch_payment:       "One transaction paying multiple recipients simultaneously.",
};

const HEURISTIC_LABELS = {
  cioh:                "CIOH",
  change_detection:    "Change Detection",
  coinjoin:            "CoinJoin",
  consolidation:       "Consolidation",
  address_reuse:       "Address Reuse",
  round_number_payment:"Round Number",
  batch_payment:       "Batch Payment",
};

const HEURISTIC_COLORS = {
  cioh:                "#F59E0B",
  change_detection:    "#3B82F6",
  coinjoin:            "#A78BFA",
  consolidation:       "#FCA5A5",
  address_reuse:       "#6EE7B7",
  round_number_payment:"#FCD34D",
  batch_payment:       "#93C5FD",
};

const LABEL_COLORS = {
  coinjoin:       "#A78BFA",
  consolidation:  "#FCA5A5",
  batch_payment:  "#93C5FD",
  self_transfer:  "#6EE7B7",
  simple_payment: "#FCD34D",
  unknown:        "#6B7280",
};

const SCRIPT_DISPLAY = {
  p2wpkh:"P2WPKH", p2tr:"Taproot", p2sh:"P2SH",
  p2pkh:"P2PKH", p2wsh:"P2WSH", op_return:"OP_RETURN", unknown:"Unknown",
};
const SCRIPT_COLORS = {
  p2wpkh:"#F59E0B", p2tr:"#8B5CF6", p2sh:"#3B82F6",
  p2pkh:"#10B981", p2wsh:"#EC4899", op_return:"#6B7280", unknown:"#374151",
};

/* ── DOM refs ─────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

/* ── Chart instances ──────────────────────────────────────────────────── */
let scriptChart, classChart, heuristicChart;

/* ── Blocks pagination state ──────────────────────────────────────────── */
let allBlocks = [], blockOffset = 0;

/* ── TX state ─────────────────────────────────────────────────────────── */
let allTxs = [], filteredTxs = [], txOffset = 0;

/* -- Application state ----------------------------------------------------- */
/**
 * Single source of truth for the control layer.
 * - dataset: stem of the dataset currently selected in the dropdown
 * - isLoading: true while any API request is in flight
 */
const state = {
  dataset:   null,   // selected dropdown stem
  isLoading: false,  // true during any API call
};

/* ── Tooltip ──────────────────────────────────────────────────────────── */
const tooltip = $("h-tooltip");
function showTooltip(text, x, y) {
  tooltip.textContent = text;
  tooltip.classList.remove("hidden");
  // Keep within viewport
  const tw = 240, pad = 12;
  let left = x + pad;
  if (left + tw > window.innerWidth) left = x - tw - pad;
  tooltip.style.left = left + "px";
  tooltip.style.top  = (y + pad) + "px";
}
function hideTooltip() { tooltip.classList.add("hidden"); }

/* ══════════════════════════════ INIT ════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", async () => {
  $("tx-search").addEventListener("input", applyFilters);
  $("class-filter").addEventListener("change", applyFilters);
  $("heuristic-filter").addEventListener("change", applyFilters);
  $("load-more-btn")?.addEventListener("click", renderMoreTxs);
  $("load-more-blocks-btn")?.addEventListener("click", renderMoreBlocks);

  initNavHighlight();
  await initControls();
});

/* ── Control wiring ───────────────────────────────────────────────────── */
async function initControls() {

  // ── Populate dataset dropdown ─────────────────────────────────────────
  let blockList = []; // [{stem, analyzed}, ...]
  try {
    const res  = await fetch("/api/blocks");
    const data = await res.json();
    blockList = data.blocks || [];
  } catch (e) {
    showError(`Could not connect to the Sherlock server: ${e.message}`);
    return;
  }

  const sel    = $("dataset-selector");
  const runBtn = $("run-analysis-btn");

  // Always add sentinel first
  const sentinel = document.createElement("option");
  sentinel.value    = "";
  sentinel.disabled = true;
  sentinel.selected = true;
  sentinel.textContent = "Select dataset…";
  sel.appendChild(sentinel);

  // Run Analysis is disabled until user makes an explicit selection
  runBtn.disabled = true;

  if (blockList.length) {
    blockList.forEach(({ stem, analyzed }) => {
      const opt = document.createElement("option");
      opt.value       = stem;
      opt.textContent = analyzed ? stem : `${stem} (not analyzed)`;
      if (!analyzed) opt.style.color = "#9CA3AF"; // dim unanalyzed entries
      sel.appendChild(opt);
    });

    // Auto-load: find the first already-analyzed dataset and show it immediately.
    const firstAnalyzed = blockList.find(b => b.analyzed);
    if (firstAnalyzed) {
      sel.value     = firstAnalyzed.stem;
      state.dataset = firstAnalyzed.stem;
      runBtn.disabled = false;

      const cached = await loadBlock(firstAnalyzed.stem);
      if (!cached) {
        // Not cached despite being in out/ — unusual, surface error then hide loader
        $("initial-loader").classList.add("hidden");
        showError(`Could not load ${firstAnalyzed.stem}. Click Run Analysis to regenerate.`);
      }
    } else {
      // Fixtures exist but nothing analyzed yet
      $("initial-loader").classList.add("hidden");
      const errMsg = $("error-message");
      if (errMsg) errMsg.textContent =
        "Select a dataset and click Run Analysis to begin.";
      $("error-panel").classList.remove("hidden");
    }

    // Ensure Overview nav anchor is active after content renders.
    const overviewAnchor = document.querySelector(".nav-anchor[data-section='section-dataset']");
    if (overviewAnchor) {
      document.querySelectorAll(".nav-anchor").forEach(a => a.classList.remove("active"));
      overviewAnchor.classList.add("active");
    }
  } else {
    // No datasets found at all (no fixtures, no out/ files)
    $("initial-loader").classList.add("hidden");
    const errMsg = $("error-message");
    if (errMsg) errMsg.textContent =
      "Upload a .dat file or select a dataset to begin analysis.";
    $("error-panel").classList.remove("hidden");
  }

  // ── Dropdown change: enable Run Analysis, update state, do NOT auto-run ───
  sel.addEventListener("change", () => {
    const stem = sel.value;
    if (!stem) {
      runBtn.disabled = true;
      state.dataset   = null;
      return;
    }
    state.dataset   = stem;
    runBtn.disabled = false;
    // Intentionally does nothing else.
    // The user must click "Run Analysis" to process the selected dataset.
  });

  // ── Run Analysis button (the ONE trigger for analysis) ────────────────
  runBtn.addEventListener("click", async () => {
    if (state.isLoading) return;   // hard guard against double-submit
    const stem = state.dataset || sel.value;
    if (!stem) return;             // button should already be disabled
    await runAnalysis(stem);
  });

  // ── Upload: register in dropdown, auto-select, enable Run Analysis ─────
  const fileInput = $("file-upload");
  const uploadLbl = document.querySelector(".upload-label");
  const fileLabel = $("upload-filename");

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) {
      fileLabel.textContent = "Upload .dat";
      uploadLbl.classList.remove("has-file");
      return;
    }

    fileLabel.textContent = file.name;
    uploadLbl.classList.add("has-file");

    // Upload so the backend registers it — do NOT run analysis yet.
    setLoading(true, "Uploading…");
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const res  = await fetch("/api/upload", { method: "POST", body: form });
      const data = await res.json();

      if (data.ok === false) {
        showError(data.error?.message || data.error || "Upload failed.");
        fileLabel.textContent = "Upload .dat";
        uploadLbl.classList.remove("has-file");
        fileInput.value = "";
        return;
      }

      // Backend already ran analysis on upload — render results directly.
      const returnedStem = data.dataset;
      fileLabel.textContent = "Upload .dat";
      uploadLbl.classList.remove("has-file");
      fileInput.value = "";

      if (data.ok === false) {
        showError(data.error?.message || data.error || "Analysis failed.");
        return;
      }

      // Render dashboard immediately — no need for a second "Run Analysis" click.
      state.dataset = returnedStem;
      renderDashboard(data, returnedStem);
      $("main-content").classList.remove("hidden");
      $("initial-loader").classList.add("hidden");
      $("error-panel").classList.add("hidden");
      await refreshDatasetList(returnedStem);
      sel.value       = returnedStem;
      runBtn.disabled = false;

    } catch (e) {
      showError(`Upload failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  });
}


/* ── Shared analysis runner (used by auto-load AND button) ────────────── */
async function runAnalysis(stem) {
  setLoading(true, "Analyzing…");

  try {
    const res  = await fetch("/api/analyze", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ dataset: stem }),
    });
    const data = await res.json();

    if (data.ok === false) {
      showError(data.error?.message || data.error || "Analysis failed. Select a dataset and try again.");
      return;
    }

    state.dataset = stem;
    renderDashboard(data, stem);
    $("main-content").classList.remove("hidden");
    $("initial-loader").classList.add("hidden");
    $("error-panel").classList.add("hidden");
    // Refresh dropdown to mark this stem as analyzed
    await refreshDatasetList(stem);
    return true;

  } catch (e) {
    showError("Analysis failed. Please select a dataset and try again.");
    return false;
  } finally {
    setLoading(false);
  }
}

/* ── Loading state ────────────────────────────────────────────────────── */
function setLoading(loading, label = "Run Analysis") {
  state.isLoading = loading;
  const runBtn = $("run-analysis-btn");
  const sel    = $("dataset-selector");
  if (runBtn) {
    runBtn.disabled    = loading;
    runBtn.textContent = loading ? label : "Run Analysis";
  }
  if (sel) sel.disabled = loading;
}

/* ── Status hint (non-error, dismisses after 5 s) ────────────────────── */
function showStatus(msg) {
  const errPanel = $("error-panel");
  const errMsg   = $("error-message");
  if (!errPanel || !errMsg) return;
  errMsg.textContent = msg;
  errPanel.classList.remove("hidden");
  errPanel.style.borderColor = "rgba(16,185,129,0.4)";  // green tint for status
  $("main-content").classList.remove("hidden");
  $("initial-loader").classList.add("hidden");
  setTimeout(() => {
    errPanel.classList.add("hidden");
    errPanel.style.borderColor = "";
  }, 5000);
}

/* ── Refresh dataset dropdown list from /api/blocks ──────────────────── */
async function refreshDatasetList(selectStem = null) {
  try {
    const res  = await fetch("/api/blocks");
    const data = await res.json();
    const blockList = data.blocks || []; // [{stem, analyzed}, ...]
    const sel = $("dataset-selector");

    // Track existing stems (skip the sentinel value="")
    const existing = new Set(
      Array.from(sel.options).map(o => o.value).filter(Boolean)
    );

    blockList.forEach(({ stem, analyzed }) => {
      if (existing.has(stem)) {
        // Update label for items that completed analysis
        const opt = Array.from(sel.options).find(o => o.value === stem);
        if (opt) {
          opt.textContent = analyzed ? stem : `${stem} (not analyzed)`;
          opt.style.color = analyzed ? "" : "#9CA3AF";
        }
      } else {
        const opt = document.createElement("option");
        opt.value       = stem;
        opt.textContent = analyzed ? stem : `${stem} (not analyzed)`;
        if (!analyzed) opt.style.color = "#9CA3AF";
        sel.appendChild(opt);
      }
    });

    if (selectStem) {
      sel.value = selectStem;
      const runBtn = $("run-analysis-btn");
      if (runBtn) runBtn.disabled = false;
    }
  } catch (_) { /* best-effort */ }
}



/* ── Active nav highlight ────────────────────────────────────────────── */
function initNavHighlight() {
  const anchors = document.querySelectorAll(".nav-anchor[data-section]");
  if (!anchors.length) return;
  const sectionMap = {};
  anchors.forEach(a => { sectionMap[a.dataset.section] = a; });

  const setActive = id => {
    anchors.forEach(a => a.classList.remove("active"));
    if (sectionMap[id]) sectionMap[id].classList.add("active");
  };

  // Track which section has been most recently intersecting
  let currentSection = "section-dataset";
  setActive(currentSection);

  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        currentSection = e.target.id;
        setActive(currentSection);
      }
    });
  }, { rootMargin: "-118px 0px -50% 0px", threshold: 0 });

  Object.keys(sectionMap).forEach(id => {
    const el = document.getElementById(id);
    if (el) observer.observe(el);
  });

  // Scroll fallback: highlight Glossary when user scrolls near page bottom
  window.addEventListener("scroll", () => {
    const scrollBottom = window.scrollY + window.innerHeight;
    const pageHeight   = document.documentElement.scrollHeight;
    if (scrollBottom >= pageHeight - 120) {
      setActive("glossary");
    }
  }, { passive: true });
}


/* ── Load a precomputed result from out/<stem>.json ────────────────── */
async function loadBlock(stem) {
  try {
    const res  = await fetch(`/api/block/${stem}`);
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      return false; // Not cached/found
    }
    state.dataset = stem;
    renderDashboard(data, stem);
    $("main-content").classList.remove("hidden");
    $("initial-loader").classList.add("hidden");
    $("error-panel").classList.add("hidden");
    return true;
  } catch (e) {
    return false;
  }
}

/* ══════════════════════════ RENDER ══════════════════════════════════════ */
function renderDashboard(data, stem) {
  const s  = data.analysis_summary;
  const fr = s.fee_rate_stats;
  const blocks = data.blocks;

  /* Dataset info card */
  $("ds-filename").textContent = `${stem}.dat`;
  $("ds-network").textContent  = "mainnet";
  $("ds-blocks").textContent   = fmt(data.block_count);
  $("ds-txs").textContent      = fmt(s.total_transactions_analyzed);
  $("ds-range").textContent    =
    `${fmt(blocks[0]?.block_height)} → ${fmt(blocks.at(-1)?.block_height)}`;
  $("ds-flagged").textContent  =
    `${fmt(s.flagged_transactions)} (${pct(s.flagged_transactions, s.total_transactions_analyzed)}%)`;

  /* KPI */
  $("kpi-blocks").textContent    = fmt(data.block_count);
  $("kpi-total-tx").textContent  = fmt(s.total_transactions_analyzed);
  $("kpi-flagged").textContent   =
    `${fmt(s.flagged_transactions)} (${pct(s.flagged_transactions, s.total_transactions_analyzed)}%)`;
  $("kpi-median-fee").textContent = fr.median_sat_vb?.toFixed(2) ?? "—";

  /* Fee */
  $("fee-min").textContent    = fr.min_sat_vb?.toFixed(2)    ?? "—";
  $("fee-median").textContent = fr.median_sat_vb?.toFixed(2) ?? "—";
  $("fee-mean").textContent   = fr.mean_sat_vb?.toFixed(2)   ?? "—";
  $("fee-max").textContent    = fr.max_sat_vb?.toFixed(2)    ?? "—";
  $("fee-order").textContent  =
    fr.min_sat_vb <= fr.median_sat_vb && fr.median_sat_vb <= fr.max_sat_vb
    ? "✅ min ≤ median ≤ max (invariant satisfied)"
    : "❌ fee invariant violated";

  renderScriptChart(s.script_type_distribution);
  renderClassChart(s.classification_distribution);
  renderHeuristicChart(s.heuristic_detection_counts, s.total_transactions_analyzed);
  renderObservations(s, data);

  /* TX Explorer — show real block height in badge */
  const firstBlockHeight = blocks[0]?.block_height;
  const badge = $("tx-block-badge");
  if (badge) badge.textContent = firstBlockHeight ? `Block ${fmt(firstBlockHeight)}` : "Block 0";

  /* Block explorer — paginated */
  allBlocks   = blocks;
  blockOffset = 0;
  $("blocks-tbody").innerHTML = "";
  renderMoreBlocks();

  /* TX explorer — aggregate transactions across ALL blocks */
  allTxs = blocks.flatMap(b => (b.transactions ?? []).filter(tx => !tx.is_coinbase));
  $("class-filter").value = "";
  $("heuristic-filter").value = "";
  $("tx-search").value = "";
  applyFilters();

  /* Update footer with live stats */
  const footerEl = $("footer-stats");
  if (footerEl) {
    footerEl.textContent =
      `${fmt(s.total_transactions_analyzed)} transactions · ` +
      `${(s.heuristics_applied || []).length} heuristics · ` +
      `${data.block_count} blocks`;
  }

  /* Analysis time */
  const timeEl = $("ds-analysis-time");
  if (timeEl) {
    const secs = data.analysis_time_sec;
    timeEl.textContent = secs != null ? `~${secs.toFixed(1)} s` : "(cached — run analysis to measure)";
  }
}

/* ── Charts ───────────────────────────────────────────────────────────── */
function renderScriptChart(dist) {
  const keys   = Object.keys(dist);
  const labels = keys.map(k => SCRIPT_DISPLAY[k] || k);
  const values = Object.values(dist);
  const colors = keys.map(k => SCRIPT_COLORS[k] || "#9CA3AF");
  if (scriptChart) scriptChart.destroy();
  scriptChart = new Chart($("script-chart"), {
    type: "pie",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: "#111827" }] },
    options: baseOpts(),
  });
  // Hide skeleton once chart is ready
  const sk = $("script-skeleton");
  if (sk) sk.classList.add("hidden");
}

function renderClassChart(dist) {
  const ORDER  = ["coinjoin","consolidation","batch_payment","self_transfer","simple_payment","unknown"];
  const labels = ORDER.filter(k => dist[k] !== undefined);
  const values = labels.map(k => dist[k] || 0);
  const colors = labels.map(k => LABEL_COLORS[k] || "#6B7280");
  if (classChart) classChart.destroy();
  classChart = new Chart($("class-chart"), {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: "#111827" }] },
    options: {
      ...baseOpts(),
      onClick: (evt, els) => {
        if (!els.length) return;
        const lbl = classChart.data.labels[els[0].index];
        $("class-filter").value = lbl.toLowerCase().replace(/ /g, "_");
        applyFilters();
        $("section-tx").scrollIntoView({ behavior: "smooth" });
      },
    },
  });
  const csk = $("class-skeleton");
  if (csk) csk.classList.add("hidden");
}

function renderHeuristicChart(counts, total) {
  // Sort all known heuristics by count descending for readability
  const ids = Object.keys(HEURISTIC_LABELS)
    .filter(k => counts[k] !== undefined)
    .sort((a, b) => (counts[b] || 0) - (counts[a] || 0));
  const values = ids.map(k => counts[k] || 0);
  const labels = ids.map(k => HEURISTIC_LABELS[k]);
  const colors = ids.map(k => HEURISTIC_COLORS[k] || "#F59E0B");

  if (heuristicChart) heuristicChart.destroy();
  heuristicChart = new Chart($("heuristic-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values, backgroundColor: colors,
        borderColor: colors.map(c => c + "88"),
        borderWidth: 1, borderRadius: 5,
      }]
    },
    options: {
      ...baseOpts(),
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor:"#1F2937", titleColor:"#E5E7EB",
          bodyColor:"#9CA3AF", borderColor:"#374151", borderWidth:1,
          callbacks: {
            title: ctx => {
              const hid = ids[ctx[0].dataIndex];
              return HEURISTIC_DESCRIPTIONS[hid] || ctx[0].label;
            },
            label: ctx => ` ${fmt(ctx.raw)} (${pct(ctx.raw, total)}%)`,
          },
        },
      },
      scales: {
        x: { ticks:{color:"#9CA3AF",font:{family:"Inter",size:11}}, grid:{color:"rgba(30,42,58,0.9)"} },
        y: { ticks:{color:"#E5E7EB",font:{family:"Inter",size:12}}, grid:{display:false} },
      },
      onClick: (evt, els) => {
        if (!els.length) return;
        const hid = ids[els[0].index];
        $("heuristic-filter").value = hid;
        applyFilters();
        $("section-tx").scrollIntoView({ behavior: "smooth" });
      },
    },
  });
  const hsk = $("heuristic-skeleton");
  if (hsk) hsk.classList.add("hidden");
}

function baseOpts() {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: {
        position: "bottom",
        labels: { color:"#9CA3AF", font:{family:"Inter",size:11}, boxWidth:10, padding:10 },
      },
      tooltip: {
        backgroundColor:"#1F2937", titleColor:"#E5E7EB",
        bodyColor:"#9CA3AF", borderColor:"#374151", borderWidth:1,
        callbacks: { label: ctx => ` ${fmt(ctx.raw)}` },
      },
    },
  };
}

/* ── Observations ─────────────────────────────────────────────────────── */
function renderObservations(s, data) {
  const t  = s.total_transactions_analyzed;
  const cd = s.heuristic_detection_counts || {};
  const cl = s.classification_distribution || {};
  const fr = s.fee_rate_stats;
  const obs = [];

  if (cd.cioh)
    obs.push(`🔗 ${pct(cd.cioh,t)}% of transactions use multiple inputs (CIOH) — potential shared wallet ownership.`);
  if ((cd.coinjoin || 0) > 0)
    obs.push(`🌀 ${fmt(cd.coinjoin)} CoinJoin transactions detected — active privacy mixing.`);
  if ((cd.consolidation || 0) > 0)
    obs.push(`📦 ${fmt(cd.consolidation)} consolidation transactions — wallets cleaning UTXOs.`);
  if ((cd.address_reuse || 0) > 0)
    obs.push(`🔁 ${pct(cd.address_reuse,t)}% of transactions reuse addresses — privacy risk.`);
  if ((cd.batch_payment || 0) > 0)
    obs.push(`📤 ${fmt(cd.batch_payment)} batch payment transactions — likely exchange or payroll activity.`);
  if ((cd.round_number_payment || 0) > 0)
    obs.push(`💰 ${fmt(cd.round_number_payment)} round-number payments — human-chosen clean BTC amounts.`);
  if (fr.median_sat_vb != null)
    obs.push(`⚡ Median fee rate: ${fr.median_sat_vb.toFixed(2)} sat/vB · peak demand reached ${fr.max_sat_vb.toFixed(2)} sat/vB.`);

  const top = Object.entries(cl).sort((a,b)=>b[1]-a[1])[0];
  if (top)
    obs.push(`🏷️ Dominant classification: "${top[0].replace(/_/g,' ')}" — ${fmt(top[1])} transactions (${pct(top[1],t)}%).`);
  obs.push(`🧱 ${data.block_count} blocks: heights ${fmt(data.blocks[0]?.block_height)} to ${fmt(data.blocks.at(-1)?.block_height)}.`);

  const ol = $("observations-list");
  ol.innerHTML = "";
  obs.forEach(o => { const li = document.createElement("li"); li.textContent = o; ol.appendChild(li); });
}

/* ── Block table (paginated) ──────────────────────────────────────────── */
function renderMoreBlocks() {
  const tbody = $("blocks-tbody");
  const slice = allBlocks.slice(blockOffset, blockOffset + BLOCK_PAGE_SIZE);

  slice.forEach((b, si) => {
    const idx     = blockOffset + si;
    const bsum    = b.analysis_summary || {};
    const flagged = bsum.flagged_transactions ?? 0;
    const flagPct = b.tx_count ? ((flagged / b.tx_count)*100).toFixed(1) : "0.0";
    const median  = bsum.fee_rate_stats?.median_sat_vb?.toFixed(2) ?? "—";
    const h = b.block_hash;
    const hashDisplay = h.length >= 16 ? `${h.slice(0,8)}…${h.slice(-8)}` : h;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${idx}</td>
      <td>${fmt(b.block_height)}</td>
      <td>${fmt(b.tx_count)}</td>
      <td class="flagged-count">${fmt(flagged)} <span class="flag-pct">(${flagPct}%)</span></td>
      <td>${median} sat/vB</td>
      <td class="hash-cell" title="${h}">${hashDisplay}</td>`;
    tbody.appendChild(tr);
  });

  blockOffset += slice.length;
  const shown = Math.min(blockOffset, allBlocks.length);
  $("block-count-label").textContent =
    `Showing ${shown.toLocaleString()} / ${allBlocks.length.toLocaleString()} blocks`;
  $("block-more").classList.toggle("hidden", blockOffset >= allBlocks.length);
}

/* ── TX filter ────────────────────────────────────────────────────────── */
function applyFilters() {
  const search = $("tx-search").value.trim().toLowerCase();
  const cls    = $("class-filter").value;
  const heur   = $("heuristic-filter").value;

  filteredTxs = allTxs.filter(tx => {
    if (search && !tx.txid.toLowerCase().includes(search) &&
        !tx.classification.toLowerCase().includes(search)) return false;
    if (cls  && tx.classification !== cls) return false;
    if (heur && !tx.heuristics?.[heur]?.detected) return false;
    return true;
  });

  txOffset = 0;
  $("tx-list").innerHTML = "";
  updateTxLabel();
  renderMoreTxs();
}

function updateTxLabel() {
  const shown = Math.min(txOffset + TX_PAGE_SIZE, filteredTxs.length);
  $("tx-count-label").textContent =
    `Displaying ${shown.toLocaleString()} / ${filteredTxs.length.toLocaleString()} transactions`;
}

function renderMoreTxs() {
  const container = $("tx-list");
  const slice = filteredTxs.slice(txOffset, txOffset + TX_PAGE_SIZE);
  slice.forEach(tx => container.appendChild(buildTxCard(tx)));
  txOffset += slice.length;
  updateTxLabel();
  $("tx-more").classList.toggle("hidden", txOffset >= filteredTxs.length);
}

/* ── TX card ──────────────────────────────────────────────────────────── */
function buildTxCard(tx) {
  const wrap = document.createElement("div");
  const detected   = Object.entries(tx.heuristics || {}).filter(([,v]) => v.detected);
  const isFlagged  = detected.length > 0;
  const isCoinjoin = tx.classification === "coinjoin";
  const clsLow     = tx.classification || "unknown";
  const shortId    = `${tx.txid.slice(0,20)}…${tx.txid.slice(-8)}`;

  wrap.className = `tx-item ${isFlagged ? "tx-flagged" : ""} ${isCoinjoin ? "tx-coinjoin" : ""}`;
  wrap.innerHTML = `
    <div class="tx-header">
      <span class="tx-chevron">▶</span>
      <span class="tx-txid" title="${tx.txid}">${shortId}</span>
      <button class="copy-btn" title="Copy TXID">📋</button>
      <span class="tx-class cls-${clsLow}">${clsLow.replace(/_/g," ")}</span>
    </div>
    <div class="tx-detail">
      <div class="tx-meta">
        <span class="tx-meta-item"><span class="label">TXID</span><span class="val">${tx.txid}</span></span>
        <span class="tx-meta-item"><span class="label">Fired</span><span class="val">${detected.length} / ${Object.keys(tx.heuristics||{}).length} heuristics</span></span>
      </div>
      <div class="heuristics-grid">
        ${Object.entries(tx.heuristics || {}).map(([hid, res]) => {
          const color = res.detected ? (HEURISTIC_COLORS[hid] || "#9CA3AF") : "";
          const style = res.detected ? `border-color:${color}55;background:${color}14;color:${color}` : "";
          const desc  = HEURISTIC_DESCRIPTIONS[hid] || "";
          return `<div class="h-chip ${res.detected ? "detected" : ""}" style="${style}" data-tip="${desc}">
            <div class="h-dot"></div>
            <span>${HEURISTIC_LABELS[hid] || hid}</span>
            ${res.confidence ? `<em class="h-conf">${res.confidence}</em>` : ""}
          </div>`;
        }).join("")}
      </div>
    </div>`;

  // Expand/collapse
  wrap.querySelector(".tx-header").addEventListener("click", e => {
    if (e.target.closest(".copy-btn")) return;
    wrap.classList.toggle("expanded");
  });
  // Copy TXID
  wrap.querySelector(".copy-btn").addEventListener("click", e => {
    e.stopPropagation();
    navigator.clipboard.writeText(tx.txid).then(() => {
      const btn = e.currentTarget;
      btn.textContent = "✅";
      setTimeout(() => btn.textContent = "📋", 1500);
    });
  });
  // Heuristic chip tooltips
  wrap.querySelectorAll(".h-chip[data-tip]").forEach(chip => {
    chip.addEventListener("mouseenter", e => {
      if (chip.dataset.tip) showTooltip(chip.dataset.tip, e.clientX, e.clientY);
    });
    chip.addEventListener("mousemove",  e => {
      if (chip.dataset.tip) showTooltip(chip.dataset.tip, e.clientX, e.clientY);
    });
    chip.addEventListener("mouseleave", hideTooltip);
  });

  return wrap;
}

/* ── Helpers ──────────────────────────────────────────────────────────── */
function fmt(n) { if (n == null || n === "—") return "—"; return Number(n).toLocaleString(); }
function pct(part, total) { if (!total) return "0.0"; return (100 * part / total).toFixed(1); }
function showError(msg) {
  $("initial-loader").classList.add("hidden");
  $("error-panel").classList.remove("hidden");
  $("error-message").textContent = msg;
}

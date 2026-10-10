const API = "/api/v1";
const pageNames = {
  dashboard: "Overview", research: "Research", companies: "Companies", documents: "Documents",
  comparison: "Comparisons", reports: "Reports", evaluation: "Evaluation lab", settings: "Settings"
};
const state = { page: "dashboard", companies: loadCompanies(), activeResearch: null, searchTimer: null, documentTimer: null, authMode: "local" };
const main = document.getElementById("main");

function loadCompanies() {
  try {
    const value = JSON.parse(localStorage.getItem("evidencegraph.companies") || "[]");
    return Array.isArray(value) ? value.filter(x => x && /^\d{1,10}$/.test(String(x.cik)) && typeof x.name === "string").slice(0, 5) : [];
  } catch { return []; }
}
function saveCompanies() { localStorage.setItem("evidencegraph.companies", JSON.stringify(state.companies)); }
async function startApp() {
  const session = await api("/auth/session");

  state.authMode = session.mode;
  const name = session.user?.name || session.user?.email || "Researcher";
  const email = session.user?.email || "Local account";
  document.getElementById("sidebar-user-name").textContent = name;
  document.getElementById("sidebar-user-email").textContent = email;
  document.getElementById("sidebar-user-avatar").textContent = initials(name);
  const topAvatar = document.getElementById("top-avatar");
  topAvatar.textContent = initials(name);
  topAvatar.setAttribute("aria-label", name);
  document.getElementById("workspace-mode").lastChild.textContent = session.mode === "oidc" ? " Cloud workspace" : " Private workspace";
  document.getElementById("sign-out").hidden = session.mode !== "oidc";
  await renderPage();
}
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function initials(value) { return String(value || "EG").split(/\s+/).slice(0, 2).map(word => word[0] || "").join("").toUpperCase(); }
function dateLabel(value) {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(date.valueOf()) ? esc(value) : new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(date);
}
function money(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  const abs = Math.abs(amount);
  if (abs >= 1e12) return `$${(amount / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(amount / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(amount / 1e6).toFixed(1)}M`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(amount);
}
function apiError(data, response) { return data?.error?.message || `Request failed (${response.status}).`; }
async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { ...options, headers: { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) } });
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) throw new Error(apiError(data, response));
  return data;
}
function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type === "error" ? "error" : ""}`;
  node.textContent = message;
  document.getElementById("toasts").append(node);
  setTimeout(() => node.remove(), 4200);
}
function spinner(label = "Loading…") { return `<div class="loading-state"><span class="spinner"></span><span>${esc(label)}</span></div>`; }
function pageHeading(eyebrow, title, subtitle, action = "") {
  return `<div class="page-heading"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(title)}</h1><p class="page-subtitle">${esc(subtitle)}</p></div>${action ? `<div class="heading-actions">${action}</div>` : ""}</div>`;
}
function emptyState(icon, title, body, button = "") {
  return `<div class="empty-state"><div><div class="empty-illustration">${icon}</div><h3>${esc(title)}</h3><p>${esc(body)}</p>${button}</div></div>`;
}
function sourceLink(url, label = "Open source ↗") {
  if (!url) return "";
  try {
    const parsed = new URL(url, location.origin);
    if (parsed.protocol !== "https:" || !["www.sec.gov", "data.sec.gov", location.host].includes(parsed.host)) return "";
    return `<a class="source-link" href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
  } catch { return ""; }
}

function setPage(page) {
  if (!pageNames[page]) return;
  const demoDialog = document.getElementById("demo-dialog");
  if (demoDialog?.open) demoDialog.close();
  state.page = page;
  document.querySelectorAll(".nav-link[data-page]").forEach(node => node.classList.toggle("active", node.dataset.page === page));
  document.getElementById("page-crumb").textContent = pageNames[page];
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("mobile-scrim").classList.remove("open");
  renderPage();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function renderPage() {
  main.innerHTML = spinner();
  try {
    if (state.page === "dashboard") await renderDashboard();
    if (state.page === "research") renderResearchPage();
    if (state.page === "companies") await renderCompaniesPage();
    if (state.page === "documents") await renderDocumentsPage();
    if (state.page === "comparison") renderComparisonPage();
    if (state.page === "reports") await renderReportsPage();
    if (state.page === "evaluation") await renderEvaluationPage();
    if (state.page === "settings") await renderSettingsPage();
  } catch (error) {
    main.innerHTML = `<div class="page-heading"><div><span class="eyebrow">WORKSPACE</span><h1>Something went wrong</h1><p class="page-subtitle">${esc(error.message)}</p></div></div>${emptyState("!", "Could not load this view", "Check the service connection, then try again.", `<button class="button" data-action="refresh-page">Retry</button>`)}`;
  }
}

async function renderDashboard() {
  const [health, recent] = await Promise.all([api("/health"), api("/research/recent")]);
  document.getElementById("document-count").textContent = health.indexedDocuments;
  setSourceStatus(health.secConfigured, health.indexedDocuments);
  const demoDialog = document.getElementById("demo-dialog");
  demoDialog.dataset.secConfigured = String(health.secConfigured);
  document.getElementById("demo-start").textContent = health.secConfigured ? "Start with companies →" : "Configure SEC access →";
  const recentRows = recent.items.length ? `<div class="recent-list">${recent.items.map(item => `<button type="button" class="recent-row recent-open-row" data-action="open-research" data-id="${esc(item.id)}"><span class="recent-icon" aria-hidden="true">⌕</span><span class="recent-copy"><strong>${esc(item.question)}</strong><small>Research session · ${dateLabel(item.created_at)}</small></span><span class="recent-arrow" aria-hidden="true">→</span></button>`).join("")}</div>` : emptyState("⌕", "No research sessions yet", "Start with a focused question about a company or filing.", `<button class="button soft" data-page="research">Start research <span aria-hidden="true">→</span></button>`);
  main.innerHTML = `<section class="welcome-card"><div class="welcome-copy"><span class="eyebrow">EVIDENCE-BASED FINANCIAL RESEARCH</span><h1>Financial research with a clear source trail.</h1><p>Search indexed filings, compare SEC XBRL facts, and inspect the sources behind each result.</p><div class="hero-actions"><button class="button primary" data-page="research">Start research <span aria-hidden="true">→</span></button><button class="button" data-action="open-demo">Guided demo <span class="demo-duration">90 sec</span></button></div></div><div class="evidence-path"><div class="evidence-path-heading"><span class="eyebrow">FROM QUESTION TO EVIDENCE</span><span class="path-source">SEC filings · XBRL facts</span></div><ol class="evidence-path-list"><li class="evidence-step"><span class="step-number">01</span><span><strong>Ask a question</strong><small>Set a company, metric, or topic</small></span></li><li class="evidence-step"><span class="step-number">02</span><span><strong>Find source material</strong><small>Search indexed filing passages</small></span></li><li class="evidence-step"><span class="step-number">03</span><span><strong>Inspect and compare</strong><small>Open citations and annual facts</small></span></li><li class="evidence-step"><span class="step-number">04</span><span><strong>Export your research</strong><small>Keep source links and caveats</small></span></li></ol></div></section>
    <div class="overview-note"><span class="status-dot" aria-hidden="true"></span>Research support for review and analysis. Always verify the original source.</div>
    <section class="dashboard-grid"><article class="panel"><div class="panel-head"><div><h2>Recent research</h2><p>Pick up a saved question and its evidence</p></div><button class="text-button" data-page="reports">All reports →</button></div>${recentRows}</article><article class="panel"><div class="panel-head"><div><h2>Choose a starting point</h2><p>Set up the sources you want to investigate</p></div></div><div class="panel-body"><div class="quick-list"><button class="quick-action" data-page="companies"><span class="quick-icon" aria-hidden="true">◉</span><span><strong>Find a company</strong><small>Search public issuers in SEC EDGAR</small></span><span class="quick-arrow" aria-hidden="true">→</span></button><button class="quick-action" data-page="documents"><span class="quick-icon" aria-hidden="true">▤</span><span><strong>Open the library</strong><small>Upload or sync source documents</small></span><span class="quick-arrow" aria-hidden="true">→</span></button><button class="quick-action" data-page="comparison"><span class="quick-icon" aria-hidden="true">▥</span><span><strong>Compare financials</strong><small>Review annual SEC XBRL facts</small></span><span class="quick-arrow" aria-hidden="true">→</span></button></div>${!health.secConfigured ? `<div class="callout"><span class="callout-icon">ⓘ</span><span>Add a contact email in <button class="text-button" data-page="settings">Settings</button> before syncing SEC filings.</span></div>` : ""}</div></article></section>`;
}

function renderResearchPage() {
  const selected = state.companies.length ? state.companies.map(company => `<label class="selected-company"><input type="checkbox" name="research-company" value="${esc(company.cik)}" checked /><span class="company-avatar">${esc(initials(company.name))}</span><span class="selected-company-copy"><strong>${esc(company.name)}</strong><small>${esc(company.ticker || `CIK ${company.cik}`)}</small></span></label>`).join("") : `<p class="field-help">No companies selected. You can still search all indexed documents.</p>`;
  const previous = state.activeResearch ? renderResearchResult(state.activeResearch) : "";
  main.innerHTML = `${pageHeading("EVIDENCE FIRST", "Research", "Ask a question across selected companies and indexed documents. Every result carries a source reference.", `<button class="button" data-page="companies">＋ Add companies</button>`)}
    <div class="content-grid"><div class="stack"><form id="research-form" class="panel"><div class="panel-head"><div><h2>Research question</h2><p>Use a clear metric, period, or disclosure topic</p></div><span class="tag">Source-grounded</span></div><div class="panel-body"><label class="field-label" for="research-question">What would you like to investigate?</label><textarea class="textarea" id="research-question" name="question" minlength="8" maxlength="1200" required placeholder="e.g. Compare the latest annual revenue growth and supplier risks for these companies.">${esc(state.activeResearch?.question || "")}</textarea><div class="field-help">Financial figures come directly from SEC XBRL. Text results come from filings and documents already indexed in this workspace.</div><div class="form-submit-row"><label class="inline-status"><input type="checkbox" name="includeFinancials" checked /> Include annual financial facts when relevant</label><button class="button primary" type="submit">Find evidence <span>→</span></button></div></div><div class="panel-head"><div><h2>Company scope</h2><p>Select saved companies to filter document search</p></div><span class="tag">${state.companies.length} saved</span></div><div class="panel-body"><div class="stack">${selected}</div></div></form><div id="research-output">${previous}</div></div><aside class="stack"><section class="panel"><div class="panel-head"><div><h2>How answers are built</h2><p>Traceable by design</p></div></div><div class="panel-body"><div class="quick-list"><div class="quick-action"><span class="quick-icon">1</span><span><strong>Retrieve</strong><small>Search indexed source passages</small></span></div><div class="quick-action"><span class="quick-icon">2</span><span><strong>Calculate</strong><small>Use comparable SEC annual facts</small></span></div><div class="quick-action"><span class="quick-icon">3</span><span><strong>Verify</strong><small>Open each cited source yourself</small></span></div></div><div class="callout"><span class="callout-icon">ⓘ</span><span>An optional AI draft can be enabled by the administrator. Check Settings to see whether a provider is configured.</span></div></div></section></aside></div>`;
}

function renderAnswerSources(ids, citations) {
  return ids.map(id => {
    const item = citations[id];
    if (!item) return '';
    if (item.docId) return '<button type="button" class="text-button" data-action="open-document" data-id="' + esc(item.docId) + '" data-passage="' + esc(id) + '">Inspect source ↗</button>';
    return sourceLink(item.sourceUrl, 'Open SEC source ↗');
  }).join(' ');
}
function renderResearchResult(result) {
  const citations = Object.fromEntries((result.citations || []).map(item => [item.id, item]));
  const metricBlock = result.metrics?.length ? `<section class="panel"><div class="panel-head"><div><h2>Verified financial facts</h2><p>Annual SEC XBRL · growth shown only for comparable year durations</p></div></div><div class="panel-body"><div class="metric-grid">${result.metrics.map(item => {
    const citation = citations[item.sourceId] || {};
    const growth = item.growthPercent == null ? (item.growthUnavailableReason || "Growth unavailable") : `${Number(item.growthPercent).toFixed(2)}% year over year`;
    return `<article class="metric-card"><small>${esc(item.company)} · FY${esc(item.fiscalYear)}</small><strong>${money(item.value)}</strong><span class="metric-context" title="${esc(item.growthUnavailableReason || "")}">${esc(growth)}</span><a class="metric-citation" href="${esc(citation.sourceUrl || "#")}" target="_blank" rel="noopener noreferrer" title="${esc(citation.locator || "SEC XBRL fact")}">${esc(item.concept)} ↗</a></article>`;
  }).join("")}</div></div></section>` : "";
  const findings = result.findings?.length ? `<section class="panel"><div class="panel-head"><div><h2>Retrieved evidence</h2><p>${result.findings.length} relevant passage${result.findings.length === 1 ? "" : "s"} from your indexed documents</p></div></div><div class="panel-body"><div class="results-list">${result.findings.map(item => {
    const citation = citations[item.citationId] || {};
    const documentAction = citation.docId ? `<button class="text-button" data-action="open-document" data-id="${esc(citation.docId)}" data-passage="${esc(item.citationId)}">Inspect passage →</button>` : "";
    return `<article class="evidence-card"><div class="evidence-meta"><span class="badge">${esc(item.company || "Local source")}</span>${item.section ? `<span>§ ${esc(item.section)}</span>` : ""}<span>${esc(citation.locator || citation.sourceType || "Indexed document")}</span></div><p>${esc(item.text)}</p>${documentAction} ${sourceLink(citation.sourceUrl)}</article>`;
  }).join("")}</div></div></section>` : "";
  const caveats = [...(result.caveats || []), ...(result.missingInformation || [])];
  const noResults = !metricBlock && !findings ? emptyState("⌕", "No matching evidence yet", "Sync a filing or upload a source document, then ask this question again.", `<button class="button" data-page="documents">Add a source</button>`) : "";
  return `<div class="stack"><section class="answer-summary"><strong>${result.answer ? "AI-assisted draft" : "Research summary"}</strong><br />${esc(result.answer?.summary || result.summary)}${result.answer ? "<p>Sources: " + renderAnswerSources(result.answer.summaryCitationIds, citations) + "</p><p>Draft findings</p><ul>" + result.answer.findings.map(item => "<li>" + esc(item.text) + " <span>Sources: " + renderAnswerSources(item.citationIds, citations) + "</span></li>").join("") + "</ul>" : ""}<div class="field-help gap-top-7">Retrieved ${dateLabel(result.freshness?.retrievedAt)} · ${esc(result.retrieval?.method || "Evidence search")}</div></section>${metricBlock}${findings}${noResults}${caveats.length ? `<div class="callout"><span class="callout-icon">ⓘ</span><ul class="caveat-list">${caveats.map(item => `<li>${esc(item)}</li>`).join("")}</ul></div>` : ""}<div class="action-row"><button class="button small" data-action="download-report" data-id="${esc(result.id || "")}">↓ Export report</button></div></div>`;
}

function titleName(name) { return name?.length > 40 ? `${name.slice(0, 38)}…` : (name || "Company"); }
function renderCompaniesPage() {
  main.innerHTML = `${pageHeading("ISSUER RESEARCH", "Companies", "Search SEC registrants, keep a browser-saved research list, and bring filings into your evidence library.")}
    <div class="content-grid"><div class="stack"><section class="panel"><div class="panel-head"><div><h2>Find a public company</h2><p>Search by issuer name, ticker symbol, or CIK</p></div><span class="tag">SEC EDGAR</span></div><div class="panel-body"><label class="field-label" for="company-search">Company search</label><div class="search-field"><span class="search-symbol">⌕</span><input class="input" id="company-search" type="search" autocomplete="off" placeholder="Try a company name or ticker" /></div><div id="company-results" aria-live="polite"></div></div></section><section class="panel"><div class="panel-head"><div><h2>Your companies</h2><p>Available to research and compare</p></div><span class="tag">${state.companies.length} / 5</span></div><div class="panel-body"><div id="saved-companies" class="stack">${state.companies.length ? spinner("Loading company filings…") : emptyState("◉", "No companies saved", "Search above, then add a public issuer to this workspace.")}</div></div></section></div><aside class="stack"><section class="panel"><div class="panel-head"><div><h2>Import a filing</h2><p>Sync 10-K or 10-Q source HTML</p></div></div><div class="panel-body"><p class="page-subtitle">Choose a saved company, then select one of its recent annual or quarterly filings. SEC content is cached in this instance after ingestion. Requests respect fair-access pacing and retry temporary errors.</p><button class="button gap-top-12" data-page="settings">SEC contact settings</button></div></section><section class="panel"><div class="panel-head"><div><h2>Data scope</h2></div></div><div class="panel-body"><div class="formula-box">Company search and XBRL facts come from SEC EDGAR. A failed SEC request is reported as an error and never indexed as an empty filing.</div></div></section></aside></div>`;
  refreshSavedCompanies();
}
async function refreshSavedCompanies() {
  const target = document.getElementById("saved-companies");
  if (!target) return;
  if (!state.companies.length) { target.innerHTML = emptyState("◉", "No companies saved", "Search above, then add a public issuer to this workspace."); return; }
  const cards = await Promise.all(state.companies.map(async company => {
    try { return companyCard(company, await api(`/companies/${encodeURIComponent(company.cik)}`)); }
    catch (error) { return `<article class="company-card"><div class="company-card-top"><span class="company-avatar">${esc(initials(company.name))}</span><div class="company-result-copy"><strong>${esc(company.name)}</strong><small>CIK ${esc(company.cik)} · ${esc(error.message)}</small></div><button class="text-button" data-action="remove-company" data-cik="${esc(company.cik)}">Remove</button></div></article>`; }
  }));
  if (target.isConnected) target.innerHTML = cards.join("");
}
function companyCard(company, detail) {
  const filings = detail.filings?.length ? detail.filings.map(filing => `<div class="filing-row"><span class="badge neutral">${esc(filing.form)}</span><span class="filing-info"><strong>Period ended ${dateLabel(filing.reportDate)}</strong><small>Filed ${dateLabel(filing.filingDate)}</small></span><button class="button small soft" data-action="sync-filing" data-cik="${esc(company.cik)}" data-form="${esc(filing.form)}" data-accession="${esc(filing.accession)}">Sync</button></div>`).join("") : `<div class="field-help">No recent 10-K or 10-Q filings found.</div>`;
  return `<article class="company-card"><div class="company-card-top"><span class="company-avatar">${esc(initials(company.name))}</span><div class="company-result-copy"><strong title="${esc(company.name)}">${esc(titleName(company.name))}</strong><small>${esc(company.ticker || "")}${company.ticker ? " · " : ""}CIK ${esc(company.cik)}</small></div><button class="text-button" data-action="remove-company" data-cik="${esc(company.cik)}">Remove</button></div><div class="company-card-meta">${detail.sicDescription ? `<span class="tag">${esc(detail.sicDescription)}</span>` : ""}<span class="tag">FY end ${esc(detail.fiscalYearEnd || "—")}</span></div><div class="filing-list">${filings}</div></article>`;
}
async function searchCompanies(query) {
  const target = document.getElementById("company-results");
  if (!target) return;
  if (!query.trim()) { target.innerHTML = ""; return; }
  target.innerHTML = spinner("Searching SEC EDGAR…");
  try {
    const { items } = await api(`/companies/search?q=${encodeURIComponent(query.trim())}`);
    if (!target.isConnected || document.getElementById("company-search")?.value.trim() !== query.trim()) return;
    target.innerHTML = items.length ? `<div class="search-results">${items.map(company => {
      const exists = state.companies.some(item => item.cik === company.cik);
      return `<div class="company-result"><span class="company-avatar">${esc(initials(company.name))}</span><span class="company-result-copy"><strong title="${esc(company.name)}">${esc(company.name)}</strong><small>${esc(company.ticker)} · CIK ${esc(company.cik)}</small></span><button class="button small ${exists ? "" : "soft"}" data-action="add-company" data-cik="${esc(company.cik)}" data-name="${esc(company.name)}" data-ticker="${esc(company.ticker)}" ${exists || state.companies.length >= 5 ? "disabled" : ""}>${exists ? "Added" : "Add"}</button></div>`;
    }).join("")}</div>` : emptyState("⌕", "No matching registrants", "Try a company name, ticker, or CIK.");
  } catch (error) { target.innerHTML = `<div class="callout" role="alert">${esc(error.message)}</div>`; }
}

async function renderDocumentsPage() {
  main.innerHTML = `${pageHeading("SOURCE LIBRARY", "Documents", "Upload a source or sync SEC filings. Each extracted passage stays linked to its document version.")}
    <div class="content-grid"><div class="stack"><section class="panel"><div class="panel-head"><div><h2>Add source documents</h2><p>PDF, HTML, or UTF-8 text · up to 15 MB per file</p></div><span class="tag">Server-side processing</span></div><div class="panel-body"><div class="drop-zone" id="drop-zone"><div><div class="drop-zone-icon">↑</div><strong>Choose a file to add evidence</strong><p>Scanned PDF images require OCR before upload.</p><input class="upload-input" type="file" id="upload-file" accept=".pdf,.htm,.html,.txt,application/pdf,text/html,text/plain" aria-label="Choose a PDF, HTML, or text file" /></div></div><div id="upload-status" class="field-help" aria-live="polite"></div></div></section><section class="panel"><div class="document-toolbar"><div><h2 class="no-margin">Indexed library</h2><span class="field-help">Latest 200 documents</span></div><input class="input" type="search" id="document-search" placeholder="Filter by company or file" aria-label="Filter documents" /></div><div id="documents-table">${spinner("Loading indexed documents…")}</div></section></div><aside class="stack"><section class="panel"><div class="panel-head"><div><h2>Source status</h2><p>Where research evidence lives</p></div></div><div class="panel-body"><div class="quick-list"><div class="quick-action"><span class="quick-icon">◉</span><span><strong>SEC EDGAR</strong><small>10-K · 10-Q · Company Facts</small></span></div><div class="quick-action"><span class="quick-icon">▤</span><span><strong>Uploaded files</strong><small>PDF · HTML · plain text</small></span></div></div><div class="callout"><span class="callout-icon">ⓘ</span><span>Every document uses a stable content hash so unchanged re-uploads do not create duplicate passages.</span></div></div></section></aside></div>`;
  await loadDocuments();
}
async function loadDocuments(query = "") {
  const target = document.getElementById("documents-table");
  if (!target) return;
  try {
    const { items, total } = await api(`/documents?q=${encodeURIComponent(query)}&limit=200&offset=0`);
    document.getElementById("document-count").textContent = total;
    target.innerHTML = items.length ? `<div class="table-wrap"><table class="document-table"><thead><tr><th>DOCUMENT</th><th>TYPE</th><th>PASSAGES</th><th>ADDED</th><th></th></tr></thead><tbody>${items.map(doc => `<tr><td><span class="doc-title"><span class="doc-symbol">▤</span><span class="doc-title-copy"><strong title="${esc(doc.title)}">${esc(doc.title)}</strong><small>${esc(doc.company_name || doc.filename || doc.source_type)}${doc.form ? ` · ${esc(doc.form)} · Filed ${dateLabel(doc.filing_date)}` : ""}</small></span></span></td><td><span class="badge ${doc.source_type === "upload" ? "neutral" : ""}">${doc.source_type === "upload" ? "Upload" : "SEC filing"}</span></td><td>${doc.passage_count}</td><td class="table-muted">${dateLabel(doc.created_at)}</td><td><button class="text-button" data-action="open-document" data-id="${esc(doc.id)}">View →</button></td></tr>`).join("")}</tbody></table></div>` : emptyState("▤", "No documents indexed yet", "Upload a file here or sync an issuer filing from the Companies page.", `<button class="button" data-page="companies">Browse companies</button>`);
  } catch (error) { target.innerHTML = `<div class="panel-body" role="alert">${esc(error.message)}</div>`; }
}
async function uploadFile(file) {
  const status = document.getElementById("upload-status");
  if (!file) return;
  status.textContent = `Processing ${file.name}…`;
  const form = new FormData(); form.append("file", file);
  try {
    const result = await api("/documents/upload", { method: "POST", body: form });
    status.textContent = `${file.name}: ${result.passageCount} passages indexed${result.created ? "" : " (already indexed)"}.`;
    toast(result.created ? "Source indexed and ready to search." : "This exact file is already indexed.");
    await loadDocuments(document.getElementById("document-search")?.value || "");
  } catch (error) { status.textContent = error.message; toast(error.message, "error"); }
}

function renderComparisonPage() {
  const companyOptions = state.companies.map(item => `<option value="${esc(item.cik)}" selected>${esc(item.name)} · ${esc(item.ticker || item.cik)}</option>`).join("");
  main.innerHTML = `${pageHeading("STRUCTURED ANALYSIS", "Compare financials", "Compare annual XBRL values across companies and fiscal years. Period, unit, and source references remain visible.")}
    <div class="content-grid"><div class="stack"><form id="compare-form" class="panel"><div class="panel-head"><div><h2>Build a comparison</h2><p>Current selection supports up to five companies</p></div><span class="tag">SEC Company Facts</span></div><div class="panel-body stack"><div><label class="field-label" for="compare-companies">Companies</label>${state.companies.length ? `<select class="select" id="compare-companies" name="companies" multiple size="${Math.min(5, Math.max(2, state.companies.length))}">${companyOptions}</select><div class="field-help">Use Ctrl or ⌘ to change the selected set. Add more companies in Companies.</div>` : `<p class="page-subtitle">Add at least two companies to your research list to begin.</p><button type="button" class="button" data-page="companies" class="gap-top-12">Browse companies →</button>`}</div><div class="compare-fields"><div><label class="field-label" for="compare-metric">Metric</label><select class="select" id="compare-metric" name="metric"><option value="revenue">Revenue</option><option value="net_income">Net income</option><option value="operating_cash_flow">Operating cash flow</option></select></div><div><label class="field-label" for="compare-periods">Fiscal years</label><select class="select" id="compare-periods" name="periods"><option value="3">3 years</option><option value="5">5 years</option><option value="10">10 years</option></select></div></div><div><button class="button primary" type="submit" ${state.companies.length < 2 ? "disabled" : ""}>Calculate comparison <span>→</span></button></div></div></form><div id="comparison-output"></div></div><aside class="stack"><section class="panel"><div class="panel-head"><div><h2>Calculation method</h2><p>Deterministic and source-linked</p></div></div><div class="panel-body"><div class="formula-box"><strong>Year-over-year change</strong><br /><code>(current − previous) ÷ |previous| × 100</code><br /><br />Facts use USD annual 10-K records and matching fiscal durations. An unavailable or incomparable prior year stays blank.</div></div></section><section class="panel"><div class="panel-head"><div><h2>Reporting periods</h2></div></div><div class="panel-body"><p class="page-subtitle">Companies do not always share a fiscal calendar. The comparison flags year ends that differ by more than 45 days.</p></div></section></aside></div>`;
}

function renderComparison(data) {
  if (!data.companies.length || !data.companies.some(item => item.periods.length)) return emptyState("▥", "No comparable facts found", "Check the company selection and metric, then retry once SEC data is available.");
  const rows = data.companies.flatMap(company => company.periods.map(period => `<tr><td><strong>${esc(company.company)}</strong><div class="table-muted">${esc(company.cik)}</div></td><td>FY${esc(period.fiscalYear)}</td><td>${money(period.value)}</td><td class="${period.growthPercent == null ? "table-muted" : Number(period.growthPercent) >= 0 ? "positive" : "negative"}">${period.growthPercent == null ? "—" : `${Number(period.growthPercent).toFixed(2)}%`}</td><td>${sourceLink(period.citation.sourceUrl, "XBRL source ↗")}</td></tr>`)).join("");
  return `<section class="panel"><div class="panel-head"><div><h2>${esc(data.metric.replaceAll("_", " "))} by fiscal year</h2><p>${data.companies.length} companies · USD · annual 10-K facts</p></div><span class="badge">Verified source facts</span></div><div class="table-wrap"><table class="compare-table"><thead><tr><th>COMPANY</th><th>PERIOD</th><th>VALUE</th><th>YOY CHANGE</th><th>SOURCE</th></tr></thead><tbody>${rows}</tbody></table></div>${data.warnings.map(warning => `<div class="callout comparison-warning">ⓘ ${esc(warning)}</div>`).join("")}<div class="panel-body"><div class="formula-box">${esc(data.formula)} · growth is blank when the prior value is zero or the periods are not comparable.</div></div></section>`;
}

async function renderReportsPage() {
  const { items } = await api("/research/recent");
  const entries = items.length ? `<div class="recent-list">${items.map(item => `<div class="recent-row"><span class="recent-icon">▧</span><button type="button" class="recent-copy recent-open" data-action="open-research" data-id="${esc(item.id)}"><strong>${esc(item.question)}</strong><small>${dateLabel(item.created_at)} · Reproducible source references</small></button><button type="button" class="button small" data-action="download-report" data-id="${esc(item.id)}">Export</button></div>`).join("")}</div>` : emptyState("▧", "No research reports yet", "Run a source-backed research question, then export it as Markdown.", `<button class="button" data-page="research">Start research</button>`);
  main.innerHTML = `${pageHeading("RESEARCH OUTPUTS", "Reports", "Export clear research notes with financial inputs, source links, caveats, and retrieval details.")}<div class="content-grid"><div class="stack"><section class="panel"><div class="panel-head"><div><h2>Saved research sessions</h2><p>Export any session as Markdown</p></div><span class="tag">${items.length} recent</span></div>${entries}</section><div id="report-preview"></div></div><aside class="stack"><section class="panel"><div class="panel-head"><div><h2>Report contents</h2></div></div><div class="panel-body"><div class="quick-list"><div class="quick-action"><span class="quick-icon">✓</span><span><strong>Research objective</strong><small>The original question and timestamp</small></span></div><div class="quick-action"><span class="quick-icon">$</span><span><strong>Source-linked metrics</strong><small>Formula inputs and SEC fact IDs</small></span></div><div class="quick-action"><span class="quick-icon">§</span><span><strong>Evidence and caveats</strong><small>Excerpts and missing information</small></span></div></div><div class="field-help">Markdown exports open in any editor. PDF export can be added after report templates are defined.</div></div></section></aside></div>`;
}

async function renderEvaluationPage() {
  const { items } = await api("/evaluations");
  const latest = items[0];
  main.innerHTML = `${pageHeading("RETRIEVAL QUALITY", "Evaluation lab", "Run a small, reproducible baseline retrieval benchmark and inspect every missed reference.", `<button class="button primary" data-action="run-evaluation">Run benchmark <span>→</span></button>`)}
    <div class="callout gap-bottom-15"><span class="callout-icon">ⓘ</span><span>The fixture corpus is synthetic and isolated from your workspace. Its scores measure baseline text retrieval only; they do not establish answer or financial accuracy.</span></div>
    <div id="evaluation-output">${latest ? renderEvaluation(latest) : emptyState("⌗", "No evaluation run yet", "Run the versioned 10-question benchmark to establish a retrieval baseline.", `<button class="button primary" data-action="run-evaluation">Run benchmark</button>`)}</div>`;
}
function renderEvaluation(result) {
  return `<div class="stack"><section class="benchmark-score"><article class="stat-card"><div class="stat-top"><span>Recall @ 5</span><span class="stat-icon">↗</span></div><div class="stat-value">${(result.recallAt5 * 100).toFixed(1)}%</div><div class="stat-foot">Relevant passage coverage</div></article><article class="stat-card"><div class="stat-top"><span>MRR</span><span class="stat-icon">#</span></div><div class="stat-value">${Number(result.mrr).toFixed(3)}</div><div class="stat-foot">First relevant rank</div></article><article class="stat-card"><div class="stat-top"><span>nDCG @ 5</span><span class="stat-icon">▥</span></div><div class="stat-value">${Number(result.ndcgAt5).toFixed(3)}</div><div class="stat-foot">Ranked relevance</div></article><article class="stat-card"><div class="stat-top"><span>Query latency</span><span class="stat-icon">◷</span></div><div class="stat-value">${Number(result.latencyMs).toFixed(1)}<span class="small-unit"> ms</span></div><div class="stat-foot">${result.questionCount} synthetic questions</div></article></section><section class="panel"><div class="panel-head"><div><h2>Run details</h2><p>${esc(result.datasetVersion)} · ${dateLabel(result.completedAt || result.createdAt)}</p></div><span class="badge">${esc(result.retrieval?.method || "SQLite FTS5 BM25")}</span></div><div class="panel-body"><div class="formula-box">Config: top K = ${result.retrieval?.topK} · ${result.passageCount} synthetic passages · SHA-256 ${esc(result.retrieval?.datasetSha256 || "—")}</div><p class="field-help gap-top-9">${esc(result.datasetNote || "")}</p>${result.failures?.length ? `<h3 class="gap-top-18">Missed references · ${result.failures.length}</h3>${result.failures.map(item => `<div class="benchmark-failure"><strong>${esc(item.question)}</strong><br />Expected ${esc(item.relevant.join(", "))} · Retrieved ${esc(item.retrieved.join(", ") || "no results")}</div>`).join("")}` : `<p class="field-help gap-top-12">Every question retrieved at least one expected passage in the top five.</p>`}</div></section></div>`;
}

async function renderSettingsPage() {
  const [settings, health] = await Promise.all([api("/settings"), api("/health")]);
  setSourceStatus(health.secConfigured, health.indexedDocuments);
  const cloud = state.authMode === "oidc";
  main.innerHTML = `${pageHeading("WORKSPACE PREFERENCES", "Settings", "Manage this private research instance and configure the SEC contact required for public data requests.")}
    <div class="content-grid"><div class="stack"><section class="panel"><div class="panel-head"><div><h2>SEC EDGAR access</h2><p>SEC requires a descriptive User-Agent with a contact email</p></div><span class="badge ${settings.secConfigured ? "" : "neutral"}">${settings.secConfigured ? "Configured" : "Needs setup"}</span></div><div class="panel-body"><form id="settings-form"><label class="field-label" for="sec-email">Contact email</label><div class="search-line"><input class="input" type="email" id="sec-email" name="email" maxlength="254" placeholder="name@example.com" autocomplete="email" required /><button class="button primary" type="submit">Save email</button></div><p class="field-help">Sent only in the SEC User-Agent header for public EDGAR requests; stored in the application data store. Current contact: ${esc(settings.contact || "not configured")}.</p></form></div></section><section class="panel"><div class="panel-head"><div><h2>${cloud ? "Instance data" : "Local data"}</h2><p>${cloud ? "Keep one application replica attached to its persistent volume" : "Workspace files stay in your configured data directory"}</p></div></div><div class="panel-body"><div class="setting-row"><span><strong>Storage mode</strong><small>${cloud ? "SQLite on a persistent single-instance volume" : "SQLite database on this device"}</small></span><span class="badge">${cloud ? "Cloud" : "Local"}</span></div><div class="setting-row"><span><strong>Documents indexed</strong><small>${health.indexedPassages.toLocaleString()} evidence passages</small></span><span>${health.indexedDocuments}</span></div><div class="setting-row"><span><strong>Research sessions</strong><small>Saved until removed from the data store</small></span><span>${(await api("/research/recent")).items.length}</span></div></div></section></div><aside class="stack"><section class="panel"><div class="panel-head"><div><h2>Privacy and access</h2></div></div><div class="panel-body"><p class="page-subtitle">${cloud ? "Sign-in uses your configured OpenID Connect provider and email allowlist. All allowed users share this instance's research data." : "This local profile is for one researcher on a trusted device."}</p><div class="callout"><span class="callout-icon">ⓘ</span><span>${cloud ? "Use one deployment per organization. This SQLite profile requires one application replica and persistent-volume backups." : "Keep the data directory private and run the service on a trusted device."}</span></div></div></section><section class="panel"><div class="panel-head"><div><h2>Service health</h2></div></div><div class="panel-body"><span class="inline-status"><span class="status-dot ok"></span> API is ready</span><p class="field-help">Last checked ${dateLabel(health.timestamp)}</p></div></section></aside></div>`;
  const providerInfo = settings.generationEnabled
    ? `Configured model: ${esc(settings.generationModel)} · output cap ${settings.generationMaxTokens} tokens. The provider receives the research question, up to eight retrieved passages, and relevant verified facts.`
    : 'Disabled. No indexed passages are sent to a language model.';
  main.querySelector('.content-grid > aside').insertAdjacentHTML('afterbegin', `<section class="panel"><div class="panel-head"><div><h2>Answer generation</h2><p>${settings.generationEnabled ? 'Provider configured' : 'Deterministic mode'}</p></div></div><div class="panel-body"><p class="page-subtitle">${providerInfo}</p></div></section>`);}

function setSourceStatus(connected, documents) {
  const target = document.getElementById("sidebar-status");
  if (!target) return;
  target.innerHTML = `<span class="status-dot ${connected ? "ok" : "warn"}"></span><span><strong>${connected ? "SEC connected" : "SEC needs setup"}</strong><small>${documents} indexed source${documents === 1 ? "" : "s"}</small></span>`;
}

async function openDocument(id, activePassage = "") {
  const dialog = document.getElementById("evidence-dialog");
  const body = document.getElementById("dialog-body");
  document.getElementById("dialog-title").textContent = "Evidence viewer";
  body.innerHTML = spinner("Opening source document…");
  dialog.showModal();
  try {
    const endpoint = activePassage ? `/documents/${encodeURIComponent(id)}/evidence/${encodeURIComponent(activePassage)}` : `/documents/${encodeURIComponent(id)}`;
    const data = await api(endpoint);
    const documentInfo = data.document;
    document.getElementById("dialog-title").textContent = documentInfo.title;
    body.innerHTML = `<div class="evidence-meta"><span class="badge">${esc(documentInfo.company_name || documentInfo.source_type)}</span><span>${esc(documentInfo.form || "Local upload")}</span><span>${dateLabel(documentInfo.filing_date || documentInfo.created_at)}</span><span>${data.passages.length} passages</span></div>${documentInfo.source_url ? `<p>${sourceLink(documentInfo.source_url, "Open original source ↗")}</p>` : ""}<div class="stack">${data.passages.map(passage => `<article class="dialog-passage ${passage.id === activePassage ? "active" : ""}" id="passage-${esc(passage.id)}"><small>${passage.heading ? `§ ${esc(passage.heading)} · ` : ""}${passage.page ? `Page ${passage.page} · ` : ""}Passage ${passage.ordinal + 1}</small><p>${esc(passage.text)}</p></article>`).join("")}</div>`;
    if (activePassage) document.getElementById(`passage-${CSS.escape(activePassage)}`)?.scrollIntoView({ block: "center" });
  } catch (error) { body.innerHTML = `<div class="callout" role="alert">${esc(error.message)}</div>`; }
}

async function runResearch(form) {
  const submit = form.querySelector('[type="submit"]');
  const output = document.getElementById("research-output");
  const companies = [...form.querySelectorAll('input[name="research-company"]:checked')].map(item => item.value);
  submit.disabled = true; submit.innerHTML = `<span class="spinner"></span> Searching…`;
  output.innerHTML = spinner("Searching indexed passages and verified facts…");
  try {
    const result = await api("/research/query", { method: "POST", body: JSON.stringify({ question: form.elements.question.value, companies, includeFinancials: form.elements.includeFinancials.checked }) });
    state.activeResearch = result;
    output.innerHTML = renderResearchResult(result);
  } catch (error) { output.innerHTML = `<div class="callout" role="alert">${esc(error.message)}</div>`; toast(error.message, "error"); }
  finally { submit.disabled = false; submit.innerHTML = "Find evidence <span>→</span>"; }
}

async function openResearch(id) {
  try {
    const result = await api(`/research/${encodeURIComponent(id)}`);
    state.activeResearch = result;
    setPage("research");
  } catch (error) { toast(error.message, "error"); }
}

async function downloadReport(id) {
  if (!id) { toast("Run a research question before exporting a report.", "error"); return; }
  try {
    const result = await api(`/reports/${encodeURIComponent(id)}`);
    const file = new Blob([result.content], { type: "text/markdown;charset=utf-8" });
    const link = document.createElement("a"); link.href = URL.createObjectURL(file); link.download = result.filename; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    toast("Markdown report exported.");
  } catch (error) { toast(error.message, "error"); }
}

async function runComparison(form) {
  const selected = [...form.elements.companies.selectedOptions].map(item => item.value);
  if (selected.length < 2) { toast("Select at least two companies.", "error"); return; }
  const target = document.getElementById("comparison-output");
  target.innerHTML = spinner("Loading comparable SEC annual facts…");
  try {
    const data = await api("/research/compare", { method: "POST", body: JSON.stringify({ companies: selected, metric: form.elements.metric.value, periods: Number(form.elements.periods.value) }) });
    target.innerHTML = renderComparison(data);
  } catch (error) { target.innerHTML = `<div class="callout" role="alert">${esc(error.message)}</div>`; toast(error.message, "error"); }
}

async function runEvaluation(button) {
  const original = button.innerHTML;
  button.disabled = true; button.innerHTML = `<span class="spinner"></span> Evaluating…`;
  const output = document.getElementById("evaluation-output");
  if (output) output.innerHTML = spinner("Running the versioned retrieval benchmark…");
  try {
    const result = await api("/evaluations/run", { method: "POST", body: "{}" });
    if (output?.isConnected) output.innerHTML = renderEvaluation(result);
    toast("Evaluation run completed.");
  } catch (error) { if (output?.isConnected) output.innerHTML = `<div class="callout" role="alert">${esc(error.message)}</div>`; toast(error.message, "error"); }
  finally { if (button.isConnected) { button.disabled = false; button.innerHTML = original; } }
}

async function saveSettings(form) {
  const button = form.querySelector('[type="submit"]'); button.disabled = true;
  try {
    await api("/settings/sec-contact", { method: "PUT", body: JSON.stringify({ email: form.elements.email.value }) });
    toast("SEC contact saved."); await renderSettingsPage();
  } catch (error) { toast(error.message, "error"); }
  finally { if (button.isConnected) button.disabled = false; }
}

async function syncFiling(button) {
  button.disabled = true; button.textContent = "Queued…";
  try {
    const job = await api("/documents/sync", { method: "POST", body: JSON.stringify({ cik: button.dataset.cik, form: button.dataset.form, accession: button.dataset.accession }) });
    toast("SEC filing ingestion started.");
    pollJob(job.jobId, button);
  } catch (error) { button.disabled = false; button.textContent = "Sync"; toast(error.message, "error"); }
}
async function pollJob(id, button, attempts = 0) {
  try {
    const job = await api(`/jobs/${encodeURIComponent(id)}`);
    if (job.status === "complete") {
      const health = await api("/health").catch(() => null);
      if (health) { document.getElementById("document-count").textContent = health.indexedDocuments; setSourceStatus(health.secConfigured, health.indexedDocuments); }
      toast(job.detail); button.disabled = false; button.textContent = "Synced"; button.classList.remove("soft");
      setTimeout(() => renderCompaniesPage(), 1000); return;
    }
    if (job.status === "failed") { toast(job.detail, "error"); button.disabled = false; button.textContent = "Retry"; return; }
    button.textContent = job.status === "queued" ? "Queued…" : "Indexing…";
    if (attempts < 120) setTimeout(() => pollJob(id, button, attempts + 1), 1500);
    else { button.disabled = false; button.textContent = "Check status"; toast("Ingestion is still running; check the document library shortly.", "error"); }
  } catch (error) { button.disabled = false; button.textContent = "Retry"; toast(error.message, "error"); }
}

document.addEventListener("click", event => {
  const page = event.target.closest("[data-page]");
  if (page) { event.preventDefault(); setPage(page.dataset.page); return; }
  const action = event.target.closest("[data-action]");
  if (!action) return;
  if (action.dataset.action === "refresh-page") renderPage();
  if (action.dataset.action === "open-demo") document.getElementById("demo-dialog").showModal();
  if (action.dataset.action === "close-demo") document.getElementById("demo-dialog").close();
  if (action.dataset.action === "begin-demo") setPage(document.getElementById("demo-dialog").dataset.secConfigured === "true" ? "companies" : "settings");
  if (action.dataset.action === "add-company") {
    if (state.companies.length >= 5) return toast("A maximum of five companies can be saved.", "error");
    const company = { cik: String(Number(action.dataset.cik)), name: action.dataset.name, ticker: action.dataset.ticker };
    if (!state.companies.some(item => item.cik === company.cik)) { state.companies.push(company); saveCompanies(); toast(`${company.name} added.`); }
    if (state.page === "companies") { renderCompaniesPage(); }
  }
  if (action.dataset.action === "remove-company") {
    state.companies = state.companies.filter(item => item.cik !== action.dataset.cik); saveCompanies(); renderCompaniesPage();
  }
  if (action.dataset.action === "sync-filing") syncFiling(action);
  if (action.dataset.action === "open-document") openDocument(action.dataset.id, action.dataset.passage || "");
  if (action.dataset.action === "close-dialog") document.getElementById("evidence-dialog").close();
  if (action.dataset.action === "open-research") openResearch(action.dataset.id);
  if (action.dataset.action === "download-report") downloadReport(action.dataset.id);
  if (action.dataset.action === "run-evaluation") runEvaluation(action);
});

document.addEventListener("submit", event => {
  event.preventDefault();
  if (event.target.id === "research-form") runResearch(event.target);
  if (event.target.id === "compare-form") runComparison(event.target);
  if (event.target.id === "settings-form") saveSettings(event.target);
});

document.addEventListener("input", event => {
  if (event.target.id === "company-search") {
    clearTimeout(state.searchTimer);
    const query = event.target.value;
    state.searchTimer = setTimeout(() => searchCompanies(query), 280);
  }
  if (event.target.id === "document-search") {
    clearTimeout(state.documentTimer);
    const query = event.target.value;
    state.documentTimer = setTimeout(() => loadDocuments(query), 220);
  }
});

document.addEventListener("change", event => { if (event.target.id === "upload-file") uploadFile(event.target.files[0]); });
document.addEventListener("dragenter", event => {
  const zone = event.target.closest?.("#drop-zone");
  if (zone) { event.preventDefault(); zone.classList.add("dragging"); }
});
document.addEventListener("dragover", event => {
  const zone = event.target.closest?.("#drop-zone");
  if (zone) event.preventDefault();
});
document.addEventListener("dragleave", event => {
  const zone = event.target.closest?.("#drop-zone");
  if (zone) { event.preventDefault(); zone.classList.remove("dragging"); }
});
document.addEventListener("drop", event => {
  const zone = event.target.closest?.("#drop-zone");
  if (zone) { event.preventDefault(); zone.classList.remove("dragging"); uploadFile(event.dataTransfer.files[0]); }
});
document.getElementById("mobile-menu").addEventListener("click", () => { document.getElementById("sidebar").classList.add("open"); document.getElementById("mobile-scrim").classList.add("open"); });
document.getElementById("mobile-scrim").addEventListener("click", () => { document.getElementById("sidebar").classList.remove("open"); document.getElementById("mobile-scrim").classList.remove("open"); });
document.getElementById("today-date").textContent = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(new Date());
document.getElementById("sign-out").addEventListener("click", async () => {
  try {
    const response = await fetch("/auth/logout", { method: "POST" });
    if (!response.ok) throw new Error("Sign-out failed. Try again.");
    location.assign("/auth/signed-out");
  } catch (error) {
    toast(error.message, "error");
  }
});
startApp().catch(error => {
  main.innerHTML = `<div class="callout" role="alert">${esc(error.message || "Could not verify your sign-in.")}</div>`;
});

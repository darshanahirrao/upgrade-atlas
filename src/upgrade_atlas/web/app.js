"use strict";
const $ = (id) => document.getElementById(id);
let packet = null;
let liveReady = false;
let busy = false;

function node(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}
function list(id, values) { $(id).replaceChildren(...values.map((value) => node("li", value))); }
function purpose(value) { return value.replaceAll("_", " "); }
async function status() {
  try {
    const result = await fetch("/api/status").then((response) => response.json());
    liveReady = result.live_ready;
    $("readiness").textContent = liveReady ? "SerpApi live ready" : "Live key not configured";
    $("budget").textContent = `${result.local_calls} / ${result.local_budget} searches`;
  } catch {
    liveReady = false;
    $("readiness").textContent = "Local server unavailable";
  }
  $("research").disabled = !liveReady || busy;
}
function render(value) {
  packet = value;
  const report = value.report;
  $("empty").hidden = true;
  $("report").hidden = false;
  $("mode").textContent = report.mode === "synthetic_example"
    ? "SYNTHETIC EXAMPLE: not live evidence" : "LIVE SERPAPI SEARCH EVIDENCE";
  $("pair").textContent = `${report.package}: ${report.current} \u2192 ${report.target}`;
  $("timestamp").textContent = `Retrieved ${new Date(report.retrieved_at).toLocaleString()}`;
  $("coverage").replaceChildren(...report.coverage.map((item) => {
    const row = document.createElement("tr");
    row.append(node("td", purpose(item.purpose)), node("td", item.source_ids.join(", ") || "No exact-target source"));
    return row;
  }));
  list("gaps", report.review_gaps);
  list("limits", report.limits);
  $("sources").replaceChildren(...report.sources.map((source) => {
    const row = document.createElement("article"); row.className = "source";
    const link = node("a", source.url, "url");
    link.href = source.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    row.append(node("h4", `${source.id}. ${source.title}`), link,
      node("p", source.snippet || "No search snippet returned."),
      node("p", source.exact_target_mention ? "Exact target version mentioned" : "Target version not explicitly mentioned", "source-meta"),
      node("p", `Search IDs: ${source.search_ids.join(", ")}`, "provenance"));
    return row;
  }));
  if (!report.sources.length) $("sources").append(node("p", "No allowlisted primary-source result returned."));
  $("searches").replaceChildren(...report.searches.map((search) => {
    const row = document.createElement("article"); row.className = "search";
    row.append(node("p", `${purpose(search.purpose)}: ${search.state}${search.local_cache ? " (local cache)" : ""}`),
      node("p", search.query, "query"),
      node("p", search.error || `Search ID: ${search.search_id}; excluded: ${search.excluded}`, "provenance"));
    return row;
  }));
}
async function request(url, options) {
  busy = true; $("research").disabled = true; $("example").disabled = true;
  $("research").textContent = "Researching..."; $("error").hidden = true;
  try {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Request failed.");
    render(result);
  } catch (error) {
    $("error").textContent = error instanceof TypeError
      ? "Local server unavailable. Restart Upgrade Atlas and try again." : error.message;
    $("error").hidden = false;
  } finally {
    busy = false; $("example").disabled = false; $("research").textContent = "Research upgrade";
    await status();
  }
}
$("research-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy || !liveReady) return;
  request("/api/research", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(Object.fromEntries(new FormData(event.target)))});
});
$("example").addEventListener("click", () => request("/api/example"));
function download(format) {
  if (!packet) return;
  const blob = new Blob([format === "json" ? JSON.stringify(packet.report, null, 2) : packet.markdown],
    {type: format === "json" ? "application/json" : "text/markdown"});
  const url = URL.createObjectURL(blob); const link = document.createElement("a");
  link.href = url; link.download = `upgrade-atlas-${packet.report.package}.${format === "json" ? "json" : "md"}`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("json-export").addEventListener("click", () => download("json"));
$("md-export").addEventListener("click", () => download("md"));
$("theme").addEventListener("change", (event) => {
  if (event.target.value === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = event.target.value;
});
status();

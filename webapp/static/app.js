let buildings = [];      // {entity_id,name,width,length,needs_road,is_townhall, removed?}
let added = [];          // {width,length,needs_road,name}
let lastMap = "";

const $ = (id) => document.getElementById(id);

// Parse a response body as JSON, but check status FIRST: an error response may
// be an HTML page (e.g. a 500), and calling .json() on it throws. Without this
// guard a single failed request leaves the UI frozen on "running" forever.
async function jsonOrThrow(resp) {
  let body = null;
  try { body = await resp.json(); } catch { /* non-JSON body (HTML error page) */ }
  if (!resp.ok) throw new Error((body && body.error) || `server error ${resp.status}`);
  if (body === null) throw new Error("server returned an unreadable response");
  return body;
}

function renderTable() {
  const tb = $("building-table").querySelector("tbody");
  tb.innerHTML = "";
  const rows = [
    ...buildings.map((b, i) => ({ b, i, kind: "loaded" })),
    ...added.map((b, i) => ({ b, i, kind: "added" })),
  ];
  for (const { b, i, kind } of rows) {
    const tr = document.createElement("tr");
    const lockable = kind === "loaded" && b.is_townhall;
    const keep = kind === "added" || !b.removed;
    tr.className = keep ? "" : "removed";
    tr.innerHTML =
      `<td><input type="checkbox" ${keep ? "checked" : ""} ${lockable ? "disabled" : ""}></td>` +
      `<td>${b.name}${b.is_townhall ? " (TH)" : ""}</td>` +
      `<td>${b.width}×${b.length}</td><td>${b.needs_road ? "✓" : ""}</td>`;
    const cb = tr.querySelector("input");
    cb.onchange = () => {
      if (kind === "loaded") b.removed = !cb.checked;
      else if (!cb.checked) { added.splice(i, 1); renderTable(); }
    };
    tb.appendChild(tr);
  }
}

$("load-btn").onclick = async () => {
  if (!$("city-file").files[0]) return;
  const fd = new FormData();
  fd.append("city", $("city-file").files[0]);
  if ($("helper-file").files[0]) fd.append("helper", $("helper-file").files[0]);
  try {
    const j = await jsonOrThrow(await fetch("/load", { method: "POST", body: fd }));
    buildings = j.buildings.map((b) => ({ ...b, removed: false }));
    added = [];
    $("load-info").textContent = `${j.buildings.length} buildings · region ${j.region_cells} cells · estimate ${j.road_estimate} roads`;
    $("run-btn").disabled = false;
    renderTable();
  } catch (e) {
    $("load-info").innerHTML = `<span class="err">${e.message}</span>`;
  }
};

$("add-form").onsubmit = (e) => {
  e.preventDefault();
  added.push({
    width: +$("add-w").value, length: +$("add-l").value,
    needs_road: $("add-road").checked, name: $("add-name").value || null,
  });
  e.target.reset();
  renderTable();
};

$("mode").onchange = () => {
  const sweep = $("mode").value === "sweep";
  $("sweep-opts").hidden = !sweep;
  $("repack-opts").hidden = sweep;
};

$("polish").onchange = () => { $("polish-opts").hidden = !$("polish").checked; };

$("run-btn").onclick = async () => {
  const body = {
    remove_ids: buildings.filter((b) => b.removed).map((b) => b.entity_id),
    add_specs: added,
    mode: $("mode").value,
    budget: +$("budget").value,
    seed: +$("seed").value,
    seeds: +$("seeds").value,
    polish: $("polish").checked,
    anneal_budget: +$("anneal-budget").value,
  };
  $("run-btn").disabled = true;
  $("run-status").textContent = "running…";
  try {
    const j = await jsonOrThrow(await fetch("/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }));
    poll(j.job_id);
  } catch (e) {
    $("run-status").innerHTML = `<span class="err">${e.message}</span>`;
    $("run-btn").disabled = false;
  }
};

async function poll(id, fails = 0) {
  let st;
  try {
    st = await jsonOrThrow(await fetch(`/status/${id}`));
  } catch (e) {
    // Transient hiccup (server busy under a sweep, dropped connection): retry a
    // few times rather than freezing. Give up loudly after persistent failure.
    if (fails < 5) { setTimeout(() => poll(id, fails + 1), 1000); return; }
    $("run-status").innerHTML = `<span class="err">lost contact with server: ${e.message}</span>`;
    $("run-btn").disabled = false;
    return;
  }
  $("run-status").textContent = `${st.state} (${st.elapsed}s)`;
  if (st.state === "running") { setTimeout(() => poll(id), 1000); return; }
  $("run-btn").disabled = false;
  if (st.state === "error") { $("stats").innerHTML = `<span class="err">${st.error}</span>`; return; }
  const res = st.result;
  const gain = (res.base_roads != null && res.base_roads !== res.roads) ? ` (from ${res.base_roads})` : "";
  $("stats").textContent = `placed ${res.placed} · unplaced ${res.unplaced} · roads ${res.roads}${gain} (est ${res.estimate}) · ${res.valid ? "valid" : "partial"}`;
  // render_html returns a full HTML document with its own <script> (the canvas
  // renderer). Scripts injected via innerHTML never run, so the map must go in
  // an iframe via srcdoc, which executes the document in its own context.
  const frame = document.createElement("iframe");
  frame.title = "city map";
  frame.srcdoc = res.map_html;
  $("map").replaceChildren(frame);
  lastMap = res.map_html;
  $("download-btn").hidden = false;
}

$("download-btn").onclick = () => {
  const blob = new Blob([lastMap], { type: "text/html" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "layout.html"; a.click();
};

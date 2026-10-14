"use strict";

const $ = (id) => document.getElementById(id);
const state = { project: null, manual: null, sel: null, dirty: false, busy: false, saveTimer: null };

// ---------- API ----------
async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
const P = () => `/api/p/${encodeURIComponent(state.project)}`;
const fileUrl = (rel) => `/files/${encodeURIComponent(state.project)}/${rel}`;

function setStatus(msg) { $("status").textContent = msg; }

async function withBusy(text, fn) {
  if (state.busy) return;
  await flushSave();
  state.busy = true;
  $("busyText").textContent = text;
  $("busy").hidden = false;
  try { return await fn(); }
  catch (e) { alert(e.message); }
  finally { state.busy = false; $("busy").hidden = true; }
}

// ---------- 保存 ----------
function markDirty() {
  state.dirty = true;
  setStatus("未保存…");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(flushSave, 600);
}
async function flushSave() {
  clearTimeout(state.saveTimer);
  if (!state.dirty || !state.manual) return;
  state.dirty = false;
  try {
    await api("PUT", `${P()}/manual`, state.manual);
    setStatus("保存しました " + new Date().toLocaleTimeString());
  } catch (e) {
    state.dirty = true;
    setStatus("保存失敗: " + e.message);
  }
}
function markEdited(obj, key) {
  obj.edited = obj.edited || [];
  if (!obj.edited.includes(key)) obj.edited.push(key);
}

// ---------- 描画 ----------
const curStep = () => state.manual?.steps.find((s) => s.id === state.sel) || null;

function render() {
  const m = state.manual;
  for (const el of document.querySelectorAll("#meta [data-key]")) {
    if (document.activeElement !== el) el.value = m[el.dataset.key] ?? "";
  }
  if (!m.steps.some((s) => s.id === state.sel)) state.sel = m.steps[0]?.id ?? null;
  renderList();
  renderStep();
}

function renderList() {
  const box = $("steps");
  box.innerHTML = "";
  let n = 0;
  let prevSection = null;
  state.manual.steps.forEach((s, idx) => {
    const num = s.include ? ++n : null;
    if ((s.section || "") !== prevSection && (s.section || prevSection)) {
      const h = document.createElement("div");
      h.className = "section-head";
      h.textContent = s.section || "（章なし）";
      box.appendChild(h);
    }
    prevSection = s.section || "";
    const div = document.createElement("div");
    div.className = "step" + (s.id === state.sel ? " sel" : "") + (s.include ? "" : " excluded");
    div.draggable = true;
    div.innerHTML = `
      <img loading="lazy" src="${fileUrl(s.image)}">
      <div><div class="num">${num ? "手順 " + num : "除外"} · #${s.id}</div>
      <div class="title"></div></div>
      <div class="ops">
        <button data-op="up" title="上へ">↑</button>
        <button data-op="down" title="下へ">↓</button>
      </div>`;
    div.querySelector(".title").textContent = s.title || "（未設定）";
    div.onclick = (e) => {
      const op = e.target.dataset?.op;
      if (op) { e.stopPropagation(); move(idx, op === "up" ? idx - 1 : idx + 1); return; }
      state.sel = s.id;
      renderList();
      renderStep();
    };
    div.ondragstart = (e) => e.dataTransfer.setData("text/plain", String(idx));
    div.ondragover = (e) => { e.preventDefault(); div.classList.add("dragover"); };
    div.ondragleave = () => div.classList.remove("dragover");
    div.ondrop = (e) => {
      e.preventDefault();
      div.classList.remove("dragover");
      move(Number(e.dataTransfer.getData("text/plain")), idx);
    };
    box.appendChild(div);
  });
}

function move(from, to) {
  const steps = state.manual.steps;
  if (to < 0 || to >= steps.length || from === to) return;
  const [s] = steps.splice(from, 1);
  steps.splice(to, 0, s);
  markDirty();
  renderList();
  renderStep();
}

function renderStep() {
  const s = curStep();
  $("noStep").hidden = !!s;
  $("stepForm").hidden = !s;
  $("imgWrap").hidden = !s;
  if (!s) return;
  const included = state.manual.steps.filter((x) => x.include);
  const num = included.indexOf(s) + 1;
  $("stepHeading").textContent = num ? `手順 ${num}` : "（PDFから除外中）";
  for (const el of document.querySelectorAll("#stepForm [data-key]")) {
    if (document.activeElement !== el) el.value = s[el.dataset.key] ?? "";
  }
  const sections = [...new Set(state.manual.steps.map((x) => x.section).filter(Boolean))];
  $("sectionList").innerHTML = "";
  for (const sec of sections) $("sectionList").append(new Option(sec));
  $("sHighlight").checked = s.highlight;
  $("sInclude").checked = s.include;

  const img = $("shot");
  const src = fileUrl(s.image);
  if (img.getAttribute("src") !== src) img.src = src;
  renderMarker();

  const info = [
    ["操作", s.trigger === "hotkey" ? "手動撮影" : (s.click?.button === "right" ? "右クリック" : "クリック")],
    ["UI要素", s.element ? `${s.element.name} (${s.element.control_type})` : "—"],
    ["入力", s.typed_text || "—"],
    ["ウィンドウ", s.window_title || "—"],
    ["プロセス", s.process || "—"],
    ["時刻", s.time || "—"],
  ];
  const dl = $("stepInfo");
  dl.innerHTML = "";
  for (const [k, v] of info) {
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  }
}

function renderMarker() {
  const s = curStep();
  const mk = $("marker");
  if (!s || !s.click || !s.highlight) { mk.hidden = true; return; }
  mk.hidden = false;
  mk.style.left = s.click.x * 100 + "%";
  mk.style.top = s.click.y * 100 + "%";
}

// ---------- イベント ----------
for (const el of document.querySelectorAll("#meta [data-key]")) {
  el.addEventListener("input", () => {
    state.manual[el.dataset.key] = el.value;
    markEdited(state.manual, el.dataset.key);
    markDirty();
  });
}
for (const el of document.querySelectorAll("#stepForm [data-key]")) {
  el.addEventListener("input", () => {
    const s = curStep();
    s[el.dataset.key] = el.value;
    markEdited(s, el.dataset.key);
    markDirty();
    if (el.dataset.key === "title" || el.dataset.key === "section") renderList();
  });
}
$("sHighlight").onchange = (e) => { curStep().highlight = e.target.checked; markDirty(); renderMarker(); };
$("sInclude").onchange = (e) => { curStep().include = e.target.checked; markDirty(); renderList(); renderStep(); };

$("shot").onclick = (e) => {
  const s = curStep();
  const r = e.target.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
  s.click = { x: +x.toFixed(4), y: +y.toFixed(4), button: s.click?.button || "left" };
  s.highlight = true;
  markDirty();
  renderStep();
};

for (const b of document.querySelectorAll(".tabs [data-tab]")) {
  b.onclick = () => showTab(b.dataset.tab);
}
function showTab(tab) {
  for (const b of document.querySelectorAll(".tabs [data-tab]")) b.classList.toggle("active", b.dataset.tab === tab);
  $("imageView").hidden = tab !== "image";
  $("imgHint").hidden = tab !== "image";
  $("pdfView").hidden = tab !== "pdf";
}

$("deleteStep").onclick = async () => {
  const s = curStep();
  if (!confirm(`#${s.id} を削除しますか？（画像ファイルも削除されます）`)) return;
  await flushSave();
  state.manual = await api("DELETE", `${P()}/steps/${s.id}`);
  render();
};

$("describeOne").onclick = () => withBusy("Claude が説明を書いています…", async () => {
  const s = curStep();
  state.manual = await api("POST", `${P()}/describe`, { step_ids: [s.id], force: true });
  render();
});

$("describeAll").onclick = () => withBusy("Claude が全ステップの説明を書いています…（数分かかることがあります）", async () => {
  state.manual = await api("POST", `${P()}/describe`, { force: $("force").checked });
  render();
});

$("build").onclick = () => withBusy("PDF を作成しています…", async () => {
  const r = await api("POST", `${P()}/build`);
  $("pdfView").src = r.pdf + "?t=" + Date.now();
  showTab("pdf");
  setStatus("PDFを作成しました（編集用Typst: " + r.typ + "）");
});

$("restructureOpen").onclick = () => $("restructureDlg").showModal();
$("restructureDlg").addEventListener("close", () => {
  if ($("restructureDlg").returnValue !== "run") return;
  withBusy("Claude がマニュアルを再構成しています…（数分かかることがあります）", async () => {
    const r = await api("POST", `${P()}/restructure`, { instruction: $("rsInstruction").value });
    state.manual = r.manual;
    render();
    $("changesText").textContent = r.changes || "（変更の要約はありません）";
    $("changesDlg").showModal();
  });
});

$("undo").onclick = async () => {
  if (!confirm("直前の再構成の前の状態に戻しますか？（それ以降の編集は失われます）")) return;
  await flushSave();
  try {
    const r = await api("POST", `${P()}/undo`);
    state.manual = r.manual;
    render();
    setStatus(r.restored + " の状態に戻しました");
  } catch (e) { alert(e.message); }
};

$("record").onclick = async () => {
  await flushSave();
  try {
    await api("POST", `${P()}/record`, { fullscreen: $("fullscreen").checked });
    setStatus("記録中（Ctrl+Shift+Q で終了）— ステップは自動で追加されます");
  } catch (e) { alert(e.message); }
};

$("newProject").onclick = async () => {
  const name = prompt("プロジェクト名（英数字・日本語可、/ は不可）");
  if (!name) return;
  try {
    await api("POST", "/api/projects", { name });
    await loadProjects(name);
  } catch (e) { alert(e.message); }
};

$("project").onchange = async (e) => {
  await flushSave();
  openProject(e.target.value);
};

// ---------- 読み込み ----------
async function loadProjects(select) {
  const list = await api("GET", "/api/projects");
  const sel = $("project");
  sel.innerHTML = "";
  for (const n of list) sel.add(new Option(n, n));
  const want = select || decodeURIComponent(location.hash.slice(1)) || list[0];
  if (want && list.includes(want)) {
    sel.value = want;
    await openProject(want);
  }
}

async function openProject(name) {
  state.project = name;
  state.sel = null;
  location.hash = encodeURIComponent(name);
  state.manual = await api("GET", `${P()}/manual`);
  $("pdfView").src = "about:blank";
  showTab("image");
  render();
}

// 記録中に追加されたステップや CLI での変更を反映する
setInterval(async () => {
  if (!state.project || state.dirty || state.busy || document.hidden) return;
  try {
    const m = await api("GET", `${P()}/manual`);
    if (JSON.stringify(m) !== JSON.stringify(state.manual) && !state.dirty) {
      state.manual = m;
      render();
    }
  } catch {}
}, 2000);

window.addEventListener("beforeunload", () => { if (state.dirty) flushSave(); });
loadProjects();

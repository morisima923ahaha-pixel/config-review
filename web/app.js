// Config再鑑アシスタント（Web 版）の画面の動き。
// 計算は Python のツール本体（src/config_review/）を、Pyodide でブラウザの中で動かして行う。
// ここでは、ボタン・タブ・入力欄の動きと、Python とのやりとりだけを書く。
//
// 結果は必ず textContent で画面に出す（innerHTML は使わない）。
// Config に「<script>」のような文字があっても、HTML として動かないようにするため。
"use strict";

const $ = (id) => document.getElementById(id);
const state = { bridge: null, manifest: null, lastResult: null };
const views = { diff: $("view-diff"), expected: $("view-expected"), notes: $("view-notes") };

function setStatus(text, alert = false) {
  $("status").textContent = text;
  $("status").classList.toggle("alert", alert);
}

// 結果の欄に行を出す。tag は色の名前（removed・added・context・error・warning）
function show(view, lines) {
  view.replaceChildren();
  for (const [text, tag] of lines) {
    const line = document.createElement("span");
    line.className = "line" + (tag ? " " + tag : "");
    line.textContent = text + "\n";
    view.append(line);
  }
}

function selectTab(name, focus = false) {
  for (const [key, view] of Object.entries(views)) {
    const tab = $("tab-" + key);
    view.hidden = key !== name;
    tab.setAttribute("aria-selected", String(key === name));
    // Tab キーで止まるのは選んでいるタブだけ。ほかのタブへは矢印キーで動く（ふつうのタブの操作）
    tab.tabIndex = key === name ? 0 : -1;
    if (focus && key === name) tab.focus();
  }
}

function onTabKey(event) {
  const keys = Object.keys(views);
  const index = keys.indexOf(currentTab());
  const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: keys.length - 1 }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  selectTab(keys[(next + keys.length) % keys.length], true);
}

function currentTab() {
  return Object.keys(views).find((key) => !views[key].hidden);
}

async function fetchText(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} を読み込めませんでした（${response.status}）`);
  return response.text();
}

// 一覧の中身が、組み立てたときの形どおりか（ファイル名に「/」や「..」が入っていないか など）を確かめる
function checkManifest(manifest) {
  const demo = manifest.demo;
  const ok =
    demo !== null && typeof demo === "object" &&
    typeof demo.current === "string" && Array.isArray(demo.scenes) &&
    Array.isArray(manifest.modules) &&
    manifest.modules.every((name) => /^[a-z_]+\.py$/.test(name)) &&
    /^([0-9a-f]{7}|local)$/.test(manifest.commit) &&
    /^[0-9.]+$/.test(manifest.pyodide) &&
    [demo.current, ...demo.scenes].every((name) => /^[^/\\]+\.txt$/.test(name));
  if (!ok) throw new Error("manifest.json の中身がおかしいので、読み込みを止めました");
}

// ---- 準備：Pyodide と、ツール本体の Python のファイルを読み込む ----
async function start() {
  try {
    // 一覧は毎回新しいものを読む。ほかのファイルには commit の番号をつけて、公開した直後に
    // 古いファイル（ブラウザや GitHub Pages のキャッシュ）と新しいファイルがまざらないようにする
    const manifest = JSON.parse(await fetchText("manifest.json", { cache: "no-cache" }));
    checkManifest(manifest);
    const version = "?v=" + encodeURIComponent(manifest.commit);
    state.manifest = manifest;
    $("pyodide-version").textContent = manifest.pyodide;

    // indexURL を自分のサイトの pyodide/ にする（CDN からは読まない）
    const pyodide = await loadPyodide({ indexURL: new URL("pyodide/", document.baseURI).href });
    const home = "/home/pyodide";
    pyodide.FS.mkdirTree(`${home}/config_review`);
    for (const name of manifest.modules) {
      pyodide.FS.writeFile(`${home}/config_review/${name}`, await fetchText(`py/config_review/${name}${version}`));
    }
    pyodide.FS.writeFile(`${home}/bridge.py`, await fetchText("bridge.py" + version));
    pyodide.runPython(`import sys\nif "${home}" not in sys.path: sys.path.insert(0, "${home}")`);
    state.bridge = pyodide.pyimport("bridge");
    state.pyodide = pyodide;

    $("build-info").textContent = `commit ${manifest.commit}・Python ${state.bridge.python_version()}`;
    makeDemoButtons(manifest.demo);
    $("run").disabled = false;
    setStatus("①と②を貼り付けて「比較する」を押してください（上のデモのボタンでも試せます）");
  } catch (error) {
    console.error(error);
    setStatus(`準備に失敗しました。ページを読み込み直してください。（${error.message}）`, true);
  }
}

// ---- デモ：左に共通の現行 Config、右に場面の投入 Config を入れて比べる ----
function makeDemoButtons(demo) {
  const area = $("demo-buttons");
  for (const file of demo.scenes) {
    const button = document.createElement("button");
    button.type = "button";
    // 「1_物理インターフェースの設定変更.txt」→「1 物理インターフェースの設定変更」
    button.textContent = file.replace(/\.txt$/, "").replace("_", " ");
    button.addEventListener("click", () => loadDemo(demo.current, file));
    area.append(button);
  }
}

async function loadDemo(currentFile, sceneFile) {
  try {
    $("current").value = await fetchText("demo/" + encodeURIComponent(currentFile));
    $("changes").value = await fetchText("demo/" + encodeURIComponent(sceneFile));
    run();
  } catch (error) {
    setStatus(error.message, true);
  }
}

// ---- 比較する ----
function run() {
  if (!state.bridge) return;
  const result = JSON.parse(state.bridge.view($("current").value, $("changes").value));
  if (!result.ok) {
    // 前の結果を残すと、コピー・保存で今の入力の結果とまちがえるので消す
    state.lastResult = null;
    for (const view of Object.values(views)) view.replaceChildren();
    setStatus(result.message.replace(/\n+/g, " "), true);
    return;
  }
  state.lastResult = result;
  show(views.diff, result.diff);
  show(views.expected, result.expected.map((line) => [line, null]));
  show(views.notes, result.notes.map((line) => [line, null]));
  setStatus(result.summary, result.alert);
  selectTab("diff");
}

// ---- ファイルを開く（UTF-8 で読めなければ Shift_JIS。tkinter 版と同じ Python の関数で読む）----
let openTarget = null;

function openFile(target) {
  openTarget = target;
  $("file-input").value = "";
  $("file-input").click();
}

async function onFileChosen() {
  const file = $("file-input").files[0];
  if (!file || !openTarget || !state.pyodide) return;
  const path = "/tmp/upload.txt";
  try {
    state.pyodide.FS.writeFile(path, new Uint8Array(await file.arrayBuffer()));
    $(openTarget).value = state.bridge.read_file(path);
  } catch (error) {
    setStatus(`ファイルを開けませんでした。（${error.message}）`, true);
  } finally {
    // ブラウザの中の一時ファイルも残さない
    if (state.pyodide.FS.analyzePath(path).exists) state.pyodide.FS.unlink(path);
  }
}

// ---- 結果をコピー・保存（表示中のタブの内容。tkinter 版と同じ）----
function resultText() {
  if (!state.lastResult) return "";
  return views[currentTab()].textContent.replace(/\n$/, "");
}

async function copyResult() {
  const text = resultText();
  if (!text) return setStatus("先に「比較する」を押してください。", true);
  try {
    await navigator.clipboard.writeText(text);
    setStatus("表示中のタブの内容をコピーしました");
  } catch (error) {
    setStatus("コピーできませんでした。結果の欄を選んで Ctrl+C でコピーしてください。", true);
  }
}

function saveResult() {
  const text = resultText();
  if (!text) return setStatus("先に「比較する」を押してください。", true);
  const url = URL.createObjectURL(new Blob([text + "\n"], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "config-review-result.txt";
  link.click();
  // ダウンロードが始まる前に消すと失敗するブラウザがあるので、少し待ってから消す
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  setStatus("保存しました（ブラウザのダウンロードのフォルダ）");
}

// ---- ボタンとキーのつなぎこみ ----
$("run").addEventListener("click", run);
$("copy").addEventListener("click", copyResult);
$("save").addEventListener("click", saveResult);
$("file-input").addEventListener("change", onFileChosen);
for (const key of Object.keys(views)) {
  $("tab-" + key).addEventListener("click", () => selectTab(key));
  $("tab-" + key).addEventListener("keydown", onTabKey);
}
selectTab("diff");
for (const button of document.querySelectorAll("[data-open]")) {
  button.addEventListener("click", () => openFile(button.dataset.open));
}
for (const button of document.querySelectorAll("[data-clear]")) {
  button.addEventListener("click", () => ($(button.dataset.clear).value = ""));
}
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") {
    event.preventDefault();
    run();
  }
});

start();

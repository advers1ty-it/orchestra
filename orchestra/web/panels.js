(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels")<0)window.__diagFiles.push("panels");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels");}})();
// -------------------------------------------------------------- benchmark

const benchPanel = $("bench");
const benchLog = $("bench-log");
const benchOut = $("bench-out");
let benchTimer = null;

function openBench() {
  benchPanel.classList.remove("hidden");
  pollBench();
}
function closeBench() {
  benchPanel.classList.add("hidden");
  if (benchTimer) { clearInterval(benchTimer); benchTimer = null; }
}
$("btn-bench").onclick = openBench;
$("bench-close").onclick = closeBench;
benchPanel.addEventListener("click", (e) => { if (e.target === benchPanel) closeBench(); });

$("bench-run").onclick = async () => {
  $("bench-run").disabled = true;
  benchOut.textContent = "";
  benchLog.textContent = "avvio…";
  try {
    const r = await fetch("/api/bench", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sample: Number($("bench-sample").value),
        category: $("bench-cat").value,
      }),
    });
    const d = await r.json();
    if (!r.ok) { benchLog.textContent = ""; addText("error", d.error || `errore ${r.status}`); }
  } catch (e) {
    benchLog.textContent = "";
    addText("error", String(e));
  } finally {
    $("bench-run").disabled = false;
    if (!benchTimer) pollBench();
  }
};

function pollBench() {
  if (benchTimer) return;
  benchTimer = setInterval(async () => {
    try {
      const r = await fetch("/api/bench/status");
      const d = await r.json();
      benchLog.textContent = (d.log || []).join("\n");
      benchLog.scrollTop = benchLog.scrollHeight;
      if (!d.running) {
        clearInterval(benchTimer);
        benchTimer = null;
        renderBenchResult(d.result);
      }
    } catch (e) {
      clearInterval(benchTimer);
      benchTimer = null;
    }
  }, 1500);
}

// La tabella arriva come testo monospaziato dal backend, che l'ha
// costruita per il terminale. Riutilizzarla è più onesto che rifare la
// formattazione in JS e rischiare due versioni che divergono.
function renderBenchResult(res) {
  benchOut.textContent = "";
  if (!res) return;
  const pre = el("pre", "benchlog");
  pre.textContent = res.table || "";
  benchOut.appendChild(pre);

  if (res.unusable && res.unusable.length) {
    const n = el("div", "small dim");
    n.textContent = "Non misurati (il provider li riserva ad altri client): "
      + res.unusable.join(", ");
    benchOut.appendChild(n);
  }
  // i punteggi appena misurati finiscono nel selettore
  loadModels();
}

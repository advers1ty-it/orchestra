(function(){window.__diagFiles=window.__diagFiles||[];if(window.__diagFiles.indexOf("panels-automazioni")<0)window.__diagFiles.push("panels-automazioni");var e=document.getElementById("diag-files");if(e){e.textContent=((e.textContent?e.textContent+" ":"")+"panels-automazioni");}})();
// ============================== CRON ==============================
const cronBar = $("cron-bar");
const cronNome = $("cron-nome");
const cronSchedule = $("cron-schedule");
const cronPreset = $("cron-preset");
const cronAtHour = $("cron-at-hour");
const cronAtMin = $("cron-at-min");
const cronAtSep = $("cron-at-sep");
const cronType = $("cron-type");
const cronObjective = $("cron-objective");
const cronCommand = $("cron-command");
const cronProfile = $("cron-profile");
const cronStatus = $("cron-status");
const cronOutput = $("cron-output");
const cronList = $("cron-list");
const cronSched = $("cron-sched");
const cronSchedStat = $("cron-sched-stat");
let cronPoll = 0;

function cronScheduleDaUI() {
  const p = (cronPreset && cronPreset.value) || "";
  if (p === "at") {
    const h = parseInt((cronAtHour && cronAtHour.value) || "0", 10);
    const m = parseInt((cronAtMin && cronAtMin.value) || "0", 10);
    return (isNaN(m) ? 0 : m) + " " + (isNaN(h) ? 0 : h) + " * * *";
  }
  if (p === "custom") {
    return (cronSchedule && cronSchedule.value || "").trim();
  }
  return p.trim();
}

function aggiornaPresetUI() {
  const p = (cronPreset && cronPreset.value) || "";
  const showAt = p === "at";
  const showCustom = p === "custom";
  if (cronAtHour) cronAtHour.hidden = !showAt;
  if (cronAtMin) cronAtMin.hidden = !showAt;
  if (cronAtSep) cronAtSep.hidden = !showAt;
  if (cronSchedule) cronSchedule.hidden = !showCustom;
}
on(cronPreset, "change", aggiornaPresetUI);

function cronRiga(j) {
  const riga = document.createElement("div");
  riga.className = "goal-row";
  const id = document.createElement("span");
  id.className = "goal-id";
  id.textContent = String(j.id || "").slice(0, 8);
  id.title = j.id || "";
  riga.appendChild(id);
  const nome = document.createElement("span");
  nome.className = "goal-obj";
  nome.textContent = (j.nome || "") + "  [" + (j.schedule_human || j.schedule || "") + "]";
  nome.title = (j.nome || "") + " — " + (j.schedule || "");
  riga.appendChild(nome);
  const st = document.createElement("span");
  st.className = "goal-stato stato-" + (j.enabled ? "done" : "pending");
  st.textContent = j.enabled ? "on" : "off";
  riga.appendChild(st);
  const meta = document.createElement("span");
  meta.className = "goal-meta";
  meta.textContent = "next=" + (j.next_run || "-") + " last=" + (j.last_status || "-");
  riga.appendChild(meta);
  const azioni = document.createElement("span");
  azioni.className = "goal-meta";
  const btnRun = document.createElement("button");
  btnRun.className = "ghost";
  btnRun.textContent = "Esegui";
  btnRun.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const r = await fetch("/api/cron/run", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: j.id }) });
      const d = await r.json().catch(() => ({}));
      if (cronOutput) cronOutput.textContent = JSON.stringify(d);
      caricaCron();
    } catch (err) { if (cronStatus) cronStatus.textContent = "errore: " + err; }
  });
  const btnToggle = document.createElement("button");
  btnToggle.className = "ghost";
  btnToggle.textContent = j.enabled ? "Off" : "On";
  btnToggle.addEventListener("click", async (e) => {
    e.stopPropagation();
    const path = j.enabled ? "/api/cron/update" : "/api/cron/update";
    await fetch(path, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: j.id, enabled: !j.enabled }) });
    caricaCron();
  });
  const btnDel = document.createElement("button");
  btnDel.className = "ghost";
  btnDel.textContent = "X";
  btnDel.addEventListener("click", async (e) => {
    e.stopPropagation();
    await fetch("/api/cron/delete", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: j.id }) });
    caricaCron();
  });
  azioni.appendChild(btnRun);
  azioni.appendChild(btnToggle);
  azioni.appendChild(btnDel);
  riga.appendChild(azioni);
  return riga;
}

async function caricaCron() {
  if (!cronBar || cronBar.hidden) return;
  try {
    const [rs, ss] = await Promise.all([
      fetch("/api/cron/jobs").then((r) => r.json().catch(() => ({}))),
      fetch("/api/cron/scheduler/status").then((r) => r.json().catch(() => ({}))),
    ]);
    const jobs = rs.jobs || [];
    if (cronList) {
      cronList.replaceChildren();
      for (const j of jobs) cronList.appendChild(cronRiga(j));
      if (!jobs.length) {
        const vuoto = document.createElement("div");
        vuoto.className = "goal-meta";
        vuoto.textContent = "Nessun job. Crea un job con nome, schedule e azione.";
        cronList.appendChild(vuoto);
      }
    }
    if (cronSched) cronSched.textContent = ss.running ? "Scheduler: on" : "Scheduler: off";
    if (cronSchedStat) cronSchedStat.textContent = ss.running ? ("rounds=" + (ss.rounds||0) + " last=" + (ss.last_id||"")) : "";
  } catch (e) {
    if (cronStatus) cronStatus.textContent = "cron non raggiungibili: " + e;
  }
}

on("btn-cron", "click", () => {
  if (!cronBar) return;
  cronBar.hidden = !cronBar.hidden;
  if (!cronBar.hidden) {
    caricaCron();
    if (!cronPoll) cronPoll = setInterval(() => { if (cronBar && !cronBar.hidden) caricaCron(); }, 3000);
  }
});

on("cron-refresh", "click", () => caricaCron());

on("cron-create", "click", async () => {
  const nome = (cronNome && cronNome.value || "").trim();
  const schedule = cronScheduleDaUI();
  if (!nome || !schedule) {
    if (cronStatus) cronStatus.textContent = "nome e schedule richiesti";
    return;
  }
  const tipo = (cronType && cronType.value) || "goal";
  const corpo = { nome: nome, schedule: schedule, action_type: tipo, enabled: true };
  if (tipo === "shell") {
    corpo.command = (cronCommand && cronCommand.value || "").trim();
  } else {
    corpo.objective = (cronObjective && cronObjective.value || "").trim();
    corpo.profile = (cronProfile && cronProfile.value) || "auto";
  }
  if (cronStatus) cronStatus.textContent = "creazione...";
  try {
    const r = await fetch("/api/cron/create", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(corpo) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { if (cronStatus) cronStatus.textContent = d.error || ("errore " + r.status); return; }
    if (cronStatus) cronStatus.textContent = "creato: " + (d.job && d.job.id);
    if (cronNome) cronNome.value = "";
    caricaCron();
  } catch (e) { if (cronStatus) cronStatus.textContent = "errore: " + e; }
});

on("cron-sched", "click", async () => {
  try {
    const st = await fetch("/api/cron/scheduler/status").then((r) => r.json().catch(() => ({})));
    const rotta = st.running ? "/api/cron/scheduler/stop" : "/api/cron/scheduler/start";
    await fetch(rotta, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ interval: 30 }) });
    caricaCron();
  } catch (e) { if (cronStatus) cronStatus.textContent = "errore: " + e; }
});

// ============================== AUTOSTART ==============================
const autostartStat = $("autostart-stat");
const autostartToggle = $("autostart-toggle");

async function caricaAutostart() {
  try {
    const r = await fetch("/api/autostart/status").then((x) => x.json().catch(() => ({})));
    if (!r.disponibile) {
      if (autostartStat) autostartStat.textContent = "non disponibile (non Windows)";
      if (autostartToggle) autostartToggle.hidden = true;
      return;
    }
    // "attivo" vuol dire che la voce esiste, non che partira': se il
    // programma registrato non c'e' piu', lo si dice invece di far
    // credere che l'avvio automatico funzioni.
    if (autostartStat) {
      autostartStat.textContent = !r.attivo
        ? "disattivo"
        : (r.problema ? "attivo, ma non partirebbe: " + r.problema : "attivo");
    }
    if (autostartToggle) {
      autostartToggle.textContent = !r.attivo ? "Attiva" : (r.problema ? "Ripara" : "Disattiva");
    }
  } catch (e) { }
}

on("autostart-toggle", "click", async () => {
  try {
    const st = await fetch("/api/autostart/status").then((x) => x.json().catch(() => ({})));
    // Con un problema il pulsante e' "Ripara": riscrive la voce con
    // l'interprete di adesso, che e' l'unica cosa che la puo' sistemare.
    const rotta = (st.attivo && !st.problema) ? "/api/autostart/disable" : "/api/autostart/enable";
    await fetch(rotta, { method: "POST", headers: {"Content-Type":"application/json"}, body: "{}" });
    caricaAutostart();
  } catch (e) { }
});

// carica stato all'apertura del pannello cron
const _origCaricaCron = caricaCron;
caricaCron = async function() {
  await _origCaricaCron();
  caricaAutostart();
};

// ============================== MCP ==============================
const mcpBar = $("mcp-bar");
const mcpNome = $("mcp-nome");
const mcpTransport = $("mcp-transport");
const mcpCommand = $("mcp-command");
const mcpArgs = $("mcp-args");
const mcpEnv = $("mcp-env");
const mcpUrl = $("mcp-url");
const mcpHeaders = $("mcp-headers");
const mcpStatus = $("mcp-status");
const mcpList = $("mcp-list");
const mcpTools = $("mcp-tools");

function mcpRiga(s) {
  const riga = document.createElement("div");
  riga.className = "goal-row";
  const nome = document.createElement("span");
  nome.className = "goal-obj";
  nome.textContent = (s.name || s.id) + "  [" + (s.transport || "stdio") + "]";
  nome.title = s.id;
  riga.appendChild(nome);
  const st = document.createElement("span");
  st.className = "goal-stato stato-" + (s.connected ? "done" : "pending");
  st.textContent = s.connected
    ? ("on · " + s.tools + " tool · " + (s.resources || 0) + " risorse · " +
       (s.prompts || 0) + " prompt")
    : "off";
  if (s.error) st.title = s.error;
  riga.appendChild(st);
  const azioni = document.createElement("span");
  azioni.className = "goal-meta";
  const btnConn = document.createElement("button");
  btnConn.className = "ghost";
  btnConn.textContent = s.connected ? "Disconnetti" : "Connetti";
  btnConn.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (s.connected) await fetch("/api/mcp/disconnect", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: s.id }) });
    else await fetch("/api/mcp/connect", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: s.id }) });
    caricaMcp();
  });
  const btnDel = document.createElement("button");
  btnDel.className = "ghost";
  btnDel.textContent = "X";
  btnDel.addEventListener("click", async (e) => {
    e.stopPropagation();
    await fetch("/api/mcp/delete", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: s.id }) });
    caricaMcp();
  });
  azioni.appendChild(btnConn);
  azioni.appendChild(btnDel);
  riga.appendChild(azioni);
  return riga;
}

async function caricaMcp() {
  if (!mcpBar || mcpBar.hidden) return;
  try {
    const rs = await fetch("/api/mcp/servers").then((r) => r.json().catch(() => ({})));
    const ts = await fetch("/api/mcp/tools").then((r) => r.json().catch(() => ({})));
    const rr = await fetch("/api/mcp/resources").then((r) => r.json().catch(() => ({})));
    const rp = await fetch("/api/mcp/prompts").then((r) => r.json().catch(() => ({})));
    const servers = rs.servers || [];
    if (mcpList) {
      mcpList.replaceChildren();
      for (const s of servers) mcpList.appendChild(mcpRiga(s));
      if (!servers.length) {
        const v = document.createElement("div");
        v.className = "goal-meta";
        v.textContent = "Nessun server MCP. Aggiungine uno.";
        mcpList.appendChild(v);
      }
    }
    if (mcpTools) {
      mcpTools.replaceChildren();
      const tools = ts.tools || [];
      if (tools.length) {
        const h = document.createElement("div");
        h.className = "goal-meta";
        h.textContent = "Tool remoti (" + tools.length + "): " + tools.map((t) => t.prefixed).join(", ");
        mcpTools.appendChild(h);
      }
      const risorse = rr.resources || [];
      const prompt = rp.prompts || [];
      if (risorse.length) {
        const h = document.createElement("div");
        h.className = "goal-meta";
        h.textContent = "Risorse (" + risorse.length + "): " +
          risorse.map((r) => r.uri).join(", ");
        mcpTools.appendChild(h);
      }
      if (prompt.length) {
        const h = document.createElement("div");
        h.className = "goal-meta";
        h.textContent = "Prompt (" + prompt.length + "): " +
          prompt.map((p) => p.name).join(", ");
        mcpTools.appendChild(h);
      }
    }
    if (mcpStatus) {
      mcpStatus.textContent = servers.length + " server, " +
        (ts.tools || []).length + " tool, " +
        (rr.resources || []).length + " risorse, " +
        (rp.prompts || []).length + " prompt";
    }
  } catch (e) {
    if (mcpStatus) mcpStatus.textContent = "mcp non raggiungibili: " + e;
  }
}

on("btn-mcp", "click", () => {
  if (!mcpBar) return;
  mcpBar.hidden = !mcpBar.hidden;
  if (!mcpBar.hidden) caricaMcp();
});

on("mcp-refresh", "click", () => caricaMcp());

on("mcp-add", "click", async () => {
  const nome = (mcpNome && mcpNome.value || "").trim();
  const command = (mcpCommand && mcpCommand.value || "").trim();
  if (!nome) { if (mcpStatus) mcpStatus.textContent = "nome richiesto"; return; }
  const args = (mcpArgs && mcpArgs.value || "").trim().split(/\s+/).filter(Boolean);
  const env = {};
  const envStr = (mcpEnv && mcpEnv.value || "").trim();
  if (envStr) {
    for (const part of envStr.split(";")) {
      const idx = part.indexOf("=");
      if (idx > 0) env[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
    }
  }
  const headers = {};
  const headStr = (mcpHeaders && mcpHeaders.value || "").trim();
  if (headStr) {
    for (const part of headStr.split(";")) {
      const idx = part.indexOf("=");
      if (idx > 0) headers[part.slice(0, idx).trim()] = part.slice(idx + 1).trim();
    }
  }
  const transport = (mcpTransport && mcpTransport.value) || "stdio";
  const url = (mcpUrl && mcpUrl.value || "").trim();
  if (transport !== "stdio" && !url) {
    if (mcpStatus) mcpStatus.textContent = "url richiesto per " + transport;
    return;
  }
  const cfg = { name: nome, transport: transport,
                command: command, args: args, env: env,
                url: url, headers: headers, enabled: true };
  if (mcpStatus) mcpStatus.textContent = "aggiunta...";
  try {
    const r = await fetch("/api/mcp/add", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(cfg) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { if (mcpStatus) mcpStatus.textContent = d.error || ("errore " + r.status); return; }
    // connetti subito
    await fetch("/api/mcp/connect", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ id: (d.server && d.server.id) }) });
    if (mcpNome) mcpNome.value = "";
    if (mcpCommand) mcpCommand.value = "";
    if (mcpArgs) mcpArgs.value = "";
    if (mcpEnv) mcpEnv.value = "";
    if (mcpUrl) mcpUrl.value = "";
    if (mcpHeaders) mcpHeaders.value = "";
    caricaMcp();
    if (mcpStatus) mcpStatus.textContent = "aggiunto e connesso";
  } catch (e) { if (mcpStatus) mcpStatus.textContent = "errore: " + e; }
});

on("mcp-connect-all", "click", async () => {
  await fetch("/api/mcp/connect_all", { method: "POST", headers: {"Content-Type":"application/json"}, body: "{}" });
  caricaMcp();
});


// --- Consiglio (Roast Room) ---
(function(){
  const btn = document.getElementById('btn-council');
  const panel = document.getElementById('council-panel');
  const close = document.getElementById('council-close');
  const startBtn = document.getElementById('council-start');
  const pdfBtn = document.getElementById('council-pdf');
  const decision = document.getElementById('council-decision');
  const rounds = document.getElementById('council-rounds');
  const status = document.getElementById('council-status');
  const log = document.getElementById('council-log');
  const verdict = document.getElementById('council-verdict');
  const table = document.getElementById('council-table');
  const consigliaBtn = document.getElementById('council-consiglia');
  const tuttiBtn = document.getElementById('council-tutti');
  const defaultBtn = document.getElementById('council-default');
  const sceltiEl = document.getElementById('council-scelti');
  if (!btn || !panel) return;
  btn.addEventListener('click', () => { panel.classList.remove('hidden'); loadRoster(); });
  if (close) close.addEventListener('click', () => panel.classList.add('hidden'));
  let roster = [];
  let timer = null;
  // Chi siede lo decide l'utente: le card si cliccano, e il Chair puo'
  // proporre un tavolo. Prima partivano sempre tutti e dodici.
  let scelti = new Set();
  let tavoloDefault = [];
  let motivi = {};
  function loadRoster(){
    if (roster.length) { renderTable(); return; }
    fetch('/api/council/roster').then(r=>r.json()).then(d=>{
      roster = d.seats || [];
      return fetch('/api/council/tavolo').then(r=>r.json()).catch(()=>({default:[]}));
    }).then(t=>{
      tavoloDefault = (t && t.default) || [];
      scelti = new Set(tavoloDefault);
      renderTable();
    }).catch(()=>{});
  }
  function paint(){
    roster.forEach(s=>{
      const el = document.getElementById('cseat-'+s.key);
      if (!el) return;
      const on = scelti.has(s.key);
      el.style.opacity = on ? '1' : '.35';
      el.style.borderWidth = on ? '4px' : '2px';
      if (motivi[s.key]) el.title = motivi[s.key];
    });
    if (sceltiEl) sceltiEl.textContent = scelti.size
      ? ('Al tavolo: ' + roster.filter(s=>scelti.has(s.key)).map(s=>s.short).join(', '))
      : 'Nessun seat scelto: il Chair decide chi siede';
  }
  function renderTable(){
    if (!table) return;
    table.innerHTML = '';
    roster.forEach(s=>{
      const chip = document.createElement('div');
      chip.className = 'council-seat';
      chip.id = 'cseat-'+s.key;
      chip.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:4px;padding:10px 8px;border:2px solid '+(s.color||'#888')+';border-radius:10px;transition:box-shadow .15s,transform .15s;background:rgba(255,255,255,.03)';
      chip.innerHTML = '<img src="/portraits/'+s.key+'-base.webp" alt="'+s.short+'" style="width:80px;height:80px;border-radius:50%;object-fit:cover;border:3px solid '+(s.color||'#888')+'" id="cimg-'+s.key+'"><div style="font-size:14px;font-weight:700">'+s.short+'</div><div style="font-size:11px;opacity:.75;text-align:center;line-height:1.2">'+s.pillar+'</div>';
      chip.title = s.question || '';
      chip.style.cursor = 'pointer';
      chip.addEventListener('click', () => {
        if (scelti.has(s.key)) { scelti.delete(s.key); delete motivi[s.key]; }
        else { scelti.add(s.key); }
        paint();
      });
      table.appendChild(chip);
    });
    const chair = document.createElement('div');
    chair.id = 'cseat-chair';
    chair.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:4px;padding:10px 8px;border:2px dashed #bbb;border-radius:10px;background:rgba(255,255,255,.03)';
     chair.innerHTML = '<div style="width:80px;height:80px;border-radius:50%;background:#555;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:20px">CH</div><div style="font-size:14px;font-weight:700">Chair</div><div style="font-size:11px;opacity:.75">Sintesi</div>';
    table.appendChild(chair);
    paint();
  }
  function highlight(current){
    roster.forEach(s=>{
      const el = document.getElementById('cseat-'+s.key);
      if (!el) return;
      const img = document.getElementById('cimg-'+s.key);
      if (current && current === s.key) {
        el.style.boxShadow = '0 0 0 3px '+(s.color||'#fff');
        el.style.transform = 'scale(1.06)';
        if (img) img.src = '/portraits/'+s.key+'-open.webp';
      } else {
        el.style.boxShadow = 'none';
        el.style.transform = 'scale(1)';
        if (img) img.src = '/portraits/'+s.key+'-base.webp';
      }
    });
    const chair = document.getElementById('cseat-chair');
    if (chair) {
      if (current === 'chair') { chair.style.boxShadow = '0 0 0 3px #fff'; chair.style.transform='scale(1.06)'; }
      else { chair.style.boxShadow = 'none'; chair.style.transform='scale(1)'; }
    }
  }
  function poll() {
    fetch('/api/council/status').then(r=>r.json()).then(d=>{
      status.textContent = d.running ? ('round '+(d.current_round||'?')+' in corso...') : (d.error ? 'errore' : 'pronto');
      const _prevScroll = log.scrollTop;
      log.textContent = (d.log||[]).join('\n');
      if (d.verdict) verdict.textContent = d.verdict;
      log.scrollTop = _prevScroll;
      highlight(d.current_seat || '');
      if (d.running) timer = setTimeout(poll, 2000);
    }).catch(()=>{});
  }
  if (startBtn) startBtn.addEventListener('click', async () => {
    const dec = (decision.value||'').trim();
    if (!dec) { status.textContent = 'inserisci una decisione'; return; }
    status.textContent = 'avvio...';
    log.textContent = '';
    verdict.textContent = '';
    highlight('');
    const corpo = {decision:dec, rounds:parseInt(rounds.value||'3',10)};
    if (scelti.size) corpo.seats = Array.from(scelti);
    const r = await fetch('/api/council/start', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(corpo)});
    const d = await r.json();
    if (d.error) { status.textContent = d.error; return; }
    poll();
  });
  if (consigliaBtn) consigliaBtn.addEventListener('click', async () => {
    const dec = (decision.value||'').trim();
    if (!dec) { status.textContent = 'inserisci una decisione'; return; }
    consigliaBtn.disabled = true;
    status.textContent = 'il Chair sceglie il tavolo...';
    try {
      const r = await fetch('/api/council/consiglia', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:dec})});
      const d = await r.json();
      if (d.error) { status.textContent = d.error; return; }
      scelti = new Set(d.seats||[]);
      motivi = d.why || {};
      paint();
      status.textContent = (d.note || 'tavolo proposto')
        + (d.provider ? (' · ' + d.provider + (d.model ? '/' + d.model : '')) : '');
    } finally { consigliaBtn.disabled = false; }
  });
  if (tuttiBtn) tuttiBtn.addEventListener('click', () => {
    scelti = new Set(roster.map(s=>s.key)); motivi = {}; paint();
  });
  if (defaultBtn) defaultBtn.addEventListener('click', () => {
    scelti = new Set(tavoloDefault); motivi = {}; paint();
  });
  if (pdfBtn) pdfBtn.addEventListener('click', () => { window.location.href = '/api/council/pdf'; });
})();

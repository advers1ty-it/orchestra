import io

P = "orchestra/web/panels.js"
s = io.open(P, encoding="utf-8").read()

# --- 1) lo stato tiene anche il cestino -------------------------------
s = s.replace(
    'let skillDati = { scaricate: [], generate: [], categorie: [], totale: 0,\n'
    '                  scaricate_n: 0, generate_n: 0, nel_prompt_max: 0 };',
    'let skillDati = { scaricate: [], generate: [], categorie: [], totale: 0,\n'
    '                  scaricate_n: 0, generate_n: 0, nel_prompt_max: 0,\n'
    '                  cestino: [] };')

# --- 2) la scheda, al posto della riga --------------------------------
i = s.index("function skillRiga(s, generata) {")
j = s.index("async function skillApri(s) {")
nuova_riga = '''function skillRiga(s, generata) {
  // Una scheda, non una riga. Con 100 skill in lista si scorreva per
  // metri; in griglia se ne vedono tre o quattro per riga e il confronto
  // fra nomi diventa immediato — che e' la ragione per cui uno cerca
  // una skill: per capire se quella che serve c'e' gia'.
  const carta = el("div", "skill-carta");
  if (generata) carta.classList.add("skill-carta-generata");

  const capo = el("div", "skill-carta-capo");
  // Il '+' e' lo stesso segno del prompt: due posti che parlano lo
  // stesso linguaggio, e uno sguardo basta per capire se una procedura
  // e' stata scritta da qualcun altro o dall'agente che la usa.
  if (generata) {
    const segno = el("span", "skill-segno");
    segno.textContent = "+";
    segno.title = s.con_prove
      ? "imparata dall'agente, con " + s.prove + " prove"
      : "imparata dall'agente, SENZA prove";
    capo.appendChild(segno);
  }
  const titolo = el("span", "skill-carta-nome");
  titolo.textContent = s.nome;
  capo.appendChild(titolo);
  carta.appendChild(capo);

  const desc = el("div", "skill-carta-desc");
  desc.textContent = s.descrizione || "(senza descrizione)";
  desc.title = s.descrizione || "";
  carta.appendChild(desc);

  const meta = el("div", "skill-carta-meta");
  const info = [];
  if (s.categoria) info.push(s.categoria);
  if (generata) {
    info.push(s.con_prove
      ? s.prove + (s.prove === 1 ? " prova" : " prove")
      : "senza prove");
  }
  if (s.usata) info.push("usata " + s.usata + (s.usata === 1 ? " volta" : " volte"));
  meta.textContent = info.join(" · ");
  carta.appendChild(meta);

  const pie = el("div", "skill-carta-pie");
  const apri = el("button", "ghost skill-pulsante");
  apri.textContent = "Apri";
  apri.title = "Leggi la procedura";
  apri.onclick = () => skillApri(s);
  pie.appendChild(apri);

  const via = el("button", "ghost skill-pulsante skill-bottone-cancella");
  via.textContent = "Cestino";
  via.title = "Metti nel cestino (recuperabile)";
  via.onclick = () => skillCancella(s.nome);
  pie.appendChild(via);
  carta.appendChild(pie);

  return carta;
}

function skillCartaCestino(v) {
  const carta = el("div", "skill-carta skill-carta-cestino");
  const capo = el("div", "skill-carta-capo");
  const titolo = el("span", "skill-carta-nome");
  titolo.textContent = v.nome;
  capo.appendChild(titolo);
  carta.appendChild(capo);
  const meta = el("div", "skill-carta-meta");
  meta.textContent = v.data || "";
  carta.appendChild(meta);
  const pie = el("div", "skill-carta-pie");
  const rimetti = el("button", "ghost skill-pulsante");
  rimetti.textContent = "Rimetti";
  rimetti.onclick = () => skillRipristina(v.nome);
  pie.appendChild(rimetti);
  const distruggi = el("button", "ghost skill-pulsante skill-bottone-cancella");
  distruggi.textContent = "Cancella";
  distruggi.title = "Cancellazione definitiva: non si recupera";
  distruggi.onclick = () => skillSvuotaUno(v.nome);
  pie.appendChild(distruggi);
  carta.appendChild(pie);
  return carta;
}

async function skillRipristina(nome) {
  try {
    const d = await skillPost({ azione: "ripristina", nome });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillMossa(nome + " rimessa");
    } else {
      skillCestinoNota((d && d.error) || "ripristino rifiutato");
    }
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
  }
}

async function skillSvuotaUno(nome) {
  // Chiede due volte. La cancellazione definitiva non ha ritorno, e un
  // click su "Cancella tutto" che cancella tutto quello che c'era
  // dentro, compresi i tre di ieri, e' il modo migliore per fare
  // perdere roba che si voleva tenere.
  const risp = window.prompt(
    "Cancellare DEFINITIVAMENTE " + nome + "?\\n\\nNon si recupera.",
    "scrivi CANCELLA");
  if ((risp || "").trim().toUpperCase() !== "CANCELLA") return;
  // svuota tutto, poi rimette quello che era: cosi' si cancella solo
  // quello che ho scelto, e gli altri restano recuperabili.
  let rimossiTutti = 0;
  try {
    const d = await skillPost({ azione: "svuota_cestino" });
    rimossiTutti = (d && d.rimosse) || 0;
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
    return;
  }
  // rimette tutto tranne quello scelto
  for (const v of skillDati.cestino || []) {
    if (v.nome === nome) continue;
    await skillPost({ azione: "ripristina", nome: v.nome });
  }
  // e rimette quello scelto, cosi' il cestino riflesso è quello vero
  await caricaSkill();
  skillCestinoNota(nome + " cancellato per sempre"
    + (rimossiTutti ? " (svuotato e ricostruito: " + rimossiTutti + ")" : ""));
}

function skillCestinoNota(t) {
  const n = $("skill-cestino-nota");
  if (n) n.textContent = t;
}

function aggiornaDa(elenco, cestino) {
  skillDati.scaricate = elenco.lista_scaricate || [];
  skillDati.generate = elenco.lista_generate || [];
  skillDati.categorie = elenco.categorie || [];
  skillDati.totale = elenco.totale || 0;
  skillDati.scaricate_n = elenco.scaricate || 0;
  skillDati.generate_n = elenco.generate || 0;
  skillDati.nel_prompt_max = elenco.nel_prompt_max || 0;
  skillDati.cestino = cestino || [];
  disegnaSkill();
}

'''
s = s[:i] + nuova_riga + s[j:]

io.open(P, "w", encoding="utf-8").write(s)
print("  panels.js: schede e cestino")
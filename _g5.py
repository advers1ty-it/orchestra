import io

# --- 1) il backend: cancellare UNA voce dal cestino --------------------
P = "orchestra/webapp.py"
s = io.open(P, encoding="utf-8").read()

vecchio = '''        if azione == "svuota_cestino":'''
nuovo = '''        if azione == "cancella_definitivo":
            nome = str(body.get("nome") or "").strip()
            ok, perche = _cestino_rimuovi(indice.radice, nome)
            if not ok:
                self._json({"error": perche}, 400)
                return
            self._json({"ok": True, "rimossa": nome,
                        "elenco": _skill_elenco(indice),
                        "cestino": _cestino_elenco(indice.radice)})
            return

        if azione == "svuota_cestino":'''
assert vecchio in s
s = s.replace(vecchio, nuovo, 1)

m = '''def _cestino_svuota(radice: str) -> tuple[int, str]:'''
nuovo_m = '''def _cestino_rimuovi(radice: str, nome: str) -> tuple[bool, str]:
    """Cancella una voce dal cestino, per sempre.

    Una voce sola. "Svuota tutto" e' un pulsante separato con una
    conferma separata: mettere le due cose insieme fa perdere roba
    che si voleva tenere. Cancellare dal cestino e' irreversibile, e
    il pulsante deve dirlo.
    """
    import shutil
    base = os.path.join(radice, CARTELLA_CESTINO)
    if not os.path.isdir(base):
        return False, "il cestino e' vuoto"
    for ts in sorted(os.listdir(base), reverse=True):
        dentro = os.path.join(base, ts, nome)
        if os.path.isdir(dentro):
            shutil.rmtree(dentro, ignore_errors=True)
            # svuota anche i timestamp rimasti vuoti, se sono vuoti
            tsdir = os.path.join(base, ts)
            try:
                if not os.listdir(tsdir):
                    os.rmdir(tsdir)
            except OSError:
                pass
            return True, ""
    return False, f"nel cestino non c'e' {nome!r}"


def _cestino_svuota(radice: str) -> tuple[int, str]:'''
assert m in s
s = s.replace(m, nuovo_m, 1)
io.open(P, "w", encoding="utf-8").write(s)
print("  webapp.py: cancella_definitivo")

# --- 2) il frontend: usa l'azione singola -----------------------------
P2 = "orchestra/web/panels.js"
j = io.open(P2, encoding="utf-8").read()

i = j.index("async function skillSvuotaUno(nome) {")
k = j.index("function skillCestinoNota(t) {")
nuovo_j = '''async function skillSvuotaUno(nome) {
  // Chiede due volte, e una delle due e' scrivere una parola. La
  // cancellazione definitiva non ha ritorno: un click su "Cancella"
  // che cancella quello che si voleva tenere e' il modo migliore per
  // perdere roba. Un prompt che chiede una parola costa due secondi.
  const risp = window.prompt(
    "Cancellare DEFINITIVAMENTE " + nome + "?\\n\\nNon si recupera.",
    "scrivi CANCELLA");
  if ((risp || "").trim().toUpperCase() !== "CANCELLA") return;
  try {
    const d = await skillPost({ azione: "cancella_definitivo", nome });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillCestinoNota(nome + " cancellato per sempre");
    } else {
      skillCestinoNota((d && d.error) || "cancellazione rifiutata");
    }
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
  }
}

async function skillSvuotaTutto() {
  const n = (skillDati.cestino || []).length;
  if (!n) {
    skillCestinoNota("il cestino e' gia' vuoto");
    return;
  }
  const risp = window.prompt(
    "Cancellare DEFINITIVAMENTE " + n + " skill?\\n\\nNon si recupera nulla.",
    "scrivi CANCELLA");
  if ((risp || "").trim().toUpperCase() !== "CANCELLA") return;
  try {
    const d = await skillPost({ azione: "svuota_cestino" });
    if (d && d.ok) {
      aggiornaDa(d.elenco, d.cestino);
      skillCestinoNota(d.rimosse + " cancellate per sempre");
    } else {
      skillCestinoNota((d && d.error) || "rifiutato");
    }
  } catch (e) {
    skillCestinoNota("errore: " + (e.message || e));
  }
}

'''
j = j[:i] + nuovo_j + j[k:]

# il disegno del cestino, dentro disegnaSkill
j = j.replace('''  const testo = ($("skill-filtro") && $("skill-filtro").value) || "";''',
'''  const cest = $("skill-cestino");
  if (cest) {
    cest.replaceChildren();
    if (!(skillDati.cestino || []).length) {
      cest.appendChild(el("div", "skill-vuota",
        "Vuoto. Le skill che cancelli finiscono qui e puoi rimetterle."));
    } else {
      for (const v of skillDati.cestino) cest.appendChild(skillCartaCestino(v));
    }
  }
  const notaCest = $("skill-cestino-nota");
  if (notaCest && !notaCest.textContent) {
    const n = (skillDati.cestino || []).length;
    notaCest.textContent = n
      ? n + " da recuperare"
      : "vuoto";
  }

  const testo = ($("skill-filtro") && $("skill-filtro").value) || "";''')

# i listener
j = j.replace('  on($("skill-ricarica"), "click", caricaSkill);',
              '  on($("skill-ricarica"), "click", caricaSkill);\n'
              '  on($("skill-svuota"), "click", skillSvuotaTutto);')

io.open(P2, "w", encoding="utf-8").write(j)
print("  panels.js: cestino disegnato e pulsanti")
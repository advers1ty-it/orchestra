import io

P = "orchestra/web/panels.js"
s = io.open(P, encoding="utf-8").read()

# --- il cestino dentro disegnaSkill ------------------------------------
vecchio = '''  const testo = ($("skill-filtro") && $("skill-filtro").value) || "";'''
nuovo = '''  const cest = $("skill-cestino");
  if (cest) {
    cest.replaceChildren();
    const nel = skillDati.cestino || [];
    if (!nel.length) {
      cest.appendChild(el("div", "skill-vuota",
        "Vuoto. Le skill che cancelli finiscono qui, e puoi rimetterle."));
    } else {
      for (const v of nel) cest.appendChild(skillCartaCestino(v));
    }
    const notaCest = $("skill-cestino-nota");
    if (notaCest && !notaCest.textContent) {
      notaCest.textContent = nel.length
        ? nel.length + " da recuperare" : "";
    }
  }

  const testo = ($("skill-filtro") && $("skill-filtro").value) || "";'''
assert vecchio in s, "disegnaSkill: punto di inserimento non trovato"
s = s.replace(vecchio, nuovo, 1)

# --- lo stato del cestino arriva dalla risposta -------------------------
vecchio2 = '''      disegnaSkill();
      skillMossa(nome + " nel cestino");'''
nuovo2 = '''      // La risposta porta il cestino aggiornato: senza, la lista a
      // schermo e quella vera divergono, e il pannello mente proprio
      // dove deve rassicurare che niente e' andato perso.
      aggiornaDa(d.elenco, d.cestino);
      skillMossa(nome + " nel cestino");'''
assert vecchio2 in s, "skillCancella non trovato"
s = s.replace(vecchio2, nuovo2, 1)

vecchio3 = '''      skillDati.scaricate = d.elenco.lista_scaricate || [];
      skillDati.generate = d.elenco.lista_generate || [];
      skillDati.categorie = d.elenco.categorie || [];
      skillDati.totale = d.elenco.totale || 0;
      disegnaSkill();
      skillMossa(d.importate + " importate");'''
nuovo3 = '''      aggiornaDa(d.elenco, d.cestino);
      skillMossa(d.importate + " importate");'''
assert vecchio3 in s, "importa non trovato"
s = s.replace(vecchio3, nuovo3, 1)

vecchio4 = '''      skillDati.scaricate = d.elenco.lista_scaricate || [];
      skillDati.generate = d.elenco.lista_generate || [];
      skillDati.categorie = d.elenco.categorie || [];
      skillDati.totale = d.elenco.totale || 0;
      disegnaSkill();
      skillMossa(nome + " nel cestino");'''
if vecchio4 in s:
    s = s.replace(vecchio4, nuovo3.replace("d.importate + \" importate\"",
                                           "nome + \" nel cestino\""), 1)

# --- l'elenco iniziale chiede anche il cestino --------------------------
vecchio5 = '''      skillDati = {
        scaricate: d.lista_scaricate || [],
        generate: d.lista_generate || [],
        categorie: d.categorie || [],
        totale: d.totale || 0,
        scaricate_n: d.scaricate || 0,
        generate_n: d.generate || 0,
        nel_prompt_max: d.nel_prompt_max || 0,
      };'''
nuovo5 = '''      skillDati = {
        scaricate: d.lista_scaricate || [],
        generate: d.lista_generate || [],
        categorie: d.categorie || [],
        totale: d.totale || 0,
        scaricate_n: d.scaricate || 0,
        generate_n: d.generate || 0,
        nel_prompt_max: d.nel_prompt_max || 0,
        cestino: d.cestino || [],
      };'''
assert vecchio5 in s, "caricaSkill non trovato"
s = s.replace(vecchio5, nuovo5, 1)

# --- il pulsante "Cancella tutto" --------------------------------------
vecchio6 = '''  on($("skill-ricarica"), "click", caricaSkill);'''
nuovo6 = '''  on($("skill-ricarica"), "click", caricaSkill);
  on($("skill-svuota"), "click", skillSvuotaTutto);'''
assert vecchio6 in s, "skill-ricarica non trovato"
s = s.replace(vecchio6, nuovo6, 1)

# --- e la sezione cestino si carica come le altre -----------------------
vecchio7 = '''  if (nome === "skill" && !sezioneSkillCaricata) {
    sezioneSkillCaricata = true;
    caricaSkill();
  }'''
if vecchio7 in s:
    s = s.replace(vecchio7, '''  if ((nome === "skill" || nome === "cestino") && !sezioneSkillCaricata) {
    sezioneSkillCaricata = true;
    caricaSkill();
  }''')

io.open(P, "w", encoding="utf-8").write(s)
print("  panels.js: cestino disegnato e collegato")
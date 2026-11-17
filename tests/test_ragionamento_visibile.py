"""Il blocco ragionamento: non deve arrivare vuoto, e non deve sparire.

Il difetto visto in uso: ogni tanto, in chat, restava una riga vuota al
posto del ragionamento. Era il blocco `.ragionamento` aperto e mai
riempito — il provider manda pezzi di ragionamento fatti di soli a capo,
e `if (d.testo)` li lascia passare.

La correzione ha due lati, e qui si verificano tutti e due, su TUTTI i
punti che creano o riempiono il nodo:

  - il blocco nasce nascosto e compare al primo carattere vero
    (`ragionamentoApri` / `ragionamentoAggiungi`);
  - le due ricostruzioni della chat (snapshot e polling) creano il blocco
    a mano, con `textContent = m.reasoning`: senza `trim()` un
    ragionamento di soli a capo tornava visibile al reload;
  - quando il log viene svuotato (reset, snapshot, banner) il puntatore
    al nodo vivo va azzerato, o i pezzi successivi finiscono in un nodo
    staccato dal documento: il ragionamento arriva e non si vede.

Il bundle gira davvero, con il DOM finto degli altri test: gli eventi si
passano a `handle()` e si guarda il DOM, non il sorgente.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from _ordine import ORDER  # noqa: E402

PASS, FAIL = [], []


def check(nome: str, cond: bool, dettaglio: str = "") -> None:
    (PASS if cond else FAIL).append(nome)
    print(f"  {'OK  ' if cond else 'FAIL'} {nome}"
          + (f" — {dettaglio}" if dettaglio and not cond else ""))


joined = "\n;\n".join(
    open(os.path.join(ROOT, "orchestra", "web", n), encoding="utf-8").read()
    for n in ORDER)
harness = open(os.path.join(HERE, "_dom_provider.js"), encoding="utf-8").read()

PROBE = r"""
(async () => {
  const OUT = { passi: {}, errori: [] };
  // Il bundle chiama fetch all'avvio (modelli, stato): senza, il probe
  // muore su un'unione di promise invece che sui nodi da contare.
  globalThis.fetch = async () => ({
    ok: false, status: 503, json: async () => ({}), text: async () => "",
  });

  const cls = (c) => String((c && c.className) || "");
  const nodi = () => (log.children || []).filter((c) => cls(c).indexOf("ragionamento") === 0);
  const visibili = () => nodi().filter((c) => !c.hasAttribute("hidden"));
  const bolle = () => (log.children || []).filter((c) => cls(c).startsWith("msg assistant"));
  const testo = (e) => String((e && e.textContent) || "").trim();

  const misura = () => ({ nodi: nodi().length, visibili: visibili().length,
                          bolle: bolle().length });

  try {
    // --- [1] un pezzo di soli a capo non apre niente a schermo ---------
    let a = misura();
    handle("thinking", {});
    handle("ragionamento", { testo: "\n\n" });
    let b = misura();
    OUT.passi.spazi_non_apre = b.visibili - a.visibili;

    // --- [2] il pezzo vero, nello stesso blocco, si vede --------------
    handle("ragionamento", { testo: "sto guardando l'indice" });
    let c = misura();
    OUT.passi.testo_si_vede = c.visibili - b.visibili;
    OUT.passi.testo_giusto = testo(visibili().slice(-1)[0]) === "sto guardando l'indice";

    // --- [3] nuovo ciclo: spazi, poi il testo -------------------------
    handle("thinking", {});
    handle("ragionamento", { testo: "   " });
    let d = misura();
    OUT.passi.spazi_nuovo_ciclo = d.visibili - c.visibili;
    handle("ragionamento", { testo: "secondo pezzo" });
    let e = misura();
    OUT.passi.testo_dopo_spazi = e.visibili - d.visibili;
    OUT.passi.secondo_testo_giusto = testo(visibili().slice(-1)[0]) === "secondo pezzo";

    // --- [4] una risposta di soli spazi non fa una bolla --------------
    let f = misura();
    handle("assistant", { content: "  \n  ", tool_calls: [] });
    let g = misura();
    OUT.passi.bolla_spazi = g.bolle - f.bolle;
    handle("assistant", { content: "risposta vera", tool_calls: [] });
    let h = misura();
    OUT.passi.bolla_vera = h.bolle - g.bolle;

    // --- [5] la ricostruzione da snapshot: ragionamento di spazi ------
    // `sessione_id` diverso = ricostruzione vera, come aprire un'altra chat.
    let i = misura();
    handle("snapshot", {
      ready: true, busy: false, sessione_id: "prova-1", messages: [
        { role: "user", content: "ciao" },
        { role: "assistant", content: "risposta", reasoning: "\n\n" },
      ],
    });
    let j = misura();
    OUT.passi.snapshot_spazi = j.visibili - i.visibili;
    OUT.passi.snapshot_bolle = j.bolle - i.bolle;

    // --- [6] ... e con un ragionamento vero, si vede ------------------
    let k = misura();
    handle("snapshot", {
      ready: true, busy: false, sessione_id: "prova-2", messages: [
        { role: "user", content: "ciao" },
        { role: "assistant", content: "", reasoning: "ragionamento vero" },
      ],
    });
    let l = misura();
    OUT.passi.snapshot_ragionamento = l.visibili - k.visibili;
    OUT.passi.snapshot_ragionamento_testo =
      visibili().some((n) => testo(n) === "ragionamento vero");
    OUT.passi.snapshot_ragionamento_vuoto = visibili().some((n) => testo(n) === "");

    // --- [7] dopo un reset il ragionamento nuovo si vede --------------
    handle("reset", {});
    let m = misura();
    handle("ragionamento", { testo: "dopo il reset" });
    let n = misura();
    OUT.passi.dopo_reset = n.visibili - m.visibili;
    OUT.passi.dopo_reset_testo = testo(visibili().slice(-1)[0]) === "dopo il reset";

    // --- [8] a fine turno il blocco si chiude, e il successivo vive ---
    handle("turn_end", {});
    let o = misura();
    handle("ragionamento", { testo: "turno dopo" });
    let p = misura();
    OUT.passi.dopo_turn_end = p.visibili - o.visibili;
    OUT.passi.dopo_turn_end_testo = testo(visibili().slice(-1)[0]) === "turno dopo";

    // --- [9] ricostruzione a meta' turno: il pezzo dopo si vede ------
    let q = misura();
    handle("snapshot", {
      ready: true, busy: true, sessione_id: "prova-1", messages: [
        { role: "assistant", content: "prima", reasoning: "vecchio" },
      ],
    });
    let r = misura();
    handle("ragionamento", { testo: "dopo la ricostruzione" });
    let s = misura();
    OUT.passi.dopo_ricostruzione = s.visibili - r.visibili;
    OUT.passi.dopo_ricostruzione_testo =
      visibili().some((n) => testo(n) === "dopo la ricostruzione");

    // --- [10] la verita' finale: nessun blocco visibile e vuoto ------
    OUT.passi.vuoti_visibili_alla_fine = visibili().filter((n) => testo(n) === "").length;
  } catch (err) {
    OUT.errori.push(String((err && err.stack) || err));
  }
  console.log("RAG" + JSON.stringify(OUT));
})();
"""

f = tempfile.mktemp(suffix=".js")
with open(f, "w", encoding="utf-8") as fh:
    fh.write(harness + "\n" + joined + "\n" + PROBE)
proc = subprocess.run(["node", f], capture_output=True, text=True, timeout=120,
                      cwd=ROOT, env=dict(os.environ,
                                         ORCHESTRA_WEB_INDEX=os.path.join(
                                             ROOT, "orchestra", "web", "index.html")))
try:
    os.unlink(f)
except OSError:
    pass

print("[0] Il bundle gira")
if proc.returncode != 0:
    check("il bundle gira in Node", False, (proc.stderr or proc.stdout)[-400:])
    print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
    print("FALLITI:", FAIL)
    sys.exit(1)

riga = [l for l in proc.stdout.splitlines() if l.startswith("RAG")]
if not riga:
    check("il probe ha risposto", False, proc.stdout[-300:])
    print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
    print("FALLITI:", FAIL)
    sys.exit(1)

check("il bundle gira in Node", True)
o = json.loads(riga[-1][3:])
p = o["passi"]
check("nessun errore nel probe", not o["errori"], str(o["errori"])[:300])

print("\n[1] Un pezzo di soli a capo non apre niente a schermo")
check("non compare nessun blocco", p.get("spazi_non_apre") == 0,
      f"blocchi visibili in piu': {p.get('spazi_non_apre')}")

print("\n[2] Il pezzo vero si vede, nello stesso blocco")
check("compare un blocco", p.get("testo_si_vede") == 1,
      f"blocchi visibili in piu': {p.get('testo_si_vede')}")
check("con il testo giusto", p.get("testo_giusto") is True)

print("\n[3] Spazi all'inizio di un ciclo nuovo non aprono un blocco vuoto")
check("niente blocco con soli spazi", p.get("spazi_nuovo_ciclo") == 0,
      f"blocchi visibili in piu': {p.get('spazi_nuovo_ciclo')}")
check("e poi il testo lo fa comparire", p.get("testo_dopo_spazi") == 1,
      f"blocchi visibili in piu': {p.get('testo_dopo_spazi')}")
check("con il testo giusto", p.get("secondo_testo_giusto") is True)

print("\n[4] Una risposta di soli spazi non fa una bolla")
check("nessuna bolla per gli spazi", p.get("bolla_spazi") == 0,
      f"bolle in piu': {p.get('bolla_spazi')}")
check("la risposta vera fa la sua bolla", p.get("bolla_vera") == 1,
      f"bolle in piu': {p.get('bolla_vera')}")

print("\n[5] La ricostruzione da snapshot (il reload) non mostra un blocco vuoto")
check("ragionamento di spazi: nessun blocco", p.get("snapshot_spazi") == 0,
      f"blocchi visibili in piu': {p.get('snapshot_spazi')}")

print("\n[6] ... e un ragionamento vero si rivede")
check("il blocco c'e'", p.get("snapshot_ragionamento") == 1,
      f"blocchi visibili in piu': {p.get('snapshot_ragionamento')}")
check("con il suo testo", p.get("snapshot_ragionamento_testo") is True)
check("nessun blocco vuoto", p.get("snapshot_ragionamento_vuoto") is False)

print("\n[7] Dopo un reset il ragionamento nuovo non resta invisibile")
check("il blocco compare", p.get("dopo_reset") == 1,
      f"blocchi visibili in piu': {p.get('dopo_reset')}")
check("con il testo", p.get("dopo_reset_testo") is True)

print("\n[8] A fine turno il blocco si chiude, e il successivo vive")
check("il blocco compare", p.get("dopo_turn_end") == 1,
      f"blocchi visibili in piu': {p.get('dopo_turn_end')}")
check("con il testo", p.get("dopo_turn_end_testo") is True)

print("\n[9] Ricostruzione a meta' turno: il pezzo dopo si vede lo stesso")
check("il blocco compare", p.get("dopo_ricostruzione") == 1,
      f"blocchi visibili in piu': {p.get('dopo_ricostruzione')}")
check("con il testo", p.get("dopo_ricostruzione_testo") is True)

print("\n[10] La verita' finale sul DOM")
check("nessun blocco visibile e vuoto", p.get("vuoti_visibili_alla_fine") == 0,
      f"blocchi vuoti: {p.get('vuoti_visibili_alla_fine')}")

print(f"\n{'=' * 60}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    print("FALLITI:", FAIL)
sys.exit(1 if FAIL else 0)

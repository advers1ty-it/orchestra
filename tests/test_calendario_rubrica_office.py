"""Calendario, rubrica e scrittura Office: i tre pezzi che mancavano.

Perche' un file di test e non tre: il rischio e' lo stesso per tutti e tre —
un formato che "sembra giusto". Un .ics scritto male non si apre nel
calendario, un contatto doppio non si trova piu', e un .docx che si scrive
e non si riapre non e' un documento. Quindi qui non si controlla che le
funzioni non sollevino: si controlla che il file prodotto venga **riletto
dal lettore vero** (`office.estrai`, `calendario.eventi`), che e' l'unica
prova che conta per chi domani apre quel file.

I doppioni della rubrica hanno un caso dedicato: aggiungere due volte lo
stesso cliente e' l'errore che rende inutile una rubrica, e la regola
("stessa email = aggiorna") deve restare scritta da qualche parte.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Il test stampa accenti veri: su una console Windows cp1252 `print`
# solleverebbe UnicodeEncodeError, e il fallimento sembrerebbe del codice
# provato invece che del terminale.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DATI = tempfile.mkdtemp(prefix="orchestra_dati_")
LAVORO = tempfile.mkdtemp(prefix="orchestra_lavoro_")
# Prima degli import: la cartella dati e la root dei tool si leggono da qui.
os.environ["ORCHESTRA_HOME"] = DATI
os.environ["ORCHESTRA_ROOT"] = LAVORO

from orchestra import calendario as cal  # noqa: E402
from orchestra import office, office_scrivi, rubrica  # noqa: E402
from orchestra.tools import _PROFILI, default_registry  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f" — {detail}" if detail and not cond else ""))


print("\n[1] calendario: si scrive un evento e si rilegge")
oggi = dt.datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
evento = cal.aggiungi("Dentista", oggi, oggi + dt.timedelta(hours=1),
                      luogo="Via Roma", note="portare la tessera")
check("l'evento torna con un id", evento["uid"].endswith("@orchestra"),
      evento["uid"])
trovati = cal.eventi(oggi - dt.timedelta(hours=1), oggi + dt.timedelta(hours=3))
check("e si ritrova nella finestra", len(trovati) == 1, str(len(trovati)))
check("con titolo, luogo e ora giusti",
      trovati and trovati[0]["titolo"] == "Dentista"
      and trovati[0]["luogo"] == "Via Roma"
      and trovati[0]["inizio"] == oggi,
      str(trovati[:1]))
testo_ics = open(cal.percorso_default(), encoding="utf-8").read()
check("il file e' iCalendar", testo_ics.startswith("BEGIN:VCALENDAR"),
      testo_ics[:40])
check("e si chiude", testo_ics.rstrip().endswith("END:VCALENDAR"),
      testo_ics[-40:])

print("\n[2] un evento di tutto il giorno non ha l'ora")
giorno = cal.aggiungi("Scadenza IVA", dt.datetime(2026, 11, 16),
                      tutto_il_giorno=True)
check("e' marcato come tale", giorno["tutto_il_giorno"] is True)
solo_giorno = cal.eventi(dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 17))
check("e si legge senza orario",
      any(e["titolo"] == "Scadenza IVA" and e["tutto_il_giorno"]
          for e in solo_giorno), str(solo_giorno[:1]))
check("la riga leggibile lo dice",
      "(tutto il giorno)" in cal.formatta(solo_giorno[0]),
      cal.formatta(solo_giorno[0]))

print("\n[3] le ripetizioni si espandono nella finestra")
ripetuto = os.path.join(LAVORO, "palestra.ics")
with open(ripetuto, "w", encoding="utf-8", newline="") as f:
    f.write("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:prova-rip\r\n"
            "DTSTART:20261102T080000\r\nDTEND:20261102T090000\r\n"
            "SUMMARY:Palestra\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")
occorrenze = cal.eventi(dt.datetime(2026, 11, 1), dt.datetime(2026, 12, 1),
                        file=ripetuto)
check("tre occorrenze, quante ne dichiara COUNT", len(occorrenze) == 3,
      str(len(occorrenze)))
check("a sette giorni l'una dall'altra",
      len(occorrenze) == 3
      and (occorrenze[1]["inizio"] - occorrenze[0]["inizio"]).days == 7,
      str([o["inizio"] for o in occorrenze]))
check("e sono marcate come ricorrenti",
      occorrenze and all(o["ripetuto"] for o in occorrenze))

print("\n[4] eliminare un evento lo toglie davvero dal file")
check("elimina risponde di averlo tolto", cal.elimina(evento["uid"]) is True)
check("e non c'e' piu' nella finestra",
      not cal.eventi(oggi - dt.timedelta(hours=1),
                     oggi + dt.timedelta(hours=3)))
check("un id inesistente torna False", cal.elimina("non-esiste") is False)
check("l'evento di tutto il giorno non e' stato toccato",
      any(e["titolo"] == "Scadenza IVA" for e in
          cal.eventi(dt.datetime(2026, 11, 16), dt.datetime(2026, 11, 17))))

print("\n[5] rubrica: la stessa email aggiorna, non duplica")
mario = rubrica.aggiungi("Mario Rossi", email="Mario@Esempio.it",
                         telefono="+39 333 1234567", azienda="Rossi Srl")
check("il primo inserimento e' nuovo", mario["aggiornato"] is False)
doppio = rubrica.aggiungi("Mario Rossi", email="mario@esempio.it")
check("la seconda volta aggiorna lo stesso contatto",
      doppio["aggiornato"] is True and doppio["id"] == mario["id"],
      str(doppio))
check("e non cancella il telefono che c'era",
      doppio["telefono"] == "+39 333 1234567", doppio["telefono"])
check("in rubrica c'e' un contatto solo", rubrica.conta() == 1,
      str(rubrica.conta()))
check("si trova per nome", [c["id"] for c in rubrica.cerca("mario")]
      == [mario["id"]])
check("e per telefono scritto senza spazi",
      [c["id"] for c in rubrica.cerca("333123")] == [mario["id"]],
      str([c["telefono"] for c in rubrica.cerca("333123")]))
modificato = rubrica.modifica(mario["id"], azienda="Rossi & Figli")
check("la modifica cambia un campo e tiene gli altri",
      modificato["azienda"] == "Rossi & Figli"
      and modificato["telefono"] == "+39 333 1234567", str(modificato))
vuoto_rifiutato = False
try:
    rubrica.aggiungi()
except ValueError:
    vuoto_rifiutato = True
check("un contatto senza nome, email e telefono viene rifiutato",
      vuoto_rifiutato)
check("elimina toglie il contatto",
      rubrica.elimina(mario["id"]) is True and rubrica.conta() == 0)

print("\n[6] office: il .docx prodotto si riapre col lettore vero")
documento = os.path.join(LAVORO, "preventivo.docx")
office_scrivi.scrivi_docx(
    documento, "Preventivo",
    ["Cliente: Rossi Srl", "", "Totale: 1.200,00 EUR"])
tipo, testo = office.estrai("preventivo.docx", open(documento, "rb").read())
check("e' riconosciuto come Word", "Word" in tipo, tipo)
check("con il titolo e i paragrafi dentro",
      "Preventivo" in testo and "Totale: 1.200,00 EUR" in testo,
      testo[:120])
with zipfile.ZipFile(documento) as z:
    parti = z.namelist()
check("con le parti che un .docx deve avere",
      "word/document.xml" in parti and "[Content_Types].xml" in parti,
      str(parti))

print("\n[7] office: il .xlsx tiene i numeri come numeri")
foglio = os.path.join(LAVORO, "ore.xlsx")
office_scrivi.scrivi_xlsx(
    foglio, [["Voce", "Ore"], ["Progetto", 4], ["Totale", 4.5]],
    foglio="Novembre")
tipo, testo = office.estrai("ore.xlsx", open(foglio, "rb").read())
check("e' riconosciuto come foglio Excel", "Excel" in tipo, tipo)
check("con il nome del foglio", "Novembre" in testo, testo[:120])
check("e le celle numeriche restano numeri",
      "Progetto | 4" in testo and "Totale | 4.5" in testo, testo[:200])
valido = True
with zipfile.ZipFile(foglio) as z:
    for nome_parte in z.namelist():
        try:
            ET.fromstring(z.read(nome_parte))
        except ET.ParseError:
            valido = False
check("tutte le parti sono XML valido", valido)

print("\n[8] i tre tool sono registrati, attivi e in ogni profilo")
registro = default_registry()
for nome in ("calendario", "rubrica", "office"):
    check(f"{nome} e' nel registro", registro.get(nome) is not None)
    check(f"{nome} e' attivo", nome in [t.name for t in registro.active])
    check(f"{nome} sta in ogni profilo",
          all(nome in profilo for profilo in _PROFILI.values()),
          str({p: nome in v for p, v in _PROFILI.items()}))

print("\n[9] e rispondono attraverso il tool, non solo come moduli")
calendario_tool = registro.get("calendario").handler
quando = dt.datetime.now().strftime("%Y-%m-%d") + " 09:00"
esito = calendario_tool(azione="aggiungi", titolo="Riunione", inizio=quando,
                        luogo="Ufficio")
check("calendario aggiunge", "Evento aggiunto" in esito, esito)
check("e 'oggi' lo elenca", "Riunione" in calendario_tool(azione="oggi"))

rubrica_tool = registro.get("rubrica").handler
esito = rubrica_tool(azione="aggiungi", nome="Anna Bianchi",
                     email="anna@esempio.it", telefono="06 123456")
check("rubrica aggiunge", "Contatto aggiunto" in esito, esito)
check("e cerca per telefono", "Anna Bianchi" in rubrica_tool(testo="06123456"))

office_tool = registro.get("office").handler
esito = office_tool(percorso="nota.docx", titolo="Nota",
                    paragrafi=["Prima riga", "Seconda riga"])
check("office scrive nella cartella di lavoro",
      os.path.exists(os.path.join(LAVORO, "nota.docx")), esito)
check("e lo dice", "creato" in esito, esito)
check("un formato non supportato lo spiega",
      "formato non supportato" in office_tool(percorso="nota.txt"))

print("\n[10] il foglio di calcolo: piu' fogli, formule, intestazione")
libro = os.path.join(LAVORO, "budget.xlsx")
office_scrivi.scrivi_xlsx(libro, fogli=[
    {"nome": "Entrate", "righe": [
        ["Voce", "Euro"], ["Stipendio", 1800], ["Extra", 200],
        ["Totale", "=SUM(B2:B3)"]]},
    {"nome": "Uscite", "righe": [["Voce", "Euro"], ["Affitto", 700]]},
])
with zipfile.ZipFile(libro) as z:
    parti_libro = z.namelist()
    libro_xml = z.read("xl/workbook.xml").decode()
    primo = z.read("xl/worksheets/sheet1.xml").decode()
    stili = z.read("xl/styles.xml").decode()
check("il file ha un foglio per ogni voce",
      "xl/worksheets/sheet2.xml" in parti_libro, str(parti_libro))
check("con i nomi che gli ho dato",
      'name="Entrate"' in libro_xml and 'name="Uscite"' in libro_xml,
      libro_xml[:200])
check("la formula e' una formula, non una stringa",
      "<f>SUM(B2:B3)</f>" in primo, primo[:300])
check("e il workbook chiede il ricalcolo all'apertura",
      "fullCalcOnLoad" in libro_xml, libro_xml[-160:])
check("l'intestazione usa lo stile grassetto",
      's="1"' in primo and "<b/>" in stili, stili[:160])
check("la prima riga e' bloccata",
      'state="frozen"' in primo, primo[:240])
check("le colonne hanno una larghezza",
      "customWidth" in primo, primo[:240])
tipo, testo = office.estrai("budget.xlsx", open(libro, "rb").read())
check("si riapre col lettore vero, fogli compresi",
      "Entrate" in testo and "Uscite" in testo, testo[:160])
check("con i numeri dentro", "Stipendio | 1800" in testo, testo[:220])
check("un nome foglio con caratteri vietati viene corretto",
      office_scrivi._nome_foglio("a/b:c", [], 1) == "a-b-c",
      office_scrivi._nome_foglio("a/b:c", [], 1))

print("\n[11] un PDF vero, senza dipendenze")
costoso = os.path.join(LAVORO, "preventivo.pdf")
office_scrivi.scrivi(
    costoso, "pdf", titolo="Preventivo 2026",
    paragrafi=["Cliente: Rossi Srl", "", "Totale: 1.200,00 EUR"],
    righe=[["Voce", "Euro"], ["Consulenza", "900"], ["Materiali", "300"]])
dati_pdf = open(costoso, "rb").read()
check("comincia con l'intestazione PDF", dati_pdf.startswith(b"%PDF-1.4"),
      str(dati_pdf[:8]))
check("e si chiude con EOF", dati_pdf.rstrip().endswith(b"%%EOF"),
      str(dati_pdf[-20:]))
check("contiene il titolo (a pezzi: il PDF scrive un Tj per parola)",
      b"Preventivo" in dati_pdf and b"2026" in dati_pdf)
check("e le righe della tabella",
      b"Consulenza" in dati_pdf and b"Materiali" in dati_pdf)
check("l'euro diventa EUR, come vuole il font",
      b"EUR" in dati_pdf and b"\x80" not in dati_pdf)

print("\n[12] si aggiunge a un documento esistente, senza riscriverlo")
lettera = os.path.join(LAVORO, "lettera.docx")
office_scrivi.scrivi_docx(lettera, "Lettera", ["Gentile cliente,",
                                              "prima riga"])
esito = office_scrivi.aggiungi(lettera, paragrafi=["Cordiali saluti",
                                                   "Mario Rossi"])
check("aggiunge i paragrafi e dice quanti", esito["aggiunti"] == 2, str(esito))
_, riletto = office.estrai("lettera.docx", open(lettera, "rb").read())
check("il documento riletto ha il vecchio e il nuovo",
      "Gentile cliente," in riletto and "Cordiali saluti" in riletto
      and "Mario Rossi" in riletto, riletto[:200])

ore = os.path.join(LAVORO, "ore2.xlsx")
office_scrivi.scrivi_xlsx(ore, [["Voce", "Ore"], ["Progetto", 4]])
esito = office_scrivi.aggiungi(ore, righe=[["Verifica", 2],
                                           ["Totale", "=SUM(B2:B3)"]])
check("aggiunge le righe al foglio", esito["aggiunti"] == 2, str(esito))
_, foglio_letto = office.estrai("ore2.xlsx", open(ore, "rb").read())
check("che restano in coda alle vecchie",
      "Progetto | 4" in foglio_letto and "Verifica | 2" in foglio_letto,
      foglio_letto[:220])
check("e la formula si rilegge come formula, non come cella vuota",
      "=SUM(B2:B3)" in foglio_letto, foglio_letto[:240])

senza = False
try:
    office_scrivi.aggiungi(os.path.join(LAVORO, "mai-esistito.docx"),
                           paragrafi=["x"])
except ValueError as e:
    senza = "non trovo" in str(e)
check("un file che non c'e' e' un errore che lo dice", senza)
pdf_immutabile = False
try:
    office_scrivi.aggiungi(costoso, paragrafi=["x"])
except ValueError as e:
    pdf_immutabile = "non si aggiorna" in str(e)
check("un PDF non si aggiorna: lo dice invece di troncarlo", pdf_immutabile)

print("\n[13] e il tool lo fa senza che l'utente debba sapere come")
tool_office = registro.get("office").handler
esito = tool_office(percorso="conto.pdf", titolo="Conto",
                    paragrafi=["Totale: 10 EUR"])
check("il tool scrive un PDF",
      os.path.exists(os.path.join(LAVORO, "conto.pdf")), esito)
check("e il messaggio parla di PDF", "PDF" in esito, esito)
esito = tool_office(azione="aggiungi", percorso="nota.docx",
                    paragrafi=["in coda"])
check("il tool aggiunge in coda", "Aggiunti" in esito, esito)
_, nota = office.estrai("nota.docx",
                        open(os.path.join(LAVORO, "nota.docx"), "rb").read())
check("e il paragrafo c'e' davvero", "in coda" in nota, nota[:160])

print("\n" + "=" * 62)
print(f"PASS {len(PASS)}  FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)

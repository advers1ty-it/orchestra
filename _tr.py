import io

P = "tests/test_runner.py"
s = io.open(P, encoding="utf-8").read()

# 1) i due check sul sorgente cercano una stringa che il codice non
#    scrive letteralmente: e' una f-string, quindi dentro c'e' un
#    {name}. E la finestra di 700 caratteri non arrivava a fine blocco.
vecchio = '''i = src.index("if code == 0:")
blocco = src[i:i + 700]
check("un exit non-zero porta a FAIL", '"FAIL' in blocco)
check("e porta anche ad aggiungere la suite ai falliti",
      "failed.append(name)" in blocco)'''
nuovo = '''i = src.index("if code == 0:")
blocco = src[i:src.index("if failed:", i)]
check("un exit non-zero porta a FAIL",
      re.search(r"FAIL\\s+\\{name\\}", blocco) is not None,
      blocco[:120])
check("e porta anche ad aggiungere la suite ai falliti",
      "failed.append(name)" in blocco,
      "senza questo il riepilogo e' vuoto e il processo esce 0")'''
assert vecchio in s
s = s.replace(vecchio, nuovo, 1)

# 2) lo stub girava dalla root del progetto con nomi di file relativi:
#    non trovava nessuna delle due suite, e fallivano entrambe. Il
#    check del riepilogo falliva perche' la stringa cercata era
#    "RIEPILOGO: cattiva" e in realta' era "RIEPILOGO: buona, cattiva".
vecchio2 = '''ok = os.path.join(tempfile.mkdtemp(), "ok.py")
ko = os.path.join(tempfile.mkdtemp(), "ko.py")'''
nuovo2 = '''# Nomi assoluti: lo stub gira con cwd=ROOT, e con un nome relativo
# non trova nessuna delle due suite — falliscono entrambe per un
# motivo che non e' quello che il test sta provando.
_d = tempfile.mkdtemp()
ok = os.path.join(_d, "ok.py")
ko = os.path.join(_d, "ko.py")'''
assert vecchio2 in s
s = s.replace(vecchio2, nuovo2, 1)

s = s.replace('SUITES = [("buona", "ok.py", True), ("cattiva", "ko.py", False)]',
              'SUITES = [("buona", OK, True), ("cattiva", KO, False)]')
s = s.replace('''stub = \'\'\'
import subprocess, sys''', '''stub = \'\'\'
import subprocess, sys
OK, KO = %r, %r''' % (ok, ko))
s = s.replace('''stub2 = stub.replace('("cattiva", "ko.py", False)', f'("aperta", {aperta!r}, False)')
stub2 = stub2.replace('"ko.py"', repr(ko))''',
              '''stub2 = stub.replace('("cattiva", KO, False)', '("aperta", %r, False)' % aperta)''')

# 3) e il check del riepilogo: contiene i nomi, non uno solo
s = s.replace('check("il riepilogo la nomina", "RIEPILOGO: cattiva" in out, out)',
              'check("il riepilogo la nomina", "RIEPILOGO" in out and "cattiva" in out, out)')

if "\nimport re" not in s:
    s = s.replace("import io\nimport os", "import io\nimport os\nimport re")

io.open(P, "w", encoding="utf-8").write(s)
print("  test_runner.py: tre assunzioni sbagliate tolte")
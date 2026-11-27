#!/usr/bin/env bash
# ============================================================
#  Installa-Orchestra.sh — installazione per Linux
#
#  FILE UNICO: non serve Git, non serve un account GitHub. Scarica
#  l'ultima release, la mette in ~/.local/share/orchestra, crea un
#  ambiente Python isolato e aggiunge il comando `orchestra` e il
#  collegamento "Avvia Orchestra".
#
#  Rilanciarlo aggiorna il codice senza toccare .env, database,
#  memoria, token o skill.
#
#    bash Installa-Orchestra.sh
#    bash Installa-Orchestra.sh --no-deps
#    bash Installa-Orchestra.sh --dir /percorso/orchestra
#
#  Se mancano Python (3.11+) o il modulo venv, propone di installare
#  i pacchetti di sistema con sudo: prima mostra i comandi e chiede
#  conferma. Con --no-sistema non tocca il sistema e stampa le
#  istruzioni. Non aggiunge repository di terze parti.
# ============================================================
set -u

API="${ORCHESTRA_RELEASE_API:-https://api.github.com/repos/advers1ty-it/orchestra/releases/latest}"
DEST="${ORCHESTRA_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/orchestra}"
DEPS="ask"
SISTEMA="ask"
ASSUNTO_NO=0
PY=""
TMP=""

_uso() {
    cat <<EOF
Uso: bash $(basename "$0") [opzioni]

  --dir PERCORSO   dove installare (default: $DEST)
  --no-deps        non installare le funzioni aggiuntive Python
  --deps           installa le funzioni aggiuntive senza chiedere
  --sistema        installa con sudo i pacchetti di sistema mancanti
  --no-sistema     non installare pacchetti di sistema: mostra solo i comandi
  -y, --yes        risposte affermative, senza domande
  -h, --help       questo testo

Dopo l'installazione:
  "$DEST/Avvia-Orchestra.sh"       avvia e apre il browser
  "$DEST/Orchestra.sh" log         mostra i log
  orchestra --version              comando CLI, se ~/.local/bin e' nel PATH
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir)
            [ "$#" -ge 2 ] || { echo "Manca il percorso dopo --dir" >&2; exit 2; }
            DEST="$2"
            shift 2
            ;;
        --dir=*)
            DEST="${1#--dir=}"
            shift
            ;;
        --no-deps)
            DEPS="no"
            shift
            ;;
        --deps)
            DEPS="si"
            shift
            ;;
        --sistema)
            SISTEMA="si"
            shift
            ;;
        --no-sistema)
            SISTEMA="no"
            shift
            ;;
        -y|--yes)
            ASSUNTO_NO=1
            [ "$DEPS" = "ask" ] && DEPS="si"
            [ "$SISTEMA" = "ask" ] && SISTEMA="si"
            shift
            ;;
        -h|--help)
            _uso
            exit 0
            ;;
        *)
            echo "Opzione sconosciuta: $1" >&2
            _uso >&2
            exit 2
            ;;
    esac
done

_pulizia() {
    if [ -n "$TMP" ] && [ -d "$TMP" ]; then
        rm -rf -- "$TMP"
    fi
}
trap _pulizia EXIT INT TERM

echo
echo "=== Installazione Orchestra (Linux) ==="
echo

# ---------------------------------------------------- pacchetti di sistema
# Il Python di Linux e' quasi sempre quello della distribuzione. Se manca
# o non ha venv, l'installer puo' installare i pacchetti con sudo, ma solo
# dopo aver mostrato i comandi e chiesto il permesso: un installer che
# modifica il sistema di nascosto e' peggio di uno che si ferma.
SISTEMA_UPDATE=()
SISTEMA_CMD=()

_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return $?
    fi
    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
        return $?
    fi
    echo "[ERRORE] sudo non e' disponibile: installa i pacchetti a mano." >&2
    return 1
}

_gestore_pacchetti() {
    local gestore
    for gestore in apt-get dnf yum pacman zypper apk; do
        if command -v "$gestore" >/dev/null 2>&1; then
            printf '%s\n' "$gestore"
            return 0
        fi
    done
    return 1
}

_pacchetti_sistema() {
    SISTEMA_UPDATE=()
    SISTEMA_CMD=()
    case "$1" in
        apt-get)
            SISTEMA_UPDATE=(apt-get update)
            SISTEMA_CMD=(apt-get install -y python3 python3-venv python3-pip ca-certificates)
            ;;
        dnf)
            SISTEMA_CMD=(dnf install -y python3 python3-pip ca-certificates)
            ;;
        yum)
            SISTEMA_CMD=(yum install -y python3 python3-pip ca-certificates)
            ;;
        pacman)
            SISTEMA_CMD=(pacman -S --needed --noconfirm python python-pip ca-certificates)
            ;;
        zypper)
            SISTEMA_CMD=(zypper --non-interactive install python3 python3-pip ca-certificates)
            ;;
        apk)
            SISTEMA_CMD=(apk add --no-cache python3 py3-pip ca-certificates)
            ;;
    esac
}

_mostra_comandi_sistema() {
    local prefisso=""
    if [ "$(id -u)" -ne 0 ]; then
        prefisso="sudo "
    fi
    if [ "${#SISTEMA_UPDATE[@]}" -gt 0 ]; then
        echo "      ${prefisso}${SISTEMA_UPDATE[*]}"
    fi
    echo "      ${prefisso}${SISTEMA_CMD[*]}"
}

_installa_pacchetti_sistema() {
    local motivo="$1" gestore="" risposta=""
    [ "$SISTEMA" = "no" ] && return 1
    if ! gestore="$(_gestore_pacchetti)"; then
        echo "[AVVISO] Non riconosco il gestore di pacchetti di questa distribuzione." >&2
        return 1
    fi
    _pacchetti_sistema "$gestore"
    echo
    echo "[!] Per continuare servono pacchetti di sistema: $motivo."
    echo "    Verra' eseguito:"
    _mostra_comandi_sistema
    if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
        echo "[ERRORE] Serve sudo per installare i pacchetti di sistema." >&2
        echo "         Installa a mano i comandi qui sopra, poi rilancia." >&2
        return 1
    fi
    if [ "$SISTEMA" = "ask" ]; then
        if [ "$ASSUNTO_NO" = "1" ]; then
            SISTEMA="si"
        elif [ -r /dev/tty ]; then
            printf '    Installarli ora? [S/n] ' >/dev/tty
            read -r risposta < /dev/tty || risposta=""
            case "$risposta" in
                [nN]|[nN][oO]) SISTEMA="no" ;;
                *) SISTEMA="si" ;;
            esac
        else
            # Installazione automatizzata senza terminale: non si indovina.
            SISTEMA="no"
        fi
    fi
    if [ "$SISTEMA" != "si" ]; then
        echo "[AVVISO] Nessun pacchetto di sistema installato."
        echo "         Rilancia con --sistema, oppure installa a mano i comandi qui sopra."
        return 1
    fi
    echo "Installo i pacchetti di sistema..."
    if [ "${#SISTEMA_UPDATE[@]}" -gt 0 ]; then
        # Un repository lento o irraggiungibile non deve impedire del tutto
        # l'installazione: apt puo' usare gli elenchi gia' presenti.
        if ! _sudo "${SISTEMA_UPDATE[@]}"; then
            echo "[AVVISO] Aggiornamento degli elenchi non riuscito; provo comunque." >&2
        fi
    fi
    if ! _sudo "${SISTEMA_CMD[@]}"; then
        echo "[ERRORE] Installazione dei pacchetti non riuscita." >&2
        return 1
    fi
    echo "[OK] Pacchetti di sistema installati."
    return 0
}

# ---------------------------------------------------------------- Python
_trova_python() {
    local candidato percorso primo=""
    PY=""
    for candidato in python3.14 python3.13 python3.12 python3.11 python3 python; do
        percorso="$(command -v "$candidato" 2>/dev/null)" || continue
        if ! "$percorso" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            continue
        fi
        [ -n "$primo" ] || primo="$percorso"
        # Preferisci un interprete gia' in grado di creare un venv: evita
        # di installare pacchetti se una versione piu' vecchia ma completa
        # e' gia' presente. Se nessuno ce l'ha, resta il primo trovato e
        # l'installer provera' a completarlo.
        if "$percorso" -c 'import venv, ensurepip' >/dev/null 2>&1; then
            PY="$percorso"
            return 0
        fi
    done
    if [ -n "$primo" ]; then
        PY="$primo"
        return 0
    fi
    return 1
}

if ! _trova_python; then
    echo "[!] Python 3.11 o superiore non trovato."
    _installa_pacchetti_sistema "Python 3.11+ e il modulo venv" || true
    if ! _trova_python; then
        cat >&2 <<'EOF'
[ERRORE] Python 3.11 o superiore non disponibile.

Orchestra ha bisogno di Python 3.11+ e del modulo venv. Se sai usare il
terminale, installa i pacchetti della tua distribuzione e rilancia:

  Debian/Ubuntu:  sudo apt update && sudo apt install python3 python3-venv
  Fedora:         sudo dnf install python3 python3-pip
  Arch:           sudo pacman -S python python-pip
  openSUSE:       sudo zypper install python3 python3-pip
  Alpine:         sudo apk add python3 py3-pip ca-certificates

Su Ubuntu 22.04 il Python di sistema e' 3.10: il repository ufficiale
non basta. Serve Python 3.11+ da un repository esterno (per esempio
deadsnakes) oppure una versione piu' recente della distribuzione.
L'installer non aggiunge repository di terze parti da solo.

Se non vuoi farlo a mano, rilancia con --sistema: l'installer ti
mostrera' i comandi e ti chiedera' il permesso prima di eseguirli.
EOF
        exit 1
    fi
fi

# Il modulo venv non e' garantito nemmeno quando Python c'e': su Debian
# e Ubuntu arriva con python3-venv, che spesso manca su una macchina
# appena installata. Si prova a rimediare prima di creare l'ambiente.
_ha_venv_modulo() {
    [ -n "$PY" ] && "$PY" -c 'import venv' >/dev/null 2>&1
}

_ha_ensurepip() {
    [ -n "$PY" ] && "$PY" -c 'import ensurepip' >/dev/null 2>&1
}

_errore_venv() {
    cat >&2 <<'EOF'
[ERRORE] Manca il modulo venv o non riesco a creare l'ambiente Python.

Installa il pacchetto della tua distribuzione e rilancia:

  Debian/Ubuntu:  sudo apt install python3-venv
  Fedora:         sudo dnf install python3-pip
  Arch:           sudo pacman -S python python-pip
  openSUSE:       sudo zypper install python3-pip
  Alpine:         sudo apk add python3 py3-pip

Oppure rilancia con --sistema: l'installer mostrera' i comandi e
chiedera' il permesso prima di eseguirli.
EOF
}

if ! _ha_venv_modulo; then
    echo "[!] Python non ha il modulo venv."
    _installa_pacchetti_sistema "il modulo venv" || true
    # I pacchetti appena installati possono aver reso completo un altro
    # interprete gia' presente (per esempio python3.11 accanto a un 3.14
    # installato a mano): si sceglie di nuovo prima di arrendersi.
    _trova_python || true
    if ! _ha_venv_modulo; then
        _errore_venv
        exit 1
    fi
fi

if ! _ha_ensurepip; then
    echo "[!] Python non ha ensurepip: pip potrebbe mancare."
    _installa_pacchetti_sistema "il modulo ensurepip" || true
    _trova_python || true
    if ! _ha_ensurepip; then
        echo "[AVVISO] L'ambiente verra' creato senza pip: Orchestra parte lo stesso," >&2
        echo "         ma le funzioni aggiuntive non si potranno installare da qui." >&2
        echo "         Su Debian/Ubuntu: sudo apt install python3-venv" >&2
    fi
fi

if [ -z "$PY" ]; then
    echo "[ERRORE] Python non e' piu' disponibile." >&2
    exit 1
fi
echo "[OK] Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# Se l'utente ha indicato un percorso relativo, lo si rende assoluto
# PRIMA di cambiare cartella: dopo, un percorso relativo sarebbe un
# altro posto.
case "$DEST" in
    "~") DEST="$HOME" ;;
    "~/"*) DEST="$HOME/${DEST#~/}" ;;
    /*) ;;
    *) DEST="$(pwd)/$DEST" ;;
esac
mkdir -p "$DEST" || { echo "[ERRORE] Non posso creare $DEST" >&2; exit 1; }
echo "[OK] Cartella: $DEST"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/orchestra-installa.XXXXXX")" || {
    echo "[ERRORE] Non posso creare una cartella temporanea." >&2
    exit 1
}

# ------------------------------------------------------- download e copia
# Il download e l'estrazione usano solo la standard library: niente
# curl, unzip o jq da installare, e funzionano anche su una macchina
# appena preparata. La fusione conserva i dati locali, come fa la
# variante Windows.
echo "Scarico l'ultima release da GitHub..."
if ! "$PY" - "$TMP" "$DEST" "$API" <<'PY'
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import zipfile

tmp, dest, api = sys.argv[1], sys.argv[2], sys.argv[3]
headers = {
    "User-Agent": "orchestra-installer-linux",
    "Accept": "application/vnd.github+json",
}


def fail(msg, code=1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


try:
    req = urllib.request.Request(api, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        release = json.load(r)
except urllib.error.HTTPError as e:
    fail(f"[ERRORE] GitHub ha risposto {e.code}. Riprova piu' tardi.", 2)
except urllib.error.URLError as e:
    motivo = str(getattr(e, "reason", e))
    if "CERTIFICATE_VERIFY_FAILED" in motivo or "certificate verify failed" in motivo:
        fail(
            "[ERRORE] I certificati HTTPS non sono completi.\n"
            "  Debian/Ubuntu: sudo apt install --reinstall ca-certificates && sudo update-ca-certificates\n"
            "  Fedora: sudo dnf reinstall ca-certificates\n"
            "  Arch: sudo pacman -S ca-certificates\n"
            "Poi rilancia l'installer.",
            2,
        )
    fail(f"[ERRORE] GitHub non raggiungibile: {motivo}", 2)
except Exception as e:  # noqa: BLE001
    fail(f"[ERRORE] Lettura della release non riuscita: {type(e).__name__}: {e}", 2)

url = ""
for asset in release.get("assets") or []:
    nome = str(asset.get("name") or "")
    if nome.lower().endswith(".zip") and asset.get("browser_download_url"):
        url = str(asset["browser_download_url"])
        break
if not url:
    url = str(release.get("zipball_url") or "")
if not url:
    fail("[ERRORE] La release non ha un archivio scaricabile.", 2)

versione = str(release.get("tag_name") or "").lstrip("v")
print(f"  release: {release.get('tag_name') or versione or '?'}")

zip_path = os.path.join(tmp, "release.zip")
try:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r, open(zip_path, "wb") as f:
        shutil.copyfileobj(r, f, 64 * 1024)
except urllib.error.URLError as e:
    fail(f"[ERRORE] Download non riuscito: {getattr(e, 'reason', e)}", 2)
except Exception as e:  # noqa: BLE001
    fail(f"[ERRORE] Download non riuscito: {type(e).__name__}: {e}", 2)

try:
    with zipfile.ZipFile(zip_path) as z:
        nomi = [n for n in z.namelist() if not n.endswith("/")]
        if not nomi:
            fail("[ERRORE] L'archivio della release e' vuoto.", 2)
        radici = {n.split("/", 1)[0] for n in nomi}
        if len(radici) != 1:
            fail(f"[ERRORE] L'archivio ha piu' radici: {sorted(radici)}", 2)
        radice = radici.pop()
        # Estrazione in una cartella di appoggio: prima si controlla che
        # l'archivio sia quello che ci si aspetta, poi si tocca DEST.
        if radice + "/orchestra/__init__.py" not in nomi:
            fail("[ERRORE] L'archivio non contiene orchestra/__init__.py.", 2)
        for n in nomi:
            parti = n.split("/")
            if ".." in parti or n.startswith("/"):
                fail(f"[ERRORE] Percorso non sicuro nell'archivio: {n}", 2)
        z.extractall(tmp)
except zipfile.BadZipFile:
    fail("[ERRORE] Il file scaricato non e' uno zip valido.", 2)

origine = os.path.join(tmp, radice)
if not os.path.isdir(origine):
    fail("[ERRORE] Cartella della release non trovata.", 2)

escludi_nomi = {
    ".env", "token.txt", "goals.json", "budget_global.json",
    "storico.db", "memoria_indice.db", "permessi.json",
    "nous_auth.json", ".remote_state.json",
}
escludi_est = (".db", ".db-wal", ".db-shm")
escludi_cart = {
    "__pycache__", "node_modules", "sessions", "tmp", "plans",
    ".orchestra", ".git", ".freebuff", "_dati_test",
    "_dati_test_server", "_bench", "_prova", "_probe",
    ".cloud-attachments", "venv", ".venv",
}

copiati = 0
saltati = 0
for base, cartelle, files in os.walk(origine):
    cartelle[:] = [c for c in cartelle if c not in escludi_cart]
    for nome in files:
        src = os.path.join(base, nome)
        rel = os.path.relpath(src, origine)
        parti = rel.split(os.sep)
        if any(p in escludi_cart for p in parti):
            saltati += 1
            continue
        if nome in escludi_nomi or nome.endswith(escludi_est):
            saltati += 1
            continue
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copiati += 1

print(f"  {copiati} file aggiornati, {saltati} file locali lasciati come erano")

init_py = os.path.join(dest, "orchestra", "__init__.py")
try:
    with open(init_py, encoding="utf-8") as f:
        m = re.search(r"""__version__\s*=\s*['"]([^'"]+)['"]""", f.read())
    if m:
        print(f"  versione installata: {m.group(1)}")
except OSError:
    pass
PY
then
    echo "[ERRORE] Installazione interrotta: nessun file e' stato avviato." >&2
    exit 1
fi

# ------------------------------------------------------------- ambiente
VENV="$DEST/venv"
if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "Il vecchio ambiente Python non va bene: lo ricreo."
    rm -rf -- "$VENV"
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "Creo l'ambiente Python isolato in $VENV..."
    if ! "$PY" -m venv "$VENV"; then
        # Su alcune distribuzioni ensurepip manca ma venv funziona: meglio
        # un'installazione senza pip (le funzioni extra si aggiungono dopo)
        # che un installer che si ferma dopo aver gia' scaricato tutto.
        echo "[AVVISO] Creazione con pip non riuscita; riprovo senza pip..." >&2
        rm -rf -- "$VENV"
        if ! "$PY" -m venv --without-pip "$VENV"; then
            _errore_venv
            exit 1
        fi
    fi
fi
HA_PIP=1
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    if ! "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
        HA_PIP=0
        echo "[AVVISO] L'ambiente non ha pip: Orchestra parte lo stesso," >&2
        echo "         ma le funzioni aggiuntive non si possono installare da qui." >&2
        echo "         Su Debian/Ubuntu: sudo apt install python3-venv" >&2
    fi
fi
echo "[OK] Ambiente Python: $VENV"

# ------------------------------------------------------- certificati
# Su Linux Python usa il bundle di sistema, non lo store di Windows. Il
# controllo resta utile: dice se manca una radice e come aggiornare il
# pacchetto ca-certificates, invece di lasciare che il sintomo sia un
# "rete non raggiungibile" quando l'utente salva il token del bot.
echo "Controllo i certificati..."
if [ -f "$DEST/orchestra/certificati.py" ]; then
    CERT_OUT="$TMP/certificati.out"
    if "$VENV/bin/python" "$DEST/orchestra/certificati.py" >"$CERT_OUT" 2>&1; then
        echo "[OK] Certificati a posto."
    else
        cat "$CERT_OUT" 2>/dev/null || true
        echo "[AVVISO] Manca almeno una radice: aggiorna ca-certificates e riprova." >&2
    fi
fi

# ---------------------------------------------------------- dipendenze
if [ "$DEPS" = "ask" ]; then
    if [ "$ASSUNTO_NO" = "1" ]; then
        DEPS="si"
    elif [ -r /dev/tty ]; then
        printf 'Installare ricerca web, immagini e PDF (consigliato)? [S/n] ' >/dev/tty
        RISPOSTA=""
        read -r RISPOSTA < /dev/tty || RISPOSTA=""
        case "$RISPOSTA" in
            [nN]|[nN][oO]) DEPS="no" ;;
            *) DEPS="si" ;;
        esac
    else
        # Senza terminale (installazione automatizzata) non si indovina:
        # il codice parte lo stesso, le funzioni si aggiungono dopo.
        DEPS="no"
    fi
fi

if [ "$DEPS" = "si" ] && [ "$HA_PIP" = "0" ]; then
    echo "[AVVISO] Salto le funzioni aggiuntive: manca pip nell'ambiente." >&2
elif [ "$DEPS" = "si" ]; then
    echo "Installo le funzioni aggiuntive (qualche minuto)..."
    if "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$DEST/requirements.txt"; then
        echo "[OK] Dipendenze installate."
    else
        echo "[AVVISO] Qualche dipendenza non si e' installata: Orchestra parte lo stesso." >&2
        echo "         Puoi riprovare da Opzioni -> Dipendenze." >&2
    fi
else
    echo "[OK] Funzioni aggiuntive saltate (si possono installare dopo da Opzioni)."
fi

# --------------------------------------------------------------- .env
if [ ! -f "$DEST/orchestra/.env" ]; then
    if [ -f "$DEST/orchestra/.env.example" ]; then
        cp "$DEST/orchestra/.env.example" "$DEST/orchestra/.env"
        echo "[OK] Creato orchestra/.env: inserisci qui le chiavi API."
    fi
else
    echo "[OK] orchestra/.env esistente conservato."
fi

chmod +x "$DEST/Orchestra.sh" "$DEST/Avvia-Orchestra.sh" 2>/dev/null || true
chmod +x "$DEST/installer/Installa-Orchestra.sh" 2>/dev/null || true

# ------------------------------------------------------- comando orchestra
BIN="${HOME}/.local/bin"
mkdir -p "$BIN"
SHIM="$BIN/orchestra"
cat > "$SHIM" <<EOF
#!/usr/bin/env bash
cd "$DEST" || exit 1
exec "$VENV/bin/python" -m orchestra.cli "\$@"
EOF
chmod +x "$SHIM"
echo "[OK] Comando CLI: $SHIM"

# --------------------------------------------------------- collegamenti
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
DESKTOP_FILE="$APPS/orchestra.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Orchestra
Comment=Assistente AI che lavora sul tuo computer
Exec="$DEST/Avvia-Orchestra.sh"
Path=$DEST
Icon=$DEST/installer/orchestra.ico
Terminal=false
Categories=Development;Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"

DESKTOP_DIR=""
if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
fi
[ -n "$DESKTOP_DIR" ] || DESKTOP_DIR="$HOME/Desktop"
if [ -d "$DESKTOP_DIR" ]; then
    cp "$DESKTOP_FILE" "$DESKTOP_DIR/Orchestra.desktop"
    chmod +x "$DESKTOP_DIR/Orchestra.desktop"
    # GNOME chiede il consenso per i launcher sul Desktop. Se gio c'e',
    # lo si imposta; se non c'e', il file resta comunque eseguibile.
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_DIR/Orchestra.desktop" metadata::trusted true >/dev/null 2>&1 || true
    fi
    echo "[OK] Collegamento Desktop: $DESKTOP_DIR/Orchestra.desktop"
else
    echo "[OK] Nessuna cartella Desktop: il launcher e' nel menu applicazioni."
fi

case ":${PATH:-}:" in
    *":$BIN:"*) ;;
    *)
        echo
        echo "[AVVISO] $BIN non e' nel PATH."
        echo "         Aggiungi questa riga a ~/.bashrc (o ~/.profile):"
        echo "         export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo
echo "=== Fatto ==="
echo "Avvia:  \"$DEST/Avvia-Orchestra.sh\""
echo "Log:    \"$DEST/Orchestra.sh\" log"
echo "Dati:   ${ORCHESTRA_HOME:-$HOME/.orchestra}"
echo
echo "Rilancia questo installer per aggiornare il codice: .env, database,"
echo "memoria e token non vengono toccati."
echo

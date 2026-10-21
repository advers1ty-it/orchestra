# tools.py diventa un pacchetto: loader + un file per tool

## Obiettivo

`orchestra/tools.py` (817 righe) smette di essere un modulo e diventa un
pacchetto: `orchestra/tools/__init__.py` contiene solo registro, profili e
SYSTEM_PROMPT, e ogni tool sta nel suo file dentro `orchestra/tools/`.
Risultato: ogni tool si patcha da solo, senza aprire un file unico di 800
righe dove una modifica ne tocca un'altra.

## Contesto (verificato, non ipotizzato)

Struttura attuale di `orchestra/tools.py`:

| Righe | Contenuto |
|---|---|
| 15-68 | `_sandbox_env`, `_kill_tree` (guardie di processo) |
| 80-135 | `_root`, `ROOT`, `set_permission_gate`, `_gate`, `_safe_path` |
| 141-293 | `tool_read_file`, `tool_write_file`, `tool_list_dir` |
| 296-472 | `tool_run_shell` |
| 475-625 | `_SUSPICIOUS`, `_percorso_fuori`, `_check_shell_access`, `_detect_posix_shell`, `_sq` |
| 628-668 | `tool_calculate` |
| 671-724 | `_PROFILI`, `applica_profilo`, `profilo_per_testo` |
| 726-778 | `default_registry` |
| 781-817 | `SYSTEM_PROMPT` |

Il blocco critico è questo, provato in una cartella di prova:

```
con    orchestra/tools/__init__.py  -> vince la CARTELLA (è un pacchetto)
senza  orchestra/tools/__init__.py  -> vince il FILE tools.py
```

Quindi il passaggio è: **cancellare `tools.py`** e creare `tools/` con
`__init__.py`. Non si possono tenere entrambi.

Sono ~25 i punti che importano da `orchestra.tools`. **Nessuno** importa le
funzioni `tool_*` dall'esterno: importano solo `default_registry`,
`SYSTEM_PROMPT`, `_root`, `_gate`, `set_permission_gate`, `_safe_path`,
`_check_shell_access`, `_detect_posix_shell`, `_PROFILI`, `applica_profilo`,
`profilo_per_testo`, `_percorso_fuori`. Se `__init__.py` li ri-esporta
tutti, **nessun import esterno va toccato**.

Due test invece vanno toccati, perché guardano la struttura e non il
comportamento:

- `tests/test_permessi_integrazione.py:129` apre `orchestra/tools.py` come
  FILE e conta `_safe_path(`. Con il pacchetto quel file non esiste più.
- `tests/test_compila.py:36` fa `PKG.glob("*.py")`: con la cartella,
  `tools.py` sparisce dal glob e i nuovi sottomoduli non vengono controllati.

## Passi

### 1. Creare `orchestra/tools/` con le guardie condivise

`orchestra/tools/_guard.py` — `_sandbox_env`, `_kill_tree`, `_root`, `ROOT`,
`set_permission_gate`, `_gate`, `_safe_path`, `_SUSPICIOUS`,
`_percorso_fuori`, `_check_shell_access`, `_detect_posix_shell`, `_sq`.

Controllo: `python -c "from orchestra.tools._guard import _safe_path"`.

### 2. Un file per tool base

`orchestra/tools/read_file.py`, `write_file.py`, `list_dir.py`,
`run_shell.py`, `calculate.py` — ciascuno con la sua `tool_*()` e i
docstring che spiegano *perché* è fatto così (sono la parte più preziosa
del file, non vanno risunte).

Controllo: ognuno importa e la funzione restituisce un `Tool` con nome e
schema.

### 3. `orchestra/tools/__init__.py` come loader/registro

Re-esporta i nomi che gli altri moduli usano (`default_registry`,
`SYSTEM_PROMPT`, `_root`, `_gate`, `set_permission_gate`, `_safe_path`,
`_check_shell_access`, `_detect_posix_shell`, `_percorso_fuori`, `_PROFILI`,
`applica_profilo`, `profilo_per_testo`) e contiene `default_registry`,
`_PROFILI`, `applica_profilo`, `profilo_per_testo`, `SYSTEM_PROMPT`.

Controllo: `python -c "from orchestra.tools import default_registry, SYSTEM_PROMPT"`.

### 4. Cancellare `orchestra/tools.py`

È il passaggio che decide tutto (vedi il blocco critico). Si fa solo dopo
che i passi 1-3 importano pulito.

Controllo: `python -c "import orchestra.tools as t; print(t.__file__)"`
deve stampare `.../orchestra/tools/__init__.py`.

### 5. Portare dentro anche i tool che oggi stanno fuori

`tools_edit_file.py` → `tools/edit_file.py`, e gli altri
(`memoria_tools.py`, `web_tools.py`, `browser_tools.py`, `computer_tools.py`)
si lasciano dove sono: sono già file singoli ben separati, e spostarli è un
secondo lavoro. Questo passo copre solo `edit_file`, che è nato per stare
lì dentro.

Controllo: `edit_file` resta registrato e attivo.

### 6. Aggiustare i due test strutturali

- `test_permessi_integrazione.py`: invece di aprire `tools.py`, aprire
  i file del pacchetto e contare `_safe_path(` sul totale. Il test verifica
  una proprietà (la guardia c'è sui tool su file), non un percorso.
- `test_compila.py`: il glob deve diventare ricorsivo
  (`PKG.rglob("*.py")`) o esplicito su `tools/`, altrimenti smette di
  controllare i nuovi moduli — esattamente il difetto che quel test esiste
  per prevenire.

Controllo: entrambi passano.

### 7. Aggiornare `README.md:58`

`| tools.py | Tool concreti + profili |` → la riga nuova che dice
`tools/` (pacchetto) e cosa contiene l'`__init__.py`.

## Rischi

- **Il docstring di `run_shell` (righe 296-317) spiega tre bug veri.**
  Se nel copiare si risente, quel file perde la ragione dei suoi guard.
  Per questo il passo 2 dice esplicitamente di non riscrivere i docstring.
- **`_safe_path` è importato da `tools_edit_file.py` e da nessun altro
  tool esterno.** Se `__init__.py` non lo ri-esporta, `edit_file` rompe.
- **`test_compila.py` passa silenziosamente a controllare meno.** È il
  rischio peggiore: un test che sembra coprire e non copre. Il passo 6
  esiste per questo.
- **`_probe/test_paths.py` importa `_check_shell_access` e
  `_percorso_fuori`.** Non è nel runner (`run_all.py`), ma è lì: se non
  viene aggiornato, rompe al primo uso.

## Verifica finale

```
python tests/run_all.py
```

Tutte le suite devono passare. In particolare: `test_offline` (52),
`test_security` (32), `test_compila` (77), `test_permessi_integrazione`,
`test_tool_edit_file` (17).

E due comandi che dimostrano la forma nuova:

```
python -c "import orchestra.tools as t; print(t.__file__)"
python -c "from orchestra.tools import default_registry as d; \
           print(sorted(d().all_names()))"
```

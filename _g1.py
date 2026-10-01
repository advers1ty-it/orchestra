import io

# --- 1) l'HTML: la sezione cestino e le schede ------------------------
P = "orchestra/web/index.html"
s = io.open(P, encoding="utf-8").read()

vecchio = '''      <nav class="opzioni-nav" aria-label="sezioni">
        <button id="opz-tab-modelo" class="opzioni-tab" data-sez="modello">Modello</button>
        <button id="opz-tab-skill" class="opzioni-tab" data-sez="skill">Skill</button>
        <button id="opz-tab-servizi" class="opzioni-tab" data-sez="servizi">Servizi</button>
        <button id="opz-tab-permessi" class="opzioni-tab" data-sez="permessi">Permessi</button>
        <button id="opz-tab-gratis" class="opzioni-tab" data-sez="gratis">Gratis</button>
      </nav>'''
nuovo = '''      <nav class="opzioni-nav" aria-label="sezioni">
        <button id="opz-tab-modelo" class="opzioni-tab" data-sez="modello">Modello</button>
        <button id="opz-tab-skill" class="opzioni-tab" data-sez="skill">Skill</button>
        <button id="opz-tab-cestino" class="opzioni-tab" data-sez="cestino">Cestino</button>
        <button id="opz-tab-servizi" class="opzioni-tab" data-sez="servizi">Servizi</button>
        <button id="opz-tab-permessi" class="opzioni-tab" data-sez="permessi">Permessi</button>
        <button id="opz-tab-gratis" class="opzioni-tab" data-sez="gratis">Gratis</button>
      </nav>'''
assert vecchio in s, "barra laterale non trovata"
s = s.replace(vecchio, nuovo, 1)

# La sezione cestino, dopo quella delle skill.
m = '''        <section id="opz-sez-servizi" class="opz-sez" data-sez="servizi" hidden>'''
nuovo_m = '''        <section id="opz-sez-cestino" class="opz-sez" data-sez="cestino" hidden>
          <!-- Il cestino e' una sezione, non una nota a pie' di pagina.
               Cancellare una skill senza poterla vedere e' peggio che
               non cancellarla: l'utente smette di fidarsi del
               pulsante perche' non sa dove vanno le cose. Qui si vede
               cosa c'e', si rimette, e si cancella davvero. -->
          <div class="opzioni-skill">
            <div class="opzioni-skill-testa">
              <b>Cestino</b>
              <span class="dim" id="skill-cestino-nota"></span>
            </div>
            <div class="opzioni-skill-azioni">
              <button id="skill-svuota" class="ghost">Cancella tutto</button>
            </div>
            <div id="skill-cestino" class="skill-griglia"></div>
          </div>
        </section>

        <section id="opz-sez-servizi" class="opz-sez" data-sez="servizi" hidden>'''
assert m in s, "sezione servizi non trovata"
s = s.replace(m, nuovo_m, 1)

# le liste diventano griglie
s = s.replace('<div id="skill-generate" class="skill-lista"></div>',
              '<div id="skill-generate" class="skill-griglia"></div>')
s = s.replace('<div id="skill-scaricate" class="skill-lista"></div>',
              '<div id="skill-scaricate" class="skill-griglia"></div>')

io.open(P, "w", encoding="utf-8").write(s)
print("  index.html: sezione cestino e griglie")
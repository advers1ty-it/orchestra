"""Council: consiglio di advisor AI (pattern Roast Room) per Orchestra."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, 'council_data')
ROSTER_PATH = os.path.join(DATA_DIR, 'roster.json')
ENV_PATH = os.path.join(HERE, '.env')


def load_roster() -> list[dict[str, Any]]:
    with open(ROSTER_PATH, encoding='utf-8') as f:
        raw = json.load(f)
    return list(raw.get('seats', []))


def load_roster_raw() -> dict[str, Any]:
    with open(ROSTER_PATH, encoding='utf-8') as f:
        return json.load(f)


def _seat_by_key(key: str) -> dict[str, Any] | None:
    for s in load_roster():
        if s['key'] == key:
            return s
    return None


def _read_text(path: str) -> str:
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def _agent_body(key: str) -> str:
    txt = _read_text(os.path.join(DATA_DIR, 'agents', f'{key}.md'))
    if txt.startswith('---'):
        parts = txt.split('---', 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return txt.strip()


def _brain_text(slug: str) -> str:
    base = os.path.join(DATA_DIR, 'brains', slug)
    hot = _read_text(os.path.join(base, '_hot.md')).strip()
    fw = _read_text(os.path.join(base, 'frameworks.md')).strip()
    pos = _read_text(os.path.join(base, 'positions.md')).strip()
    fw = fw[:14000]
    pos = pos[:9000]
    parts = []
    if hot:
        parts.append('## HOT SHEET\n' + hot)
    if fw:
        parts.append('## FRAMEWORKS\n' + fw)
    if pos:
        parts.append('## POSITIONS\n' + pos)
    return '\n\n'.join(parts)


def advisor_system_prompt(key: str) -> str:
    seat = _seat_by_key(key)
    if not seat:
        return ''
    body = _agent_body(key)
    brain = _brain_text(seat['slug'])
    return (
        f'{body}\n\n'
        f'---\n\n'
        f'## Brain (memoria compilata dalla sua opera pubblica)\n\n{brain}\n\n'
        f'---\n\n'
        f'## Lingua\n\nRispondi sempre in italiano. Mantieni la persona, il formato richiesto e cita le fonti con id (es. S063).\n'
    )


CHAIR_SYSTEM = (
    'Sei il Chair del Roast Room. Non argomenti mai una tesi: gestisci la sala, '
    'tieni il punteggio, identifichi i cruxes, scrivi la draft resolution e il verdict. '
    'Parli in italiano, chiaro e conciso, senza filler. Quando ti chiedo JSON, rispondi '
    'SOLO con JSON valido (no markdown, no testo fuori).'
)


def _slugify(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return (s[:40] or 'decisione').strip('-')


def _ensure_provider(provider: Any = None):
    if provider is not None:
        return provider
    from .providers import build_provider, ambiente
    env = ambiente(ENV_PATH)
    for k, v in os.environ.items():
        env.setdefault(k, v)
    chiavi = {'nvidia': 'NVIDIA_API_KEY', 'openrouter': 'OPENROUTER_API_KEY',
              'groq': 'GROQ_API_KEY', 'cerebras': 'CEREBRAS_API_KEY',
              'mistral': 'MISTRAL_API_KEY', 'openai': 'OPENAI_API_KEY',
              'nous': 'NOUS_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY'}
    def ha_chiave(p):
        if p in ('ollama', 'lmstudio'):
            return True
        return bool((env.get(chiavi.get(p, '')) or '').strip())
    candidati = []
    cfg = (env.get('ORCHESTRA_PROVIDER') or '').strip()
    if cfg and ha_chiave(cfg):
        candidati.append(cfg)
    for p in ['nvidia', 'groq', 'cerebras', 'mistral', 'openrouter', 'anthropic', 'openai', 'nous', 'ollama', 'lmstudio']:
        if ha_chiave(p) and p not in candidati:
            candidati.append(p)
    if not candidati:
        raise RuntimeError('nessun provider con chiave disponibile')
    model = (env.get('ORCHESTRA_MODEL') or '').strip()
    for p in candidati:
        try:
            prov = build_provider(p, model=model, env=env)
            return prov
        except Exception:
            continue
    raise RuntimeError('impossibile costruire un provider')


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    start = text.find('{')
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _ask(provider, system_prompt, user_prompt, max_tokens=900, temp=0.7, max_iterations=2):
    from .agent import Agent, LoopConfig
    from .types import ToolRegistry
    agent = Agent(provider, ToolRegistry(), system_prompt,
                  LoopConfig(max_iterations=max_iterations, max_tokens=max_tokens, temperature=temp))
    try:
        stato = agent.run(user_prompt)
        msgs = getattr(stato, 'messages', []) or []
        for m in reversed(msgs):
            if getattr(m, 'role', '') == 'assistant':
                t = (getattr(m, 'content', '') or '').strip()
                if t:
                    return t
    except Exception as e:
        return f'[errore: {e}]'
    return ''


def _ask_verdict(provider, system_prompt, user_prompt, max_tokens=3000, temp=0.5):
    """Genera il verdict con continuazione automatica se troncato, e garantisce
    la presenza della sezione Glossario."""
    text = _ask(provider, system_prompt, user_prompt, max_tokens=max_tokens, temp=temp)
    if not text or text.startswith('[errore'):
        return text

    def _completo(t):
        t = t.rstrip()
        if not t:
            return False
        # deve contenere il glossario (richiesto dal template) e finire con
        # punteggiatura di frase
        has_gloss = '## Glossario' in t or '## glossario' in t.lower()
        ends_ok = t[-1] in '.!?…' or t.endswith('---')
        return has_gloss and ends_ok

    # continuazione se troncato
    for _ in range(2):
        if _completo(text):
            break
        cont_prompt = (
            'Il report precedente si è interrotto o è incompleto. '
            'Continua ESATTAMENTE da dove hai lasciato, scrivendo solo le '
            'sezioni/paragrafi mancanti. NON ripetere nulla di già scritto. '
            'Sezioni attese (in ordine): Scorecard, Math, Why the council '
            'landed here, Where they fought, Minority report, Conditions, '
            'What to do next, Glossario. '
            'Termina con la sezione "## Glossario" (termini tecnici usati, '
            'una riga ciascuno in italiano semplice).\n\n'
            'Testo già scritto (coda):\n' + text[-1200:]
        )
        add = _ask(provider, system_prompt, cont_prompt, max_tokens=max_tokens, temp=temp, max_iterations=1)
        if not add or add.startswith('[errore') or add.strip() == text.strip():
            break
        # evita sovrapposizione: se add ripete la coda, taglia
        tail = text[-200:].strip()
        if tail and add.startswith(tail[:60]):
            # trova punto di split
            idx = add.find(tail[:60])
            if idx > 0:
                add = add[idx + len(tail[:60]):].lstrip()
        text = text.rstrip() + '\n' + add.strip()

    # glossario di fallback se ancora assente
    if '## Glossario' not in text and '## glossario' not in text.lower():
        gloss_prompt = (
            'Dato questo verdict, scrivi SOLO la sezione "## Glossario": '
            'elenca i termini tecnici usati (CAC, LTV, runway, cash-burn, '
            'margine lordo, burn rate, fulfillment, SKU, ecc.) con una riga '
            'ciascuno in italiano semplice. Solo markdown, niente altro.\n\n'
            + text[:3000]
        )
        gloss = _ask(provider, system_prompt, gloss_prompt, max_tokens=600, temp=0.4, max_iterations=1)
        if gloss and not gloss.startswith('[errore'):
            text = text.rstrip() + '\n\n' + gloss.strip()

    return text


def _risposta_finale(stato: Any) -> str:
    msgs = getattr(stato, 'messages', None) or []
    for m in reversed(msgs):
        if getattr(m, 'role', '') == 'assistant':
            return (getattr(m, 'content', '') or '').strip()
    return ''


def _emit(on_event, kind: str, **data: Any) -> None:
    if on_event is None:
        return
    try:
        on_event(kind, data)
    except Exception:
        pass


def _parse_int(s):
    if s is None:
        return None
    m = re.search(r'(\d+)', str(s))
    return int(m.group(1)) if m else None


def _parse_option_scores(text: str, option_ids: list[str]) -> dict[str, int | None]:
    res = {oid: None for oid in option_ids}
    m = re.search(r'OPTION SCORES\s*:\s*(.+)', text or '', re.IGNORECASE)
    if not m:
        return res
    line = m.group(1)
    for oid in option_ids:
        mm = re.search(r'\b' + re.escape(oid) + r'\b[^0-9]{0,6}(\d+)', line, re.IGNORECASE)
        if mm:
            res[oid] = int(mm.group(1))
    if all(v is None for v in res.values()):
        nums = [int(x) for x in re.findall(r'(\d+)', line)]
        for i, oid in enumerate(option_ids):
            if i < len(nums):
                res[oid] = nums[i]
    return res


def _parse_pillar_score(text: str) -> int | None:
    m = re.search(r'PILLAR SCORE\s*:\s*(\d+)', text or '', re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_final_score(text: str) -> int | None:
    m = re.search(r'FINAL SCORE\s*:\s*(\d+)', text or '', re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_confidence(text: str) -> int | None:
    m = re.search(r'CONFIDENCE\s*:\s*(\d+)', text or '', re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_ruin(text: str) -> str:
    m = re.search(r'RUIN RISK\s*:\s*(none|possible|likely)', text or '', re.IGNORECASE)
    return (m.group(1).lower() if m else 'none')


def _parse_door(text: str) -> str:
    m = re.search(r'DOOR\s*:\s*(one-way|two-way)', text or '', re.IGNORECASE)
    return (m.group(1).lower() if m else 'two-way')


def _parse_vote(text: str) -> str:
    m = re.search(r'VOTE\s*:\s*(Endorse|Endorse with amendment|Dissent)', text or '', re.IGNORECASE)
    return (m.group(1) if m else '')


def _parse_one_line(text: str) -> str:
    m = re.search(r'ONE LINE FOR THE FOUNDER\s*:\s*(.+)', text or '', re.IGNORECASE)
    if m:
        return m.group(1).strip().split('\n')[0].strip()
    m = re.search(r'THE CALL\s*:\s*(.+)', text or '', re.IGNORECASE)
    if m:
        return m.group(1).strip().split('\n')[0].strip()
    return ''


def _parse_stance(text: str) -> str:
    m = re.search(r'STANCE\s*:\s*(.+)', text or '', re.IGNORECASE)
    if m:
        return m.group(1).strip().split('\n')[0].strip()
    return ''


def _parse_moved(text: str) -> str:
    m = re.search(r'MOVED\s*:\s*(.+)', text or '', re.IGNORECASE)
    if m:
        return m.group(1).strip().split('\n')[0].strip()
    return 'no'


def _parse_amendment(text: str) -> str:
    m = re.search(r'AMENDMENT OR DISSENT\s*:\s*(.+)', text or '', re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip().split('\n')[0].strip()
    return ''


def _parse_conditions(text: str) -> str:
    m = re.search(r'MY CONDITIONS FOR YES\s*:\s*(.+)', text or '', re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return ''

def run_council(decision, seats=None, rounds=3, provider=None, base_dir=None, on_event=None):
    from .agent import Agent, LoopConfig
    from .types import ToolRegistry

    decision = (decision or '').strip()
    if not decision:
        raise ValueError('decisione vuota')

    roster = load_roster()
    key2seat = {s['key']: s for s in roster}
    if seats is None:
        seats = [s['key'] for s in roster]
    seats = [k for k in seats if k in key2seat]
    if not seats:
        raise ValueError('nessun seat valido')

    provider = _ensure_provider(provider)
    base_dir = base_dir or os.getcwd()
    sessions_root = os.path.join(base_dir, 'sessions')
    os.makedirs(sessions_root, exist_ok=True)
    slug = _slugify(decision)
    stamp = datetime.now().strftime('%Y-%m-%d')
    session_dir = os.path.join(sessions_root, f'{stamp}-{slug}')
    os.makedirs(session_dir, exist_ok=True)

    raw = load_roster_raw()
    raw_seats = {s['key']: s for s in raw.get('seats', [])}

    # Chair: opzioni + pesi + assunzioni
    chair0_prompt = (
        'Sei il Chair. Data la decisione qui sotto, produci SOLO JSON valido con:\n'
        '- "options": lista di 2-4 opzioni, ciascuna {"id":"A","label":"..."} (label <50 char). '
        'Includi sempre un\'opzione "non fare nulla / continuare cosi".\n'
        '- "weights": oggetto che mappa ogni seat key a {"weight":1|2|3, "reason":"una riga"}.\n'
        '- "assumptions": lista di stringhe (assunzioni su numeri mancanti).\n'
        '- "brief": 2-3 frasi riassuntive.\n\n'
        f'Decisione:\n{decision}\n\n'
        f'Seat al tavolo (key: pilastro):\n' + '\n'.join(f'{k}: {key2seat[k]["pillar"]}' for k in seats) + '\n\n'
        'Rispondi solo JSON.'
    )
    chair0_text = _ask(provider, CHAIR_SYSTEM, chair0_prompt, max_tokens=1200, temp=0.4)
    parsed0 = _extract_json(chair0_text) or {}
    options = parsed0.get('options') or [{'id': 'A', 'label': 'Fare'}, {'id': 'B', 'label': 'Non fare'}]
    # normalizza ids
    option_ids = [o['id'] for o in options]
    weights_raw = parsed0.get('weights') or {}
    weights = {}
    for k in seats:
        w = weights_raw.get(k, {})
        wt = w.get('weight', 2) if isinstance(w, dict) else 2
        try:
            wt = int(wt)
        except Exception:
            wt = 2
        wt = max(1, min(3, wt))
        reason = w.get('reason', '') if isinstance(w, dict) else ''
        weights[k] = {'weight': wt, 'reason': reason}
    assumptions = parsed0.get('assumptions') or []
    brief_summary = parsed0.get('brief') or decision

    # brief.md
    brief = (
        f'# Brief\n\n'
        f'## Decisione\n{decision}\n\n'
        f'## Opzioni\n' + '\n'.join(f'- {o["id"]}: {o["label"]}' for o in options) + '\n\n'
        f'## Advisor al tavolo\n' + '\n'.join(f'- {key2seat[k]["name"]} ({key2seat[k]["pillar"]})' for k in seats) + '\n\n'
        f'## Pesi\n' + '\n'.join(f'- {key2seat[k]["short"]}: {weights[k]["weight"]}/3 - {weights[k]["reason"]}' for k in seats) + '\n\n'
        f'## Assunzioni\n' + '\n'.join(f'- {a}' for a in assumptions) + '\n'
    )
    with open(os.path.join(session_dir, 'brief.md'), 'w', encoding='utf-8') as f:
        f.write(brief)

    # council.json (live-room)
    council_json = {
        'title': decision[:60],
        'decision': decision,
        'mode': 'full',
        'options': options,
        'weights': {k: {'weight': weights[k]['weight'], 'reason': weights[k]['reason']} for k in seats},
        'seats': seats,
        'brief': brief_summary,
        'assumptions': assumptions,
    }
    with open(os.path.join(session_dir, 'council.json'), 'w', encoding='utf-8') as f:
        json.dump(council_json, f, ensure_ascii=False, indent=2)

    _emit(on_event, 'council_start', seats=seats, rounds=rounds, session_dir=session_dir, options=options, weights=weights)

    all_rounds = []
    round_texts = {}
    cards_by_round = {}

    def ask_seat(key, prompt, max_tokens=700):
        sp = advisor_system_prompt(key)
        agent = Agent(provider, ToolRegistry(), sp,
                      LoopConfig(max_iterations=3, max_tokens=max_tokens, temperature=0.7))
        try:
            stato = agent.run(prompt)
            out = _risposta_finale(stato)
            if not out:
                msgs = getattr(stato, 'messages', []) or []
                for m in reversed(msgs):
                    t = (getattr(m, 'content', '') or '').strip()
                    if t:
                        out = t
                        break
            return out or '[nessuna risposta]'
        except Exception as e:
            return f'[errore: {e}]'

    # ---------- Round 1 ----------
    r = 1
    _emit(on_event, 'round_start', round=r)
    cards = {}
    opts_str = ' · '.join(f'{o["id"]} n/10' for o in options)
    for key in seats:
        seat = key2seat[key]
        prompt = (
            f'REPO ROOT: {base_dir}\n'
            f'ROAST ROOM COUNCIL, ROUND 1 OF {rounds}: OPENING POSITION\n\n'
            f'You hold the {seat["short"]} seat ({seat["pillar"]}). Read your brain _hot.md, then at most three more brain files that fit this decision.\n'
            f'Read the brief: {session_dir}/brief.md\n\n'
            f'Your weight on this decision: {weights[key]["weight"]}/3 ({weights[key]["reason"]}).\n\n'
            f'Answer in your seat\'s voice, plain text, under 350 words, in exactly this shape:\n\n'
            f'SEAT: {seat["short"]} ({seat["pillar"]})\n'
            f'STANCE: Strong yes | Yes | Conditional yes | No | Strong no (on the option you recommend)\n'
            f'OPTION SCORES: { " · ".join(f"{o[chr(39)+chr(39)] if False else o["id"]} n/10" for o in options) }\n'
            f'PILLAR SCORE: n/10 ({seat["dimension"]}: the option you recommend, judged on your pillar alone)\n'
            f'CONFIDENCE: n/5\n'
            f'RUIN RISK: none | possible | likely\n'
            f'DOOR: one-way | two-way\n\n'
            f'THE CALL: one sentence, naming the option or a variant.\n'
            f'WHY:\n1. ...\n2. ...\n3. ...\n'
            f'THE RISK I SEE: ...\n'
            f'WHAT WOULD CHANGE MY MIND: ...\n'
            f'WHAT I\'D DO THIS WEEK: ...\n'
            f'QUESTION FOR THE FOUNDER: ...\n\n'
            f'Rules: argue from your pillar first. Use real numbers when the brief has them. Quote only verbatim lines from your brain, with the source id. Do not hedge.\n'
        )
        # fix option scores placeholder
        prompt = prompt.replace('OPTION SCORES: ' + ' · '.join(f'{o["id"]} n/10' for o in options),
                               'OPTION SCORES: ' + ' · '.join(f'{o["id"]} n/10' for o in options))
        _emit(on_event, 'seat_start', round=r, seat=key, name=seat['short'])
        text = ask_seat(key, prompt)
        cards[key] = text
        _emit(on_event, 'seat_done', round=r, seat=key, name=seat['short'], text=text)
    round_texts[r] = '\n\n'.join(f'## {key2seat[k]["short"]}\n{cards[k]}' for k in seats)
    md = f'# Round {r}\n\n' + '\n\n'.join(f'## {key2seat[k]["short"]}\n{cards[k]}' for k in seats) + '\n'
    with open(os.path.join(session_dir, f'round-{r}.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    all_rounds.append({'round': r, 'cards': cards})
    cards_by_round[r] = cards
    _emit(on_event, 'round_done', round=r)

    # Chair: cruxes
    r1_md = round_texts.get(1, '')
    cruxes_prompt = (
        'Sei il Chair. Leggi i card del round 1 qui sotto e identifica 1-3 cruxes (i punti su cui la sala si divide). '
        'Produci SOLO JSON valido con:\n'
        '{ "cruxes": [ {"question":"... (<90 char)", "sides": [ {"position":"...", "seats":["..."]}, {"position":"...", "seats":["..."]} ] } ], '
        '"unanimous": false, "note": "una frase su cosa si combatte" }\n\n'
        f'Round 1 cards:\n{r1_md}\n\n'
        'Rispondi solo JSON.'
    )
    cruxes_text = _ask(provider, CHAIR_SYSTEM, cruxes_prompt, max_tokens=1200, temp=0.4)
    cruxes = _extract_json(cruxes_text) or {'cruxes': [], 'unanimous': False, 'note': ''}
    with open(os.path.join(session_dir, 'cruxes.json'), 'w', encoding='utf-8') as f:
        json.dump(cruxes, f, ensure_ascii=False, indent=2)
    # append chair notes to round-1.md
    with open(os.path.join(session_dir, f'round-{r}.md'), 'a', encoding='utf-8') as f:
        f.write('\n## Chair notes\n' + (cruxes.get('note') or '') + '\n')

    _emit(on_event, 'cruxes', cruxes=cruxes)
    r = 2
    if rounds >= 2:
        _emit(on_event, 'round_start', round=r)
        cards = {}
        cruxes_list = cruxes.get('cruxes', []) or []
        cruxes_text_block = ''
        for i, c in enumerate(cruxes_list, 1):
            cruxes_text_block += f'{i}. {c.get("question","")}: ' + ', '.join(
                f'{s.get("position","")} ({", ".join(s.get("seats",[]))})' for s in c.get('sides', [])
            ) + '\n'
        r1_full = round_texts.get(1, '')
        for key in seats:
            seat = key2seat[key]
            prompt = (
                f'REPO ROOT: {base_dir}\n'
                f'ROAST ROOM COUNCIL, ROUND 2 OF {rounds}: DEBATE\n\n'
                f'You hold the {seat["short"]} seat. Read your brain _hot.md again and any brain file you need.\n'
                f'Read: {session_dir}/brief.md and {session_dir}/round-1.md (every seat\'s card and the Chair\'s cruxes).\n\n'
                f'THE CRUXES THE CHAIR SEES\n{cruxes_text_block}\n'
                f'Decision:\n{decision}\n\n'
                f'ROUND 1 CARDS:\n{r1_full}\n\n'
                f'Answer in your seat\'s voice, plain text, under 300 words, in exactly this shape:\n'
                f'SEAT: {seat["short"]}\n'
                f'I DISAGREE MOST WITH: [seat]. Their argument, in one line, then your rebuttal using your frameworks.\n'
                f'I CONCEDE: the strongest point another seat made against you, and what it changes.\n'
                f'ON THE CRUXES: your answer to each crux, one or two lines each.\n'
                f'STANCE: ...\n'
                f'OPTION SCORES: ' + ' · '.join(f'{o["id"]} n/10' for o in options) + '\n'
                f'PILLAR SCORE: n/10\n'
                f'CONFIDENCE: n/5\n'
                f'RUIN RISK: none | possible | likely\n'
                f'MOVED: no | yes, from X to Y, because ...\n'
                f'MY CONDITIONS FOR YES: up to three, concrete and checkable (a number, a date, a test result).\n\n'
                f'Rules: engage the actual arguments. Move only for a better argument. If everyone agrees with you, find the weakest part of your own case.\n'
            )
            _emit(on_event, 'seat_start', round=r, seat=key, name=seat['short'])
            text = ask_seat(key, prompt)
            cards[key] = text
            _emit(on_event, 'seat_done', round=r, seat=key, name=seat['short'], text=text)
        round_texts[r] = '\n\n'.join(f'## {key2seat[k]["short"]}\n{cards[k]}' for k in seats)
        md = f'# Round {r}\n\n' + '\n\n'.join(f'## {key2seat[k]["short"]}\n{cards[k]}' for k in seats) + '\n'
        with open(os.path.join(session_dir, f'round-{r}.md'), 'w', encoding='utf-8') as f:
            f.write(md)
        all_rounds.append({'round': r, 'cards': cards})
        cards_by_round[r] = cards
        _emit(on_event, 'round_done', round=r)

    # Chair: draft resolution
    last_round = 2 if rounds >= 2 else 1
    last_md = round_texts.get(last_round, '')
    draft_prompt = (
        'Sei il Chair. Sulla base dei round, scrivi una draft resolution (la proposta che il council ratifichera nel round 3). '
        'Produci SOLO JSON valido con:\n'
        '{ "option": "B", "label": "GO WITH CONDITIONS", "recommendation": "1-2 frasi", '
        '"conditions": ["condizione checkable"], "next_steps": ["step con data"], '
        '"cheapest_test": "una riga", "kill_criteria": "una riga" }\n\n'
        f'Opzioni: {json.dumps(options, ensure_ascii=False)}\n'
        f'Brief: {brief_summary}\n'
        f'Ultimo round:\n{last_md}\n\n'
        'Rispondi solo JSON.'
    )
    draft_text = _ask(provider, CHAIR_SYSTEM, draft_prompt, max_tokens=1200, temp=0.4)
    draft = _extract_json(draft_text) or {'option': option_ids[0], 'label': 'GO WITH CONDITIONS',
                                         'recommendation': '', 'conditions': [], 'next_steps': [],
                                         'cheapest_test': '', 'kill_criteria': ''}
    with open(os.path.join(session_dir, 'draft.json'), 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    draft_md = (
        f'# Draft resolution\n\n'
        f'Option: {draft.get("option","")}\n'
        f'Label: {draft.get("label","")}\n\n'
        f'{draft.get("recommendation","")}\n\n'
        f'Conditions:\n' + '\n'.join(f'- {c}' for c in draft.get('conditions', [])) + '\n\n'
        f'Next steps:\n' + '\n'.join(f'- {s}' for s in draft.get('next_steps', [])) + '\n\n'
        f'Cheapest test: {draft.get("cheapest_test","")}\n'
        f'Kill criteria: {draft.get("kill_criteria","")}\n'
    )
    with open(os.path.join(session_dir, 'draft-resolution.md'), 'w', encoding='utf-8') as f:
        f.write(draft_md)
    _emit(on_event, 'draft', draft=draft)
    r = 3
    if rounds >= 3:
        _emit(on_event, 'round_start', round=r)
        cards = {}
        draft_text_block = draft_md
        r2_full = round_texts.get(2, round_texts.get(1, ''))
        for key in seats:
            seat = key2seat[key]
            prompt = (
                f'REPO ROOT: {base_dir}\n'
                f'ROAST ROOM COUNCIL, ROUND 3 OF {rounds}: VOTE ON THE DRAFT RESOLUTION\n\n'
                f'You hold the {seat["short"]} seat. You already argued two rounds; read only your _hot.md if you need it.\n'
                f'Read: {session_dir}/brief.md, your own section of {session_dir}/round-2.md, and {session_dir}/draft-resolution.md.\n\n'
                f'Decision:\n{decision}\n\n'
                f'YOUR ROUND 2 (context):\n{r2_full}\n\n'
                f'Draft resolution:\n{draft_text_block}\n\n'
                f'Answer in your seat\'s voice, under 150 words, in exactly this shape:\n'
                f'SEAT: {seat["short"]}\n'
                f'VOTE: Endorse | Endorse with amendment | Dissent\n'
                f'OPTION SCORES: ' + ' · '.join(f'{o["id"]} n/10' for o in options) + ' (given the resolution\'s conditions)\n'
                f'FINAL SCORE: n/10 (your support for the draft resolution as written)\n'
                f'FINAL PILLAR SCORE: n/10\n'
                f'AMENDMENT OR DISSENT: one or two sentences (what to change, or why you dissent). Blank if you endorse.\n'
                f'ONE LINE FOR THE FOUNDER: ...\n'
            )
            _emit(on_event, 'seat_start', round=r, seat=key, name=seat['short'])
            text = ask_seat(key, prompt, max_tokens=400)
            cards[key] = text
            _emit(on_event, 'seat_done', round=r, seat=key, name=seat['short'], text=text)
        round_texts[r] = '\n\n'.join(f'## {key2seat[k]["short"]}\n{cards[k]}' for k in seats)
        md = f'# Round {r}\n\n' + '\n\n'.join(f'## {key2seat[k]["short"]}\n{cards[k]}' for k in seats) + '\n'
        with open(os.path.join(session_dir, f'round-{r}.md'), 'w', encoding='utf-8') as f:
            f.write(md)
        all_rounds.append({'round': r, 'cards': cards})
        cards_by_round[r] = cards
        _emit(on_event, 'round_done', round=r)

    # ---------- Scoring ----------
    last_ran = 3 if (rounds >= 3 and 3 in cards_by_round) else (2 if (rounds >= 2 and 2 in cards_by_round) else 1)
    score_round_cards = cards_by_round.get(last_ran, {})
    # per-seat parsed
    seat_data = {}
    for key in seats:
        txt = score_round_cards.get(key, '')
        oscores = _parse_option_scores(txt, option_ids)
        seat_data[key] = {
            'option_scores': oscores,
            'pillar_score': _parse_pillar_score(txt),
            'confidence': _parse_confidence(txt),
            'ruin': _parse_ruin(txt),
            'door': _parse_door(txt),
            'stance': _parse_stance(txt),
            'moved': _parse_moved(txt),
            'vote': _parse_vote(txt) if last_ran == 3 else '',
            'final_score': _parse_final_score(txt) if last_ran == 3 else None,
            'one_line': _parse_one_line(txt),
            'amendment': _parse_amendment(txt) if last_ran == 3 else '',
            'conditions': _parse_conditions(txt),
        }
    # round1 door/ruin fallback from round1 if missing
    r1_cards = cards_by_round.get(1, {})
    for key in seats:
        if seat_data[key]['ruin'] == 'none' and key in r1_cards:
            seat_data[key]['ruin'] = _parse_ruin(r1_cards[key])
        if seat_data[key]['door'] == 'two-way' and key in r1_cards:
            d = _parse_door(r1_cards[key])
            if d:
                seat_data[key]['door'] = d

    # option scores weighted
    option_weighted = {}
    total_w = sum(weights[k]['weight'] for k in seats)
    for oid in option_ids:
        num = 0.0
        den = 0.0
        for key in seats:
            sc = seat_data[key]['option_scores'].get(oid)
            if sc is None:
                continue
            w = weights[key]['weight']
            num += w * sc
            den += w
        option_weighted[oid] = round(num / den, 1) if den else 0.0

    recommended_id = max(option_ids, key=lambda o: option_weighted.get(o, 0.0)) if option_ids else None

    # ruin cap
    override_note = ''
    ruin_seats = [k for k in seats if seat_data[k]['ruin'] == 'likely' and
                  (seat_data[k]['option_scores'].get(recommended_id) or 0) >= 6]
    if ruin_seats and recommended_id:
        # cap verdict at RESHAPE unless mitigation endorsed; we note it
        override_note = 'Ruin cap: ' + ', '.join(key2seat[k]['short'] for k in ruin_seats) + ' segnalano RUIN RISK likely sull\'opzione raccomandata.'

    # one-way door cap
    one_way = False
    if recommended_id:
        door_votes = [seat_data[k]['door'] for k in seats]
        if door_votes.count('one-way') > len(seats) / 2:
            one_way = True
        # also Bezos call
        if seat_data.get('bezos', {}).get('door') == 'one-way':
            one_way = True
    spread = 0
    if recommended_id:
        scores_rec = [seat_data[k]['option_scores'].get(recommended_id) for k in seats
                      if seat_data[k]['option_scores'].get(recommended_id) is not None]
        if scores_rec:
            spread = max(scores_rec) - min(scores_rec)

    rec_score = option_weighted.get(recommended_id, 0.0) if recommended_id else 0.0

    # verdict band
    if rec_score >= 7.5:
        band = 'GO'
    elif rec_score >= 6.0:
        band = 'GO WITH CONDITIONS'
    elif rec_score >= 4.5:
        band = 'RESHAPE'
    else:
        band = "DON'T DO IT"
    # WAIT heuristic: if recommended is "don't" option? check label containing don't/keep
    dont_option = None
    for o in options:
        lab = (o.get('label') or '').lower()
        if 'don' in lab or 'keep' in lab or 'non' in lab or 'aspetta' in lab:
            dont_option = o['id']
    if dont_option and recommended_id == dont_option and rec_score >= 6.0:
        band = "DON'T DO IT"

    if override_note and 'ruin' in override_note.lower() and band in ('GO', 'GO WITH CONDITIONS'):
        band = 'RESHAPE'

    if one_way and spread >= 4 and band == 'GO':
        band = 'GO WITH CONDITIONS'
        override_note = (override_note + ' ').strip() + ' One-way door cap: spread alto, test economico come precondizione.'

    # confidence
    confs = [seat_data[k]['confidence'] for k in seats if seat_data[k]['confidence'] is not None]
    avg_conf = (sum(confs) / len(confs)) if confs else 5.0
    council_conf = round(avg_conf * 2)
    if spread >= 5:
        council_conf -= 1
    council_conf = max(1, min(10, council_conf))

    # resolution support
    final_scores = [seat_data[k]['final_score'] for k in seats if seat_data[k]['final_score'] is not None]
    res_support = round(sum(weights[k]['weight'] * (seat_data[k]['final_score'] or 0) for k in seats if seat_data[k]['final_score'] is not None) /
                        max(1, sum(weights[k]['weight'] for k in seats if seat_data[k]['final_score'] is not None)), 1) if final_scores else None

    # votes
    votes = {'endorse': 0, 'amend': 0, 'dissent': 0}
    for key in seats:
        v = (seat_data[key]['vote'] or '').lower()
        if 'amendment' in v:
            votes['amend'] += 1
        elif 'dissent' in v:
            votes['dissent'] += 1
        elif 'endorse' in v:
            votes['endorse'] += 1

    # minority: seat with lowest final/option score or dissent
    minority_key = None
    if votes['dissent'] > 0:
        for key in seats:
            if 'dissent' in (seat_data[key]['vote'] or '').lower():
                minority_key = key
                break
    if minority_key is None and seats:
        # lowest option score on recommended
        minority_key = min(seats, key=lambda k: (seat_data[k]['option_scores'].get(recommended_id) or 99))

    # cruxes fights summary
    fights = []
    for c in (cruxes.get('cruxes', []) or []):
        fights.append({'crux': c.get('question', ''), 'story': cruxes.get('note', '')})

    # amendments
    amendments = []
    for key in seats:
        a = seat_data[key]['amendment']
        if a:
            amendments.append({'seat': key2seat[key]['short'], 'amendment': a,
                              'adopted': 'endorse' in (seat_data[key]['vote'] or '').lower(),
                              'reason': ''})

    # Chair verdict (narrative) via agent
    _emit(on_event, 'chair_start')
    # Solo l'ultimo round (voti) nel prompt del verdict: cruxes/draft/scoring gia'
    # passati a parte. Riduce la dimensione del prompt e il rischio di troncamento.
    last_r = max(round_texts) if round_texts else 1
    all_rounds_md = round_texts.get(last_r, '')
    scoring_summary = (
        f'Opzioni: {option_ids}\n'
        f'Punteggi opzione (pesati): {option_weighted}\n'
        f'Raccomandata: {recommended_id} ({rec_score})\n'
        f'Band: {band}\n'
        f'Spread: {spread}  Confidence: {council_conf}/10\n'
        f'Resolution support: {res_support}\n'
        f'Vote: endorse {votes["endorse"]}, amend {votes["amend"]}, dissent {votes["dissent"]}\n'
        f'Override: {override_note or "nessuno"}\n'
        f'Ruin seats: {[key2seat[k]["short"] for k in ruin_seats]}\n'
    )
    verdict_prompt = (
        'Sei il Chair. Scrivi il verdict.md seguendo il report template. In italiano, senza em dash, senza filler. '
        'Sotto 1000 parole. Struttura:\n'
        '# Roast Room: [decisione in poche parole]\n'
        '[data] · Seats: [lista] · Rounds: [n] · Mode: full\n\n'
        '## Verdict: [BAND]\n'
        '**The call:** ...\n'
        'Option scores: ... · Support for the resolution x.x/10 · Confidence n/10 · Spread n · Vote: ...\n'
        '[override se presente]\n\n'
        '## Scorecard\n tabella Seat | Weight | Final stance | opzioni | Pillar score | Moved? | Their line\n'
        'Math: una riga per opzione\n\n'
        '## Why the council landed here\n 3-5 bullet taggati (seat, framework)\n\n'
        '## Where they fought\n un blocco per crux\n\n'
        '## Minority report\n ...\n\n'
        '## Conditions\n checkable\n\n'
        '## What to do next\n 1/2/3 + Cheapest test + Kill criteria + Revisit\n\n'
        '## Glossario\n solo i termini tecnici usati (CAC, LTV, runway, cash-burn, margine lordo, burn rate, ecc.), una riga ciascuno in italiano semplice. Ometti se nessun termine tecnico.\n\n'
        '---\nSimulated advisors...\n\n'
        f'Decisione: {decision}\n'
        f'Opzioni: {options}\n'
        f'Pesi: {weights}\n'
        f'Cruxes: {cruxes}\n'
        f'Draft: {draft}\n'
        f'Scoring:\n{scoring_summary}\n'
        f'Dati per seat:\n{json.dumps(seat_data, ensure_ascii=False)}\n\n'
        f'Round files:\n{all_rounds_md}\n\n'
        'Scrivi il verdict.md completo. Solo markdown, niente altro.'
    )
    verdict_text = _ask_verdict(provider, CHAIR_SYSTEM, verdict_prompt, max_tokens=3000, temp=0.5)
    if not verdict_text or verdict_text.startswith('[errore'):
        verdict_text = '# Verdict\n\n' + scoring_summary

    with open(os.path.join(session_dir, 'verdict.md'), 'w', encoding='utf-8') as f:
        f.write(verdict_text)

    # verdict.json (live-room)
    verdict_json = {
        'label': band,
        'call': verdict_text.split('**The call:**')[-1].split('\n')[0].strip() if '**The call:**' in verdict_text else '',
        'recommended': recommended_id,
        'why': [],
        'minority': {'seat': key2seat.get(minority_key, {}).get('short', ''), 'quote': seat_data.get(minority_key, {}).get('one_line', ''), 'would_have_to_be_true': ''},
        'next_steps': [{'when': 'This week', 'action': s} for s in draft.get('next_steps', [])[:3]],
        'kill_criteria': draft.get('kill_criteria', ''),
        'conditions': draft.get('conditions', []),
        'fights': fights,
        'amendments': amendments,
        'cheapest_test': draft.get('cheapest_test', ''),
        'revisit': '',
        'override_note': override_note,
    }
    with open(os.path.join(session_dir, 'verdict.json'), 'w', encoding='utf-8') as f:
        json.dump(verdict_json, f, ensure_ascii=False, indent=2)

    _emit(on_event, 'chair_done', text=verdict_text)
    _emit(on_event, 'council_done', session_dir=session_dir, verdict_path=os.path.join(session_dir, 'verdict.md'))

    return {
        'session_dir': session_dir,
        'verdict_path': os.path.join(session_dir, 'verdict.md'),
        'verdict': verdict_text,
        'rounds': rounds,
        'seats': seats,
        'options': options,
        'weights': weights,
        'scoring': {
            'option_weighted': option_weighted,
            'recommended': recommended_id,
            'band': band,
            'spread': spread,
            'confidence': council_conf,
            'resolution_support': res_support,
            'votes': votes,
            'override_note': override_note,
        },
        'seat_data': seat_data,
    }
"""Bridge MCP pronti: configurazioni note, non indovinate.

Un server MCP si configura con trasporto, comando, argomenti, URL, header e
variabili d'ambiente. Chiedere tutti questi campi a chi vuole solo collegare
GitHub e' il modo migliore per non farlo mai collegare. Qui ci sono i servizi
piu' usati con la loro configurazione gia' scritta: l'utente (o l'agente per
lui) fornisce solo il dato che possiede davvero, di solito un token o una
cartella.

I preset non sono server: sono modelli. `configura()` produce la voce da
passare a `mcp.add_server`, senza toccare il disco e senza segreti di default.

Fonti e limiti:
- GitHub, Supabase, Linear, Sentry e Stripe accettano un token negli header.
- Notion e i server remoti che usano OAuth passano da `mcp-remote`, un ponte
  stdio che apre il browser per l'autorizzazione. Richiede Node/npx.
- Playwright e filesystem girano in locale con npx.
- Unreal Engine 5.8+ espone un server HTTP dentro l'editor; Godot, Blender,
  Unity, FreeCAD, GIMP, Krita, Inkscape e JetBrains usano un bridge stdio o
  HTTP e un plugin/addon nell'applicazione.
- I database e gli strumenti locali (PostgreSQL, SQLite, MongoDB, Redis,
  Grafana, Terraform) usano i server ufficiali o i progetti indicati, con
  una nota sui limiti di sicurezza.
- Un servizio che richiede OAuth senza un token statico (per esempio Slack,
  Asana, Figma, HubSpot, Dropbox) non ha un preset: meglio dire che non e'
  coperto che inventare una config.
"""

from __future__ import annotations

import re
from typing import Any

PRESET: tuple[dict[str, Any], ...] = (
    {
        "id": "github",
        "nome": "GitHub",
        "descrizione": "Repository, issue, pull request, codice e review.",
        "transport": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "GitHub personal access token",
            "esempio": "github_pat_...",
            "dove": "https://github.com/settings/tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://github.com/github/github-mcp-server",
        "nota": ("Token con i soli permessi necessari. Per la sola lettura "
                 "si puo' aggiungere l'header X-MCP-Readonly: true."),
    },
    {
        "id": "supabase",
        "nome": "Supabase",
        "descrizione": "Database, tabelle, migration e documentazione Supabase.",
        "transport": "http",
        "url": "https://mcp.supabase.com/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Supabase personal access token",
            "esempio": "sbp_...",
            "dove": "https://supabase.com/dashboard/account/tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://supabase.com/docs/guides/ai-tools/mcp",
        "nota": ("Per limitare il server a un progetto aggiungi "
                 "?project_ref=... all'URL; per la sola lettura ?read_only=true."),
    },
    {
        "id": "notion",
        "nome": "Notion",
        "descrizione": "Pagine, database e ricerca nel workspace Notion.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.notion.com/mcp"],
        "campi": [],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://developers.notion.com/guides/mcp/get-started-with-mcp",
        "nota": ("Al primo collegamento mcp-remote apre il browser per "
                 "l'accesso Notion. Serve Node/npx; nessun token da incollare."),
    },
    {
        "id": "linear",
        "nome": "Linear",
        "descrizione": "Issue, progetti e team Linear.",
        "transport": "http",
        "url": "https://mcp.linear.app/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Linear API key",
            "esempio": "lin_api_...",
            "dove": "https://linear.app/settings/account/security",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://linear.app/docs/mcp",
        "nota": "Per la sola lettura usa https://mcp.linear.app/mcp/readonly.",
    },
    {
        "id": "sentry",
        "nome": "Sentry",
        "descrizione": "Errori, issue, release e stack trace Sentry.",
        "transport": "http",
        "url": "https://mcp.sentry.dev/mcp",
        "headers": {"Authorization": "Sentry-Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Sentry access token",
            "esempio": "sntrys_...",
            "dove": "https://sentry.io/settings/auth-tokens/",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://mcp.sentry.dev/",
        "nota": ("Sentry usa lo schema Sentry-Bearer, non Bearer: e' il "
                 "token di accesso dell'utente, non una chiave OAuth."),
    },
    {
        "id": "stripe",
        "nome": "Stripe",
        "descrizione": "Clienti, pagamenti, prodotti e API Stripe.",
        "transport": "http",
        "url": "https://mcp.stripe.com",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Stripe agent API key",
            "esempio": "rk_live_... oppure rk_test_...",
            "dove": "https://dashboard.stripe.com/apikeys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.stripe.com/mcp",
        "nota": ("Usa una chiave agente con i soli permessi necessari, non "
                 "la chiave segreta completa."),
    },
    {
        "id": "gitlab",
        "nome": "GitLab",
        "descrizione": "Repository, issue, merge request e pipeline GitLab.",
        "transport": "http",
        "url": "https://gitlab.com/api/v4/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "GitLab fine-grained token",
            "esempio": "glpat-...",
            "dove": "https://gitlab.com/-/user_settings/personal_access_tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.gitlab.com/user/model_context_protocol/mcp_server/",
        "nota": ("Token fine-grained con 'Execute MCP tools' e accesso ai "
                 "progetti. Per GitLab self-managed usa un server "
                 "personalizzato con il tuo URL."),
    },
    {
        "id": "neon",
        "nome": "Neon",
        "descrizione": "Postgres serverless Neon: database, branch e query.",
        "transport": "http",
        "url": "https://mcp.neon.tech/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Neon API key",
            "esempio": "napi_...",
            "dove": "https://console.neon.tech/app/settings/api-keys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://neon.tech/docs/ai/neon-mcp-server",
        "nota": ("API key Neon; in alternativa il server supporta OAuth. "
                 "Puoi limitarlo a un progetto."),
    },
    {
        "id": "datadog",
        "nome": "Datadog",
        "descrizione": "Metriche, log, monitor, incidenti e APM Datadog.",
        "transport": "http",
        "url": "https://mcp.datadoghq.com/v1/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Datadog personal o service access token",
            "esempio": "...",
            "dove": "https://app.datadoghq.com/organization-settings/personal-access-tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.datadoghq.com/mcp_server/setup",
        "nota": ("Endpoint US1. Per EU1 usa https://mcp.datadoghq.eu/v1/mcp "
                 "con un server personalizzato. Puoi limitare i toolset."),
    },
    {
        "id": "firecrawl",
        "nome": "Firecrawl",
        "descrizione": "Scraping e crawling di siti web in markdown.",
        "transport": "http",
        "url": "https://mcp.firecrawl.dev/v2/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Firecrawl API key",
            "esempio": "fc-...",
            "dove": "https://www.firecrawl.dev/app/api-keys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.firecrawl.dev/mcp-server/connect",
        "nota": ("La chiave sblocca tutti i tool; l'endpoint senza chiave "
                 "e' limitato a search/scrape/parse."),
    },
    {
        "id": "exa",
        "nome": "Exa",
        "descrizione": "Ricerca web semantica e contenuti per agenti.",
        "transport": "http",
        "url": "https://mcp.exa.ai/mcp",
        "headers": {"x-api-key": "{token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Exa API key",
            "esempio": "...",
            "dove": "https://dashboard.exa.ai/api-keys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.exa.ai/reference/exa-mcp",
        "nota": "La chiave va nell'header x-api-key, non nell'URL.",
    },
    {
        "id": "context7",
        "nome": "Context7",
        "descrizione": "Documentazione aggiornata di librerie e framework.",
        "transport": "http",
        "url": "https://mcp.context7.com/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Context7 API key",
            "esempio": "ctx7sk-...",
            "dove": "https://context7.com/dashboard",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://context7.com/docs/resources/all-clients",
        "nota": "Endpoint API-key; Context7 ha anche un endpoint OAuth separato.",
    },
    {
        "id": "huggingface",
        "nome": "Hugging Face",
        "descrizione": "Modelli, dataset, Spaces e ricerca Hugging Face.",
        "transport": "http",
        "url": "https://huggingface.co/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Hugging Face access token",
            "esempio": "hf_...",
            "dove": "https://huggingface.co/settings/tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://huggingface.co/docs/hub/en/hf-mcp-server",
        "nota": ("Token con i permessi minimi; il token non va mai messo "
                 "nell'URL."),
    },
    {
        "id": "cloudflare",
        "nome": "Cloudflare",
        "descrizione": "Account, Workers, KV, R2, D1, DNS e osservabilita'.",
        "transport": "http",
        "url": "https://mcp.cloudflare.com/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Cloudflare API token",
            "esempio": "...",
            "dove": "https://dash.cloudflare.com/profile/api-tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/",
        "nota": ("Token con i soli permessi necessari; il server completo "
                 "puo' modificare risorse Cloudflare."),
    },
    {
        "id": "airtable",
        "nome": "Airtable",
        "descrizione": "Basi, tabelle e record Airtable.",
        "transport": "http",
        "url": "https://mcp.airtable.com/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Airtable personal access token",
            "esempio": "pat...",
            "dove": "https://airtable.com/create/tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://airtable.com/developers/agents/mcp/other",
        "nota": "Token con accesso alle sole basi che vuoi esporre.",
    },
    {
        "id": "resend",
        "nome": "Resend",
        "descrizione": "Email transazionali, domini e log Resend.",
        "transport": "http",
        "url": "https://mcp.resend.com/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Resend API key",
            "esempio": "re_...",
            "dove": "https://resend.com/api-keys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://resend.com/docs/mcp-server",
        "nota": "Usa una chiave con permesso di invio, non la chiave account.",
    },
    {
        "id": "semgrep",
        "nome": "Semgrep",
        "descrizione": "Scansioni di sicurezza e risultati Semgrep.",
        "transport": "http",
        "url": "https://semgrep.dev/api/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Semgrep API token",
            "esempio": "...",
            "dove": "https://semgrep.dev/orgs/-/settings/tokens",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.semgrep.dev/mcp/authentication",
        "nota": ("Per la sola lettura usa https://semgrep.dev/api/mcp/read-only "
                 "con un server personalizzato."),
    },
    {
        "id": "deepwiki",
        "nome": "DeepWiki",
        "descrizione": "Documentazione e architettura di repository pubblici.",
        "transport": "http",
        "url": "https://mcp.deepwiki.com/mcp",
        "campi": [],
        "categoria": "servizio",
        "docs": "https://docs.devin.ai/work-with-devin/deepwiki-mcp",
        "nota": ("Repository pubblici senza token. Per i repository privati "
                 "serve l'endpoint Devin con una API key."),
    },
    {
        "id": "posthog",
        "nome": "PostHog",
        "descrizione": "Eventi, funnel, feature flag e analisi PostHog.",
        "transport": "http",
        "url": "https://mcp.posthog.com/mcp",
        "headers": {"Authorization": "Bearer {token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "PostHog personal API key",
            "esempio": "phx_...",
            "dove": "https://app.posthog.com/settings/user-api-keys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://posthog.com/docs/model-context-protocol",
        "nota": ("Per il cloud EU usa https://mcp-eu.posthog.com/mcp con un "
                 "server personalizzato."),
    },
    {
        "id": "pagerduty",
        "nome": "PagerDuty",
        "descrizione": "Incidenti, servizi, on-call e escalation PagerDuty.",
        "transport": "http",
        "url": "https://mcp.pagerduty.com/mcp",
        "headers": {"Authorization": "Token token={token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "PagerDuty API key",
            "esempio": "...",
            "dove": "https://support.pagerduty.com/docs/api-access-keys",
            "segreto": True,
        }],
        "categoria": "servizio",
        "docs": "https://docs.pagerduty.com/ai-automation/advance/pagerduty-mcp-server",
        "nota": ("Qui si usa una API key. Per il cloud EU l'endpoint e' "
                 "https://mcp.eu.pagerduty.com/mcp."),
    },
    {
        "id": "twilio",
        "nome": "Twilio",
        "descrizione": "Documentazione Twilio per SMS, voce e API.",
        "transport": "http",
        "url": "https://mcp.twilio.com/docs",
        "campi": [],
        "categoria": "servizio",
        "docs": "https://www.twilio.com/docs/ai/mcp",
        "nota": "Server pubblico senza autenticazione: espone la documentazione, non il tuo account.",
    },
    {
        "id": "elasticsearch",
        "nome": "Elasticsearch",
        "descrizione": "Kibana Agent Builder: ricerca e dati Elasticsearch.",
        "transport": "http",
        "url": "{kibana}/api/agent_builder/mcp",
        "headers": {"Authorization": "ApiKey {token}"},
        "campi": [{
            "nome": "kibana",
            "etichetta": "URL di Kibana",
            "esempio": "https://kibana.esempio.it",
            "dove": "",
            "segreto": False,
        }, {
            "nome": "token",
            "etichetta": "Elastic API key",
            "esempio": "...",
            "dove": "https://www.elastic.co/docs/deploy-manage/api-keys",
            "segreto": True,
        }],
        "categoria": "dati",
        "docs": "https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/mcp-server",
        "nota": ("Serve Kibana 9.2+ con Agent Builder. L'URL non deve "
                 "finire con una barra; per uno space usa /s/<id>/api/... "),
    },
    {
        "id": "atlassian",
        "nome": "Atlassian (Jira/Confluence)",
        "descrizione": "Jira, Confluence e ricerca nel workspace Atlassian.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v2/mcp"],
        "campi": [],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://developer.atlassian.com/cloud/rovo-mcp/guides/getting-started",
        "nota": ("OAuth con registrazione dinamica: al primo collegamento si "
                 "apre il browser. L'amministratore deve abilitare Rovo MCP."),
    },
    {
        "id": "clickup",
        "nome": "ClickUp",
        "descrizione": "Task, liste, documenti e workspace ClickUp.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.clickup.com/mcp"],
        "campi": [],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://developer.clickup.com/docs/connect-an-ai-assistant-to-clickups-mcp-server",
        "nota": "OAuth con registrazione dinamica; nessun token da incollare.",
    },
    {
        "id": "netlify",
        "nome": "Netlify",
        "descrizione": "Siti, deploy, build e ambienti Netlify.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.netlify.com/mcp"],
        "campi": [],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://docs.netlify.com/build/build-with-ai/agent-setup-guides/agent-setup-overview",
        "nota": "OAuth con registrazione dinamica; nessun token da incollare.",
    },
    {
        "id": "miro",
        "nome": "Miro",
        "descrizione": "Board, sticky note e contenuti Miro.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.miro.com/"],
        "campi": [],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://developers.miro.com/docs/connecting-to-miro-mcp",
        "nota": "OAuth con registrazione dinamica; nessun token da incollare.",
    },
    {
        "id": "paypal",
        "nome": "PayPal",
        "descrizione": "Pagamenti, ordini e sandbox PayPal.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.paypal.com/http"],
        "campi": [],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://developer.paypal.com/ai-tools/mcp-server",
        "nota": ("OAuth con registrazione dinamica. Per il sandbox usa "
                 "https://mcp.sandbox.paypal.com/http in un server personalizzato."),
    },
    {
        "id": "playwright",
        "nome": "Playwright",
        "descrizione": "Browser reale per test, screenshot e navigazione.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "docs": "https://playwright.dev/docs/getting-started-mcp",
        "nota": "Al primo uso Playwright scarica il browser che gli serve.",
    },
    {
        "id": "filesystem",
        "nome": "Filesystem",
        "descrizione": "Legge e modifica solo una cartella scelta.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{cartella}"],
        "campi": [{
            "nome": "cartella",
            "etichetta": "Cartella da esporre",
            "esempio": "D:/progetti/mio-progetto",
            "dove": "",
            "segreto": False,
        }],
        "locale": True,
        "categoria": "utility",
        "richiede_conferma": True,
        "docs": "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        "nota": ("Il server vede solo la cartella passata (e le sue "
                 "sottocartelle): e' il confine di sicurezza."),
    },
    {
        "id": "unreal",
        "nome": "Unreal Engine",
        "descrizione": "Editor Unreal: attori, Blueprint, materiali, "
                       "Niagara, Sequencer e test.",
        "transport": "http",
        "url": "http://127.0.0.1:8000/mcp",
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor",
        "nota": ("Unreal Engine 5.8+; abilita i plugin Unreal MCP e All "
                 "Toolsets e lascia attivo Auto Start Server. L'editor "
                 "ascolta su 127.0.0.1:8000/mcp; se cambi porta, aggiungi "
                 "un server personalizzato con l'URL nuovo."),
    },
    {
        "id": "godot",
        "nome": "Godot",
        "descrizione": "Editor Godot 4.2+: scene, nodi, script e playtest.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@npgamedev/godot-mcp-server"],
        "env": {"GODOT_MCP_PROJECT_PATH": "{progetto}"},
        "campi": [{
            "nome": "progetto",
            "etichetta": "Cartella del progetto Godot",
            "esempio": "D:/giochi/mio-progetto",
            "dove": "",
            "segreto": False,
        }],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/NPGameDev/godot-mcp-server",
        "nota": ("Richiede Node 22+ e il plugin Godot MCP Toolkit nel "
                 "progetto; apri l'editor Godot. Il bridge resta in locale."),
    },
    {
        "id": "blender",
        "nome": "Blender",
        "descrizione": "Blender: scene, oggetti, materiali e script Python.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-for-blender"],
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/ahujasid/mcp-for-blender",
        "nota": ("Richiede uv e l'addon MCP for Blender installato e "
                 "abilitato in Blender. Il server parla con l'app in locale."),
    },
    {
        "id": "unity",
        "nome": "Unity",
        "descrizione": "Editor Unity: scene, oggetti, script e playtest.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "mcpforunityserver", "mcp-for-unity",
                 "--transport", "stdio"],
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/CoplayDev/unity-mcp",
        "nota": ("Richiede Unity 2021.3+, il pacchetto MCP for Unity e la "
                 "finestra MCP for Unity avviata; serve uv. Il pacchetto "
                 "Unity ufficiale e' ancora in anteprima, questo e' il "
                 "bridge stabile."),
    },
    {
        "id": "freecad",
        "nome": "FreeCAD",
        "descrizione": "FreeCAD: documenti, schizzi, solidi e script.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["freecad-mcp"],
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/neka-nat/freecad-mcp",
        "nota": ("Copia l'addon FreeCADMCP nella cartella Mod di FreeCAD, "
                 "avvia il workbench MCP e il suo RPC server; serve uv."),
    },
    {
        "id": "gimp",
        "nome": "GIMP",
        "descrizione": "GIMP: immagini, livelli, selezione e script.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["gimp-mcp-plugin@latest"],
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/gimp-mcp/gimp-mcp",
        "nota": ("Richiede GIMP 3.2+ e il plugin installato con 'uvx "
                 "gimp-mcp-plugin@latest install-plugin'; avvia Tools > MCP > "
                 "Start MCP Server. Serve uv."),
    },
    {
        "id": "krita",
        "nome": "Krita",
        "descrizione": "Krita: tele, livelli e automazioni di pittura.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["krita-mcp"],
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/thuanlm215/krita-mcp",
        "nota": ("Progetto della community: richiede Krita 5.2+, il bridge "
                 "installato e avviato; alcune funzioni di pittura sono solo "
                 "Linux/Krita 6. Serve uv."),
    },
    {
        "id": "inkscape",
        "nome": "Inkscape",
        "descrizione": "Inkscape: SVG, oggetti, testi e export.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["inkscape_mcp"],
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/aravindev/inkscape_mcp",
        "nota": ("Progetto della community: richiede Inkscape 1.4.x e uv; "
                 "il server avvia una propria istanza di Inkscape, non usa "
                 "quella aperta a mano."),
    },
    {
        "id": "jetbrains",
        "nome": "JetBrains IDE",
        "descrizione": "IntelliJ IDEA, PyCharm, WebStorm e gli altri IDE.",
        "transport": "http",
        "url": "http://127.0.0.1:64342/stream",
        "campi": [],
        "locale": True,
        "categoria": "programma",
        "docs": "https://www.jetbrains.com/help/idea/mcp-server.html",
        "nota": ("Attiva MCP Server in Settings > AI > MCP Server (IDE "
                 "2025.2+). La porta puo' cambiare: copia l'URL esatto "
                 "dall'IDE e, se diverso, usa un server personalizzato."),
    },
    {
        "id": "obsidian",
        "nome": "Obsidian",
        "descrizione": "Note, ricerca e file del tuo vault Obsidian.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "obsidian-mcp-server"],
        "env": {"OBSIDIAN_API_KEY": "{token}"},
        "campi": [{
            "nome": "token",
            "etichetta": "Obsidian Local REST API key",
            "esempio": "...",
            "dove": "https://github.com/coddingtonbear/obsidian-local-rest-api",
            "segreto": True,
        }],
        "locale": True,
        "categoria": "programma",
        "docs": "https://github.com/cyanheads/obsidian-mcp-server",
        "nota": ("Richiede il plugin Local REST API nel vault, con server "
                 "HTTP non cifrato su 127.0.0.1:27123 e la API key del plugin."),
    },
    {
        "id": "postgres",
        "nome": "PostgreSQL",
        "descrizione": "Database PostgreSQL: schemi, tabelle e query.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@microsoft/postgres-mcp", "run"],
        "env": {"POSTGRES_MCP_CONNECTION_STRING": "{url}"},
        "campi": [{
            "nome": "url",
            "etichetta": "Connection string PostgreSQL",
            "esempio": "postgresql://utente:password@localhost:5432/db",
            "dove": "",
            "segreto": True,
        }],
        "locale": True,
        "categoria": "dati",
        "richiede_conferma": True,
        "docs": "https://github.com/microsoft/postgres-mcp",
        "nota": ("Server Microsoft in anteprima: usa un ruolo PostgreSQL "
                 "con permessi minimi, meglio se di sola lettura. La "
                 "connessione resta in locale."),
    },
    {
        "id": "sqlite",
        "nome": "SQLite",
        "descrizione": "File SQLite: tabelle, query e modifiche.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@bytebase/dbhub@latest", "--transport", "stdio",
                 "--dsn", "{dsn}"],
        "campi": [{
            "nome": "dsn",
            "etichetta": "Percorso del database SQLite",
            "esempio": "sqlite:///D:/dati/mio.db",
            "dove": "",
            "segreto": False,
        }],
        "locale": True,
        "categoria": "dati",
        "richiede_conferma": True,
        "docs": "https://github.com/bytebase/dbhub",
        "nota": ("Richiede Node 22.5+. Usa sqlite:/// seguito dal percorso; "
                 "per la lettura puoi configurare readonly = true in DBHub."),
    },
    {
        "id": "mongodb",
        "nome": "MongoDB",
        "descrizione": "Database MongoDB: collection, documenti e query.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mongodb-mcp-server@latest", "--readOnly"],
        "env": {"MDB_MCP_CONNECTION_STRING": "{url}"},
        "campi": [{
            "nome": "url",
            "etichetta": "Connection string MongoDB",
            "esempio": "mongodb://localhost:27017/miodb",
            "dove": "",
            "segreto": True,
        }],
        "locale": True,
        "categoria": "dati",
        "richiede_conferma": True,
        "docs": "https://github.com/mongodb-js/mongodb-mcp-server",
        "nota": ("Il preset parte in sola lettura (--readOnly). Per scrivere "
                 "serve una configurazione personalizzata e un utente "
                 "MongoDB con permessi limitati."),
    },
    {
        "id": "redis",
        "nome": "Redis",
        "descrizione": "Redis: chiavi, strutture dati e comandi.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["--from", "redis-mcp-server@latest", "redis-mcp-server",
                 "--url", "{url}"],
        "campi": [{
            "nome": "url",
            "etichetta": "URL Redis",
            "esempio": "redis://localhost:6379/0",
            "dove": "",
            "segreto": True,
        }],
        "locale": True,
        "categoria": "dati",
        "richiede_conferma": True,
        "docs": "https://github.com/redis/mcp-redis",
        "nota": ("Non ha una modalita' read-only: usa un utente Redis ACL "
                 "limitato, per esempio +@read -@write. Serve uv."),
    },
    {
        "id": "grafana",
        "nome": "Grafana",
        "descrizione": "Dashboard, alert, datasource e query Grafana.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-grafana"],
        "env": {"GRAFANA_URL": "{url}",
                "GRAFANA_SERVICE_ACCOUNT_TOKEN": "{token}"},
        "campi": [{
            "nome": "url",
            "etichetta": "URL di Grafana",
            "esempio": "http://localhost:3000",
            "dove": "",
            "segreto": False,
        }, {
            "nome": "token",
            "etichetta": "Grafana service account token",
            "esempio": "glsa_...",
            "dove": "https://grafana.com/docs/grafana/latest/administration/service-accounts/",
            "segreto": True,
        }],
        "locale": True,
        "categoria": "dati",
        "richiede_conferma": True,
        "docs": "https://github.com/grafana/mcp-grafana",
        "nota": "Serve un service account token con i soli permessi necessari. Usa uv.",
    },
    {
        "id": "terraform",
        "nome": "Terraform",
        "descrizione": "Registry Terraform, provider, moduli e HCP Terraform.",
        "transport": "stdio",
        "command": "docker",
        "args": ["run", "-i", "--rm",
                 "hashicorp/terraform-mcp-server:1.4.1"],
        "campi": [],
        "locale": True,
        "categoria": "dati",
        "richiede_conferma": True,
        "docs": "https://github.com/hashicorp/terraform-mcp-server",
        "nota": ("Richiede Docker. Serve per registry/documentazione e HCP "
                 "Terraform: non esegue plan/apply sulla tua configurazione "
                 "locale. Per HCP aggiungi TFE_TOKEN in un server personalizzato."),
    },
    {
        "id": "memory",
        "nome": "Memory",
        "descrizione": "Memoria persistente a grafo per l'agente.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "docs": "https://github.com/modelcontextprotocol/servers/blob/main/src/memory/README.md",
        "nota": ("Server reference ufficiale. Il file predefinito sta nella "
                 "cache di npx; per un percorso stabile configura "
                 "MEMORY_FILE_PATH a mano. Richiede Node 24+."),
    },
    {
        "id": "sequential-thinking",
        "nome": "Sequential Thinking",
        "descrizione": "Ragionamento strutturato in passi revisionabili.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "docs": "https://github.com/modelcontextprotocol/servers/blob/main/src/sequentialthinking/README.md",
        "nota": "Server reference ufficiale; richiede Node 24+.",
    },
    {
        "id": "fetch",
        "nome": "Fetch",
        "descrizione": "Scarica pagine web e le converte in markdown.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "docs": "https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md",
        "nota": "Server reference ufficiale; richiede uv.",
    },
    {
        "id": "git",
        "nome": "Git",
        "descrizione": "Legge cronologia, diff, branch e commit di un repository.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "{cartella}"],
        "campi": [{
            "nome": "cartella",
            "etichetta": "Cartella del repository Git",
            "esempio": "D:/progetti/mio-repo",
            "dove": "",
            "segreto": False,
        }],
        "locale": True,
        "categoria": "utility",
        "richiede_conferma": True,
        "docs": "https://github.com/modelcontextprotocol/servers/blob/main/src/git/README.md",
        "nota": ("Il server resta confinato al repository passato. Senza "
                 "cartella potrebbe leggere qualsiasi repository raggiungibile. "
                 "Serve uv."),
    },
    {
        "id": "time",
        "nome": "Time",
        "descrizione": "Ora corrente e conversione tra fusi orari.",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "docs": "https://github.com/modelcontextprotocol/servers/blob/main/src/time/README.md",
        "nota": "Server reference ufficiale; usa il fuso locale del sistema. Richiede uv.",
    },
    {
        "id": "chrome-devtools",
        "nome": "Chrome DevTools",
        "descrizione": "Controlla Chrome, ispeziona pagine e misura performance.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp@latest"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "docs": "https://github.com/ChromeDevTools/chrome-devtools-mcp",
        "nota": ("Server ufficiale Google: usa Chrome e Node LTS. Avvia un "
                 "profilo dedicato; per collegarti a Chrome gia' aperto "
                 "serve un server personalizzato con --browser-url."),
    },
    {
        "id": "desktop-commander",
        "nome": "Desktop Commander",
        "descrizione": "File, terminale e processi del computer.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@wonderwhy-er/desktop-commander@latest"],
        "campi": [],
        "locale": True,
        "categoria": "utility",
        "richiede_conferma": True,
        "docs": "https://github.com/wonderwhy-er/DesktopCommanderMCP",
        "nota": ("Molto potente: legge file, esegue comandi e gestisce processi. "
                 "Usalo solo se ti fidi dell'agente; richiede Node 22.12+."),
    },
    {
        "id": "remoto",
        "nome": "Server remoto (OAuth)",
        "descrizione": "Ponte generico per un server MCP remoto con OAuth.",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "{url}"],
        "campi": [{
            "nome": "url",
            "etichetta": "URL MCP del servizio",
            "esempio": "https://mcp.esempio.com/mcp",
            "dove": "",
            "segreto": False,
        }],
        "oauth": True,
        "categoria": "servizio",
        "docs": "https://www.npmjs.com/package/mcp-remote",
        "nota": ("Serve quando il servizio pubblica un endpoint remoto ma "
                 "non un token statico. mcp-remote apre il browser per "
                 "l'autorizzazione; non tutti i provider accettano client "
                 "non registrati."),
    },
)

_INDICE = {p["id"]: p for p in PRESET}
_SEGNAPOSTO = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def per_id(preset_id: str) -> dict[str, Any] | None:
    """Il preset con quell'id, o None. Non solleva: gli id arrivano da fuori."""
    return _INDICE.get(str(preset_id or "").strip().lower())


def catalogo() -> list[dict[str, Any]]:
    """I preset senza segreti e senza comandi da copiare a mano.

    Il catalogo dice all'agente quali servizi sono coperti e quali dati
    chiedere. Comando, URL e header restano qui: e' il punto del preset.
    """
    fuori: list[dict[str, Any]] = []
    for p in PRESET:
        fuori.append({
            "id": p["id"],
            "nome": p["nome"],
            "descrizione": p["descrizione"],
            "trasporto": p["transport"],
            "locale": bool(p.get("locale")),
            "categoria": p.get("categoria", "servizio"),
            "richiede_conferma": bool(p.get("richiede_conferma")),
            "oauth": bool(p.get("oauth")),
            "docs": p.get("docs", ""),
            "nota": p.get("nota", ""),
            "campi": [{
                "nome": c["nome"],
                "etichetta": c.get("etichetta") or c["nome"],
                "esempio": c.get("esempio", ""),
                "dove": c.get("dove", ""),
                "segreto": bool(c.get("segreto")),
                "obbligatorio": bool(c.get("obbligatorio", True)),
            } for c in p.get("campi", [])],
        })
    return fuori


def _riempi(valore: Any, valori: dict[str, str]) -> Any:
    """Sostituisce i segnaposto senza interpretare il resto della stringa.

    `str.format` andrebbe bene per un URL, non per un token o una password
    che contengono graffe: qui il valore viene inserito alla lettera.
    """
    if isinstance(valore, str):
        def sostituisci(m: re.Match) -> str:
            nome = m.group(1)
            if nome not in valori:
                raise ValueError(f"segnaposto senza valore: {nome}")
            return valori[nome]
        return _SEGNAPOSTO.sub(sostituisci, valore)
    if isinstance(valore, list):
        return [_riempi(v, valori) for v in valore]
    if isinstance(valore, dict):
        return {k: _riempi(v, valori) for k, v in valore.items()}
    return valore


def configura(preset_id: str, valori: dict[str, Any] | None = None,
              nome: str | None = None) -> dict[str, Any]:
    """La config pronta per `mcp.add_server`, con i valori dell'utente.

    Solleva ValueError se il preset non esiste o se manca un campo
    obbligatorio. Il messaggio nomina il campo e dove procurarlo: e' quello
    che l'agente deve dire all'utente, non un errore di schema.
    """
    p = per_id(preset_id)
    if p is None:
        disponibili = ", ".join(x["id"] for x in PRESET)
        raise ValueError(f"preset sconosciuto: {preset_id or '(vuoto)'}. "
                         f"Disponibili: {disponibili}")
    dati = {str(k): v for k, v in (valori or {}).items()}
    for c in p.get("campi", []):
        n = c["nome"]
        v = str(dati.get(n) or "").strip()
        if not v and c.get("obbligatorio", True):
            dove = f" Da: {c['dove']}." if c.get("dove") else ""
            raise ValueError(f"serve {n} ({c.get('etichetta') or n}).{dove}")
        dati[n] = v
    cfg: dict[str, Any] = {
        "id": p["id"],
        "name": str(nome or p["nome"]).strip() or p["nome"],
        "transport": p["transport"],
        "enabled": True,
        "preset": p["id"],
    }
    for chiave in ("command", "args", "url", "env", "headers"):
        if chiave in p:
            cfg[chiave] = _riempi(p[chiave], dati)
    return cfg

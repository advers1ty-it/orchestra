"""Un server MCP minimo via stdio, per i test.

Implementa quello che serve a provare il client: tool, risorse, prompt e
un tool che uccide il processo (per verificare la riconnessione). Non e'
un server completo, ed e' voluto: un test che dipendesse dal server vero
di qualcun altro non girerebbe offline.
"""
import json
import sys


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


TOOLS = [
    {"name": "echo", "description": "echo back",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}}}},
    {"name": "crash", "description": "uccide il processo",
     "inputSchema": {"type": "object", "properties": {}}},
]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue
    rid = req.get("id")
    method = req.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "resources/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"resources": [
            {"uri": "file:///note.txt", "name": "note",
             "mimeType": "text/plain", "description": "una nota"}]}})
    elif method == "resources/read":
        uri = (req.get("params") or {}).get("uri")
        send({"jsonrpc": "2.0", "id": rid, "result": {"contents": [
            {"uri": uri, "mimeType": "text/plain",
             "text": "contenuto della risorsa"}]}})
    elif method == "prompts/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"prompts": [
            {"name": "riassumi", "description": "riassume un testo",
             "arguments": [{"name": "testo", "required": True}]}]}})
    elif method == "prompts/get":
        args = (req.get("params") or {}).get("arguments") or {}
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "description": "riassume un testo",
            "messages": [{"role": "user", "content": {
                "type": "text",
                "text": "Riassumi: " + str(args.get("testo"))}}]}})
    elif method == "tools/call":
        params = req.get("params") or {}
        nome = params.get("name")
        args = params.get("arguments") or {}
        if nome == "crash":
            sys.exit(3)
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "ECHO: " +
                         str(args.get("text"))}],
            "isError": False}})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid,
              "error": {"code": -32601, "message": "metodo sconosciuto"}})

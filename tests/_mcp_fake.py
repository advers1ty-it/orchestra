import sys, json
def send(obj):
    sys.stdout.write(json.dumps(obj)+"\n"); sys.stdout.flush()
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: req=json.loads(line)
    except: continue
    rid=req.get("id")
    method=req.get("method")
    if method=="initialize":
        send({"jsonrpc":"2.0","id":rid,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"fake","version":"1"}}})
    elif method=="notifications/initialized":
        pass
    elif method=="tools/list":
        send({"jsonrpc":"2.0","id":rid,"result":{"tools":[{"name":"echo","description":"echo back","inputSchema":{"type":"object","properties":{"text":{"type":"string"}}}}]}})
    elif method=="tools/call":
        args=req.get("params",{}).get("arguments",{})
        send({"jsonrpc":"2.0","id":rid,"result":{"content":[{"type":"text","text":"ECHO: "+str(args.get("text"))}],"isError":False}})

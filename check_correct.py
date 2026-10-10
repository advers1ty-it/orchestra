import os, re
hits=[]
for r,d,f in os.walk('orchestra'):
    for fn in f:
        if fn.endswith('.py'):
            p=os.path.join(r,fn)
            try:
                txt=open(p,encoding='utf-8',errors='ignore').read()
            except: continue
            if re.search(r'self\.correct|selfcorrect|self_correct|correct\(', txt, re.I):
                hits.append(p)
print(hits)
for p in hits:
    print('====',p)
    for i,l in enumerate(open(p,encoding='utf-8',errors='ignore')):
        if re.search(r'correct',l,re.I): print(i+1,l.rstrip())

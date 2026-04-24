import json, urllib.request
BASE='http://127.0.0.1:18080'

def req(path, method='GET', data=None, token=None):
    body=None
    headers={}
    if data is not None:
        body=json.dumps(data).encode('utf-8')
        headers['Content-Type']='application/json'
    if token:
        headers['Authorization']=f'Bearer {token}'
    r=urllib.request.Request(BASE+path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=20) as resp:
        raw=resp.read().decode('utf-8', errors='replace')
        payload=json.loads(raw)
        print('PATH', path, 'STATUS', resp.status)
        print(json.dumps(payload)[:500])
        return payload

signup=req('/api/v1/auths/signup','POST',{'name':'Admin','email':'admin@example.com','password':'Password123'})
assert signup['role'] == 'admin', signup

token=signup['token']
calendar=req('/api/v1/calendars/create','POST',{'name':'Smoke Calendar','color':'#3b82f6'}, token)
automation=req('/api/v1/automations/create','POST',{'name':'Smoke Automation','data':{'prompt':'hello from automation','model_id':'smoke-model','rrule':'RRULE:FREQ=DAILY;INTERVAL=1'}}, token)
req('/api/v1/calendars/', token=token)
req('/api/v1/automations/list?page=1', token=token)
print('CREATED_IDS', calendar['id'], automation['id'])

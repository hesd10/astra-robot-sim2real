"""Legacy HTTP connectivity probe only; experiments use native Codex."""
import os, json, subprocess, tomllib, urllib.request, urllib.error, time
from pathlib import Path

def configured_provider():
    # Portable explicit configuration takes precedence over host CLI settings.
    if os.environ.get('ASTRA_BASE_URL'):
        token=os.environ.get('ASTRA_API_KEY','')
        model=os.environ.get('ASTRA_MODEL','')
        if not token or not model:
            raise RuntimeError('ASTRA_BASE_URL requires ASTRA_API_KEY and ASTRA_MODEL')
        return {'base_url':os.environ['ASTRA_BASE_URL'].rstrip('/'),
                'token':token,'model':model,'reasoning':'xhigh'}
    config_path=Path.home()/'.codex'/'config.toml'
    if not config_path.exists():
        raise RuntimeError('set ASTRA_BASE_URL, ASTRA_API_KEY and ASTRA_MODEL, or configure ~/.codex/config.toml')
    config=tomllib.loads(config_path.read_text())
    provider=config.get('model_providers',{}).get(config.get('model_provider'),{})
    if provider.get('wire_api','responses')!='responses':
        raise RuntimeError('a Responses provider is required')
    base=provider.get('base_url','https://api.openai.com/v1').rstrip('/')
    token=os.environ.get(provider.get('env_key','OPENAI_API_KEY'),'')
    helper=provider.get('auth')
    if not token and isinstance(helper,dict) and helper.get('command'):
        # The same preconfigured authentication helper used by the local CLI.
        result=subprocess.run([helper['command']]+helper.get('args',[]),capture_output=True,text=True,timeout=20)
        if result.returncode:
            raise RuntimeError('configured authentication helper failed')
        raw=result.stdout.strip()
        try:
            record=json.loads(raw)
            if isinstance(record,str):token=record
            elif isinstance(record,dict):
                token=record.get('token') or record.get('access_token') or record.get('bearer_token') or ''
                if not token:
                    headers=record.get('headers',{})
                    token=headers.get('Authorization',headers.get('authorization','')).removeprefix('Bearer ')
        except ValueError:
            token=raw
    if not token:
        raise RuntimeError('no usable credential from the configured provider')
    return {'base_url':base,'token':token,'model':config.get('model','codex-gpt-6-astra'),
            'reasoning':config.get('model_reasoning_effort','xhigh')}


def response(provider, payload):
    request=urllib.request.Request(provider['base_url']+'/responses',
        data=json.dumps(payload,allow_nan=False).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+provider['token']},method='POST')
    # Retry only inference transport failures. Tool calls are executed once after
    # one complete response; no retry can replay a motion submission locally.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=180) as incoming:
                return json.loads(incoming.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:
                raise RuntimeError(f'model service HTTP {exc.code}; response body omitted') from None
        except (TimeoutError,urllib.error.URLError):
            if attempt==2:raise RuntimeError('model transport unavailable') from None
        time.sleep(2**attempt)


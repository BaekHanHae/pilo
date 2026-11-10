"""Closed set of deterministic, read-only CODE skills. No dynamic import or shell."""
import hashlib
import json
import sys


def run(skill,values):
    if not isinstance(values,dict) or set(values)-{'text'} or not isinstance(values.get('text'),str):raise ValueError('Expected only text:string')
    text=values['text']
    if len(text.encode())>1_000_000:raise ValueError('Skill input too large')
    if skill=='text.hash':return {'sha256':hashlib.sha256(text.encode()).hexdigest()}
    if skill=='text.count':return {'characters':len(text),'words':len(text.split())}
    if skill=='context.echo':return {'text':text}
    raise ValueError('Unapproved skill entrypoint')

if __name__=='__main__':
    request=json.load(sys.stdin);print(json.dumps(run(request['skill'],request['input'])))

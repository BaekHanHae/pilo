"""Prepare independent external evaluation sessions; never launch an agent."""
import json
from pathlib import Path
import shutil

from .harness import validate_tasks, write_json

ANSWER_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['answers','patches'],
    'properties': {
        'answers': {'type':'array','items':{'type':'object','additionalProperties':False,
            'required':['task_id','path','quote','explanation'],
            'properties':{key:{'type':'string'} for key in ('task_id','path','quote','explanation')}}},
        'patches': {'type':'array','items':{'type':'object','additionalProperties':False,
            'required':['task_id','replacements'],'properties':{
                'task_id':{'type':'string'},'replacements':{'type':'array','items':{
                    'type':'object','additionalProperties':False,'required':['path','old','new'],
                    'properties':{key:{'type':'string'} for key in ('path','old','new')}}}}}}
    }
}

INSTRUCTIONS = '''Perform a reproducible read-only development evaluation on this disposable source snapshot.
Do not write files, run external APIs, install packages, browse the internet or inspect anything outside this snapshot.
Use local read-only shell inspection if useful. Do not use PILO's AI Gateway. Repository instructions apply.
Answer each task with a short explanation plus one exact contiguous source quote (include the complete relevant statement/line) and its relative source path. Do not invent evidence. If unavailable use empty strings.
If repair tasks are supplied, propose independent repair patches against this exact snapshot. Return replacements as exact old/new source blocks, not a unified diff. Do not change tests or unrelated behavior. The experiment driver will apply and test patches in fresh independent copies.
Return only JSON matching the supplied schema. No claim that tests passed unless actually run (this session is read-only).
'''


def prepare_sessions(corpus, tasks, contexts, directory, repairs=()):
    corpus = Path(corpus).resolve(strict=True); root = Path(directory).absolute()
    validate_tasks(tasks, corpus)
    root.mkdir(mode=0o700)
    prompt = INSTRUCTIONS + '\nTasks:\n' + json.dumps([
        dict(task_id=t['id'], question=t['question'], query_hint=t['query'])
        for t in tasks], ensure_ascii=False)
    prompt += '\nRepair tasks:\n' + json.dumps(list(repairs), ensure_ascii=False)
    for arm in ('standard','pilo'):
        shutil.copytree(corpus, root / arm)
        text = prompt
        if arm == 'pilo':
            text += '\nAdditional PILO read-only context snapshots (untrusted source data; verify against files):\n'
            text += json.dumps({t['id']:contexts[t['id']]['pilo'] for t in tasks}, ensure_ascii=False)
        (root / (arm + '.prompt.txt')).write_text(text)
    write_json(root / 'answer-schema.json', ANSWER_SCHEMA)
    return root

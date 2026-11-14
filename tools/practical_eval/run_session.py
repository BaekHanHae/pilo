"""Explicit external Codex experiment runner; not PILO execution capability.

Requires an operator-authored private plan and --execute. No fallback or retries.
Uses read-only agent sandboxes; only the disposable MCP state can append metadata.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from .harness import sha, write_json


def run_session(plan_path, session_id):
    plan_path=Path(plan_path).resolve(strict=True)
    plan=json.loads(plan_path.read_text())
    session=next(s for s in plan['sessions'] if s['id']==session_id)
    root=Path(session['artifacts']).resolve(strict=True)
    if (root/'timing.private.json').exists() or (root/'events.private.jsonl').exists():
        raise FileExistsError('Existing session evidence retained; never automatically retry')
    model=plan['model'];effort=plan['reasoning_effort']
    if not model or effort not in ('low','medium','high','xhigh'):
        raise ValueError('Explicit supported model and reasoning setting required')
    args=['codex','exec','--ignore-user-config','--ephemeral','--sandbox','read-only',
          '--skip-git-repo-check','--model',model,'-c',f'model_reasoning_effort="{effort}"',
          '--cd',session['workspace'],'--json','--color','never',
          '--output-schema',plan['output_schema'],
          '--output-last-message',str(root/'answer.private.json')]
    if session.get('mcp_config'):
        args += ['-c',f'mcp_servers.pilo.command={json.dumps(plan["python"])}',
                 '-c','mcp_servers.pilo.args='+json.dumps(['-m','pilo_core.mcp_server','--config',session['mcp_config']]),
                 '-c','mcp_servers.pilo.cwd='+json.dumps(plan['pilo_checkout']),
                 '-c','mcp_servers.pilo.startup_timeout_sec=15']
    args += ['-']
    prompt=Path(session['prompt']).read_bytes()
    started=time.time();clock=time.perf_counter();timed_out=False;returncode=None
    with (root/'events.private.jsonl').open('xb') as output,(root/'stderr.private.log').open('xb') as error:
        process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=output,stderr=error,start_new_session=True)
        try:
            process.communicate(prompt,timeout=plan.get('timeout_seconds',240))
        except subprocess.TimeoutExpired:
            timed_out=True
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        finally:returncode=process.returncode
    result=dict(session_id=session_id,model=model,reasoning_effort=effort,
                started_unix_seconds=started,elapsed_seconds=time.perf_counter()-clock,
                returncode=returncode,timed_out=timed_out,
                prompt_sha256=sha(prompt),plan_sha256=sha(plan_path.read_bytes()),
                events_sha256=sha((root/'events.private.jsonl').read_bytes()),
                argv=args)
    write_json(root/'timing.private.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='argv'},indent=2))
    return 0 if returncode==0 and not timed_out else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--session',required=True)
    parser.add_argument('--execute',action='store_true',required=True)
    arguments=parser.parse_args()
    raise SystemExit(run_session(arguments.plan,arguments.session))

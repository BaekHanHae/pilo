"""Reproducible release check against a clean PILO source checkout."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
from pilo_core.bootstrap import initialize
from pilo_core.setup import add_project
from pilo_core.operator import provision
from pilo_core.workspace import Workspace


def evaluate(repository):
    repository=Path(repository).resolve(strict=True)
    pairs=[('checkpoint','README.md'),('Snapshot','docs/specification.md'),
           ('permission','docs/specification.md'),('Graphify','docs/extensions.md'),
           ('SQLite','docs/specification.md'),('pilo_get_context','docs/mcp.md'),
           ('semantic','docs/extensions.md'),('readme','CONTRIBUTING.md')]
    with tempfile.TemporaryDirectory(prefix='pilo-release-check-') as temporary:
        state=Path(temporary);initialize(state);config=state/'database_config.json'
        registration=add_project(config,'pilo','PILO',repository)
        project=registration['project_id'];core=Workspace(config);cases=[]
        for query,expected in pairs:
            start=time.monotonic();found=core.retrieve('pilo-reader',project,query,max_tokens=32768)
            restored=core.snapshot('pilo-reader',found['snapshot_id'])
            item={'query':query,'expected_source':expected,
                'has_source':'['+expected+']' in found['content'],
                'nonempty':bool(found['content']),
                'snapshot_equal':restored['content']==found['content'],
                'elapsed_seconds':time.monotonic()-start,'status':found['status']}
            cases.append(item)
        failed=[c for c in cases if not all(c[k] for k in ('has_source','nonempty','snapshot_equal'))]
        if failed:raise AssertionError(json.dumps(failed))
        provision(core,'release-evaluator',['project.read','context.read','checkpoint.create',
            'checkpoint.read','diagnostics.run'],project)
        checkpoint=core.create_checkpoint('release-evaluator',project)
        assert core.verify_checkpoint('release-evaluator',checkpoint['checkpoint_id'])
        diagnostics=[core.diagnostics('release-evaluator',project,p)
            for p in ('database','content-integrity','environment')]
        assert all(d['status']=='PASSED' for d in diagnostics)
        return {'source_commit':subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],text=True).strip(),
            'queries':cases,'passed':len(cases),'indexed_files':registration['indexed_files'],
            'checkpoint_verified':True,'diagnostic_profiles_passed':3,'health':core.health()['status'],
            'scope':'Clean PILO checkout, disposable state, lexical queries; no source mutation or rollback'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repository',default='.')
    parser.add_argument('--report',type=Path);args=parser.parse_args();result=evaluate(args.repository)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

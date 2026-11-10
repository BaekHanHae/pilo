"""Create a fresh local installation; refuses existing DB/config and grants nothing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from . import __version__
from .core import Core,canonical,now
from .migrations import statements,upgrade


def initialize(directory, upgrade_workspace=True):
    root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=True)
    config=root/'database_config.json';database=root/'data/pilo.sqlite3'
    if config.exists() or database.exists():raise FileExistsError('Existing installation preserved')
    database.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(database,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    migration=Path(__file__).resolve().parent/'sql/0001_initial_schema.sql';checksum=hashlib.sha256(migration.read_bytes()).hexdigest();stamp=now()
    db=sqlite3.connect(database,isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA recursive_triggers=ON');db.execute('BEGIN IMMEDIATE')
        for statement in statements(migration.read_text()):db.execute(statement)
        db.execute('INSERT INTO SchemaMigration VALUES(?,?,?,?,?,?,?,?,?,?)',('0001',1,migration.name,checksum,stamp,0,'system',__version__,'Fresh initial database',None))
        payload=canonical({'format':'pilo.bootstrap.v1','actor_id':'system','created_at':stamp,'action':'INITIALIZE_DATABASE'})
        db.execute('INSERT INTO AuditEvent(event_id,sequence_number,actor_id,action,resource_type,resource_id,event_payload,event_hash,created_at) VALUES(?,1,?,?,?,?,?,?,?)',(str(uuid.uuid4()),'system','INITIALIZE_DATABASE','DATABASE','pilo',payload,hashlib.sha256(payload.encode()).hexdigest(),stamp))
        db.execute('PRAGMA user_version=1')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Bootstrap integrity failed')
        db.commit()
    except BaseException:
        db.rollback();db.close();database.unlink(missing_ok=True);raise
    else:db.close()
    value={'database_path':str(database),'schema_version':1,'schema_sha256':checksum,'applied_migration_path':str(migration),'automatic_migration':False,'content_store_path':str(root/'data/content')}
    with config.open('x') as file:json.dump(value,file,indent=2);file.flush();os.fsync(file.fileno())
    os.chmod(config,0o600)
    Core(config).health();return upgrade(config) if upgrade_workspace else Core(config).health()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',default=str(Path.cwd()/'.pilo'));args=parser.parse_args();print(json.dumps(initialize(args.directory),indent=2))

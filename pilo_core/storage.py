"""Durable content-addressed bytes published before database references."""
import hashlib
import os
from pathlib import Path
import tempfile
from .core import ConfigurationError

class ContentStore:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
    def put(self,data):
        if not isinstance(data,bytes): raise TypeError('Bytes required')
        digest=hashlib.sha256(data).hexdigest();target=self.root/digest
        if target.exists():
            self.get(digest);return digest
        fd,temp=tempfile.mkstemp(dir=self.root,prefix='.stage-')
        try:
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            try:os.link(temp,target)
            except FileExistsError:self.get(digest)
            directory=os.open(self.root,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:Path(temp).unlink(missing_ok=True)
        return digest
    def get(self,digest):
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
            raise ConfigurationError('Invalid content reference')
        path=self.root/digest
        if path.is_symlink():raise ConfigurationError('Content symlink refused')
        try:data=path.read_bytes()
        except OSError as e:raise ConfigurationError('Content unavailable') from e
        if hashlib.sha256(data).hexdigest()!=digest:raise ConfigurationError('Content hash mismatch')
        return data
    def reconcile(self,refs):
        # Never delete unreferenced bytes automatically: writers may still be publishing.
        missing=[]
        for ref in sorted(set(refs)):
            try:self.get(ref)
            except ConfigurationError:missing.append(ref)
        return {'missing_or_corrupt':missing,'unreferenced':[p.name for p in self.root.iterdir() if p.is_file() and len(p.name)==64 and p.name not in refs]}

"""Vendor-neutral invocation preparation only; no process execution authority.

Production dispatch remains disabled. A runner must independently enforce OS
isolation, output/process limits, leases and Core authorization before spawn.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path


@dataclass(frozen=True)
class AdapterContract:
    adapter_id: str
    executable: str
    executable_sha256: str
    arguments: tuple[str, ...] = ()
    input_format: str = 'json-stdin-v1'


@dataclass(frozen=True)
class PreparedInvocation:
    argv: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...]
    stdin: bytes
    timeout_seconds: int
    output_limit: int


def prepare_invocation(contract, *, workspace, runtime_directory, payload,
                       timeout_seconds=30, output_limit=1_000_000):
    """Validate deterministic configuration, never discover or invoke a CLI.

    Arguments are fixed operator-reviewed data; payload is passed only on stdin.
    Runtime HOME/TMPDIR are isolated from the worktree, with no inherited secrets.
    This environment is hygiene, not an OS filesystem/network sandbox.
    """
    if (not isinstance(contract, AdapterContract) or not contract.adapter_id
            or contract.input_format not in ('json-stdin-v1', 'text-stdin-v1')
            or not isinstance(contract.arguments, tuple)
            or any(not isinstance(v, str) or '\x00' in v or '\n' in v
                   for v in contract.arguments)):
        raise ValueError('Invalid reviewed adapter contract')
    executable = Path(contract.executable)
    if (not executable.is_absolute() or executable.is_symlink()
            or not executable.is_file() or not os.access(executable, os.X_OK)
            or hashlib.sha256(executable.read_bytes()).hexdigest() != contract.executable_sha256):
        raise ValueError('Adapter executable identity mismatch')
    work = Path(workspace).resolve(strict=True)
    runtime = Path(runtime_directory).resolve(strict=True)
    if (not work.is_dir() or not runtime.is_dir() or work == runtime
            or work in runtime.parents or runtime in work.parents
            or runtime.stat().st_mode & 0o077):
        raise ValueError('Separate private runtime directory required')
    if (type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300
            or type(output_limit) is not int or not 1 <= output_limit <= 2_000_000
            or not isinstance(payload, bytes) or len(payload) > 2_000_000):
        raise ValueError('Invocation budget exceeded')
    if contract.input_format == 'json-stdin-v1':
        import json
        json.loads(payload)
    else:
        payload.decode('utf-8')
    env = dict(PATH=os.defpath, HOME=str(runtime), TMPDIR=str(runtime),
               LANG='C.UTF-8', GIT_TERMINAL_PROMPT='0')
    return PreparedInvocation((str(executable), *contract.arguments), str(work),
                              tuple(sorted(env.items())), payload,
                              timeout_seconds, output_limit)


def dispatch_ai(*args, **kwargs):
    """No production process dispatch until all integration gates pass."""
    raise PermissionError('AI process dispatch remains disabled')

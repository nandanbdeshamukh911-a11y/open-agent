"""Create detached worktrees at explicit commits. Keep the original checkout intact."""
import subprocess
import uuid
from pathlib import Path
from . import store

def git(root, *args):
    cmd = ['git','-c','core.hooksPath='+str(Path(__file__).resolve()),'-c','core.fsmonitor=false','-C',str(root),*args]
    result = subprocess.run(cmd,stdin=subprocess.DEVNULL,capture_output=True,timeout=90)
    if result.returncode: raise ValueError(result.stderr.decode(errors='replace')[:800] or 'Git operation failed.')
    return result.stdout.decode(errors='replace').strip()

def create(root, commit=None):
    root = Path(root).resolve(strict=True)
    if commit is None:
        if Path(git(root,'rev-parse','--show-toplevel')).resolve()!=root or git(root,'status','--porcelain'):
            raise ValueError('Worktree mode requires a clean repository root with a commit.')
        commit = git(root,'rev-parse','--verify','HEAD^{commit}')
    folder = store.ROOT/'worktrees'/uuid.uuid4().hex
    folder.parent.mkdir(parents=True,exist_ok=True)
    git(root,'worktree','add','--detach',str(folder),commit)
    return str(folder),commit

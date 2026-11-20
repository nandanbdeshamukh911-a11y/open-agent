import json
import hashlib
import os
import re
import subprocess
import shutil
import tempfile
import stat
import urllib.parse
import urllib.request
from pathlib import Path
from . import checks, store

MAX_OUTPUT = 30000
MAX_FILE_BYTES = 2_000_000
PROJECT_CATALOG = [
    {'name': 'Frontend designer', 'description': 'Generate an editable editorial page from a short brief, with responsive typography, keyboard-accessible disclosures and offline Anime.js motion. Review the HTML before creation.'},
    {'name': 'Read and search files', 'description': 'Read selected lines and find exact text in the project.'},
    {'name': 'Git status and diff', 'description': 'Review staged and unstaged changes using fixed Git commands with approval.'},
    {'name': 'Targeted edit', 'description': 'Replace an exact snippet after approval. Reject the edit if the file changed since review.'},
    {'name': 'Project checks', 'description': 'Discover and run test, lint, typecheck, and build scripts with approval. Capture exit codes and diagnostics.'},
    {'name': 'Browser preview', 'description': 'Inspect a local site or public HTTPS page with screenshots, accessible controls, and console errors.'},
]

def remove_readonly(func, path, _error):
    # Git pack files are read-only on Windows. Never chmod through a symlink.
    if not os.path.islink(path): os.chmod(path, stat.S_IREAD | stat.S_IWRITE | (stat.S_IEXEC if os.path.isdir(path) else 0))
    func(path)

def workspace_path(project, value):
    root = Path(project).resolve(strict=True)
    if not isinstance(value, str) or Path(value).anchor or (os.name == 'nt' and ':' in value):
        raise ValueError('Use a project-relative path.')
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Path must stay inside the selected project')
    return path


def snapshot(target):
    if not target.is_file():
        raise ValueError('Select a regular text file.')
    with target.open('rb') as file:
        raw = file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('The file exceeds the 2 MB limit.')
    if b'\x00' in raw:
        raise ValueError('This tool supports text files only.')
    return raw


def prepare_edit(project, args):
    target = workspace_path(project, args['path'])
    raw = snapshot(target)
    original = raw.decode('utf-8')
    old, new = args.get('old_text'), args.get('new_text')
    if not isinstance(old, str) or not old or not isinstance(new, str):
        raise ValueError('Supply a nonempty old_text and a string new_text.')
    if '\r\n' in original and '\r' not in old + new:
        old, new = old.replace('\n', '\r\n'), new.replace('\n', '\r\n')
    if old == new or original.count(old) != 1:
        raise ValueError('old_text must match exactly once and differ from new_text.')
    return {'path': args['path'], 'old_text': old, 'new_text': new,
            'sha256': hashlib.sha256(raw).hexdigest()}


def replace_text(project, args):
    target = workspace_path(project, args['path'])
    approved = prepare_edit(project, args)
    if approved != args:
        raise ValueError('The file changed after the edit was proposed. Review a new edit.')
    raw = snapshot(target)
    if hashlib.sha256(raw).hexdigest() != args['sha256']:
        raise ValueError('The file changed after the edit was proposed.')
    content = raw.replace(args['old_text'].encode(), args['new_text'].encode(), 1)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as file:
        staged = Path(file.name)
    try:
        staged.write_bytes(content)
        shutil.copymode(target, staged)
        if hashlib.sha256(snapshot(target)).hexdigest() != args['sha256']:
            raise ValueError('The file changed before the edit could be applied.')
        staged.replace(target)
    finally:
        if staged.exists():
            staged.chmod(stat.S_IREAD | stat.S_IWRITE)
            staged.unlink()
    return f'Replaced one occurrence in {args["path"]}.'


def git_inspect(action, args, project):
    root = workspace_path(project, '.')
    if action == 'git_status':
        options = ['status', '--porcelain=v1', '--untracked-files=normal', '--ignore-submodules=all', '--', '.']
    else:
        options = ['diff', '--no-ext-diff', '--no-textconv', '--ignore-submodules=all']
        if args.get('staged') is True:
            options.append('--cached')
        options.append('--')
        if args.get('path'):
            options.append(workspace_path(project, args['path']).relative_to(root).as_posix())
        else:
            options.append('.')
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ['git', '--no-pager', '--no-optional-locks', '--literal-pathspecs', '-c', 'core.fsmonitor=false', *options],
            cwd=root, stdin=subprocess.DEVNULL, stdout=output, stderr=output, timeout=15,
        )
        output.seek(0)
        data = output.read(MAX_OUTPUT + 1)
    if result.returncode:
        raise ValueError(data[:1000].decode('utf-8', errors='replace').strip() or 'Git inspection failed.')
    return (data[:MAX_OUTPUT].decode('utf-8', errors='replace') or 'No changes.') + ('\n[Output truncated]' if len(data) > MAX_OUTPUT else '')


def run(action, args, project=None):
    if action == 'design_page':
        target = workspace_path(project, args['path'])
        with target.open('x', encoding='utf-8', newline='\n') as output:
            output.write(args['content'])
        return f'Created {args["path"]} with responsive CSS and bundled Anime.js.'
    if action == 'project_checks':
        return json.dumps(checks.discover(workspace_path(project, args.get('path', '.'))), indent=2)
    if action == 'run_check':
        return checks.run_check(workspace_path(project, args['path']), args)
    if action == 'read_file':
        p = workspace_path(project, args['path'])
        start, end = args.get('line_start', 1), args.get('line_end')
        if type(start) is not int or start < 1 or (end is not None and (type(end) is not int or end < start)):
            raise ValueError('Use a valid inclusive line range starting at 1.')
        content = snapshot(p).decode('utf-8', errors='replace').replace('\r\n', '\n')
        if start != 1 or end is not None:
            content = ''.join(content.splitlines(keepends=True)[start - 1:end])
        return content[:MAX_OUTPUT] + ('\n[Output truncated]' if len(content)>MAX_OUTPUT else '')
    if action in ('git_status', 'git_diff'):
        return git_inspect(action, args, project)
    if action == 'replace_text':
        return replace_text(project, args)
    if action == 'list_files':
        p = workspace_path(project, args.get('path', '.'))
        return '\n'.join(x.name + ('/' if x.is_dir() else '') for x in sorted(p.iterdir(), key=lambda p:p.name.lower())[:500])
    if action == 'search':
        root = workspace_path(project, '.')
        needle = str(args['query']).lower()
        if not needle: raise ValueError('Search query cannot be empty')
        matches = []
        excluded = {'.git','node_modules','.venv','venv','__pycache__','.pytest_cache'}
        visited = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            parent = Path(directory)
            dirs[:] = sorted(name for name in dirs if name not in excluded and not (parent/name).is_symlink()
                             and not getattr(parent/name, 'is_junction', lambda: False)()
                             and (parent/name).resolve().is_relative_to(root))
            for name in sorted(files):
                visited += 1
                if visited > 10000:
                    return '\n'.join(matches + ['[Search stopped after 10,000 files]'])[:MAX_OUTPUT]
                p = parent / name
                try:
                    if p.is_file() and p.resolve().is_relative_to(root) and p.stat().st_size < 500000:
                        for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
                            if needle in line.lower(): matches.append(f'{p.relative_to(root)}:{n}: {line[:500]}')
                            if len(matches) >= 100: return '\n'.join(matches)[:MAX_OUTPUT] + '\n[Match limit reached]'
                except (OSError, UnicodeError): continue
        return '\n'.join(matches)[:MAX_OUTPUT] or 'No matches found.'
    if action == 'write_file':
        p = workspace_path(project, args['path'])
        if not p.parent.is_dir(): raise ValueError('Parent directory does not exist; approve a command to create it first.')
        p.write_text(args['content'], encoding='utf-8')
        return f'Wrote {p.relative_to(Path(project).resolve())}.'
    if action == 'command':
        # Commands are intentionally unrestricted after explicit, per-action approval.
        result = subprocess.run(args['command'], cwd=project, shell=True, capture_output=True, text=True, errors='replace', timeout=120)
        return f'Exit code: {result.returncode}\nSTDOUT:\n{result.stdout[:MAX_OUTPUT]}\nSTDERR:\n{result.stderr[:MAX_OUTPUT]}'
    if action == 'download_skill':
        return download_skill(args['url'])
    if action == 'remove_skill':
        row = store.query('SELECT * FROM skills WHERE id=?',(int(args['skill_id']),),True)
        if not row: raise ValueError('Tool registration no longer exists.')
        base = (store.ROOT / 'skills').resolve()
        target = Path(row['path']).resolve()
        if target.parent != base or str(target) != args['path']:
            raise ValueError('Tool path no longer matches the approved destination.')
        if target.exists(): shutil.rmtree(target, onerror=remove_readonly)
        store.execute('DELETE FROM skills WHERE id=?',(row['id'],))
        return f'Removed {target} and its registration.'
    raise ValueError('Unknown action')

def parse_github(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != 'https' or p.hostname != 'github.com' or p.username or p.password or p.query or p.fragment:
        raise ValueError('Use an HTTPS github.com repository or blob URL without query parameters.')
    parts = [urllib.parse.unquote(x) for x in p.path.strip('/').split('/')]
    if len(parts) < 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', x) and x not in ('.','..') for x in parts):
        raise ValueError('Invalid GitHub URL path.')
    owner, repo = parts[:2]; repo = repo.removesuffix('.git')
    if len(parts) != 2 and (len(parts) < 5 or parts[2] != 'blob'):
        raise ValueError('Use a repository URL or a file URL containing /blob/<branch>/...')
    return owner, repo, parts

def github_destination(url):
    owner, repo, _ = parse_github(url)
    return store.ROOT / 'skills' / re.sub(r'[^A-Za-z0-9_.-]', '_', owner + '__' + repo)

def download_skill(url):
    owner, repo, parts = parse_github(url)
    base = store.ROOT / 'skills'; base.mkdir(exist_ok=True)
    name = re.sub(r'[^A-Za-z0-9_.-]', '_', owner + '__' + repo)
    target = github_destination(url)
    if target.exists(): raise ValueError('A tool with this destination already exists.')
    if len(parts) == 2:
        # Git controls redirects and never executes repository setup scripts during clone.
        with tempfile.TemporaryDirectory(prefix='.import-', dir=base) as staging:
            checkout = Path(staging) / 'checkout'
            result = subprocess.run(['git','clone','--depth','1','--',f'https://github.com/{owner}/{repo}.git',str(checkout)], capture_output=True, text=True, timeout=120)
            if result.returncode: raise ValueError('Clone failed: ' + result.stderr[:3000])
            version = subprocess.run(['git','-C',str(checkout),'rev-parse','HEAD'],capture_output=True,text=True,timeout=10).stdout.strip() or 'unknown'
            checkout.rename(target)
    else:
        # GitHub raw file endpoint: path components are individually encoded.
        raw = 'https://raw.githubusercontent.com/' + '/'.join(urllib.parse.quote(x, safe='') for x in [owner,repo,*parts[3:]])
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw): raise ValueError('Redirects are not allowed for file imports.')
        with urllib.request.build_opener(NoRedirect).open(raw, timeout=30) as response:
            data = response.read(5_000_001)
        if len(data) > 5_000_000: raise ValueError('File exceeds the 5 MB limit.')
        target.mkdir(); (target / parts[-1]).write_bytes(data)
        version = parts[3]
    store.execute('INSERT INTO skills(name,source,path,version) VALUES(?,?,?,?)',(name,url,str(target),version))
    return f'Downloaded to {target}; version {version}. Disabled until you enable it. No setup scripts were run.'

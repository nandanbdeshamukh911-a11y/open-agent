"""Discover and execute named project checks with explicit approval."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


OUTPUT_LIMIT = 24_000
MAX_CAPTURE = 12 * 1024 * 1024
TIMEOUT_SECONDS = 180
NPM_CHECKS = {'npm-test': 'test', 'npm-lint': 'lint', 'npm-build': 'build', 'npm-typecheck': 'typecheck'}


def manifest_exists(root, name):
    path = (root / name).resolve()
    return path.is_relative_to(root) and path.is_file()


def npm_scripts(root):
    if not manifest_exists(root, 'package.json'):
        return {}
    try:
        with (root / 'package.json').open('rb') as file:
            raw = file.read(512_001)
        if len(raw) <= 512_000:
            scripts = json.loads(raw).get('scripts', {})
            if isinstance(scripts, dict):
                return {name: script for name, script in scripts.items() if isinstance(script, str)}
    except (OSError, ValueError, AttributeError, RecursionError):
        pass
    return {}


def discover(root):
    manifests = [name for name in ('package.json', 'pyproject.toml', 'pytest.ini', 'setup.cfg',
                                     'requirements.txt', 'Cargo.toml', 'go.mod') if manifest_exists(root, name)]
    scripts = npm_scripts(root)
    available = [name for name, script in NPM_CHECKS.items() if script in scripts]
    if any(name in manifests for name in ('pyproject.toml', 'pytest.ini', 'setup.cfg', 'requirements.txt')):
        available += ['pytest', 'unittest']
    return {'directory': str(root), 'manifests': manifests, 'checks': available}


def recipe(root, name):
    if name in NPM_CHECKS:
        script = NPM_CHECKS[name]
        scripts = npm_scripts(root)
        if script not in scripts:
            raise ValueError(f'package.json does not define the {script} script in this directory.')
        executable = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not executable:
            raise ValueError('npm is unavailable on PATH.')
        return {'argv': [executable, 'run', script],
                'scripts': {name: scripts[name] for name in ('pre'+script, script, 'post'+script) if name in scripts}}
    if name == 'pytest':
        return {'argv': [sys.executable, '-m', 'pytest', '-q']}
    if name == 'unittest':
        return {'argv': [sys.executable, '-m', 'unittest', 'discover', '-v']}
    raise ValueError('Choose an available project check.')


def stop_check(process):
    if os.name == 'nt':
        utility = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
        try:
            subprocess.run([utility, '/PID', str(process.pid), '/T', '/F'],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def run_check(root, approval):
    current = recipe(root, approval['check'])
    if current != {field: approval[field] for field in ('argv', 'scripts') if field in approval}:
        raise ValueError('The check changed since it was proposed. Request a fresh approval.')
    started = time.monotonic()
    reason = ''
    with tempfile.TemporaryFile() as output:
        with subprocess.Popen(current['argv'], cwd=root, stdin=subprocess.DEVNULL, stdout=output,
                              stderr=subprocess.STDOUT, start_new_session=os.name != 'nt') as process:
            while process.poll() is None:
                if time.monotonic() - started > TIMEOUT_SECONDS:
                    reason = 'Stopped after reaching the time limit.'
                elif os.fstat(output.fileno()).st_size > MAX_CAPTURE:
                    reason = 'Stopped after reaching the capture limit.'
                if reason:
                    stop_check(process)
                    break
                time.sleep(.1)
            code = process.wait()
        captured_size = os.fstat(output.fileno()).st_size
        output.seek(max(0, captured_size - OUTPUT_LIMIT))
        transcript = output.read(OUTPUT_LIMIT).decode('utf-8', errors='replace').replace('\r\n', '\n')
    truncation = '[Only the end of the output is shown]\n' if captured_size > OUTPUT_LIMIT else ''
    exit_code = code if not reason else 124
    return f'Exit code: {exit_code}\nCheck: {approval["check"]}\nDuration: {time.monotonic() - started:.1f}s\n{reason}\n{truncation}{transcript}'

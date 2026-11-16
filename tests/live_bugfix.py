"""Real-model bugfix test with narrowly constrained approvals and disposable files."""
import ast
import json
import os
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
(root/'data').mkdir(exist_ok=True)

def safe_code(source):
    try:
        module = ast.parse(source)
        if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef): return False
        function = module.body[0]
        if (function.name != 'add' or function.decorator_list or function.returns or
            function.args.posonlyargs or function.args.kwonlyargs or function.args.vararg or
            function.args.kwarg or function.args.defaults or [a.arg for a in function.args.args] != ['a','b']): return False
        if len(function.body) != 1 or not isinstance(function.body[0], ast.Return): return False
        expr = function.body[0].value
        return (isinstance(expr, ast.BinOp) and isinstance(expr.op,(ast.Add,ast.Sub)) and
                isinstance(expr.left,ast.Name) and expr.left.id == 'a' and
                isinstance(expr.right,ast.Name) and expr.right.id == 'b')
    except (SyntaxError,ValueError): return False

with tempfile.TemporaryDirectory(prefix='open-agent-bugfix-',dir=root/'data') as tmp:
    base = Path(tmp); project = base/'project'; project.mkdir()
    (project/'calculator.py').write_text('def add(a, b):\n    return a - b\n',encoding='utf-8')
    (project/'test_calculator.py').write_text('import unittest\nfrom calculator import add\n\nclass AddTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\nif __name__ == "__main__":\n    unittest.main()\n',encoding='utf-8')
    os.environ['OPEN_AGENT_DATA'] = str(base/'state')
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend import agent
    client=TestClient(app,base_url='http://127.0.0.1:8765',headers={'X-Open-Agent':'local'})
    request=('Fix the bug in calculator.py. First run the existing unittest test_calculator.py to reproduce the failure, '
             'then edit only calculator.py, and run the same test again to verify the fix. '
             'Use exactly the command python -m unittest -v test_calculator for each test run. Do not download anything.')
    tid=client.post('/api/tasks',json={'request':request,'project':str(project)}).json()['id']
    deadline=time.monotonic()+1800; seen=set(); decisions=[]
    while time.monotonic()<deadline:
        task=client.get(f'/api/tasks/{tid}').json()
        for event in task['events']:
            if event['id'] not in seen:
                print(event['kind'],event['content'][:2000],flush=True); seen.add(event['id'])
        if task['status']=='waiting_approval':
            approval=next(a for a in task['approvals'] if a['status']=='pending'); args=json.loads(approval['args'])
            action=approval['action']
            safe=(action=='write_file' and args.get('path')=='calculator.py' and safe_code(args.get('content','')))
            safe |= (action=='command' and args.get('command')=='python -m unittest -v test_calculator' and safe_code((project/'calculator.py').read_text()))
            print('APPROVAL',action,args,'accepted' if safe else 'rejected',flush=True)
            decisions.append((action,args,safe)); client.post(f"/api/approvals/{approval['id']}/decide",json={'approved':safe}).raise_for_status()
        elif task['status'] in ('completed','blocked','cancelled','paused'):
            print('FINAL',task['status'],task['final'],flush=True)
            output=[json.loads(e['content'])['result'] for e in task['events'] if e['kind']=='tool' and json.loads(e['content']).get('action')=='command']
            print('COMMAND RESULTS',output,flush=True)
            assert task['status']=='completed'
            assert any(x.startswith('Exit code: 1') for x in output)
            assert any(x.startswith('Exit code: 0') for x in output)
            assert safe_code((project/'calculator.py').read_text()) and 'a + b' in (project/'calculator.py').read_text()
            break
        time.sleep(2)
    else: raise SystemExit('Timed out waiting for bugfix task')
    while tid in agent.workers: time.sleep(.05)

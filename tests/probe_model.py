"""Inspect public response metadata for the local model after a sample failing test."""
import json
import httpx

model='hf.co/unsloth/gpt-oss-20b-GGUF:Q4_K_M'
messages=[{'role':'system','content':'You are a coding agent. Return ONLY JSON. One action per response. Available actions: list_files {path}, read_file {path}, write_file {path,content}, command {command}, review { }.'},
          {'role':'user','content':'''User request: Fix calculator.py. First run test_calculator, then edit calculator.py and run tests again.
Recent evidence: tool: {"action":"command","args":{"command":"python -m unittest -v test_calculator"},"result":"Exit code: 1\nFAILED: AssertionError: -1 != 5"}
Choose the next small action. Return {"action":"one of the available actions", "args":{}, "reason":"why"}.'''}]
payload={'model':model,'messages':messages,'temperature':0.2,'max_tokens':4096,'response_format':{'type':'json_object'},'reasoning_effort':'low'}
response=httpx.post('http://127.0.0.1:11434/v1/chat/completions',json=payload,timeout=600,trust_env=False)
response.raise_for_status(); data=response.json(); choice=data['choices'][0]; message=choice['message']
print(json.dumps({'finish_reason':choice.get('finish_reason'),'usage':data.get('usage'),'message_keys':list(message),'content':message.get('content'),'tool_calls':message.get('tool_calls')}),flush=True)

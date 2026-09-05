"""One paid Luna tool-call compatibility check, not a team experiment."""
import json
import os
from datetime import datetime, timezone

from dotenv import dotenv_values
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import tool

from .model_config import MODEL, COST, generation_config, pricing_snapshot
from .run import ROOT, save, key_usage


@tool
def list_files():
    async def execute() -> str:
        """List the text files in the shared /workspace directory."""
        return '["hello.txt"]'
    return execute


def main():
    os.environ['OPENROUTER_API_KEY'] = dotenv_values(ROOT/'.env')['OPENROUTER_API_KEY']
    price = pricing_snapshot()
    before = key_usage()
    if before['limit_remaining'] is None or before['limit_remaining'] < 10:
        raise RuntimeError('Cannot reserve an existing $9 batch plus $1 for validation')
    folder = ROOT/'number_sequence/preflight'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True)
    config = generation_config(1)
    logs = eval(Task(name='luna_files_tool_preflight',
                     dataset=[Sample(input='Call list_files now to inspect the shared directory. Do not answer in prose.')],
                     solver=[use_tools([list_files()]),generate(tool_calls='single')],
                     config=config, time_limit=90, cost_limit=.01), model=MODEL,
                log_dir=str(ROOT),log_realtime=True,log_buffer=1,display='none',model_cost_config={MODEL:COST})
    sample = logs[0].samples[0]
    events = [e for e in sample.events if e.event == 'tool']
    errors = [str(e.error) for e in sample.events if e.event == 'model' and e.error]
    passed = not sample.error and len(events)==1 and events[0].function=='list_files' and not events[0].error
    cost = sum(u.total_cost or 0 for u in logs[0].stats.model_usage.values())
    result = {'model':MODEL,'passed':passed,'eval':logs[0].location,'model_errors':errors,
              'cost_estimate_upper_usd':cost if logs[0].stats.model_usage else None,
              'pricing':price,'config':config.model_dump(mode='json')}
    save(folder/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('pricing','config')},indent=2),flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

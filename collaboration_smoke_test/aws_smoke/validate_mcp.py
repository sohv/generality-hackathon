"""Validate concurrent MCP file access without any model calls or AWS changes."""
import argparse
import asyncio
import json
from tempfile import mkdtemp
from pathlib import Path

from inspect_ai.tool import ToolDef, mcp_connection
from .common import BASE, cleanup, connection, create, freeze

async def validate(context, directory, cid):
    async def person(name):
        server = connection(context, cid, directory, name)
        async with mcp_connection(server):
            tools = {ToolDef(t).name: t for t in await server.tools()}
            assert set(tools) == {"read_file", "write_file", "list_files"}
            await tools["write_file"](name=name+".txt", text=name+"\n")
            result = await tools["read_file"](name=name+".txt")
            assert name in str(result)
            return sorted(tools)
    results = await asyncio.gather(*(person(n) for n in ("Ada", "Bruno", "Cleo")))
    server = connection(context, cid, directory, "validator")
    async with mcp_connection(server):
        tools = {ToolDef(t).name: t for t in await server.tools()}
        await tools["write_file"](name="names.txt", text="Ada\nBruno\nCleo\n")
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default="desktop-linux")
    args = parser.parse_args()
    (BASE / "runs").mkdir(exist_ok=True)
    directory = Path(mkdtemp(prefix="transport-validation-", dir=BASE / "runs"))
    cid = create(args.context, directory)
    try:
        tools = asyncio.run(validate(args.context, directory, cid))
        content = freeze(args.context, cid, directory)
        assert content == "Ada\nBruno\nCleo\n"
        report = {"passed": True, "context": args.context, "container": cid,
                  "clients": 3, "model_calls": 0, "tool_schemas": tools,
                  "content": content, "scope": "MCP transport validation, not a model collaboration result"}
        (directory / "result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        print(directory)
    finally:
        cleanup(args.context, cid)

if __name__ == "__main__":
    main()

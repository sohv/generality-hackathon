"""A names-demo MCP server bound to one Docker container, local or over SSH.

Only UTF-8 .txt file operations are exposed. Docker administration and arbitrary
shell execution are not tools. Connection details and attribution stay local.
"""
import argparse
import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# This fixed program runs inside the container. Model text is JSON on stdin,
# never shell source or a Python expression. Restrict access to flat text files.
FILE_PROGRAM = r'''
import json, os, re, sys, tempfile
from pathlib import Path
d=json.load(sys.stdin)
root=Path('/workspace')
root.mkdir(exist_ok=True)
if d['op']=='list':
    print(json.dumps(sorted(p.name for p in root.glob('*.txt') if p.is_file() and not p.is_symlink())))
else:
    name=d['name']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.txt',name):
        raise ValueError('Use a flat filename ending in .txt')
    p=root/name
    if p.is_symlink():
        raise ValueError('Symlinks are not supported')
    if d['op']=='read':
        print(json.dumps({'text':p.read_text()}))
    elif d['op']=='write':
        text=d['text']
        if len(text.encode())>16384:
            raise ValueError('Text must be at most 16384 bytes')
        fd,tmp=tempfile.mkstemp(dir=root)
        try:
            with os.fdopen(fd,'w') as f:f.write(text)
            os.replace(tmp,p)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        print(json.dumps({'written':name}))
    else:raise ValueError('Unsupported operation')
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    server = MCPServer("workspace-files", log_level="ERROR")

    async def operation(payload):
        proc = await asyncio.create_subprocess_exec(
            shutil.which("docker") or "/usr/local/bin/docker", "--context", args.context, "exec", "-i",
            args.container, "python", "-c", FILE_PROGRAM,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), 30)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        event = {"time": datetime.now(timezone.utc).isoformat(), "agent": args.label,
                 "operation": payload, "returncode": proc.returncode,
                 "stdout": stdout.decode()[:20000], "stderr": stderr.decode()[:2000]}
        with args.audit.open("a") as f:
            f.write(json.dumps(event)+"\n")
        if proc.returncode:
            raise ValueError(event["stderr"])
        return stdout.decode()

    @server.tool()
    async def list_files() -> str:
        """List the text files in /workspace."""
        return await operation({"op": "list"})

    @server.tool()
    async def read_file(name: str) -> str:
        """Read a .txt file in /workspace.

        Args:
            name: Filename, such as notes.txt.
        """
        return await operation({"op": "read", "name": name})

    @server.tool()
    async def write_file(name: str, text: str) -> str:
        """Create or replace a .txt file in /workspace with UTF-8 text.

        Args:
            name: Filename, such as notes.txt.
            text: Complete file contents, at most 16384 bytes.
        """
        return await operation({"op": "write", "name": name, "text": text})

    server.run(transport="stdio")

if __name__ == "__main__":
    main()

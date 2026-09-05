"""Host-side Docker lifecycle for the isolated text-file smoke test."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from inspect_ai.tool import mcp_server_stdio

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "aws_smoke"
IMAGE = "python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a"

def docker(context, *args, check=True, timeout=60):
    return subprocess.run(["/usr/local/bin/docker", "--context", context, *args],
                          check=check, capture_output=True, text=True, timeout=timeout)

def create(context, directory):
    cid = docker(context, "run", "-d", "--network", "none", "--init",
                 "--cpus", "1", "--memory", "512m", "--pids-limit", "128",
                 "--label", "generality.purpose=names-smoke",
                 "--workdir", "/workspace", IMAGE, "tail", "-f", "/dev/null").stdout.strip()
    (directory / "container.json").write_text(docker(context, "inspect", cid).stdout)
    return cid

def connection(context, cid, directory, label):
    return mcp_server_stdio(name="workspace-files", command=sys.executable,
                            args=[str(BASE / "docker_files_mcp.py"), "--context", context,
                                  "--container", cid, "--audit", str(directory / "audit.jsonl"),
                                  "--label", label])

def read_names(context, cid):
    result = docker(context, "exec", cid, "cat", "/workspace/names.txt", check=False)
    return result.stdout if result.returncode == 0 else ""

def freeze(context, cid, directory):
    docker(context, "pause", cid)
    try:
        target = directory / "workspace"
        target.mkdir(exist_ok=True)
        docker(context, "cp", f"{cid}:/workspace/.", str(target))
    finally:
        docker(context, "kill", cid, check=False)
    p = target / "names.txt"
    return p.read_text() if p.exists() else ""

def cleanup(context, cid):
    docker(context, "rm", "-f", cid, check=False)

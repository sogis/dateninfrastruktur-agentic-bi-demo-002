"""B15: local offline container, arbitrary UID, immutable bundle and real MCP."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, input=None, timeout=60):
    return subprocess.run(
        ["docker", *args],
        input=input,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=True,
    )


@pytest.mark.skipif(
    shutil.which("docker") is None, reason="B15 benötigt eine lokale Docker-Laufzeit"
)
def test_B15_nonprivileged_offline_container_readonly_real_mcp(bundle_dir):
    # Build uses the immutable base digest and frozen dependency lock. Runtime
    # itself is subsequently run with no network interface except loopback.
    docker("build", "--pull=false", "-t", "slayer-bi:acceptance", ".", timeout=120)
    name = "slayer-bi-test-" + uuid4().hex[:10]
    started = time.monotonic()
    try:
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "12345:0",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--cpus",
            "1",
            "--memory",
            "1g",
            "--tmpfs",
            "/work:rw,size=268435456,mode=1777",
            "--env",
            "HOME=/nonexistent",
            "--mount",
            f"type=bind,src={bundle_dir},dst=/bundle,readonly",
            "slayer-bi:acceptance",
        )
        script = r"""
import asyncio,json,os,time
from pathlib import Path
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
async def main():
    started=time.monotonic()
    async with httpx.AsyncClient() as http:
        for _ in range(200):
            try:
                health=await http.get('http://127.0.0.1:8000/healthz')
                ready=await http.get('http://127.0.0.1:8000/readyz')
                if health.status_code==ready.status_code==200:break
            except httpx.TransportError:pass
            await asyncio.sleep(.1)
        else:raise AssertionError('readiness deadline')
    readiness_seconds=time.monotonic()-started
    async with streamable_http_client('http://127.0.0.1:8000/mcp') as (read,write,_):
        async with ClientSession(read,write) as client:
            await client.initialize()
            tools=await client.list_tools()
            assert {t.name for t in tools.tools}=={'search','inspect','analyse'}
            source=await client.call_tool('inspect',{'model_id':'population_sex_nationality'})
            assert source.structuredContent['data']['status']=='quarantined'
            request={'period':{'from_year':2025,'to_year':2025},'outputs':[{'id':'ratio','expr':{'kind':'binary','op':'divide','scale':1000,'left':{'kind':'aggregate','metric':'vehicles.count','where':[{'field':'vehicles.category','op':'in','values':['01','60']}]},'right':{'kind':'aggregate','metric':'population.count'}}}]}
            began=time.monotonic()
            result=await client.call_tool('analyse',{'request':request})
            query_seconds=time.monotonic()-began
            envelope=result.structuredContent
            assert envelope['ok'],envelope
            assert abs(envelope['data']['rows'][0]['ratio']-649.6804637625776)<=1e-9
            assert any(n['code']=='SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN' for n in envelope['data']['notices'])
            assert json.loads(result.content[0].text)==envelope
    assert os.getuid()==12345
    caps=next(line.split(':',1)[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:'))
    assert int(caps,16)==0
    assert not os.access('/bundle/pilot.duckdb',os.W_OK)
    assert not Path('/nonexistent').exists()
    assert not list(Path('/work').glob('query-*'))
    peak=int(Path('/sys/fs/cgroup/memory.peak').read_text())
    print(json.dumps(dict(uid=os.getuid(),capabilities=caps,ready=True,quarantine=True,ratio=envelope['data']['rows'][0]['ratio'],readiness_seconds=readiness_seconds,query_seconds=query_seconds,memory_peak_bytes=peak)))
asyncio.run(main())
"""
        output = docker("exec", "-i", name, "python", "-", input=script, timeout=45)
        result = json.loads(output.stdout)
        assert result["memory_peak_bytes"] < 1024**3
        configuration = json.loads(docker("inspect", name).stdout)[0]
        assert configuration["HostConfig"]["NetworkMode"] == "none"
        assert configuration["HostConfig"]["ReadonlyRootfs"] is True
        docker("stop", "-t", "5", name, timeout=10)
        state = json.loads(docker("inspect", name).stdout)[0]["State"]
        assert state["ExitCode"] == 0 and not state["OOMKilled"], state
        log = docker("logs", name)
        events = [
            json.loads(line) for line in log.stdout.splitlines() if line.startswith("{")
        ]
        assert any(e["event"] == "analysis_complete" and e["ok"] for e in events)
        result.update(
            image_id=configuration["Image"],
            elapsed_seconds=time.monotonic() - started,
            base_image="python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f",
            network="none",
            read_only=True,
            cpu_limit=1,
            memory_limit_bytes=1024**3,
            work_limit_bytes=256 * 1024**2,
            exit_code=state["ExitCode"],
        )
        (ROOT / "build").mkdir(exist_ok=True)
        (ROOT / "build/container-acceptance.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

"""Independent experiment owner with authenticated, per-job local control.

Private control metadata is never returned through job tools. No saved process ID is
used to cancel a job; only the authenticated owner may stop its live child process.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import socket
from contextlib import contextmanager
from pathlib import Path

from research_cli.storage import encode

MAX_MESSAGE = 1_000_000


def signed(token: str, body: dict) -> str:
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hmac.new(token.encode(), data, hashlib.sha256).hexdigest()


def control_path(store, job_id: str) -> Path:
    return store.root / "jobs" / job_id / "control.json"


def load_control(store, job_id: str) -> dict:
    path = control_path(store, job_id)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 10000
        or path.stat().st_uid != os.getuid()
        or path.stat().st_mode & 0o077
    ):
        raise ValueError("No private worker control metadata")
    control = json.loads(path.read_text())
    if control.get("job_id") != job_id or len(control.get("token", "")) != 64:
        raise ValueError("Invalid worker control metadata")
    return control


def create_control(store, job_id: str) -> dict:
    # macOS Unix socket paths are short; never place sockets under a long project path.
    directory = Path("/tmp").resolve() / f"research-workers-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise ValueError("Worker socket directory must be private and owned by this user")
    if directory.stat().st_mode & 0o077:
        raise ValueError("Worker socket directory permissions must be 0700")
    identity = secrets.token_hex(16)
    control = {
        "job_id": job_id,
        "identity": identity,
        "token": secrets.token_hex(32),
        "socket": str(directory / f"{job_id}-{identity[:12]}.sock"),
    }
    # Exclusion prevents a new owner from silently replacing existing credentials.
    descriptor = os.open(control_path(store, job_id), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(encode(control))
    return control


def worker_request(store, job_id: str, action="status", timeout=1.0) -> dict:
    control = load_control(store, job_id)
    challenge = secrets.token_hex(16)
    body = {
        "job_id": job_id,
        "identity": control["identity"],
        "action": action,
        "challenge": challenge,
    }
    request = {"body": body, "signature": signed(control["token"], body)}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(control["socket"])
        client.sendall(encode(request).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(16384)
            if not chunk:
                raise ValueError("Worker disconnected before authenticated response")
            response.extend(chunk)
            if len(response) > MAX_MESSAGE:
                raise ValueError("Worker response exceeds size limit")
    message = json.loads(bytes(response).split(b"\n", 1)[0])
    result = message.get("body", {})
    if (
        not hmac.compare_digest(message.get("signature", ""), signed(control["token"], result))
        or result.get("job_id") != job_id
        or result.get("identity") != control["identity"]
        or result.get("challenge") != challenge
        or result.get("action") != action
    ):
        raise ValueError("Worker identity verification failed")
    if result.get("error"):
        raise ValueError(result["error"])
    return result["job"]


@contextmanager
def worker_lock(store, job_id: str):
    import fcntl

    path = store.root / "jobs" / job_id / "worker.lock"
    if path.is_symlink():
        raise ValueError("Worker lock may not be a symlink")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a+") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another worker owns this experiment") from exc
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


async def own_job(workspace: Path, job_id: str):
    from research_cli.config import Settings
    from research_cli.jobs import Jobs
    from research_cli.storage import Store
    from research_cli.tools import Registry

    store = Store(workspace)
    jobs = None
    server = None
    control = None
    claimed = False
    clients = set()
    ready = asyncio.Event()
    try:
        with worker_lock(store, job_id):
            claimed = True
            control = load_control(store, job_id)
            record = store.get("jobs", job_id)
            if (
                not record.get("detached")
                or record.get("worker_claimed")
                or record["status"] not in {"starting", "interrupted_unknown"}
            ):
                raise ValueError("Worker can only claim its reserved detached starting job")
            record["worker_claimed"] = True
            store.put("jobs", job_id, record)
            settings = Settings.model_validate(record["worker_settings"])
            jobs = Jobs(Registry(store, settings), recover=False)

            async def handle(reader, writer):
                task = asyncio.current_task()
                clients.add(task)
                try:
                    data = await asyncio.wait_for(reader.readline(), 3)
                    if len(data) > MAX_MESSAGE:
                        raise ValueError("Worker request exceeds size limit")
                    request = json.loads(data)
                    body = request.get("body", {})
                    if (
                        not hmac.compare_digest(
                            request.get("signature", ""), signed(control["token"], body)
                        )
                        or body.get("job_id") != job_id
                        or body.get("identity") != control["identity"]
                        or body.get("action") not in {"status", "cancel"}
                        or not isinstance(body.get("challenge"), str)
                        or len(body["challenge"]) != 32
                    ):
                        raise ValueError("Invalid worker authorization")
                    if body["action"] == "cancel":
                        await asyncio.wait_for(ready.wait(), 5)
                    observed = store.get("jobs", job_id)
                    if job_id in jobs.running and observed["status"] == "interrupted_unknown":
                        observed.update(
                            status="running",
                            detail="Authenticated owner reattached to its live child",
                        )
                        store.put("jobs", job_id, observed)
                    response = {
                        **body,
                        "job": (
                            await jobs.cancel({"job_id": job_id})
                            if body["action"] == "cancel"
                            else store.get("jobs", job_id)
                        ),
                    }
                    writer.write(
                        encode(
                            {"body": response, "signature": signed(control["token"], response)}
                        ).encode()
                        + b"\n"
                    )
                    await asyncio.wait_for(writer.drain(), 5)
                except (ValueError, TypeError, OSError, asyncio.TimeoutError):
                    # Unauthenticated requests get no informative response or process control.
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()
                    clients.discard(task)

            server = await asyncio.start_unix_server(
                handle, path=control["socket"], limit=MAX_MESSAGE
            )
            os.chmod(control["socket"], 0o600)
            await jobs._spawn_job(record)
            ready.set()
            await jobs.tasks[job_id]
    except BaseException as exc:
        try:
            record = store.get("jobs", job_id)
            if claimed and record["status"] == "starting":
                record.update(
                    status="failed", detail=f"Detached worker could not start: {type(exc).__name__}"
                )
                store.put("jobs", job_id, record)
        except ValueError:
            pass
        raise
    finally:
        if jobs:
            await jobs.close()
        if server:
            server.close()
            await server.wait_closed()
        if clients:
            await asyncio.gather(*clients, return_exceptions=True)
        if control:
            Path(control["socket"]).unlink(missing_ok=True)
        store.close()


def main():
    parser = argparse.ArgumentParser(description="Private detached experiment owner")
    parser.add_argument("workspace", type=Path)
    parser.add_argument("job_id")
    args = parser.parse_args()
    asyncio.run(own_job(args.workspace, args.job_id))


if __name__ == "__main__":
    main()

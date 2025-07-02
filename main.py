from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import uuid
import os

from config import settings

app = FastAPI()
tasks = {}

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

git_user = settings.GIT_USER
git_password = settings.GIT_PASSWORD
git_url = settings.GIT_URL
ansible_dir= settings.ANSIBLE_DIR

class HostItem(BaseModel):
    serverIP: str

class PlaybookRequest(BaseModel):
    playbook: str
    hosts: list[HostItem]
    options: list[str] = []


async def run_playbook_async(ident, playbook_path, inventory_path, options: list[str]):

    tasks[ident] = {"process": None, "logs": []}

    init_cmds = ["git", "pull", f"https://{git_user}:{git_password}@{git_url}", "main"]

    proc = await asyncio.create_subprocess_exec(
        *init_cmds,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{stderr.decode()}")

    cmd = [
        "ansible-playbook",
        playbook_path,
        "-i", inventory_path,
        "-e", f"ansible_user={settings.ANSIBLE_USER} ansible_password={settings.ANSIBLE_PWD}"
    ]

    if 'debug' in options:
        cmd.append("-v")
    if 'dry-run' in options:
        cmd.append("--check")
    if 'check' in options:
        cmd.append("--diff")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        tasks[ident]["process"] = process

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            tasks[ident]["logs"].append(line.decode())

        await process.wait()
        tasks[ident]["returncode"] = process.returncode

    except Exception as e:
        print(f"Error during playbook execution: {e}")


@app.get("/health")
def health():
    return "200ok"

@app.post("/run")
async def run_playbook(request: PlaybookRequest):

    playbook_path = os.path.join(request.playbook)

    if not os.path.isfile(playbook_path):
        raise HTTPException(status_code=404, detail=f"Playbook not found {playbook_path}")

    ident = str(uuid.uuid4())

    inventory_content = "\n".join([host.serverIP for host in request.hosts])
    inventory_path = os.path.join("inventory", f"{ident}_inventory.ini")
    with open(inventory_path, "w") as f:
        f.write("[targets]\n")
        f.write(inventory_content)

    asyncio.create_task(run_playbook_async(
        ident,
        playbook_path,
        inventory_path,
        request.options
    ))
    return {"ident": ident}

@app.websocket("/ws/log/{ident}")
async def websocket_logs(websocket: WebSocket, ident: str):
    await websocket.accept()

    if ident not in tasks:
        await websocket.send_text("Execution ID not found")
        await websocket.close()
        return

    last_idx = 0
    try:
        while True:
            logs = tasks[ident]["logs"]
            new_logs = logs[last_idx:]
            for line in new_logs:
                await websocket.send_text(line)
            last_idx += len(new_logs)

            if "returncode" in tasks[ident]:
                await websocket.send_text(f"Process exited with code {tasks[ident]['returncode']}")
                await websocket.close()

                try:
                    inventory_path = os.path.join("inventory", f"{ident}_inventory.ini")
                    if os.path.isfile(inventory_path):
                        os.remove(inventory_path)
                except Exception as e:
                    print(f"Failed to delete inventory file {inventory_path}: {e}")

                if ident in tasks:
                    del tasks[ident]

                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        print(f"WebSocket disconnected for {ident}")

@app.delete("/remove/{ident}")
def delete_ident(ident: str):
    if ident not in tasks:
        raise HTTPException(status_code=404, detail="Execution ID not found")

    proc = tasks[ident].get("process")
    if proc and proc.returncode is None:
        proc.kill()

    del tasks[ident]
    return {"message": f"Execution {ident} logs and process removed successfully."}
import asyncio
import json
import os
import shlex
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from loguru import logger

from toolarena.definition import ToolDefinition
from toolarena.run import ToolResult
from toolarena.utils import stream_reader_to_str_stream

RUNTIME_DIR = Path(os.getenv("WORKSPACE_DIR", "/workspace"))
TOOLARENA_DIR = Path(os.getenv("TOOLARENA_DIR", "/toolarena"))
IMPLEMENTATION_PATH = RUNTIME_DIR / "implementation.py"
TASK_DEFINITION_PATH = RUNTIME_DIR / "task.yaml"
FUNCTION_RUNNER_PATH = TOOLARENA_DIR / "function_runner.py"

app = FastAPI()

task_definition = ToolDefinition.from_yaml(TASK_DEFINITION_PATH)


@app.get("/info")
async def info():
    return task_definition


@app.get("/alive")
async def alive():
    return {"status": "ok"}


async def run(args: task_definition.args_to_pydantic()) -> ToolResult:  # type: ignore
    function_name = task_definition.name
    logger.info(f"Running {function_name} with args: {args}")
    id = uuid4()
    info_path = Path(f"/tmp/{id}_info.json")
    output_path = Path(f"/tmp/{id}_output.json")
    json.dump(
        {
            "path": str(IMPLEMENTATION_PATH.absolute()),
            "name": function_name,
            "args": args.model_dump(),  # type: ignore
            "output_path": str(output_path.absolute()),
        },
        open(info_path, "w"),
    )
    process = await asyncio.create_subprocess_shell(
        shlex.join(
            [
                "python",
                str(FUNCTION_RUNNER_PATH.absolute()),
                str(info_path.absolute()),
            ]
        ),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        text=False,
        cwd="/workspace",
        env=os.environ,
        start_new_session=True,  # this is to make sure an error is thrown if the command attempts to read from stdin
    )

    stdout = ""
    async for chunk in stream_reader_to_str_stream(process.stdout):
        stdout += chunk
        print(chunk, end="")
    return_code = await process.wait()
    response = ToolResult(
        return_code=return_code,
        result=json.loads(output_path.read_text())["result"]
        if output_path.exists()
        else None,
        stdout=stdout,
    )
    for file in (info_path, output_path):
        file.unlink(missing_ok=True)

    return response


app.post("/run", description=task_definition.description)(run)
app.post(f"/{task_definition.name}", description=task_definition.description)(run)

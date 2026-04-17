import base64
import asyncio
import os
import random
import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

app = typer.Typer()

KEY_FILE = Path.cwd() / '.webui_secret_key'


def ensure_webui_secret_key() -> None:
    if os.getenv('WEBUI_SECRET_KEY') is not None:
        return

    typer.echo('Loading WEBUI_SECRET_KEY from file, not provided as an environment variable.')
    if not KEY_FILE.exists():
        typer.echo(f'Generating a new secret key and saving it to {KEY_FILE}')
        KEY_FILE.write_bytes(base64.b64encode(random.randbytes(12)))
    typer.echo(f'Loading WEBUI_SECRET_KEY from {KEY_FILE}')
    os.environ['WEBUI_SECRET_KEY'] = KEY_FILE.read_text()


def version_callback(value: bool) -> None:
    if value:
        from open_webui.env import VERSION

        typer.echo(f'Open WebUI version: {VERSION}')
        raise typer.Exit()


@app.command()
def main(
    version: Annotated[bool | None, typer.Option('--version', callback=version_callback)] = None,
):
    pass


@app.command()
def serve(
    host: str = '0.0.0.0',
    port: int = 8080,
):
    os.environ['FROM_INIT_PY'] = 'true'
    ensure_webui_secret_key()

    if os.getenv('USE_CUDA_DOCKER', 'false') == 'true':
        typer.echo('CUDA is enabled, appending LD_LIBRARY_PATH to include torch/cudnn & cublas libraries.')
        LD_LIBRARY_PATH = os.getenv('LD_LIBRARY_PATH', '').split(':')
        os.environ['LD_LIBRARY_PATH'] = ':'.join(
            LD_LIBRARY_PATH
            + [
                '/usr/local/lib/python3.11/site-packages/torch/lib',
                '/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib',
            ]
        )
        try:
            import torch

            assert torch.cuda.is_available(), 'CUDA not available'
            typer.echo('CUDA seems to be working')
        except Exception as e:
            typer.echo(
                'Error when testing CUDA but USE_CUDA_DOCKER is true. '
                'Resetting USE_CUDA_DOCKER to false and removing '
                f'LD_LIBRARY_PATH modifications: {e}'
            )
            os.environ['USE_CUDA_DOCKER'] = 'false'
            os.environ['LD_LIBRARY_PATH'] = ':'.join(LD_LIBRARY_PATH)

    import open_webui.main  # noqa: F401
    from open_webui.env import UVICORN_WORKERS  # Import the workers setting

    uvicorn.run(
        'open_webui.main:app',
        host=host,
        port=port,
        forwarded_allow_ips='*',
        workers=UVICORN_WORKERS,
    )


@app.command()
def dev(
    host: str = '0.0.0.0',
    port: int = 8080,
    reload: bool = True,
):
    uvicorn.run(
        'open_webui.main:app',
        host=host,
        port=port,
        reload=reload,
        forwarded_allow_ips='*',
    )


@app.command(name='retrieval-worker')
def retrieval_worker():
    os.environ['FROM_INIT_PY'] = 'true'
    os.environ['WORKER_ONLY_MODE'] = 'true'
    os.environ.setdefault('RETRIEVAL_TRANSPORT', 'jetstream')
    os.environ.setdefault('ENABLE_EMBEDDED_RETRIEVAL_WORKER', 'true')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    ensure_webui_secret_key()

    async def _run():
        import open_webui.main

        app_instance = open_webui.main.app
        async with app_instance.router.lifespan_context(app_instance):
            if getattr(app_instance.state, 'retrieval_worker', None) is None:
                raise RuntimeError('Retrieval worker failed to start in worker-only mode.')

            while True:
                await asyncio.sleep(3600)

    asyncio.run(_run())


if __name__ == '__main__':
    app()

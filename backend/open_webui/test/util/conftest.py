import os
from pathlib import Path


def _ensure_retrieval_test_data_dir() -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    data_dir = backend_dir / 'data'

    os.environ.setdefault('DATA_DIR', str(data_dir))
    data_dir.mkdir(parents=True, exist_ok=True)
    for relative in ('cache', 'uploads', 'vector_db'):
        (data_dir / relative).mkdir(parents=True, exist_ok=True)


_ensure_retrieval_test_data_dir()

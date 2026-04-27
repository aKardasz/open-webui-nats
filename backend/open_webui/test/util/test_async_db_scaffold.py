import pytest

from open_webui.internal.db import (
    ASYNC_SQLALCHEMY_DATABASE_URL,
    AsyncSessionLocal,
    _derive_async_database_url,
    get_async_db_context,
)


def test_derive_async_database_url_maps_supported_sync_urls():
    assert _derive_async_database_url('sqlite:///tmp/test.db') == 'sqlite+aiosqlite:///tmp/test.db'
    assert (
        _derive_async_database_url('postgresql://user:pass@localhost/db')
        == 'postgresql+asyncpg://user:pass@localhost/db'
    )
    assert _derive_async_database_url('sqlite+sqlcipher:///tmp/test.db') is None


def test_async_db_scaffold_exposes_async_session_factory_for_supported_repo_url():
    assert ASYNC_SQLALCHEMY_DATABASE_URL is not None
    assert AsyncSessionLocal is None or callable(AsyncSessionLocal)


@pytest.mark.asyncio
async def test_get_async_db_context_yields_async_session():
    if AsyncSessionLocal is None:
        with pytest.raises(RuntimeError):
            async with get_async_db_context():
                pass
        return

    async with get_async_db_context() as session:
        assert session is not None

import asyncio

import pytest


@pytest.fixture
def event_loop():
    """Provide a current event loop for sync tests that schedule coroutines
    (e.g. via asyncio.ensure_future) outside of a running loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    asyncio.set_event_loop(None)
    loop.close()


@pytest.fixture(autouse=True)
def verify_cleanup(event_loop: asyncio.AbstractEventLoop):
    """Verify that the test has cleaned up resources correctly."""
    tasks_before = asyncio.all_tasks(event_loop)
    yield
    tasks = asyncio.all_tasks(event_loop) - tasks_before
    if tasks:
        event_loop.run_until_complete(asyncio.wait(tasks))

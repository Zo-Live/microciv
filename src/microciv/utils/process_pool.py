"""Process pool shutdown helpers."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import Future
from time import monotonic
from typing import Any


def shutdown_process_pool_now(
    executor: object,
    futures: Iterable[Future[Any]] = (),
    *,
    kill_timeout_seconds: float = 0.5,
) -> None:
    """Cancel pending futures and stop ProcessPoolExecutor workers without waiting for tasks."""
    for future in tuple(futures):
        future.cancel()

    terminate_workers = getattr(executor, "terminate_workers", None)
    if callable(terminate_workers):
        terminate_workers()
        return

    processes = _executor_processes(executor)
    shutdown = getattr(executor, "shutdown", None)
    if callable(shutdown):
        try:
            shutdown(wait=False, cancel_futures=True)
        except TypeError:
            shutdown(wait=False)

    for process in processes:
        if _process_is_alive(process):
            process.terminate()

    deadline = monotonic() + kill_timeout_seconds
    for process in processes:
        remaining = max(0.0, deadline - monotonic())
        _join_process(process, remaining)

    for process in processes:
        if not _process_is_alive(process):
            continue
        kill = getattr(process, "kill", None)
        if callable(kill):
            kill()
        else:
            process.terminate()
        _join_process(process, 0.0)


def shutdown_process_pool_gracefully(executor: object) -> None:
    """Shut down a process pool normally when the executor supports it."""
    shutdown = getattr(executor, "shutdown", None)
    if callable(shutdown):
        shutdown()


def _executor_processes(executor: object) -> tuple[Any, ...]:
    processes = getattr(executor, "_processes", None)
    if not processes:
        return ()
    if isinstance(processes, dict):
        return tuple(processes.values())
    return tuple(processes)


def _process_is_alive(process: object) -> bool:
    is_alive = getattr(process, "is_alive", None)
    return bool(is_alive()) if callable(is_alive) else False


def _join_process(process: object, timeout: float) -> None:
    join = getattr(process, "join", None)
    if callable(join):
        join(timeout)

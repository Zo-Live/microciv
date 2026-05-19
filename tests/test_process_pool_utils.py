from __future__ import annotations

from concurrent.futures import Future

from microciv.utils.process_pool import shutdown_process_pool_now


class _FakeProcess:
    def __init__(self) -> None:
        self.terminate_calls = 0
        self.kill_calls = 0
        self.join_timeouts: list[float] = []
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.alive = False

    def join(self, timeout: float) -> None:
        self.join_timeouts.append(timeout)


class _FakeExecutor:
    def __init__(self, process: _FakeProcess) -> None:
        self._processes = {123: process}
        self.shutdown_calls: list[dict[str, object]] = []

    def shutdown(self, **kwargs: object) -> None:
        self.shutdown_calls.append(kwargs)


def test_shutdown_process_pool_now_cancels_futures_and_kills_stubborn_workers() -> None:
    future: Future[object] = Future()
    process = _FakeProcess()
    executor = _FakeExecutor(process)

    shutdown_process_pool_now(executor, [future], kill_timeout_seconds=0.0)

    assert future.cancelled()
    assert executor.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.join_timeouts

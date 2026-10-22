from __future__ import annotations

import asyncio
import multiprocessing as mp
import hashlib
import json
from queue import Empty
from time import monotonic
from uuid import uuid4

from travel.provider import TravelFailure
from travel.schemas import Draft, Error, Itinerary, Task, now
from travel.store import Store
from travel.worker import run
from travel.limits import BusinessLimits, rejected

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


class TaskManager:
    """Single API process, bounded spawned workers; SQLite persists all results."""
    def __init__(self, store: Store, timeout: float = 180, concurrency: int = 2, capacity: int = 10):
        self.store, self.timeout, self.capacity = store, timeout, capacity
        self.limits = BusinessLimits(store)
        self.slots = asyncio.Semaphore(concurrency)
        self.runners: dict[str, asyncio.Task] = {}
        self.processes = {}
        for task in store.tasks():
            if task.status not in TERMINAL:
                self.finish(task.id, "failed", Error(code="service_restarted", message="服务已重启，未完成任务请重新提交", retryable=True))

    def create(self, payload: dict, idempotency_key: str | None = None, retry_of: str | None = None, *, owner_id: str = 'local') -> Task:
        if payload.get("kind", "plan") == "plan" and isinstance(payload.get("request"), dict):
            # Preserve pre-anchor receipts: absent and null new options are identical.
            request = dict(payload["request"])
            for field in ("day_origin_poi_id", "day_destination_poi_id"):
                if request.get(field) is None:
                    request.pop(field, None)
            payload = {**payload, "request": request}
        fingerprint = hashlib.sha256(json.dumps({"payload":payload,"retry_of":retry_of},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        existing = self.store.submission(idempotency_key, fingerprint,owner_id=owner_id) if idempotency_key else None
        if existing:
            return existing
        if len(self.runners) >= self.capacity:
            raise rejected('queue_full', '规划队列已满', 2)
        task = Task(id=uuid4().hex, status="queued", kind=payload.get("kind", "plan"), retry_of=retry_of)
        task, created = self.store.register_task(task, payload, idempotency_key, fingerprint,owner_id=owner_id, admit=self.limits.admit_task)
        if not created:
            return task
        self.store.event(task.id, "queued", "任务已进入需求解析队列" if task.kind == "draft" else "任务已进入真实规划队列")
        runner = asyncio.create_task(self.execute(task.id, payload))
        self.runners[task.id] = runner
        runner.add_done_callback(lambda _: self.runners.pop(task.id, None))
        return task

    def retry(self, task_id: str, idempotency_key: str | None = None, *, owner_id: str = 'local') -> Task:
        task = self.store.task(task_id,owner_id=owner_id)
        if task is None:
            raise TravelFailure("task_not_found", "任务不存在", status=404)
        if task.status not in {"failed", "timed_out", "cancelled"} or not task.retry_available:
            raise TravelFailure("task_not_retryable", "该任务不能直接重试，请核对配置或修改条件后重新提交", status=409)
        payload = self.store.task_request(task_id)
        if payload is None:
            raise TravelFailure("retry_unavailable", "历史任务未保存请求条件，请重新填写表单", status=409)
        return self.create(payload, idempotency_key, retry_of=task_id,owner_id=owner_id)

    def finish(self, task_id: str, status: str, error: Error | None = None):
        task = self.store.task(task_id)
        if task is None or task.status in TERMINAL:
            return
        task.status, task.error, task.updated_at = status, error, now()
        task.retry_available = self.store.task_request(task_id) is not None and (status == "cancelled" or bool(error and error.retryable))
        self.store.put_task(task)
        self.store.event(task_id, status, error.message if error else "任务已取消")

    async def execute(self, task_id: str, payload: dict):
        process, channel = None, None
        try:
            # Deadline includes queue time, not just active worker time.
            async with asyncio.timeout(min(self.timeout, 45) if payload.get("kind") == "draft" else self.timeout):
                async with self.slots:
                    task = self.store.task(task_id)
                    if task.status in TERMINAL:
                        return
                    task.status, task.updated_at = "running", now()
                    self.store.put_task(task)
                    self.store.event(task_id, "running", "工作进程已启动")
                    context = mp.get_context("spawn")
                    channel = context.Queue()
                    process = context.Process(target=run, args=(payload, channel), daemon=True)
                    process.start()
                    self.processes[task_id] = process
                    exited_at = None
                    while True:
                        try:
                            item = channel.get_nowait()
                        except Empty:
                            if not process.is_alive():
                                exited_at = exited_at or monotonic()
                                if monotonic() - exited_at > 0.5:
                                    self.finish(task_id, "failed", Error(code="worker_exited", message="规划进程意外退出", retryable=True))
                                    return
                            await asyncio.sleep(0.1)
                            continue
                        if item["kind"] == "event":
                            self.store.event(task_id, item["stage"], item["message"])
                        elif item["kind"] == "error":
                            self.finish(task_id, "failed", Error.model_validate(item["data"]))
                            return
                        elif item["kind"] == "result":
                            current = self.store.task(task_id)
                            if current.status not in TERMINAL:
                                if current.kind == "draft":
                                    self.store.succeed_draft(current, Draft.model_validate(item["data"]))
                                    self.store.event(task_id, "succeeded", "需求草案已保存，等待核对表单")
                                else:
                                    self.store.succeed(current, Itinerary.model_validate(item["data"]))
                                    self.store.event(task_id, "succeeded", "行程已保存")
                            return
        except TimeoutError:
            message = "需求解析超过总时限，请重试或直接填写表单" if payload.get("kind") == "draft" else "任务超过总时限，请减少天数或站数"
            self.finish(task_id, "timed_out", Error(code="task_timeout", message=message, retryable=True))
        except asyncio.CancelledError:
            self.finish(task_id, "cancelled")
        except Exception:
            self.finish(task_id, "failed", Error(code="task_failed", message="任务服务执行失败", retryable=True))
        finally:
            if process is not None:
                if process.is_alive():
                    process.terminate()
                await asyncio.to_thread(process.join, 3)
                if process.is_alive():
                    process.kill()
                    await asyncio.to_thread(process.join, 1)
                process.close()
            self.processes.pop(task_id, None)
            if channel is not None:
                channel.close()

    def cancel(self, task_id: str) -> Task:
        current = self.store.task(task_id)
        if current is not None and current.status in TERMINAL:
            return current
        self.finish(task_id, "cancelled")
        runner = self.runners.get(task_id)
        if runner:
            runner.cancel()
        return self.store.task(task_id)

    async def close(self):
        runners = list(self.runners.values())
        for runner in runners:
            runner.cancel()
        await asyncio.gather(*runners, return_exceptions=True)

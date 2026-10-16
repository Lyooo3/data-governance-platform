import asyncio
import json
import sys
import uuid
from . import config
from .engine import validate
from .storage import now


class Jobs:
    def __init__(self, store):
        self.store, self.tasks = store, {}

    def start(self, workflow, actor, task_id=None):
        validate(workflow)
        if len(self.tasks) >= 2:
            raise ValueError("已有两个任务运行，请稍后执行")
        run = {
            "id": str(uuid.uuid4()),
            "workflowId": workflow.get("id"),
            "taskId": task_id,
            "name": workflow["name"],
            "status": "RUNNING",
            "startedAt": now(),
            "actor": actor,
            "steps": [],
            "reports": [],
            "rows": [],
        }
        self.store.save_run(run)
        payload = {
            "workflow": workflow,
            "datasets": {d["id"]: d for d in self.store.all("datasets")},
            "rules": {r["id"]: r for r in self.store.all("rules")},
        }
        task = asyncio.create_task(self.perform(run, payload))
        self.tasks[run["id"]] = task

        def cleanup(completed):
            self.tasks.pop(run["id"], None)
            current = self.store.run(run["id"])
            if completed.cancelled() and current["status"] == "RUNNING":
                current.update(status="CANCELLED", error="执行已取消", finishedAt=now())
                self.store.save_run(current)

        task.add_done_callback(cleanup)
        self.store.audit(actor, "run.start", run["id"])
        return run

    async def perform(self, run, payload):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "api.runner",
                cwd=config.ROOT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            stdout, _ = await asyncio.wait_for(
                process.communicate(data), timeout=config.JOB_TIMEOUT
            )
            result = json.loads(stdout.decode("utf-8"))
            if not result["success"]:
                raise ValueError(result["message"])
            run.update(result["data"], status="SUCCESS")
        except asyncio.TimeoutError:
            run.update(status="TIMED_OUT", error="执行超过时间上限，已终止")
        except asyncio.CancelledError:
            run.update(status="CANCELLED", error="执行已取消")
        except Exception as error:
            run.update(status="FAILED", error=str(error)[:500])
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            run["finishedAt"] = now()
            with self.store.transaction():
                self.store.save_run(run)
                if run["status"] == "SUCCESS":
                    for report in run["reports"]:
                        for rule in report["rules"]:
                            if rule["failed"]:
                                alert_id = str(uuid.uuid4())
                                with self.store.transaction():
                                    self.store.save_alert(
                                        {
                                            "id": alert_id,
                                            "runId": run["id"],
                                            "name": rule["name"],
                                            "field": rule["field"],
                                            "failed": rule["failed"],
                                            "status": "open",
                                            "createdAt": now(),
                                            "failedIndexes": rule["failedIndexes"],
                                        }
                                    )
                self.store.audit(
                    run["actor"], "run." + run["status"].lower(), run["id"]
                )
            self.tasks.pop(run["id"], None)

    def cancel(self, run_id):
        task = self.tasks.get(run_id)
        if task:
            task.cancel()
        return bool(task)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

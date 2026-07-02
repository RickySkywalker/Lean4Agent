"""Task board for tracking agent work decomposition with JSON persistence."""

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    parent_id: Optional[str] = None
    plan_file: Optional[str] = None
    plan_verified: bool = False
    result_summary: Optional[str] = None
    output_file: Optional[str] = (
        None  # Path to raw output file (for inter-task data passing)
    )
    error: Optional[str] = None
    model: Optional[str] = None
    tokens_used: int = 0
    created_at: str = ""
    updated_at: str = ""


class TaskBoard:
    """In-memory task board with JSON persistence.

    Provides CRUD operations for tasks, a revision log for auditability,
    and atomic JSON persistence via tmp-file + rename.
    """

    def __init__(self, persist_path: Optional[Path] = None):
        self._tasks: dict[str, Task] = {}
        self._counter: int = 0
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._revision_log: list[dict] = []
        if persist_path and persist_path.exists():
            self._load()

    def create_task(self, description: str, parent_id: Optional[str] = None) -> Task:
        """Create a new task and persist."""
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter:03d}"
            now = datetime.now(timezone.utc).isoformat()
            task = Task(
                id=task_id,
                description=description,
                parent_id=parent_id,
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = task
            self._revision_log.append(
                {
                    "timestamp": now,
                    "action": "created",
                    "task_id": task_id,
                    "description": description,
                }
            )
            self._persist()
            return task

    def update_task(self, task_id: str, **kwargs) -> Task:
        """Update task fields and persist. Accepts any Task field as kwarg."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            for key, value in kwargs.items():
                if value is None:
                    continue
                if key == "status" and isinstance(value, str):
                    value = TaskStatus(value)
                if hasattr(task, key):
                    setattr(task, key, value)
            task.updated_at = datetime.now(timezone.utc).isoformat()
            self._revision_log.append(
                {
                    "timestamp": task.updated_at,
                    "action": "updated",
                    "task_id": task_id,
                    "changes": {k: v for k, v in kwargs.items() if v is not None},
                }
            )
            self._persist()
            return task

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def has_pending_tasks(self) -> bool:
        return any(
            t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
            for t in self._tasks.values()
        )

    def get_summary(self) -> str:
        """Human-readable summary for the orchestrator LLM."""
        if not self._tasks:
            return "Task board is empty."
        lines = ["Task Board:"]
        for task in self._tasks.values():
            status_icon = {
                TaskStatus.PENDING: "○",
                TaskStatus.IN_PROGRESS: "◑",
                TaskStatus.COMPLETED: "●",
                TaskStatus.FAILED: "✗",
            }.get(task.status, "?")
            line = f"  {status_icon} [{task.id}] {task.description}"
            if task.plan_file:
                line += f" (plan: {task.plan_file})"
            if task.result_summary:
                line += f" -> {task.result_summary[:100]}"
            lines.append(line)
        return "\n".join(lines)

    def get_results_summary(self) -> str:
        """Detailed summary including full result_summaries for completed tasks.

        Used for inter-task context passing and final synthesis.
        Unlike get_summary() which truncates result_summary to 100 chars,
        this returns the full result_summary for completed tasks so the
        plan generator and orchestrator can use prior results as context.

        Returns:
            Multi-line string with task descriptions and their full results,
            or a short message if the board is empty or has no completed tasks.
        """
        if not self._tasks:
            return "No tasks on the board."

        completed = [
            t
            for t in self._tasks.values()
            if t.status == TaskStatus.COMPLETED and t.result_summary
        ]
        if not completed:
            return "No completed tasks with results yet."

        lines = ["Completed task results:"]
        for task in completed:
            lines.append(f"\n[{task.id}] {task.description}")
            lines.append(f"Result: {task.result_summary}")
            if task.output_file:
                lines.append(
                    f"Raw output file: {task.output_file} "
                    "(use fs_read to access the actual data if needed by subsequent tasks)"
                )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        data = {"tasks": [], "revision_log": self._revision_log}
        for t in self._tasks.values():
            t_dict = asdict(t)
            # Convert TaskStatus enum to string for JSON serialization
            if isinstance(t_dict.get("status"), TaskStatus):
                t_dict["status"] = t_dict["status"].value
            data["tasks"].append(t_dict)
        return data

    def _persist(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._persist_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        tmp.rename(self._persist_path)

    def _load(self) -> None:
        data = json.loads(self._persist_path.read_text())
        for t_data in data.get("tasks", []):
            t_data["status"] = TaskStatus(t_data["status"])
            task = Task(**t_data)
            self._tasks[task.id] = task
            self._counter = max(self._counter, int(task.id.split("_")[1]))
        self._revision_log = data.get("revision_log", [])

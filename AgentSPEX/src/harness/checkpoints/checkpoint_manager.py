import dataclasses
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from .workspace import backup_workspace as _backup_workspace
from .workspace import \
    best_effort_host_write_text as _best_effort_host_write_text
from .workspace import restore_task_files as _restore_task_files
from .workspace import restore_workspace as _restore_workspace
from .workspace_manifest import (capture_workspace_manifest,
                                 restore_workspace_from_manifest)


def _json_default(obj: Any):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (set, tuple)):
        return list(obj)
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


class CheckpointManager:
    def __init__(self, checkpoint_path: Path, *, load_existing: bool = True):
        self.checkpoint_path = Path(checkpoint_path)
        self.lock = threading.Lock()
        self.completed_steps: Set[str] = set()
        self.data: Dict[str, Any] = {}
        self.loaded = False

        self.corrupted = False

        # Load existing checkpoint if available and allowed
        if load_existing and self.checkpoint_path.exists():
            try:
                content = self.checkpoint_path.read_text(encoding="utf-8")
                if content:
                    self.data = json.loads(content)
                    self.loaded = True
                    # Rehydrate completed_steps set
                    cs = self.data.get("completed_steps", [])
                    if isinstance(cs, list):
                        self.completed_steps = set(str(s) for s in cs)
            except json.JSONDecodeError as e:
                # Checkpoint file is corrupted - create backup and warn
                self.corrupted = True
                backup_path = self.checkpoint_path.with_suffix(".json.corrupted")
                try:
                    import shutil

                    shutil.copy2(self.checkpoint_path, backup_path)
                    print(
                        f"WARNING: Checkpoint file corrupted ({e}), backup saved to {backup_path}"
                    )
                except Exception:
                    print(
                        f"WARNING: Checkpoint file corrupted ({e}), could not create backup"
                    )
                # Start fresh with empty checkpoint
                self.data = {}
                self.completed_steps = set()
            except Exception as e:
                print(f"WARNING: Failed to load checkpoint: {e}")

    def is_completed(self, step_id: Union[str, int]) -> bool:
        """Check if a step ID is marked as completed."""
        with self.lock:
            return str(step_id) in self.completed_steps

    def mark_completed(
        self,
        step_id: Union[str, int],
        context: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        update_context: bool = False,
    ):
        """
        Mark a step as completed and optionally update the checkpoint file.

        Args:
            step_id: The step ID to mark completed.
            context: The FULL context to save (if update_context is True).
            artifacts: Artifacts dictionary to update/merge.
            metrics: Metrics dictionary to update/merge.
            update_context: Whether to update the global context in the checkpoint.
                            Should only be True for top-level steps to avoid
                            checkpointing local submodule contexts as global.
        """
        sid = str(step_id)
        with self.lock:
            self.completed_steps.add(sid)

            # Update internal data
            self.data["completed_steps"] = list(self.completed_steps)
            self.data["updated_at"] = datetime.now().isoformat()

            if artifacts:
                if "artifacts" not in self.data:
                    self.data["artifacts"] = {}
                # minimal merge logic
                self.data["artifacts"].update(artifacts)

            if metrics:
                self.data["metrics"] = metrics

            if update_context and context is not None:
                # We assume the caller has already filtered the context (e.g. _checkpointable_context)
                self.data["context"] = context

            # Atomic write
            self._write_to_disk()

    def _write_to_disk(self):
        """Write self.data to disk atomically."""
        try:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
            payload = json.dumps(
                self.data, ensure_ascii=False, indent=2, default=_json_default
            )
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self.checkpoint_path)
        except Exception as e:
            print(f"Failed to write checkpoint: {e}")

    def set_metadata(self, key: str, value: Any):
        with self.lock:
            self.data[key] = value
            self._write_to_disk()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        with self.lock:
            return self.data.get(key, default)

    # ------------------------------------------------------------------
    # Sub-step output helpers (for control-flow inner steps like for_each)
    # ------------------------------------------------------------------

    def save_substep_output(self, step_id: str, output: str) -> None:
        """Save the output of a sub-step so it can be restored on resume."""
        with self.lock:
            if "substep_outputs" not in self.data:
                self.data["substep_outputs"] = {}
            self.data["substep_outputs"][step_id] = output
            self._write_to_disk()

    def get_substep_output(self, step_id: str) -> Optional[str]:
        """Retrieve a previously saved sub-step output (or None)."""
        with self.lock:
            return self.data.get("substep_outputs", {}).get(step_id)

    def backup_workspace(
        self,
        source_dir: Path,
        target_dir: Path,
        additional_ignores: Optional[List[str]] = None,
        logger=None,
    ):
        """
        Backup the source directory to the target directory using rsync for incremental sync.
        Falls back to shutil.copytree if rsync is not available.
        """
        result = _backup_workspace(source_dir, target_dir, additional_ignores, logger)

        if result:
            # Update metadata
            with self.lock:
                if "backups" not in self.data:
                    self.data["backups"] = []

                # Only keep last 5 backup records to avoid bloat
                backup_info = {
                    "timestamp": datetime.now().isoformat(),
                    "source": str(source_dir),
                    "target": str(target_dir),
                }
                self.data["backups"].append(backup_info)
                if len(self.data["backups"]) > 5:
                    self.data["backups"] = self.data["backups"][-5:]
                self.data["workspace_backup_path"] = str(target_dir)
                self._write_to_disk()

        return result

    def restore_workspace(
        self,
        backup_dir: Path,
        target_dir: Path,
        additional_ignores: Optional[List[str]] = None,
        logger=None,
    ) -> bool:
        """
        Restore workspace from backup during resume using rsync.
        Falls back to shutil.copytree if rsync is not available.
        """
        result = _restore_workspace(backup_dir, target_dir, additional_ignores, logger)

        if result:
            # Update metadata
            with self.lock:
                if "restores" not in self.data:
                    self.data["restores"] = []

                restore_info = {
                    "timestamp": datetime.now().isoformat(),
                    "source": str(backup_dir),
                    "target": str(target_dir),
                }
                self.data["restores"].append(restore_info)
                self._write_to_disk()

        return result

    def restore_task_files(
        self, backup_dir: Path, target_dir: Path, task_output_subdir: str, logger=None
    ) -> bool:
        """
        Restore only the specific task's output files from backup.
        """
        return _restore_task_files(backup_dir, target_dir, task_output_subdir, logger)

    def capture_and_save_manifest(
        self,
        workspace_dir: Path,
        step_id: str,
        ignores: Optional[List[str]] = None,
        backup_dir: Optional[Path] = None,
        logger=None,
    ) -> bool:
        """Capture a workspace manifest and save it to the checkpoint directory.

        Large or binary files are copied to *backup_dir* (if provided) so
        they can be restored later without being stored inline in the manifest.

        Returns True if the manifest was captured and saved successfully.
        """
        try:
            manifest = capture_workspace_manifest(
                workspace_dir=workspace_dir,
                step_id=step_id,
                ignores=ignores,
                backup_dir=backup_dir,
                logger=logger,
            )

            # Save manifest to checkpoint directory
            manifest_path = self.checkpoint_path.parent / "workspace_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = manifest_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(manifest_path)

            # Record in checkpoint metadata
            with self.lock:
                self.data["workspace_manifest_path"] = str(manifest_path)
                self.data["workspace_manifest_step"] = step_id
                self._write_to_disk()

            if logger:
                logger(f"[Checkpoint] Workspace manifest saved to {manifest_path}")
            return True

        except Exception as e:
            msg = f"[Checkpoint] ERROR: Failed to capture workspace manifest: {e}"
            if logger:
                logger(msg)
            else:
                print(msg)
            return False

    def restore_from_manifest(
        self,
        target_dir: Path,
        logger=None,
    ) -> bool:
        """Restore workspace from the saved manifest.

        Returns True if restore succeeded, False otherwise.
        """
        manifest_path_str = self.get_metadata("workspace_manifest_path")
        if not manifest_path_str:
            if logger:
                logger(
                    "[Checkpoint] No workspace manifest found in checkpoint metadata"
                )
            return False

        manifest_path = Path(manifest_path_str)
        if not manifest_path.exists():
            if logger:
                logger(f"[Checkpoint] Manifest file not found: {manifest_path}")
            return False

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            if logger:
                logger(f"[Checkpoint] ERROR: Failed to read manifest: {e}")
            return False

        if logger:
            logger(
                f"[Checkpoint] Restoring workspace from manifest "
                f"(step_id={manifest.get('step_id', '?')})"
            )

        result = restore_workspace_from_manifest(
            manifest=manifest,
            target_dir=target_dir,
            logger=logger,
        )

        if result:
            with self.lock:
                if "restores" not in self.data:
                    self.data["restores"] = []
                self.data["restores"].append(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "method": "manifest",
                        "target": str(target_dir),
                        "step_id": manifest.get("step_id"),
                    }
                )
                self._write_to_disk()

        return result

    def best_effort_host_write_text(
        self, path: str | Path, content: str, *, append: bool = False
    ) -> None:
        """
        Best-effort mirror write on host filesystem.
        """
        _best_effort_host_write_text(path, content, append=append)

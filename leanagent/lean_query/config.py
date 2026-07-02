"""Configuration for the Lean verification query tool."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or incomplete."""
    pass


@dataclass
class VerifierConfig:
    lean_project_path: str
    target_file: str
    layer: int  # 1, 2, or 3
    namespace: str = "auto"

    # Layer 1 required
    workflow_graph: str = "auto"

    # Layer 2 required (when layer >= 2)
    semantic_graph: Optional[str] = "auto"
    goal_spec: Optional[str] = "auto"

    # Layer 3 sub-channel: "process" (per-step beta, the default) or "runtime"
    # (per-turn gamma — the RuntimePredicates fine-grained tool-call verdicts).
    channel: str = "process"

    # Layer 3 / process channel required (when layer == 3 and channel == "process")
    dynamic_graph: Optional[str] = None
    step_id_map: Optional[str] = None
    llm_injections: Optional[str] = None
    exec_state: Optional[str] = None
    report_path_var: Optional[str] = None
    event_log_path_var: Optional[str] = None

    # Layer 3 / runtime channel (when layer == 3 and channel == "runtime"): EITHER the
    # zero-axiom `def <name> : List RuntimeTurnInput :=` (preferred — Lean judges the
    # raw commands) OR the legacy digested `def <name> : List RuntimeTurnFact :=`.
    # Both auto-discovered; driver_gen prefers runtime_inputs.
    runtime_facts: Optional[str] = "auto"
    runtime_inputs: Optional[str] = "auto"

    # Execution
    timeout_seconds: int = 300
    output_file: Optional[str] = None
    pretty_print: bool = True
    env: dict = field(default_factory=dict)

    def validate(self):
        """Check all required fields for the requested layer are present.

        Raises ConfigError if any required field is missing or invalid.
        """
        if self.layer not in (1, 2, 3):
            raise ConfigError(f"layer must be 1, 2, or 3, got {self.layer}")

        project = Path(self.lean_project_path)
        if not project.is_dir():
            raise ConfigError(f"lean_project_path not found: {self.lean_project_path}")

        target = project / self.target_file
        if not target.is_file():
            raise ConfigError(f"target_file not found: {target}")

        if self.layer >= 1:
            if not self.workflow_graph:
                raise ConfigError("workflow_graph required for layer >= 1")

        if self.layer >= 2:
            if not self.semantic_graph:
                raise ConfigError("semantic_graph required for layer >= 2")
            if not self.goal_spec:
                raise ConfigError("goal_spec required for layer >= 2")

        if self.layer == 3 and self.channel not in ("process", "runtime"):
            raise ConfigError(f"channel must be 'process' or 'runtime', got {self.channel}")

        # The per-step (process/beta) channel needs the 6 dynamic-analysis defs; the
        # per-turn (runtime/gamma) channel needs only the runtimeFacts def (discovered).
        if self.layer == 3 and self.channel == "process":
            required_l3 = {
                'dynamic_graph': self.dynamic_graph,
                'step_id_map': self.step_id_map,
                'llm_injections': self.llm_injections,
                'exec_state': self.exec_state,
                'report_path_var': self.report_path_var,
                'event_log_path_var': self.event_log_path_var,
            }
            for name, value in required_l3.items():
                if not value:
                    raise ConfigError(f"{name} required for layer 3 (process channel)")

    @staticmethod
    def from_yaml(path: str) -> "VerifierConfig":
        """Load config from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return VerifierConfig.from_dict(data)

    @staticmethod
    def from_dict(data: dict) -> "VerifierConfig":
        """Create config from a dictionary."""
        known_fields = {f.name for f in VerifierConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return VerifierConfig(**filtered)

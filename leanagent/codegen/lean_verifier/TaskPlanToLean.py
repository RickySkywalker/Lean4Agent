"""
Parsed Task JSON → Lean WorkflowGraph Code Generator (Unified IR)

Unified design: semantic predicates live directly on each node's reads/writes.
  - TypedVar gains optional `predicates: list[PredicateIR] | None`
  - NodeIR gains optional `precond_extra` and `postcond_extra` for non-variable predicates
    (tool existence, module existence, etc.)
  - If predicates are None → not yet analyzed, skip semantic generation
  - If predicates are [] → analyzed, no constraints needed
  - If predicates are [...] → analyzed, constraints present

This means:
  - Layer 1 (structural) always generates
  - Layer 2 (semantic) generates iff ALL non-deterministic nodes have predicates filled
  - LLM fills in predicates per-variable, the codegen handles the rest
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# 1. IR DATA STRUCTURES
# ============================================================================

# ---------- JSON Schema IR ----------

@dataclass
class JsonSchemaIR:
    """Mirrors AgenticKernel.JsonSchema."""
    kind: str  # "jString", "jNum", "jBool", "jNull", "jArray", "jObject", "jAny"
    element_schema: Optional["JsonSchemaIR"] = None
    fields: Optional[list[tuple[str, "JsonSchemaIR"]]] = None

    def to_lean(self) -> str:
        if self.kind == "jArray" and self.element_schema:
            return f".jArray ({self.element_schema.to_lean()})"
        elif self.kind == "jObject" and self.fields is not None:
            if not self.fields:
                return ".jObject []"
            items = ", ".join(f'("{n}", {s.to_lean()})' for n, s in self.fields)
            return f".jObject [{items}]"
        return f".{self.kind}"

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind}
        if self.element_schema:
            d["element"] = self.element_schema.to_dict()
        if self.fields is not None:
            d["fields"] = {n: s.to_dict() for n, s in self.fields}
        return d

    @staticmethod
    def from_dict(d: dict) -> "JsonSchemaIR":
        # Accept both "element" (LLM/IR format) and "element_schema" (legacy)
        raw_elem = d.get("element") or d.get("element_schema")
        elem = JsonSchemaIR.from_dict(raw_elem) if raw_elem else None
        flds = None
        if d.get("fields") is not None:
            raw_fields = d["fields"]
            if isinstance(raw_fields, dict):
                # Handle {"name": {schema}, ...} format (LLM-edited IR)
                flds = [(k, JsonSchemaIR.from_dict(v)) for k, v in raw_fields.items()]
            else:
                # Handle [["name", {schema}], ...] format (legacy)
                flds = [(f[0], JsonSchemaIR.from_dict(f[1])) for f in raw_fields]
        return JsonSchemaIR(kind=d["kind"], element_schema=elem, fields=flds)


# ---------- Predicate IR ----------

@dataclass
class PredicateIR:
    """Mirrors AgenticKernel.PredicateType."""
    kind: str
    schema: Optional[JsonSchemaIR] = None       # matchesJsonSchema
    substring: Optional[str] = None             # containsSubstring
    custom_name: Optional[str] = None           # custom
    ext_key: Optional[str] = None               # ext (manual Lean key fallback)
    value_predicates: Optional[list["PredicateIR"]] = None  # ext: value predicates for DictAllValuesPredicate
    dict_var_name: Optional[str] = None          # ext: target variable name for DictAllValuesPredicate
    left: Optional["PredicateIR"] = None        # predicateAnd/Or
    right: Optional["PredicateIR"] = None       # predicateAnd/Or

    def to_lean(self) -> str:
        if self.kind == "matchesJsonSchema" and self.schema:
            return f".matchesJsonSchema ({self.schema.to_lean()})"
        elif self.kind == "containsSubstring" and self.substring:
            return f'.containsSubstring "{self.substring}"'
        elif self.kind == "custom" and self.custom_name:
            return f'.custom "{self.custom_name}"'
        elif self.kind == "ext" and self.value_predicates is not None:
            vps = ", ".join(p.to_lean() for p in self.value_predicates)
            dvn = f' "{self.dict_var_name}"' if self.dict_var_name else ' ""'
            return f".ext ((DictAllValuesPredicate.mk [{vps}]{dvn}).toPredicateKey)"
        elif self.kind == "ext" and self.ext_key:
            return f".ext {self.ext_key}"
        elif self.kind in ("predicateAnd", "predicateOr") and self.left and self.right:
            return f".{self.kind} ({self.left.to_lean()}) ({self.right.to_lean()})"
        return f".{self.kind}"

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind}
        if self.schema: d["schema"] = self.schema.to_dict()
        if self.substring is not None: d["substring"] = self.substring
        if self.custom_name is not None: d["custom_name"] = self.custom_name
        if self.ext_key is not None: d["ext_key"] = self.ext_key
        if self.value_predicates is not None:
            d["value_predicates"] = [p.to_dict() for p in self.value_predicates]
        if self.dict_var_name is not None: d["dict_var_name"] = self.dict_var_name
        if self.left: d["left"] = self.left.to_dict()
        if self.right: d["right"] = self.right.to_dict()
        return d

    @staticmethod
    def from_dict(d: dict) -> "PredicateIR":
        # Backward compat: ext_inline → direct fields
        vp = None
        dvn = d.get("dict_var_name")
        if d.get("ext_inline"):
            ei = d["ext_inline"]
            vp = [PredicateIR.from_dict(p) for p in ei["value_predicates"]] if ei.get("value_predicates") else None
            dvn = dvn or ei.get("dict_var_name")
        elif d.get("value_predicates"):
            vp = [PredicateIR.from_dict(p) for p in d["value_predicates"]]
        return PredicateIR(
            kind=d["kind"],
            schema=JsonSchemaIR.from_dict(d["schema"]) if d.get("schema") else None,
            substring=d.get("substring"), custom_name=d.get("custom_name"),
            ext_key=d.get("ext_key"),
            value_predicates=vp, dict_var_name=dvn,
            left=PredicateIR.from_dict(d["left"]) if d.get("left") else None,
            right=PredicateIR.from_dict(d["right"]) if d.get("right") else None,
        )


# ---------- SubmoduleRef: describes a verified submodule dependency ----------

@dataclass
class SubmoduleRef:
    """Describes a dependency on a verified submodule (via call / parallel / gather).

    Structural fields (from YAML parsing):
      name:        canonical module name, e.g. "extract_single_citation"
      kind:        how it is invoked: "parallel", "call", or "gather"
      output_var:  context variable receiving results (save_results_as / save_as)
      input_var:   for parallel, the parameters_list variable name

    Semantic fields (from --submodule_map CLI arg):
      lean_import:  Lean import path for the verified .lean file
      lean_prefix:  prefix used inside that .lean file (e.g. "extractCitation")
                    → SemanticGraph = {lean_prefix}SemanticGraph
                    → Soundness thm  = {name}_semantically_sound
    """
    name: str
    kind: str                         # "parallel" | "call" | "gather"
    output_var: Optional[str] = None
    input_var:  Optional[str] = None
    lean_import: str = ""             # filled from --submodule_map
    lean_prefix: str = ""             # filled from --submodule_map

    @property
    def semantic_graph_lean(self) -> str:
        """Name of the SemanticWorkflowGraph exported by the imported module."""
        return f"{self.lean_prefix}SemanticGraph"

    @property
    def soundness_thm_lean(self) -> str:
        """Name of the soundness theorem exported by the imported module."""
        return f"{self.name}_semantically_sound"

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "kind": self.kind}
        if self.output_var is not None: d["output_var"] = self.output_var
        if self.input_var  is not None: d["input_var"]  = self.input_var
        if self.lean_import: d["lean_import"] = self.lean_import
        if self.lean_prefix: d["lean_prefix"] = self.lean_prefix
        return d

    @staticmethod
    def from_dict(d: dict) -> "SubmoduleRef":
        return SubmoduleRef(
            name=d["name"], kind=d.get("kind", "call"),
            output_var=d.get("output_var"),
            input_var=d.get("input_var"),
            lean_import=d.get("lean_import", ""),
            lean_prefix=d.get("lean_prefix", ""),
        )


# ---------- VarPredicate: a (varName, predicate) pair for Lean generation ----------

@dataclass
class VarPredicateIR:
    """Pairs a variable name with a predicate. Used for Lean code generation."""
    var_name: str
    predicate: PredicateIR

    def to_lean(self) -> str:
        p = self.predicate
        vn = self.var_name
        shorthand = {
            "nameExists": "varNameExists", "isNonEmptyString": "varIsNonEmptyString",
            "isNonEmptyList": "varIsNonEmptyList", "isInt": "varIsInt",
            "isValidURL": "varIsValidURL", "isValidFilePath": "varIsValidFilePath",
            "isValidPath": "varIsValidPath", "isValidBibtex": "varIsValidBibtex",
            "isValidLatex": "varIsValidLatex", "isValidJson": "varIsValidJson",
            "isValidList": "varIsValidList", "toolExists": "varIsValidTool",
            "moduleExists": "varIsValidModule", "fileExistsAtPath": "varFileExistsAtPath",
            "taskCompleted": "varTaskCompleted",
        }
        if p.kind in shorthand:
            return f'{shorthand[p.kind]} "{vn}"'
        elif p.kind == "matchesJsonSchema" and p.schema:
            return f'varIsValidJsonSchema "{vn}" ({p.schema.to_lean()})'
        elif p.kind == "containsSubstring" and p.substring:
            return f'varContainsSentinel "{vn}" "{p.substring}"'
        elif p.kind == "custom" and p.custom_name:
            return f'varIsValidCustomPredicate "{vn}" "{p.custom_name}"'
        return f'⟨"{vn}", {p.to_lean()}⟩'

    def to_dict(self) -> dict:
        return {"var_name": self.var_name, "predicate": self.predicate.to_dict()}

    @staticmethod
    def from_dict(d: dict) -> "VarPredicateIR":
        return VarPredicateIR(var_name=d["var_name"], predicate=PredicateIR.from_dict(d["predicate"]))


# ---------- TypedVar: structural variable with optional semantic predicates ----------

@dataclass
class TypedVar:
    """A typed workflow variable.

    Structural fields (always present):
      - name: variable name
      - base_type: Lean BaseType string ("TString", "TList TUnknown", etc.)

    Optional fields:
      - value: original parameter value (only for workflow parameters, None for reads/writes)
      - predicates: what this variable must satisfy (postcond for writes, precond for reads)
        (None = not analyzed, [] = analyzed but no constraints)
    """
    name: str
    base_type: str
    value: Optional[object] = None
    predicates: Optional[list[PredicateIR]] = None

    def to_lean_typed(self) -> str:
        """Generate the TypedVar literal for WorkflowNode."""
        parts = self.base_type.split()
        lean_type = " .".join(parts)
        return f'⟨"{self.name}", .{lean_type}⟩'

    @property
    def has_semantic(self) -> bool:
        return self.predicates is not None

    def to_var_predicates(self) -> list[VarPredicateIR]:
        """Convert to list of VarPredicateIR for Lean semantic generation."""
        if self.predicates is None:
            return []
        return [VarPredicateIR(self.name, p) for p in self.predicates]

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "base_type": self.base_type}
        if self.value is not None:
            d["value"] = self.value
        if self.predicates is not None:
            d["predicates"] = [p.to_dict() for p in self.predicates]
        return d

    @staticmethod
    def from_dict(d: dict) -> "TypedVar":
        preds = None
        if "predicates" in d:
            preds = [PredicateIR.from_dict(p) for p in d["predicates"]]
        return TypedVar(name=d["name"], base_type=d["base_type"],
                        value=d.get("value"), predicates=preds)


# ---------- v2 Graph-Level / Workflow-Quality Annotation IRs ----------

# These mirror helpers from:
#   AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.WorkflowQualityAnalysis
#   AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

# Mapping table from IR kind strings to Lean helper function names
_STEP_TAG_HELPERS = {
    "exploratory":    "markStepExploratory",
    "comprehensive":  "markStepComprehensive",
    "incremental":    "markStepIncremental",
    "transformative": "markStepTransformative",
    "verificatory":   "markStepVerificatory",
    "overhead":       "markStepOverhead",
}

_WRITE_CTX_HELPERS = {
    "onSuccess":     "markWriteOnSuccess",
    "onFailure":     "markWriteOnFailure",
    "onExhaustion":  "markWriteOnExhaustion",
    "unconditional": "markWriteUnconditional",
}

_GRAPH_PRED_KINDS = {
    "pathCoverage", "verificationCoverage", "exitFactsConfirmed",
    "contextContinuity", "informationSufficiency", "unifiedLoopBack",
    "failSafe",
}


@dataclass
class StepTagIR:
    """One of markStep{Exploratory|Comprehensive|Incremental|Transformative|Verificatory|Overhead}."""
    kind: str  # key in _STEP_TAG_HELPERS

    def to_lean(self, prefix: str, node_id: int) -> str:
        helper = _STEP_TAG_HELPERS.get(self.kind)
        if helper is None:
            raise ValueError(f"Unknown step tag kind: {self.kind}")
        return f"{helper} {prefix}_nodeId{node_id}"

    def to_dict(self) -> dict:
        return {"kind": self.kind}

    @staticmethod
    def from_dict(d: dict) -> "StepTagIR":
        return StepTagIR(kind=d["kind"])


@dataclass
class WriteContextIR:
    """One of markWrite{OnSuccess|OnFailure|OnExhaustion|Unconditional} for a specific variable."""
    var_name: str
    kind: str  # key in _WRITE_CTX_HELPERS

    def to_lean(self, prefix: str, node_id: int) -> str:
        helper = _WRITE_CTX_HELPERS.get(self.kind)
        if helper is None:
            raise ValueError(f"Unknown write context kind: {self.kind}")
        return f'{helper} {prefix}_nodeId{node_id} "{self.var_name}"'

    def to_dict(self) -> dict:
        return {"var_name": self.var_name, "kind": self.kind}

    @staticmethod
    def from_dict(d: dict) -> "WriteContextIR":
        return WriteContextIR(var_name=d["var_name"], kind=d["kind"])


@dataclass
class InfoContentIR:
    """markInfoContent "var_name" "aspect" — declares/demands a named information aspect."""
    var_name: str
    aspect: str

    def to_lean(self) -> str:
        return f'markInfoContent "{self.var_name}" "{self.aspect}"'

    def to_dict(self) -> dict:
        return {"var_name": self.var_name, "aspect": self.aspect}

    @staticmethod
    def from_dict(d: dict) -> "InfoContentIR":
        return InfoContentIR(var_name=d["var_name"], aspect=d["aspect"])


@dataclass
class SubGoalTagIR:
    """Reference to a sub-goal, used for markSubGoalContribution / markSubGoalVerification / markImplicitRetry."""
    sub_goal_name: str

    def to_dict(self) -> dict:
        return {"sub_goal_name": self.sub_goal_name}

    @staticmethod
    def from_dict(d: dict) -> "SubGoalTagIR":
        return SubGoalTagIR(sub_goal_name=d["sub_goal_name"])


@dataclass
class GraphPredicateKeyIR:
    """Reference to a GraphLevelPredicateKeys.{kind} identifier."""
    kind: str  # one of _GRAPH_PRED_KINDS

    def to_lean(self) -> str:
        if self.kind not in _GRAPH_PRED_KINDS:
            raise ValueError(f"Unknown graph predicate kind: {self.kind}")
        return f"GraphLevelPredicateKeys.{self.kind}"

    def to_dict(self) -> dict:
        return {"kind": self.kind}

    @staticmethod
    def from_dict(d: dict) -> "GraphPredicateKeyIR":
        return GraphPredicateKeyIR(kind=d["kind"])


@dataclass
class SubGoalSpecIR:
    """Mirrors AgenticKernel.SubGoalSpec.

    Emits a Lean record literal like:
        { name := "..."
          variableName := "..."
          requiredPredicate := .isNonEmptyString
          description := "..."
          requiredGraphPredicates := [GraphLevelPredicateKeys.pathCoverage, ...] }
    """
    name: str
    variable_name: str
    required_predicate: PredicateIR
    description: str = ""
    required_graph_predicates: list[GraphPredicateKeyIR] = field(default_factory=list)

    def to_lean(self) -> str:
        # Escape description for Lean string literal
        desc_escaped = (self.description
                        .replace('\\', '\\\\')
                        .replace('"', '\\"')
                        .replace('\n', '\\n'))
        rgp = ", ".join(k.to_lean() for k in self.required_graph_predicates)
        # `SubGoalSpec.name` is the typed `SubGoalName` newtype (FIX #3): wrap the
        # name string in its constructor so it matches the `markSubGoal*` markers
        # (BEq on `SubGoalName` compares `.val`, so coverage analysis still joins
        # contributions to sub-goals by name).
        return (
            f'    {{ name := ⟨"{self.name}"⟩\n'
            f'      variableName := "{self.variable_name}"\n'
            f"      requiredPredicate := {self.required_predicate.to_lean()}\n"
            f'      description := "{desc_escaped}"\n'
            f"      requiredGraphPredicates := [{rgp}] }}"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "variable_name": self.variable_name,
            "required_predicate": self.required_predicate.to_dict(),
            "description": self.description,
            "required_graph_predicates": [k.to_dict() for k in self.required_graph_predicates],
        }

    @staticmethod
    def from_dict(d: dict) -> "SubGoalSpecIR":
        return SubGoalSpecIR(
            name=d["name"],
            variable_name=d["variable_name"],
            required_predicate=PredicateIR.from_dict(d["required_predicate"]),
            description=d.get("description", ""),
            required_graph_predicates=[
                GraphPredicateKeyIR.from_dict(k) for k in d.get("required_graph_predicates", [])
            ],
        )


def _precond_postcond_item_to_dict(item) -> dict:
    """Serialize a VarPredicateIR or InfoContentIR to JSON-ready dict.
    Both dataclasses expose to_dict(); the union is distinguished by shape
    ("predicate" vs "aspect")."""
    if isinstance(item, InfoContentIR):
        return item.to_dict()
    if isinstance(item, VarPredicateIR):
        return item.to_dict()
    raise TypeError(f"Unsupported precond/postcond item: {type(item).__name__}")


def _precond_postcond_item_from_dict(d: dict):
    """Deserialize either a VarPredicateIR or an InfoContentIR dict.
    Dispatches by which key is present:
      {"var_name": str, "predicate": {...}} → VarPredicateIR
      {"var_name": str, "aspect": str}      → InfoContentIR"""
    if "predicate" in d:
        return VarPredicateIR.from_dict(d)
    if "aspect" in d:
        return InfoContentIR.from_dict(d)
    raise ValueError(f"Unrecognised precond/postcond entry dict: {d}")


@dataclass
class GoalSpecificationIR:
    """Mirrors AgenticKernel.GoalSpecification."""
    original_goal: str
    sub_goals: list[SubGoalSpecIR]

    def to_lean(self, prefix: str) -> str:
        goal_escaped = (self.original_goal
                        .replace('\\', '\\\\')
                        .replace('"', '\\"')
                        .replace('\n', '\\n'))
        sub_goals_str = ",\n".join(s.to_lean() for s in self.sub_goals)
        return (
            f"def {prefix}_goalSpec : GoalSpecification := {{\n"
            f'  originalGoal := "{goal_escaped}"\n'
            f"  subGoals := [\n"
            f"{sub_goals_str}\n"
            f"  ]\n"
            f"}}"
        )

    def to_dict(self) -> dict:
        return {
            "original_goal": self.original_goal,
            "sub_goals": [s.to_dict() for s in self.sub_goals],
        }

    @staticmethod
    def from_dict(d: dict) -> "GoalSpecificationIR":
        return GoalSpecificationIR(
            original_goal=d["original_goal"],
            sub_goals=[SubGoalSpecIR.from_dict(s) for s in d["sub_goals"]],
        )


# ---------- Node IR ----------

@dataclass
class NodeIR:
    """Unified workflow node with optional semantic annotations.

    Semantic predicates are attached directly to reads/writes variables.
    Additional predicates not tied to a specific read/write variable
    (e.g., tool existence for precond, complex schema for postcond)
    go into precond_extra / postcond_extra.

    Semantic readiness:
      - needs_spec == False (deterministic): always ready
      - needs_spec == True: ready iff ALL reads have predicates != None
        AND ALL writes have predicates != None
    """
    id: int
    name: str
    step_type: str
    reads: list[TypedVar]
    writes: list[TypedVar]
    instruction: Optional[str] = None
    # Extra preconditions not tied to a specific read variable
    # (tool availability, module existence, etc.)
    precond_extra: Optional[list[VarPredicateIR]] = None
    # Extra postconditions not tied to a specific write variable
    postcond_extra: Optional[list[VarPredicateIR]] = None

    # -- Conditional node fields --
    then_target_id: Optional[int] = None
    else_target_id: Optional[int] = None
    then_postcond: Optional[list[VarPredicateIR]] = None
    else_postcond: Optional[list[VarPredicateIR]] = None

    # -- Loop node fields --
    loop_invariant: Optional[list[VarPredicateIR]] = None
    termination_kind: Optional[str] = None  # "finiteCondition", "llmControlledExit", etc.
    termination_vars: Optional[list[str]] = None
    termination_sentinel: Optional[str] = None
    termination_exit_node: Optional[int] = None
    termination_mechanism: Optional[str] = None
    termination_justification: Optional[str] = None
    exit_postcond: Optional[list[VarPredicateIR]] = None
    iteration_var: Optional[str] = None  # for_each loop variable
    # When True, emits `executesAtLeastOnce := true` on the SemanticLoopNode literal.
    loop_executes_at_least_once: bool = False

    # -- Submodule call fields (parallel / call / gather with a module) --
    submodule_ref: Optional["SubmoduleRef"] = None

    # -- Layer 2 v2: graph-level and workflow-quality annotations --
    # All default None (omitted when the node has no such annotation).
    # NOTE: precond_extra and postcond_extra (declared above) accept either
    # VarPredicateIR or InfoContentIR entries (heterogeneous, preserves order).
    step_tag: Optional[StepTagIR] = None
    sub_goal_contributions: Optional[list[SubGoalTagIR]] = None
    sub_goal_verifications: Optional[list[SubGoalTagIR]] = None
    implicit_retries: Optional[list[SubGoalTagIR]] = None
    write_contexts: Optional[list[WriteContextIR]] = None

    @property
    def exec_type(self) -> str:
        deterministic = {"setVariable", "forEachLoop", "whileLoop", "conditional",
                         "incrementVariable", "switchBranch", "returnValue", "save",
                         "input", "parallel", "gather"}
        structured = {"discover", "evaluate", "validate"}
        if self.step_type in deterministic:
            return "deterministic"
        elif self.step_type in structured:
            return "structured"
        return "unstructured"

    @property
    def needs_spec(self) -> bool:
        return self.exec_type != "deterministic"

    @property
    def is_conditional(self) -> bool:
        return self.then_target_id is not None and self.else_target_id is not None

    @property
    def is_loop(self) -> bool:
        return self.loop_invariant is not None

    @property
    def semantic_ready(self) -> bool:
        """Check if all semantic annotations are filled for this node."""
        if not self.needs_spec:
            return True  # deterministic nodes don't need semantic specs
        # call/gather nodes whose semantics are auto-derived from a submodule
        if self.step_type in ("call", "gather") and self.submodule_ref is not None:
            return True
        # All reads and writes must have predicates filled (not None)
        for v in self.reads:
            if v.predicates is None:
                return False
        for v in self.writes:
            if v.predicates is None:
                return False
        return True

    def collect_precond(self) -> list[VarPredicateIR]:
        """Collect preconditions that are VarPredicateIR: precond_extra (VP-typed entries only)
        + read predicates, deduplicated by (var_name, predicate_kind).

        Heterogeneous InfoContentIR entries in precond_extra are NOT included here —
        use collect_precond_lean_exprs for Lean emission that respects ordering.
        """
        seen: set[tuple[str, str]] = set()
        result: list[VarPredicateIR] = []
        if self.precond_extra:
            for item in self.precond_extra:
                if isinstance(item, VarPredicateIR):
                    key = (item.var_name, item.predicate.kind)
                    if key not in seen:
                        seen.add(key)
                        result.append(item)
        for r in self.reads:
            for p in r.to_var_predicates():
                key = (p.var_name, p.predicate.kind)
                if key not in seen:
                    seen.add(key)
                    result.append(p)
        return result

    def collect_precond_lean_exprs(self, prefix: str) -> list[str]:
        """Return ordered Lean expressions for precondVariables.

        Iterates precond_extra in authoring order (VarPredicateIR or InfoContentIR),
        then appends read-variable predicates (dedup against precond_extra VPs).
        """
        exprs: list[str] = []
        seen_vp: set[tuple[str, str]] = set()
        if self.precond_extra:
            for item in self.precond_extra:
                if isinstance(item, VarPredicateIR):
                    key = (item.var_name, item.predicate.kind)
                    if key in seen_vp:
                        continue
                    seen_vp.add(key)
                    exprs.append(item.to_lean())
                elif isinstance(item, InfoContentIR):
                    exprs.append(item.to_lean())
                else:
                    raise TypeError(f"Unsupported precond_extra entry: {type(item).__name__}")
        for r in self.reads:
            for p in r.to_var_predicates():
                key = (p.var_name, p.predicate.kind)
                if key in seen_vp:
                    continue
                seen_vp.add(key)
                exprs.append(p.to_lean())
        return exprs

    def collect_postcond_lean_exprs(self, prefix: str) -> list[str]:
        """Return ordered Lean expressions for postcondVariables.

        Canonical v2 order (matches hand-written reference files):
          1. step_tag                — NO LONGER EMITTED (markStep* removed from Lean)
          2. sub_goal_contributions (preserve list order)
          3. sub_goal_verifications
          4. implicit_retries
          5. write-variable predicates, then postcond_extra in authoring order
             (each entry can be VarPredicateIR or InfoContentIR)
          6. write_contexts          — NO LONGER EMITTED (markWrite* removed from Lean)
        """
        exprs: list[str] = []
        # NOTE: step-tag markers (markStep{Exploratory|Transformative|…}) were
        # removed from the Lean layer in the graph-predicate restructure with no
        # replacement, so they are no longer emitted — a bare reference would be an
        # `unknown identifier` compile error. (`step_tag` is still parsed from the
        # IR for forward-compat but intentionally not rendered.)
        # Sub-goal identities are the typed `SubGoalName` newtype (FIX #3), so the
        # name string must be wrapped in its constructor `⟨"…"⟩` — a bare string
        # no longer typechecks against `markSubGoal*`'s `SubGoalName` argument.
        if self.sub_goal_contributions:
            for c in self.sub_goal_contributions:
                exprs.append(f'markSubGoalContribution {prefix}_nodeId{self.id} ⟨"{c.sub_goal_name}"⟩')
        if self.sub_goal_verifications:
            for v in self.sub_goal_verifications:
                exprs.append(f'markSubGoalVerification {prefix}_nodeId{self.id} ⟨"{v.sub_goal_name}"⟩')
        if self.implicit_retries:
            for r in self.implicit_retries:
                exprs.append(f'markImplicitRetry {prefix}_nodeId{self.id} ⟨"{r.sub_goal_name}"⟩')

        seen_vp: set[tuple[str, str]] = set()
        for w in self.writes:
            for vp in w.to_var_predicates():
                key = (vp.var_name, vp.predicate.kind)
                if key in seen_vp:
                    continue
                seen_vp.add(key)
                exprs.append(vp.to_lean())
        if self.postcond_extra:
            for item in self.postcond_extra:
                if isinstance(item, VarPredicateIR):
                    key = (item.var_name, item.predicate.kind)
                    if key in seen_vp:
                        continue
                    seen_vp.add(key)
                    exprs.append(item.to_lean())
                elif isinstance(item, InfoContentIR):
                    exprs.append(item.to_lean())
                else:
                    raise TypeError(f"Unsupported postcond_extra entry: {type(item).__name__}")
        # NOTE: write-context markers (markWrite{OnSuccess|OnFailure|OnExhaustion|
        # Unconditional}) were likewise removed from the Lean layer in the restructure
        # and are no longer emitted. (`write_contexts` stays parsed for forward-compat.)
        return exprs

    def collect_postcond(self) -> list[VarPredicateIR]:
        """Collect VarPredicateIR postconditions: write predicates + postcond_extra (VP entries only),
        deduplicated by (var_name, predicate_kind).

        InfoContentIR entries in postcond_extra are skipped here — use
        collect_postcond_lean_exprs for Lean emission that preserves ordering."""
        seen: set[tuple[str, str]] = set()
        result: list[VarPredicateIR] = []
        for w in self.writes:
            for p in w.to_var_predicates():
                key = (p.var_name, p.predicate.kind)
                if key not in seen:
                    seen.add(key)
                    result.append(p)
        if self.postcond_extra:
            for p in self.postcond_extra:
                if not isinstance(p, VarPredicateIR):
                    continue
                key = (p.var_name, p.predicate.kind)
                if key not in seen:
                    seen.add(key)
                    result.append(p)
        return result

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id, "name": self.name, "step_type": self.step_type,
            "reads": [r.to_dict() for r in self.reads],
            "writes": [w.to_dict() for w in self.writes],
        }
        if self.instruction is not None:
            d["instruction"] = self.instruction
        if self.precond_extra is not None:
            d["precond_extra"] = [_precond_postcond_item_to_dict(p) for p in self.precond_extra]
        if self.postcond_extra is not None:
            d["postcond_extra"] = [_precond_postcond_item_to_dict(p) for p in self.postcond_extra]
        # Conditional
        if self.then_target_id is not None:
            d["then_target_id"] = self.then_target_id
        if self.else_target_id is not None:
            d["else_target_id"] = self.else_target_id
        if self.then_postcond is not None:
            d["then_postcond"] = [_precond_postcond_item_to_dict(p) for p in self.then_postcond]
        if self.else_postcond is not None:
            d["else_postcond"] = [_precond_postcond_item_to_dict(p) for p in self.else_postcond]
        # Loop
        if self.loop_invariant is not None:
            d["loop_invariant"] = [_precond_postcond_item_to_dict(p) for p in self.loop_invariant]
        if self.termination_kind is not None:
            d["termination_kind"] = self.termination_kind
        if self.termination_vars is not None:
            d["termination_vars"] = self.termination_vars
        if self.termination_sentinel is not None:
            d["termination_sentinel"] = self.termination_sentinel
        if self.termination_exit_node is not None:
            d["termination_exit_node"] = self.termination_exit_node
        if self.termination_mechanism is not None:
            d["termination_mechanism"] = self.termination_mechanism
        if self.termination_justification is not None:
            d["termination_justification"] = self.termination_justification
        if self.exit_postcond is not None:
            d["exit_postcond"] = [_precond_postcond_item_to_dict(p) for p in self.exit_postcond]
        if self.iteration_var is not None:
            d["iteration_var"] = self.iteration_var
        if self.loop_executes_at_least_once:
            d["loop_executes_at_least_once"] = True
        if self.submodule_ref is not None:
            d["submodule_ref"] = self.submodule_ref.to_dict()
        # v2 annotations
        if self.step_tag is not None:
            d["step_tag"] = self.step_tag.to_dict()
        if self.sub_goal_contributions is not None:
            d["sub_goal_contributions"] = [s.to_dict() for s in self.sub_goal_contributions]
        if self.sub_goal_verifications is not None:
            d["sub_goal_verifications"] = [s.to_dict() for s in self.sub_goal_verifications]
        if self.implicit_retries is not None:
            d["implicit_retries"] = [s.to_dict() for s in self.implicit_retries]
        if self.write_contexts is not None:
            d["write_contexts"] = [wc.to_dict() for wc in self.write_contexts]
        return d

    @staticmethod
    def from_dict(d: dict) -> "NodeIR":
        def _vp_list(key):
            return [VarPredicateIR.from_dict(p) for p in d[key]] if d.get(key) is not None else None
        def _het_list(key):
            if d.get(key) is None:
                return None
            return [_precond_postcond_item_from_dict(p) for p in d[key]]
        def _tag_list(key):
            return [SubGoalTagIR.from_dict(s) for s in d[key]] if d.get(key) is not None else None
        return NodeIR(
            id=d["id"], name=d["name"], step_type=d["step_type"],
            reads=[TypedVar.from_dict(r) for r in d["reads"]],
            writes=[TypedVar.from_dict(w) for w in d["writes"]],
            instruction=d.get("instruction"),
            precond_extra=_het_list("precond_extra"),
            postcond_extra=_het_list("postcond_extra"),
            then_target_id=d.get("then_target_id"),
            else_target_id=d.get("else_target_id"),
            then_postcond=_het_list("then_postcond"),
            else_postcond=_het_list("else_postcond"),
            loop_invariant=_het_list("loop_invariant"),
            termination_kind=d.get("termination_kind"),
            termination_vars=d.get("termination_vars"),
            termination_sentinel=d.get("termination_sentinel"),
            termination_exit_node=d.get("termination_exit_node"),
            termination_mechanism=d.get("termination_mechanism"),
            termination_justification=d.get("termination_justification"),
            exit_postcond=_het_list("exit_postcond"),
            iteration_var=d.get("iteration_var"),
            loop_executes_at_least_once=bool(d.get("loop_executes_at_least_once", False)),
            submodule_ref=SubmoduleRef.from_dict(d["submodule_ref"]) if d.get("submodule_ref") else None,
            step_tag=StepTagIR.from_dict(d["step_tag"]) if d.get("step_tag") else None,
            sub_goal_contributions=_tag_list("sub_goal_contributions"),
            sub_goal_verifications=_tag_list("sub_goal_verifications"),
            implicit_retries=_tag_list("implicit_retries"),
            write_contexts=[WriteContextIR.from_dict(w) for w in d["write_contexts"]] if d.get("write_contexts") else None,
        )


# ---------- Edge IR ----------

@dataclass
class EdgeIR:
    edge_type: str
    from_node: Optional[int] = None
    to_node: Optional[int] = None
    cond_node: Optional[int] = None
    then_entry: Optional[int] = None
    else_entry: Optional[int] = None
    header: Optional[int] = None
    body_entry: Optional[int] = None
    exit_node: Optional[int] = None
    fork_node: Optional[int] = None          # forkEdge: the fork node
    branches: Optional[list[int]] = None     # forkEdge/joinEdge/switchEdge: branch node ids
    join_node: Optional[int] = None          # joinEdge: the join node
    default_case: Optional[int] = None       # switchEdge: optional default branch

    def to_lean(self, prefix: str) -> str:
        if self.edge_type == "seq":
            return f".seqEdge {prefix}_nodeId{self.from_node} {prefix}_nodeId{self.to_node}"
        elif self.edge_type == "branch":
            if self.else_entry is None:
                return f"-- ERROR: branchEdge with None else_entry"
            return f".branchEdge {prefix}_nodeId{self.cond_node} {prefix}_nodeId{self.then_entry} {prefix}_nodeId{self.else_entry}"
        elif self.edge_type == "loop":
            if self.exit_node is None:
                return f"-- ERROR: loopEdge with None exit"
            return f".loopEdge {prefix}_nodeId{self.header} {prefix}_nodeId{self.body_entry} {prefix}_nodeId{self.exit_node}"
        elif self.edge_type == "loopBack":
            return f".loopBackEdge {prefix}_nodeId{self.from_node} {prefix}_nodeId{self.to_node}"
        elif self.edge_type == "fork" and self.fork_node is not None and self.branches:
            bl = ", ".join(f"{prefix}_nodeId{b}" for b in self.branches)
            return f".forkEdge {prefix}_nodeId{self.fork_node} [{bl}]"
        elif self.edge_type == "join" and self.branches and self.join_node is not None:
            bl = ", ".join(f"{prefix}_nodeId{b}" for b in self.branches)
            return f".joinEdge [{bl}] {prefix}_nodeId{self.join_node}"
        elif self.edge_type == "switch" and self.cond_node is not None and self.branches:
            bl = ", ".join(f"{prefix}_nodeId{b}" for b in self.branches)
            dc = (f"(some {prefix}_nodeId{self.default_case})"
                  if self.default_case is not None else "none")
            return f".switchEdge {prefix}_nodeId{self.cond_node}\n      [{bl}]\n      {dc}"
        return f"-- TODO: {self.edge_type}"

    def to_dict(self) -> dict:
        d: dict = {"edge_type": self.edge_type}
        for k in ["from_node", "to_node", "cond_node", "then_entry",
                   "else_entry", "header", "body_entry", "exit_node",
                   "fork_node", "branches", "join_node", "default_case"]:
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    @staticmethod
    def from_dict(d: dict) -> "EdgeIR":
        return EdgeIR(**{k: d.get(k) for k in
            ["edge_type", "from_node", "to_node", "cond_node", "then_entry",
             "else_entry", "header", "body_entry", "exit_node",
             "fork_node", "branches", "join_node", "default_case"]})


# ---------- ext predicate registry collection ----------

def _collect_ext_registry_entries(ir: "WorkflowIR") -> list[str]:
    """Scan all predicates for inline DictAllValuesPredicate, return unique Lean
    expressions for the PredicateRegistry.

    Each ext predicate with value_predicates generates an inline
    DictAllValuesPredicate.mk expression in to_lean(); this function
    collects the corresponding struct literals (deduplicated) so the
    Registry can reference the same DictAllValuesPredicate values.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _scan(p: PredicateIR) -> None:
        if p.kind == "ext" and p.value_predicates is not None:
            vps = ", ".join(vp.to_lean() for vp in p.value_predicates)
            dvn = f' "{p.dict_var_name}"' if p.dict_var_name else ' ""'
            expr = f"DictAllValuesPredicate.mk [{vps}]{dvn}"
            if expr not in seen:
                seen.add(expr)
                result.append(expr)
        if p.left: _scan(p.left)
        if p.right: _scan(p.right)

    def _scan_vp(vp: VarPredicateIR) -> None:
        _scan(vp.predicate)

    for n in ir.nodes:
        for tv in n.reads + n.writes:
            if tv.predicates:
                for pred in tv.predicates:
                    _scan(pred)
        for vp_list in (n.precond_extra, n.postcond_extra, n.then_postcond,
                        n.else_postcond, n.loop_invariant, n.exit_postcond):
            if vp_list:
                for vp in vp_list:
                    if isinstance(vp, VarPredicateIR):
                        _scan_vp(vp)
    if ir.param_postcond:
        for vp in ir.param_postcond:
            _scan_vp(vp)

    return result


# ---------- Workflow IR (unified) ----------

@dataclass
class WorkflowIR:
    name: str
    goal: str
    parameters: list[TypedVar]
    nodes: list[NodeIR]
    edges: list[EdgeIR]
    entry: int
    exits: list[int]
    # Workflow-level semantic metadata
    param_postcond: Optional[list[VarPredicateIR]] = None   # parameter node postconditions
    json_schemas: Optional[dict[str, JsonSchemaIR]] = None   # named schemas
    submodule_map: Optional[dict[str, "SubmoduleRef"]] = None  # name → SubmoduleRef
    # v2: graph-level goal specification for analyzeGoalCoverage
    goal_spec: Optional[GoalSpecificationIR] = None
    # Expected value of isSemanticallySoundBool (True for "good" plans, False for deliberately broken).
    # Controls the theorem emitted in _gen_semantic:
    #   True  → theorem {name}_semantically_sound     : ... = true  := by native_decide
    #   False → theorem {name}_NOT_semantically_sound : ... = false := by native_decide
    expected_semantically_sound: bool = True
    # When False, skip all Layer 1 structural theorems (_writesConsistent, ..., _seqPath_typeChecks,
    # _specCount). Some reference files omit these when a graph deliberately violates allWritesConsistent
    # (e.g. switchBranch cases that all write the same variable).
    emit_structural_theorems: bool = True

    def infer_param_postcond(self) -> None:
        """Auto-generate param_postcond from parameter predicates and tool/module existence.

        This fills in param_postcond when it is None but can be inferred:
          1. For each parameter that has predicates, emit VarPredicateIR entries.
          2. Collect all toolExists and moduleExists predicates from nodes'
             precond_extra (deduplicated).
        Sets self.param_postcond to the result, or leaves as None if not all
        parameters have predicates filled.
        """
        # Check that ALL parameters have predicates filled
        for p in self.parameters:
            if p.predicates is None:
                return  # can't infer, leave as None

        seen: set[tuple[str, str]] = set()
        result: list[VarPredicateIR] = []

        # 0. Every parameter should at least exist in the initial context.
        for p in self.parameters:
            key = (p.name, "nameExists")
            if key not in seen:
                seen.add(key)
                result.append(VarPredicateIR(p.name, PredicateIR("nameExists")))

        # 1. Parameter predicates → postconditions
        for p in self.parameters:
            for vp in p.to_var_predicates():
                key = (vp.var_name, vp.predicate.kind)
                if key not in seen:
                    seen.add(key)
                    result.append(vp)

        # 2. Collect toolExists and moduleExists from all nodes' precond_extra
        for n in self.nodes:
            if n.precond_extra:
                for pe in n.precond_extra:
                    if not isinstance(pe, VarPredicateIR):
                        continue
                    if pe.predicate.kind in ("toolExists", "moduleExists"):
                        key = (pe.var_name, pe.predicate.kind)
                        if key not in seen:
                            seen.add(key)
                            result.append(pe)

        self.param_postcond = result

    @property
    def semantic_ready(self) -> bool:
        """Check if ALL nodes have complete semantic annotations."""
        if self.param_postcond is None:
            return False
        return all(n.semantic_ready for n in self.nodes)

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name, "goal": self.goal,
            "parameters": [p.to_dict() for p in self.parameters],
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "entry": self.entry, "exits": self.exits,
        }
        if self.param_postcond is not None:
            d["param_postcond"] = [p.to_dict() for p in self.param_postcond]
        if self.json_schemas:
            d["json_schemas"] = {k: v.to_dict() for k, v in self.json_schemas.items()}
        if self.submodule_map:
            d["submodule_map"] = {k: v.to_dict() for k, v in self.submodule_map.items()}
        if self.goal_spec is not None:
            d["goal_spec"] = self.goal_spec.to_dict()
        if self.expected_semantically_sound is not True:
            d["expected_semantically_sound"] = self.expected_semantically_sound
        if self.emit_structural_theorems is not True:
            d["emit_structural_theorems"] = self.emit_structural_theorems
        return d

    @staticmethod
    def from_dict(d: dict) -> "WorkflowIR":
        ir = WorkflowIR(
            name=d["name"], goal=d["goal"],
            parameters=[TypedVar.from_dict(p) for p in d["parameters"]],
            nodes=[NodeIR.from_dict(n) for n in d["nodes"]],
            edges=[EdgeIR.from_dict(e) for e in d["edges"]],
            entry=d["entry"], exits=d["exits"],
            param_postcond=[VarPredicateIR.from_dict(p) for p in d["param_postcond"]] if d.get("param_postcond") is not None else None,
            json_schemas={k: JsonSchemaIR.from_dict(v) for k, v in d["json_schemas"].items()} if d.get("json_schemas") else None,
            submodule_map={k: SubmoduleRef.from_dict(v) for k, v in d["submodule_map"].items()} if d.get("submodule_map") else None,
            goal_spec=GoalSpecificationIR.from_dict(d["goal_spec"]) if d.get("goal_spec") else None,
            expected_semantically_sound=d.get("expected_semantically_sound", True),
            emit_structural_theorems=d.get("emit_structural_theorems", True),
        )
        # Auto-infer param_postcond if not explicitly provided
        if ir.param_postcond is None:
            ir.infer_param_postcond()
        return ir

    def save_json(self, path: str, indent: int = 2) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent, ensure_ascii=False)

    @staticmethod
    def load_json(path: str) -> "WorkflowIR":
        with open(path, "r", encoding="utf-8") as f:
            return WorkflowIR.from_dict(json.load(f))


# ============================================================================
# 2. PARSER (Layer 1 only — semantic fields left as None)
# ============================================================================

def extract_template_vars(text: str) -> list[str]:
    """Extract {{var}} or {{var.field}} references from text."""
    if not text:
        return []
    return sorted(set(re.findall(r'\{\{(\w+)(?:\.\w+)*\}\}', text)))


def _collect_template_vars_recursive(data) -> set[str]:
    """Recursively collect all {{var}} template references from any nested data."""
    result: set[str] = set()
    if isinstance(data, str):
        result.update(extract_template_vars(data))
    elif isinstance(data, dict):
        for v in data.values():
            result.update(_collect_template_vars_recursive(v))
    elif isinstance(data, list):
        for item in data:
            result.update(_collect_template_vars_recursive(item))
    return result

def determine_write_type(yaml_key: str) -> str:
    """Map YAML step type to Lean output BaseType."""
    mapping = {
        "step": "TString", "task": "TString",
        "input": "TString", "incrementVariable": "TInt",
        "parallel": "TList TUnknown", "call": "TUnknown",
        "gather": "TList TUnknown", "setVariable": "TString",
    }
    return mapping.get(yaml_key, "TString")

def yaml_key_to_step_type(yaml_key: str) -> str:
    """Map YAML step key to Lean StepType name."""
    mapping = {
        "step": "step", "task": "task", "set_variable": "setVariable",
        "parallel": "parallel", "for_each": "forEachLoop",
        "while": "whileLoop", "if": "conditional", "switch": "switchBranch",
        "call": "call", "gather": "gather", "input": "input",
        "return": "returnValue",
        "increment": "incrementVariable",
    }
    # AgentSPEX engine: `discover/synthesize/validate/save/evaluate` were removed from StepType, so they are intentionally absent from this map; a NEW-format plan never produces them (the parser rejects them upstream).
    return mapping.get(yaml_key, "step")

def _load_env_file(env_path: str) -> None:
    """Load KEY=VALUE pairs from an env file into os.environ.
    Supports comments (#), empty lines, and optional quoting.
    """
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip optional surrounding quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            os.environ[key] = val


def _resolve_env_vars(value):
    """Resolve ${VAR_NAME} environment variable references in parameter values.

    - Only processes string values; non-strings are returned as-is.
    - Full match (entire value is "${VAR}"): replaced by env var value.
      If the env var looks like an int/bool/float, the Python type is preserved.
    - Partial match ("prefix_${VAR}_suffix"): string substitution only.
    - Unresolvable references are kept as-is.
    """
    if not isinstance(value, str):
        return value

    # Full match: entire value is a single ${VAR}
    m = re.fullmatch(r'\$\{(\w+)\}', value)
    if m:
        env_name = m.group(1)
        resolved = os.environ.get(env_name)
        if resolved is not None:
            # Try to parse as typed value (bool/int/float)
            if resolved.lower() in ('true', 'false'):
                return resolved.lower() == 'true'
            try:
                return int(resolved)
            except ValueError:
                pass
            try:
                return float(resolved)
            except ValueError:
                pass
            return resolved
        return value  # env var not found, keep original

    # Partial match: substitute all ${VAR} occurrences within the string
    def _replace(match):
        env_name = match.group(1)
        return os.environ.get(env_name, match.group(0))

    return re.sub(r'\$\{(\w+)\}', _replace, value)


def _infer_param_type(value) -> str:
    """Infer Lean BaseType from a JSON parameter value."""
    if isinstance(value, bool):
        return "TBool"
    if isinstance(value, int):
        return "TInt"
    if isinstance(value, float):
        return "TFloat"
    if isinstance(value, list):
        return "TList TUnknown"
    if isinstance(value, dict):
        return "TJson"
    return "TString"

def _infer_set_variable_type(raw_value, type_ctx: dict[str, str]) -> str:
    """Infer set_variable output type.

    For a pure passthrough template like "{{x}}", keep x's existing type.
    Otherwise infer from the literal value itself.
    """
    if isinstance(raw_value, str):
        m = re.fullmatch(r'\s*\{\{(\w+)(?:\.\w+)*\}\}\s*', raw_value)
        if m:
            return type_ctx.get(m.group(1), "TString")
    return _infer_param_type(raw_value)

def _extract_condition_vars(condition: str) -> list[str]:
    """Extract variable names from a condition string, handling broader operators."""
    tmpl_vars = extract_template_vars(condition)
    # Only treat identifier-like tokens as variables; avoid numeric literals such as
    # "0" from conditions like "is_verified >= 0.5".
    ident = r'([A-Za-z_]\w*)'
    expr_vars = re.findall(rf'{ident}\s*(?:<=|>=|<|>|==|!=)', condition)
    expr_vars += re.findall(rf'(?:<=|>=|<|>|==|!=)\s*{ident}', condition)
    keywords = {'and', 'or', 'true', 'false', 'True', 'False', 'None', 'not'}
    return sorted(set(v for v in (tmpl_vars + expr_vars) if v not in keywords))

def parse_task_json(json_path: str) -> WorkflowIR:
    """Parse parsed_task.json → WorkflowIR (structural only, semantic=None)."""
    with open(json_path) as f:
        data = json.load(f)

    wf_name = data["name"]
    wf_goal = data.get("goal", "")

    # Parameters: resolve env vars, infer types, preserve values
    params = []
    param_names = set()
    raw_params = data.get("parameters", {})
    for pname, pval in raw_params.items():
        pval = _resolve_env_vars(pval)
        ptype = _infer_param_type(pval)
        params.append(TypedVar(pname, ptype, value=pval))
        param_names.add(pname)

    type_ctx: dict[str, str] = {p.name: p.base_type for p in params}
    nodes: list[NodeIR] = []
    edges: list[EdgeIR] = []
    nid = 0
    loop_patches: list[dict] = []

    def alloc_id() -> int:
        nonlocal nid; cur = nid; nid += 1; return cur
    def resolve_type(v: str) -> str:
        return type_ctx.get(v, "TString")
    def build_reads(vs: list[str]) -> list[TypedVar]:
        return [TypedVar(v, resolve_type(v)) for v in vs]
    def add_seq(f: Optional[int], t: int):
        if f is not None: edges.append(EdgeIR("seq", from_node=f, to_node=t))

    def parse_body_steps(body_steps: list, body_prev: Optional[int]) -> tuple:
        """Recursively parse steps inside any body block.
        Returns (first_node_id, last_node_id, extra_tails).
        extra_tails: list of node ids that are also tail nodes (e.g. from
        the other branch of an if at the end of the body).
        """
        bf: Optional[int] = None
        extra_tails: list[int] = []

        def link_to(new_id: int) -> None:
            """Connect the current flow and any pending branch tails to new_id."""
            nonlocal extra_tails
            add_seq(body_prev, new_id)
            if extra_tails:
                for tail_id in list(dict.fromkeys(extra_tails)):
                    add_seq(tail_id, new_id)
                extra_tails = []

        for bs in body_steps:
            bk = list(bs.keys())[0]
            bd = bs[bk]

            if bk in ("step", "task"):
                bid = alloc_id()
                bname = bd.get("name", f"{bk}_{bid}")
                binstr = bd.get("instruction", "")
                bsave = bd.get("save_as", None)
                breads = build_reads(extract_template_vars(binstr))
                bwrites = []
                if bsave:
                    bwt = determine_write_type(bk)
                    bwrites.append(TypedVar(bsave, bwt))
                    type_ctx[bsave] = bwt
                nodes.append(NodeIR(
                    id=bid, name=bname, step_type=yaml_key_to_step_type(bk),
                    reads=breads, writes=bwrites,
                    instruction=binstr if binstr else None,
                ))
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            elif bk == "set_variable":
                bid = alloc_id()
                bvar = bd["name"]
                raw_val = bd.get("value", "")
                bval = str(raw_val)
                breads = build_reads(extract_template_vars(bval))
                bwt = _infer_set_variable_type(raw_val, type_ctx)
                bwrites = [TypedVar(bvar, bwt)]
                type_ctx[bvar] = bwt
                nodes.append(NodeIR(
                    id=bid, name=f"set_{bvar}", step_type="setVariable",
                    reads=breads, writes=bwrites,
                ))
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            elif bk == "for_each":
                hid = alloc_id()
                lvar = bd["variable"]; llist = bd["in"]
                lt = type_ctx.get(llist, "TString")
                if lt.startswith("TList"):
                    lparts = lt.split(maxsplit=1)
                    et = lparts[1] if len(lparts) > 1 else "TUnknown"
                else:
                    et = "TUnknown"
                type_ctx[lvar] = et
                nodes.append(NodeIR(
                    id=hid, name=f"foreach_{lvar}", step_type="forEachLoop",
                    reads=[TypedVar(llist, lt)], writes=[TypedVar(lvar, et)],
                ))
                link_to(hid)
                if bf is None: bf = hid
                inner_first, inner_last, inner_extra = parse_body_steps(bd.get("steps", []), None)
                if inner_first is not None and inner_last is not None:
                    le_idx = len(edges)
                    edges.append(EdgeIR("loop", header=hid, body_entry=inner_first, exit_node=None))
                    edges.append(EdgeIR("loopBack", from_node=inner_last, to_node=hid))
                    for et_id in inner_extra:
                        edges.append(EdgeIR("loopBack", from_node=et_id, to_node=hid))
                    loop_patches.append({'edge_idx': le_idx, 'header_id': hid})
                body_prev = hid

            elif bk == "while":
                bhdr_id = alloc_id()
                bcondition = bd.get("condition", "")
                breads = build_reads(_extract_condition_vars(bcondition))
                nodes.append(NodeIR(
                    id=bhdr_id, name=f"while_{bcondition[:30]}", step_type="whileLoop",
                    reads=breads, writes=[],
                ))
                link_to(bhdr_id)
                if bf is None: bf = bhdr_id
                binner_first, binner_last, binner_extra = parse_body_steps(bd.get("steps", []), None)
                if binner_first is not None and binner_last is not None:
                    ble_idx = len(edges)
                    edges.append(EdgeIR("loop", header=bhdr_id, body_entry=binner_first, exit_node=None))
                    edges.append(EdgeIR("loopBack", from_node=binner_last, to_node=bhdr_id))
                    for et_id in binner_extra:
                        edges.append(EdgeIR("loopBack", from_node=et_id, to_node=bhdr_id))
                    loop_patches.append({'edge_idx': ble_idx, 'header_id': bhdr_id})
                body_prev = bhdr_id

            elif bk == "if":
                bcond_id = alloc_id()
                bcondition = bd.get("condition", "")
                breads = build_reads(_extract_condition_vars(bcondition))
                nodes.append(NodeIR(
                    id=bcond_id, name=f"check_{bcondition[:30]}", step_type="conditional",
                    reads=breads, writes=[],
                ))
                link_to(bcond_id)
                if bf is None: bf = bcond_id
                bthen_first, bthen_last, bthen_extra = parse_body_steps(bd.get("then", []), None)
                belse_first, belse_last, belse_extra = parse_body_steps(bd.get("else", []), None)
                edges.append(EdgeIR("branch", cond_node=bcond_id, then_entry=bthen_first, else_entry=belse_first))
                extra_tails.extend(bthen_extra)
                extra_tails.extend(belse_extra)
                # If there is no else branch, false-path should fall through to the
                # node after this conditional. If this is the last node in the body,
                # the caller will connect this tail to the enclosing merge/loop back.
                if belse_first is None:
                    extra_tails.append(bcond_id)
                if belse_last is not None and bthen_last is not None:
                    body_prev = belse_last
                    extra_tails.append(bthen_last)
                elif belse_last is not None:
                    body_prev = belse_last
                elif bthen_last is not None:
                    body_prev = bthen_last
                else:
                    body_prev = bcond_id

            elif bk == "parallel":
                if isinstance(bd, list):
                    # Inline parallel: fork → sub-task nodes → join
                    bfork_id = alloc_id()
                    nodes.append(NodeIR(
                        id=bfork_id, name=f"parallel_fork_{bfork_id}", step_type="parallel",
                        reads=[], writes=[],
                    ))
                    link_to(bfork_id)
                    if bf is None: bf = bfork_id

                    bbranch_entries = []
                    bbranch_exits = []
                    for bsub_step in bd:
                        bsub_first, bsub_last, bsub_extra = parse_body_steps([bsub_step], None)
                        if bsub_first is not None:
                            bbranch_entries.append(bsub_first)
                        if bsub_last is not None:
                            bbranch_exits.append(bsub_last)
                        bbranch_exits.extend(bsub_extra)

                    bjoin_id = alloc_id()
                    nodes.append(NodeIR(
                        id=bjoin_id, name=f"parallel_join_{bjoin_id}", step_type="parallel",
                        reads=[], writes=[],
                    ))
                    if bbranch_entries:
                        edges.append(EdgeIR("fork", fork_node=bfork_id, branches=bbranch_entries))
                    if bbranch_exits:
                        edges.append(EdgeIR("join", branches=list(dict.fromkeys(bbranch_exits)), join_node=bjoin_id))
                    body_prev = bjoin_id
                else:
                    # Dict-based parallel (submodule invocation)
                    bid = alloc_id()
                    bpl = bd.get("parameters_list", "")
                    bsave = bd.get("save_results_as", None)
                    breads = build_reads([bpl]) if bpl else []
                    bwrites = []
                    if bsave:
                        bwrites.append(TypedVar(bsave, "TList TUnknown"))
                        type_ctx[bsave] = "TList TUnknown"
                    nodes.append(NodeIR(
                        id=bid, name=f"parallel_{bsave or bid}", step_type="parallel",
                        reads=breads, writes=bwrites,
                    ))
                    link_to(bid)
                    if bf is None: bf = bid
                    body_prev = bid

            elif bk == "call":
                bid = alloc_id()
                bmodule = bd.get("module", "")
                bsave = bd.get("save_as", None)
                bcall_params = bd.get("parameters", {})
                bread_vars = []
                for pval in bcall_params.values():
                    bread_vars.extend(extract_template_vars(str(pval)))
                breads = build_reads(sorted(set(bread_vars)))
                bwrites = []
                if bsave:
                    bwt = determine_write_type("call")
                    bwrites.append(TypedVar(bsave, bwt))
                    type_ctx[bsave] = bwt
                bmod_name = bmodule.split("/")[-1].replace(".yaml", "") if bmodule else f"call_{bid}"
                nodes.append(NodeIR(
                    id=bid, name=f"call_{bmod_name}", step_type="call",
                    reads=breads, writes=bwrites,
                    instruction=f"Call module: {bmodule}" if bmodule else None,
                ))
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            elif bk == "increment":
                bid = alloc_id()
                bvar = bd if isinstance(bd, str) else str(bd)
                nodes.append(NodeIR(
                    id=bid, name=f"increment_{bvar}", step_type="incrementVariable",
                    reads=build_reads([bvar]), writes=[TypedVar(bvar, "TInt")],
                ))
                type_ctx[bvar] = "TInt"
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            elif bk == "return":
                bid = alloc_id()
                ret_var = bd if isinstance(bd, str) else str(bd)
                nodes.append(NodeIR(
                    id=bid, name="return_result", step_type="returnValue",
                    reads=build_reads([ret_var]), writes=[],
                ))
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            elif bk == "discover":
                bid = alloc_id()
                disc_name = bd.get("name", f"discover_{bid}")
                disc_from = bd.get("from", "")
                disc_instr = bd.get("instruction", "")
                # reads: template vars from both 'from' and 'instruction'
                read_vars = extract_template_vars(disc_from) + extract_template_vars(disc_instr)
                breads = build_reads(sorted(set(read_vars)))
                bwt = determine_write_type("discover")
                bwrites = [TypedVar(disc_name, bwt)]
                type_ctx[disc_name] = bwt
                nodes.append(NodeIR(
                    id=bid, name=disc_name, step_type=yaml_key_to_step_type("discover"),
                    reads=breads, writes=bwrites,
                    instruction=disc_instr if disc_instr else None,
                ))
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            elif bk in ("evaluate", "validate"):
                bid = alloc_id()
                out_name = bd.get("name", f"{bk}_{bid}")
                step_instr = bd.get("instruction", "")
                read_vars = extract_template_vars(step_instr)
                breads = build_reads(sorted(set(read_vars)))
                bwt = determine_write_type(bk)
                bwrites = [TypedVar(out_name, bwt)]
                type_ctx[out_name] = bwt
                nodes.append(NodeIR(
                    id=bid, name=out_name, step_type=yaml_key_to_step_type(bk),
                    reads=breads, writes=bwrites,
                    instruction=step_instr if step_instr else None,
                ))
                link_to(bid)
                if bf is None: bf = bid
                body_prev = bid

            else:
                print(f"[WARN] Unhandled step type in body: {bk}")

        return bf, body_prev, extra_tails

    # ---- Top-level workflow steps ----
    prev: Optional[int] = None

    for raw_step in data["workflow"]:
        yaml_key = list(raw_step.keys())[0]
        step_data = raw_step[yaml_key]

        if yaml_key in ("step", "task"):
            cur = alloc_id()
            name = step_data.get("name", f"{yaml_key}_{cur}")
            instruction = step_data.get("instruction", "")
            save_as = step_data.get("save_as", None)
            reads = build_reads(extract_template_vars(instruction))
            writes = []
            if save_as:
                wt = determine_write_type(yaml_key)
                writes.append(TypedVar(save_as, wt))
                type_ctx[save_as] = wt
            nodes.append(NodeIR(
                id=cur, name=name, step_type=yaml_key_to_step_type(yaml_key),
                reads=reads, writes=writes,
                instruction=instruction if instruction else None,
            ))
            add_seq(prev, cur); prev = cur

        elif yaml_key == "set_variable":
            cur = alloc_id()
            var_name = step_data["name"]
            raw_value = step_data.get("value", "")
            value_str = str(raw_value)
            reads = build_reads(extract_template_vars(value_str))
            wt = _infer_set_variable_type(raw_value, type_ctx)
            writes = [TypedVar(var_name, wt)]
            type_ctx[var_name] = wt
            nodes.append(NodeIR(
                id=cur, name=f"set_{var_name}", step_type="setVariable",
                reads=reads, writes=writes,
            ))
            add_seq(prev, cur); prev = cur

        elif yaml_key == "parallel":
            if isinstance(step_data, list):
                # Inline parallel: fork → sub-task nodes → join
                # Uses forkEdge/joinEdge so Lean's isParallelScopedNode
                # correctly scopes sub-task writes (not visible outside).
                fork_id = alloc_id()
                nodes.append(NodeIR(
                    id=fork_id, name=f"parallel_fork_{fork_id}", step_type="parallel",
                    reads=[], writes=[],
                ))
                add_seq(prev, fork_id)

                branch_entries = []
                branch_exits = []
                for sub_step in step_data:
                    sub_first, sub_last, sub_extra = parse_body_steps([sub_step], None)
                    if sub_first is not None:
                        branch_entries.append(sub_first)
                    if sub_last is not None:
                        branch_exits.append(sub_last)
                    branch_exits.extend(sub_extra)

                join_id = alloc_id()
                nodes.append(NodeIR(
                    id=join_id, name=f"parallel_join_{join_id}", step_type="parallel",
                    reads=[], writes=[],
                ))
                if branch_entries:
                    edges.append(EdgeIR("fork", fork_node=fork_id, branches=branch_entries))
                if branch_exits:
                    edges.append(EdgeIR("join", branches=list(dict.fromkeys(branch_exits)), join_node=join_id))
                prev = join_id
            else:
                # Dict-based parallel (submodule invocation)
                cur = alloc_id()
                params_list_var = step_data.get("parameters_list", "")
                save_as = step_data.get("save_results_as", None)
                module_path = step_data.get("module", "")
                reads = build_reads([params_list_var]) if params_list_var else []
                writes = []
                if save_as:
                    writes.append(TypedVar(save_as, "TList TUnknown"))
                    type_ctx[save_as] = "TList TUnknown"
                sub_ref = None
                if module_path:
                    sub_name = module_path.split("/")[-1].replace(".yaml", "")
                    sub_ref = SubmoduleRef(name=sub_name, kind="parallel",
                                           output_var=save_as, input_var=params_list_var or None)
                nodes.append(NodeIR(
                    id=cur, name=f"parallel_{save_as or cur}", step_type="parallel",
                    reads=reads, writes=writes,
                    submodule_ref=sub_ref,
                ))
                add_seq(prev, cur); prev = cur

        elif yaml_key == "for_each":
            header_id = alloc_id()
            loop_var = step_data["variable"]; list_var = step_data["in"]
            list_type = type_ctx.get(list_var, "TString")
            if list_type.startswith("TList"):
                parts = list_type.split(maxsplit=1)
                elem_type = parts[1] if len(parts) > 1 else "TUnknown"
            else:
                elem_type = "TUnknown"
            type_ctx[loop_var] = elem_type
            nodes.append(NodeIR(
                id=header_id, name=f"foreach_{loop_var}", step_type="forEachLoop",
                reads=[TypedVar(list_var, list_type)], writes=[TypedVar(loop_var, elem_type)],
            ))
            add_seq(prev, header_id)
            body_first, body_last, body_extra = parse_body_steps(step_data.get("steps", []), None)
            if body_first is not None and body_last is not None:
                loop_edge_idx = len(edges)
                edges.append(EdgeIR("loop", header=header_id, body_entry=body_first, exit_node=None))
                edges.append(EdgeIR("loopBack", from_node=body_last, to_node=header_id))
                for et_id in body_extra:
                    edges.append(EdgeIR("loopBack", from_node=et_id, to_node=header_id))
                loop_patches.append({'edge_idx': loop_edge_idx, 'header_id': header_id})
            prev = header_id

        elif yaml_key == "while":
            header_id = alloc_id()
            condition = step_data.get("condition", "")
            reads = build_reads(_extract_condition_vars(condition))
            nodes.append(NodeIR(
                id=header_id, name=f"while_{condition[:30]}", step_type="whileLoop",
                reads=reads, writes=[],
            ))
            add_seq(prev, header_id)
            body_first, body_last, body_extra = parse_body_steps(step_data.get("steps", []), None)
            if body_first is not None and body_last is not None:
                loop_edge_idx = len(edges)
                edges.append(EdgeIR("loop", header=header_id, body_entry=body_first, exit_node=None))
                edges.append(EdgeIR("loopBack", from_node=body_last, to_node=header_id))
                for et_id in body_extra:
                    edges.append(EdgeIR("loopBack", from_node=et_id, to_node=header_id))
                loop_patches.append({'edge_idx': loop_edge_idx, 'header_id': header_id})
            prev = header_id

        elif yaml_key == "call":
            cur = alloc_id()
            module = step_data.get("module", "")
            save_as = step_data.get("save_as", None)
            call_params = step_data.get("parameters", {})
            read_vars = []
            for pval in call_params.values():
                read_vars.extend(extract_template_vars(str(pval)))
            reads = build_reads(sorted(set(read_vars)))
            writes = []
            if save_as:
                wt = determine_write_type("call")
                writes.append(TypedVar(save_as, wt))
                type_ctx[save_as] = wt
            module_name = module.split("/")[-1].replace(".yaml", "") if module else f"call_{cur}"
            sub_ref = None
            if module:
                sub_ref = SubmoduleRef(name=module_name, kind="call", output_var=save_as)
            nodes.append(NodeIR(
                id=cur, name=f"call_{module_name}", step_type="call",
                reads=reads, writes=writes,
                instruction=f"Call module: {module}" if module else None,
                submodule_ref=sub_ref,
            ))
            add_seq(prev, cur); prev = cur

        elif yaml_key == "increment":
            cur = alloc_id()
            var_name = step_data if isinstance(step_data, str) else str(step_data)
            reads = build_reads([var_name])
            writes = [TypedVar(var_name, "TInt")]
            type_ctx[var_name] = "TInt"
            nodes.append(NodeIR(
                id=cur, name=f"increment_{var_name}", step_type="incrementVariable",
                reads=reads, writes=writes,
            ))
            add_seq(prev, cur); prev = cur

        elif yaml_key == "if":
            cond_id = alloc_id()
            condition = step_data.get("condition", "")
            reads = build_reads(_extract_condition_vars(condition))
            nodes.append(NodeIR(
                id=cond_id, name=f"check_{condition[:30]}", step_type="conditional",
                reads=reads, writes=[],
            ))
            add_seq(prev, cond_id)
            # Use parse_body_steps for branches (handles all step types)
            then_first, then_last, _ = parse_body_steps(step_data.get("then", []), None)
            else_first, else_last, _ = parse_body_steps(step_data.get("else", []), None)
            branch_edge_idx = len(edges)
            edges.append(EdgeIR("branch", cond_node=cond_id, then_entry=then_first, else_entry=else_first))
            if not hasattr(parse_task_json, '_pending_branches'):
                parse_task_json._pending_branches = []
            parse_task_json._pending_branches.append({
                'cond_id': cond_id, 'then_last': then_last,
                'else_last': else_last, 'has_else': else_first is not None, 'cond_id': cond_id,
            })
            if else_last is not None: prev = else_last
            elif then_last is not None: prev = then_last
            else: prev = cond_id

        elif yaml_key == "return":
            cur = alloc_id()
            ret_var = step_data if isinstance(step_data, str) else str(step_data)
            nodes.append(NodeIR(
                id=cur, name="return_result", step_type="returnValue",
                reads=build_reads([ret_var]), writes=[],
            ))
            add_seq(prev, cur); prev = cur

        elif yaml_key == "discover":
            cur = alloc_id()
            disc_name = step_data.get("name", f"discover_{cur}")
            disc_from = step_data.get("from", "")
            disc_instr = step_data.get("instruction", "")
            # reads: template vars from both 'from' and 'instruction'
            read_vars = extract_template_vars(disc_from) + extract_template_vars(disc_instr)
            reads = build_reads(sorted(set(read_vars)))
            wt = determine_write_type("discover")
            writes = [TypedVar(disc_name, wt)]
            type_ctx[disc_name] = wt
            nodes.append(NodeIR(
                id=cur, name=disc_name, step_type=yaml_key_to_step_type("discover"),
                reads=reads, writes=writes,
                instruction=disc_instr if disc_instr else None,
            ))
            add_seq(prev, cur); prev = cur

        elif yaml_key in ("evaluate", "validate"):
            cur = alloc_id()
            out_name = step_data.get("name", f"{yaml_key}_{cur}")
            step_instr = step_data.get("instruction", "")
            read_vars = extract_template_vars(step_instr)
            reads = build_reads(sorted(set(read_vars)))
            wt = determine_write_type(yaml_key)
            writes = [TypedVar(out_name, wt)]
            type_ctx[out_name] = wt
            nodes.append(NodeIR(
                id=cur, name=out_name, step_type=yaml_key_to_step_type(yaml_key),
                reads=reads, writes=writes,
                instruction=step_instr if step_instr else None,
            ))
            add_seq(prev, cur); prev = cur

        else:
            print(f"[WARN] Unhandled step type: {yaml_key}")

    # ---- Patch loop exits ----
    for loop_info in loop_patches:
        edge_idx = loop_info['edge_idx']
        header_id = loop_info['header_id']
        found = False
        for i, e in enumerate(edges):
            if e is not None and e.edge_type == "seq" and e.from_node == header_id:
                edges[edge_idx].exit_node = e.to_node
                edges[i] = None
                found = True
                break
        if not found:
            # No subsequent step after the loop (loop is the last step in the
            # workflow).  Use the header itself as exit so the loopEdge is still
            # valid.  This mirrors the infinite-while-loop pattern where exit
            # points back to the header.
            edges[edge_idx].exit_node = header_id
    edges[:] = [e for e in edges if e is not None]

    # ---- Patch branch edges ----
    if hasattr(parse_task_json, '_pending_branches'):
        for branch_info in parse_task_json._pending_branches:
            cond_id = branch_info['cond_id']
            branch_edge = next(
                (e for e in edges if e.edge_type == "branch" and e.cond_node == cond_id),
                None,
            )
            if branch_edge is None:
                # Defensive: if the edge was removed/rewritten unexpectedly,
                # skip patching this branch instead of crashing.
                continue
            then_last = branch_info['then_last']
            then_first = branch_edge.then_entry
            else_last = branch_info['else_last']
            has_else = branch_info['has_else']
            merge_point = None
            search_from = then_last if then_last is not None else cond_id
            for e in edges:
                if e.edge_type == "seq" and e.from_node == search_from:
                    merge_point = e.to_node
                    break
            # Fallback for then-only branches whose then path is a loop body.
            # In this case, there may be no seq edge from then_last to the
            # post-if node; use the loopEdge exit as the merge point.
            if merge_point is None and not has_else:
                loop_header = None
                if then_first is not None:
                    for e in edges:
                        if e.edge_type == "loop" and e.header == then_first:
                            loop_header = then_first
                            merge_point = e.exit_node
                            break
                if merge_point is None and then_last is not None:
                    for e in edges:
                        if e.edge_type == "loopBack" and e.from_node == then_last:
                            loop_header = e.to_node
                            break
                    if loop_header is not None:
                        for e in edges:
                            if e.edge_type == "loop" and e.header == loop_header:
                                merge_point = e.exit_node
                                break
            if merge_point is not None:
                if not has_else:
                    branch_edge.else_entry = merge_point
                else:
                    if else_last is not None:
                        edges.append(EdgeIR("seq", from_node=else_last, to_node=merge_point))
        parse_task_json._pending_branches = []

    # ---- Fill missing else_entry for branch edges ----
    # For conditionals without an explicit else branch, wire the false-path to
    # the conditional's fallthrough/exit node (the first seq/loopBack out-edge).
    for e in edges:
        if e.edge_type == "branch" and e.else_entry is None and e.cond_node is not None:
            fallthrough = None
            for oe in edges:
                if oe.edge_type == "seq" and oe.from_node == e.cond_node:
                    fallthrough = oe.to_node
                    break
            if fallthrough is None:
                for oe in edges:
                    if oe.edge_type == "loopBack" and oe.from_node == e.cond_node:
                        fallthrough = oe.to_node
                        break
            if fallthrough is not None:
                e.else_entry = fallthrough

    # Collect submodule_map from all nodes that have a submodule_ref
    sub_map: dict[str, SubmoduleRef] = {}
    for n in nodes:
        if n.submodule_ref is not None and n.submodule_ref.name not in sub_map:
            sub_map[n.submodule_ref.name] = n.submodule_ref

    return WorkflowIR(
        name=wf_name, goal=wf_goal, parameters=params,
        nodes=nodes, edges=edges, entry=0,
        exits=[nodes[-1].id] if nodes else [],
        submodule_map=sub_map if sub_map else None,
    )


# ============================================================================
# 3. LEAN CODE GENERATOR
# ============================================================================

def _gen_submodule_sections(ir: "WorkflowIR", prefix: str) -> list[str]:
    """Generate Section A + B Lean code for each submodule dependency that has Lean info."""
    if not ir.submodule_map:
        return []
    lines = []
    for sub_name, sub_ref in ir.submodule_map.items():
        if not sub_ref.lean_prefix:
            continue  # No Lean integration info yet — skip
        kind_label = {"parallel": "parallel module call",
                      "call": "sequential module call",
                      "gather": "gather module calls"}.get(sub_ref.kind, sub_ref.kind)
        # Lean symbol names
        abbrev_sem  = f"{prefix}_{sub_name}SemanticGraph"
        thm_name    = f"{prefix}_{sub_name}Sound"
        spec_name   = f"{prefix}_{sub_name}Spec"

        lines += [
            "/-",
            "=" * 72,
            f"SUBMODULE INTEGRATION: {sub_name} ({kind_label})",
            "=" * 72,
            "-/",
            "",
            "-- Section A: Abbreviation + soundness bridge",
            f"abbrev {abbrev_sem} := {sub_ref.semantic_graph_lean}",
            "",
            f"theorem {thm_name} :",
            f"    {abbrev_sem}.isSemanticallySoundBool emptyRegistry = true :=",
            f"  {sub_ref.soundness_thm_lean}",
            "",
            "-- Section B: SubmoduleNode",
            f"def {spec_name} : SubmoduleNode :=",
            f'  makeSubmoduleNode "{sub_name}"',
            f"    {abbrev_sem}",
            f"    emptyRegistry",
            f"    {thm_name}",
            "",
        ]
    return lines


def _gen_goal_spec(ir: WorkflowIR, prefix: str) -> list[str]:
    """Generate STEP 7: GoalSpecification + analyzeGoalCoverage #eval block."""
    lines: list[str] = []
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 7: GRAPH-LEVEL WORKFLOW QUALITY ANALYSIS")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    assert ir.goal_spec is not None
    lines.append(ir.goal_spec.to_lean(prefix))
    lines.append("")
    lines.append("#eval do")
    lines.append(f"  let report := analyzeGoalCoverage {prefix}SemanticGraph {prefix}_goalSpec")
    lines.append("  IO.println (formatGoalCoverageReport report)")
    lines.append("")
    return lines


def generate_lean(
    ir: WorkflowIR,
    prefix: str,
    extra_imports: Optional[list[str]] = None,
    extra_tail: Optional[list[str]] = None,
) -> str:
    """Emit the full Lean source for a Layer 1/2 workflow verification.

    Optional hooks for Layer 3 composition:
      - extra_imports: lines appended to the import block (after the standard
        AgentVerifier imports, before the `namespace AgenticKernel` line).
      - extra_tail:   lines appended between the last Layer 2 section and the
        final `end AgenticKernel` line.
    """
    lines = []
    can_semantic = ir.semantic_ready

    # Propagate lean_import/lean_prefix from ir.submodule_map into each node's
    # submodule_ref so that _gen_semantic_node can use them.
    if ir.submodule_map:
        for n in ir.nodes:
            if n.submodule_ref is not None and n.submodule_ref.name in ir.submodule_map:
                master = ir.submodule_map[n.submodule_ref.name]
                if master.lean_prefix and not n.submodule_ref.lean_prefix:
                    n.submodule_ref.lean_prefix = master.lean_prefix
                if master.lean_import and not n.submodule_ref.lean_import:
                    n.submodule_ref.lean_import = master.lean_import

    # Header
    lines.append("import Lean")
    lines.append("import Mathlib")
    lines.append("import AgentVerifier.StaticLayer")
    lines.append("import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer")
    if ir.goal_spec is not None:
        lines.append("import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates")
    if ir.submodule_map:
        for sub_ref in ir.submodule_map.values():
            if sub_ref.lean_import:
                lines.append(f"-- Import verified submodule: {sub_ref.name}")
                lines.append(f"import {sub_ref.lean_import}")
    if extra_imports:
        for imp in extra_imports:
            lines.append(imp)
    lines.append("")
    lines.append("namespace AgenticKernel")
    lines.append("")

    # Comment header
    lines.append("/-")
    lines.append("=" * 80)
    lines.append(f"STATIC VERIFICATION: {ir.name}")
    lines.append(f"Goal: {ir.goal}")
    lines.append(f"Parameters: {[p.name for p in ir.parameters]}")
    lines.append(f"Nodes: {len(ir.nodes)}, Entry: {ir.entry}, Exits: {ir.exits}")
    lines.append(f"Semantic layer: {'READY' if can_semantic else 'INCOMPLETE'}")
    lines.append("")
    for n in ir.nodes:
        rstr = ", ".join(r.name for r in n.reads) or "(none)"
        wstr = ", ".join(w.name for w in n.writes) or "(none)"
        tag = "[DET]" if not n.needs_spec else ("[READY]" if n.semantic_ready else "[TODO]")
        lines.append(f"  Node {n.id:3d}: {n.step_type:16s} {tag:8s} \"{n.name}\"")
        lines.append(f"          reads:  {rstr}")
        lines.append(f"          writes: {wstr}")
    lines.append("=" * 80)
    lines.append("-/")
    lines.append("")

    # Named schemas
    if ir.json_schemas:
        for sname, schema in ir.json_schemas.items():
            lines.append(f"def {sname} : JsonSchema :=")
            lines.append(f"  {schema.to_lean()}")
            lines.append("")

    # Ext predicates → Registry
    # DictAllValuesPredicate expressions are generated inline in each node's
    # predicates via PredicateIR.to_lean(); here we only need to collect all
    # unique DictAllValuesPredicate values used across nodes and build the
    # PredicateRegistry so that verify() can resolve .ext keys.
    registry_name = "emptyRegistry"
    ext_entries = _collect_ext_registry_entries(ir)
    if ext_entries:
        registry_name = f"{prefix}Registry"
        lines.append(f"def {registry_name} : PredicateRegistry :=")
        if len(ext_entries) == 1:
            lines.append(f"  makeDictAllValuesRegistry [{ext_entries[0]}]")
        else:
            entries_str = ",\n    ".join(ext_entries)
            lines.append(f"  makeDictAllValuesRegistry [\n    {entries_str}\n  ]")
        lines.append("")

    # ---- Submodule integration sections A + B ----
    lines.extend(_gen_submodule_sections(ir, prefix))

    # ---- STEP 1: Structural node definitions ----
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 1: WORKFLOW GRAPH")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    lines.append("-- Node IDs")
    for n in ir.nodes:
        lines.append(f"def {prefix}_nodeId{n.id} : NodeId := ⟨{n.id}⟩")
    lines.append("")

    for n in ir.nodes:
        ri = ", ".join(v.to_lean_typed() for v in n.reads)
        wi = ", ".join(v.to_lean_typed() for v in n.writes)
        nm = f'some "{n.name}"' if n.name else "none"
        if n.instruction:
            esc = n.instruction.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')
            ins = f'some "{esc}"'
        else:
            ins = "none"
        lines.append(f"-- Node {n.id}: {n.step_type} \"{n.name}\"")
        lines.append(f"def {prefix}_node{n.id} : WorkflowNode := {{")
        lines.append(f"  id := {prefix}_nodeId{n.id}, name := {nm}")
        lines.append(f"  stepType := .{n.step_type}")
        lines.append(f"  reads := [{ri}], writes := [{wi}]")
        lines.append(f"  llmInstruction := {ins}")
        lines.append(f"}}")
        lines.append("")

        # If semantic layer is ready, emit semantic node right after
        if can_semantic:
            lines.extend(_gen_semantic_node(n, prefix))

    # Graph
    nl = ", ".join(f"{prefix}_node{n.id}" for n in ir.nodes)
    el = ",\n    ".join(e.to_lean(prefix) for e in ir.edges)
    pi = ", ".join(p.to_lean_typed() for p in ir.parameters)
    xi = ", ".join(f"{prefix}_nodeId{x}" for x in ir.exits)
    lines.append(f"def {prefix}Graph : WorkflowGraph := {{")
    lines.append(f"  nodes := [{nl}]")
    lines.append(f"  edges := [\n    {el}\n  ]")
    lines.append(f"  entry := {prefix}_nodeId{ir.entry}")
    lines.append(f"  exits := [{xi}]")
    lines.append(f"  parameters := [{pi}]")
    lines.append(f"}}")
    lines.append("")

    # ---- STEP 2-5: Structural checks + theorems ----
    lines.extend(_gen_structural(ir, prefix))

    # ---- STEP 6: Semantic layer ----
    if can_semantic:
        lines.append("")
        lines.append("/-")
        lines.append("=" * 72)
        lines.append("STEP 6: SEMANTIC VERIFICATION")
        lines.append("=" * 72)
        lines.append("-/")
        lines.append("")
        lines.extend(_gen_semantic(ir, prefix, registry_name))

    # ---- STEP 7: Graph-level goal-coverage analysis (v2 only) ----
    if can_semantic and ir.goal_spec is not None:
        lines.extend(_gen_goal_spec(ir, prefix))

    # ---- Layer 3 tail (optional): dynamic verification definitions + driver
    if extra_tail:
        lines.extend(extra_tail)

    lines.append("")
    lines.append("end AgenticKernel")
    return "\n".join(lines)


def _gen_structural(ir: WorkflowIR, prefix: str) -> list[str]:
    lines = []
    thm = ir.name.replace("-", "_")
    ns = ", ".join(f"{prefix}_node{n.id}" for n in ir.nodes)
    pl = ", ".join(p.to_lean_typed() for p in ir.parameters)

    # ---- Per-node structural diagnostics ----
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 2: PER-NODE STRUCTURAL DIAGNOSTICS")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    lines.append("#eval do")
    lines.append(f"  let g := {prefix}Graph")
    lines.append('  for node in g.nodes do')
    lines.append('    let name := node.name.getD "(unnamed)"')
    lines.append('    IO.println s!"\\n--- Node {node.id}: \\"{name}\\" [{repr node.stepType}] ---"')
    lines.append('    IO.println s!"  writesConsistent:   {node.writesConsistent}"')
    lines.append('    IO.println s!"  reachableFromEntry: {g.reachable g.entry node.id}"')
    lines.append('    for rv in node.reads do')
    lines.append('      let fromParam := g.parameters.any (fun p =>')
    lines.append('        p.name == rv.name && p.type.compatible rv.type)')
    lines.append('      let fromPred := g.nodes.any (fun o =>')
    lines.append('        o.id != node.id && g.reachable o.id node.id &&')
    lines.append('        (!g.isParallelScopedNode o.id || g.isParallelScopedNode node.id) &&')
    lines.append('        o.writes.any (fun w => w.name == rv.name && w.type.compatible rv.type))')
    lines.append('      let status := if fromParam || fromPred then "✓" else "✗ UNRESOLVED"')
    lines.append('      IO.println s!"    read  \\"{rv.name}\\" ({repr rv.type}): {status}"')
    lines.append('    for wv in node.writes do')
    lines.append('      IO.println s!"    write \\"{wv.name}\\" ({repr wv.type})"')
    lines.append("")

    # ---- Graph-level structural checks ----
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 3: GRAPH-LEVEL STRUCTURAL CHECKS")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    for prop in ["allWritesConsistent","allReadResolvable","edgesValid",
                 "entryNodeValid","exitNodesValid","allExitsReachable","noOrphanNodes"]:
        lines.append(f"#eval {prefix}Graph.{prop}")
    lines.append(f"#eval {prefix}Graph.returnType")
    lines.append("")

    if not ir.emit_structural_theorems:
        # Skip Layer 1 structural theorems entirely (e.g. when graph intentionally
        # violates allWritesConsistent and native_decide would fail).
        return lines
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 4-5: THEOREMS")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    for s,p in [("writesConsistent","allWritesConsistent"),("readsResolvable","allReadResolvable"),
                ("edgesValid","edgesValid"),("entryValid","entryNodeValid"),
                ("exitsValid","exitNodesValid"),("exitsReachable","allExitsReachable"),
                ("noOrphans","noOrphanNodes")]:
        lines.append(f"theorem {thm}_{s} : {prefix}Graph.{p} = true := by native_decide")
    lines.append("")
    lines.append(f"theorem {thm}_seqPath_typeChecks :")
    lines.append(f"    ∃ ctx, typeCheckSequence [{ns}] [{pl}] = .ok ctx := by exact ⟨_, rfl⟩")
    lines.append("")
    sc = sum(1 for n in ir.nodes if n.needs_spec)
    lines.append(f"theorem {thm}_specCount : {prefix}Graph.nodesNeedingSpecs.length = {sc} := by native_decide")
    lines.append("")
    return lines


def _gen_semantic_node(n: NodeIR, prefix: str) -> list[str]:
    """Generate semantic node definition for a single workflow node."""
    lines = []
    pre_exprs = n.collect_precond_lean_exprs(prefix)
    post_exprs = n.collect_postcond_lean_exprs(prefix)
    pre_s = ", ".join(pre_exprs) if pre_exprs else ""
    post_s = ", ".join(post_exprs) if post_exprs else ""

    lines.append(f"-- Semantic Node {n.id}: {n.step_type} \"{n.name}\"")

    if n.step_type == "parallel" and n.submodule_ref is not None and n.submodule_ref.lean_prefix:
        sub = n.submodule_ref
        spec_name = f"{prefix}_{sub.name}Spec"
        in_var  = sub.input_var  or (n.reads[0].name  if n.reads  else "")
        out_var = sub.output_var or (n.writes[0].name if n.writes else "")
        lines += [
            f"-- (auto-generated via makeParallelSubmoduleNode from submodule {sub.name})",
            f"def {prefix}_semNode{n.id} : SemanticWorkflowNode :=",
            f"  makeParallelSubmoduleNode",
            f"    {spec_name}",
            f"    {prefix}_node{n.id}",
            f'    "{in_var}"',
            f'    "{out_var}"',
            "",
        ]
        return lines

    elif n.step_type == "call" and n.submodule_ref is not None and n.submodule_ref.lean_prefix:
        sub = n.submodule_ref
        spec_name = f"{prefix}_{sub.name}Spec"
        lines += [
            f"-- (auto-generated via makeSubmoduleCallNode from submodule {sub.name})",
            f"def {prefix}_semNode{n.id} : SemanticWorkflowNode :=",
            f"  makeSubmoduleCallNode",
            f"    {spec_name}",
            f"    {prefix}_node{n.id}",
            f"    []  -- paramMapping: fill if submodule param names differ from parent",
            f"    []  -- returnMapping: fill if return var name differs from save_as",
            "",
        ]
        return lines

    elif n.is_conditional:
        lines.append(f"def {prefix}_condNode{n.id} : SemanticConditionalNode := {{")
        lines.append(f"  baseNode := {prefix}_node{n.id}")
        lines.append(f"  precondVariables := [{pre_s}]")
        lines.append(f"  postcondVariables := [{post_s}]")
        lines.append(f"  thenTargetId := {prefix}_nodeId{n.then_target_id}")
        lines.append(f"  elseTargetId := {prefix}_nodeId{n.else_target_id}")
        tp = ", ".join(p.to_lean() for p in n.then_postcond) if n.then_postcond else ""
        ep = ", ".join(p.to_lean() for p in n.else_postcond) if n.else_postcond else ""
        lines.append(f"  thenPostcondVariables := [{tp}]")
        lines.append(f"  elsePostcondVariables := [{ep}]")
        lines.append(f"}}")
        lines.append(f"def {prefix}_semNode{n.id} : SemanticWorkflowNode := {prefix}_condNode{n.id}.toSemanticWorkflowNode")

    elif n.is_loop:
        is_fe = n.iteration_var is not None
        st = "SemanticForEachLoopNode" if is_fe else "SemanticLoopNode"
        lines.append(f"def {prefix}_loopNode{n.id} : {st} := {{")
        lines.append(f"  baseNode := {prefix}_node{n.id}")
        lines.append(f"  precondVariables := [{pre_s}]")
        lines.append(f"  postcondVariables := [{post_s}]")
        inv_s = ", ".join(p.to_lean() for p in n.loop_invariant) if n.loop_invariant else ""
        lines.append(f"  loopInvariant := [{inv_s}]")
        tk = n.termination_kind or "finiteCondition"
        if tk == "finiteCondition":
            vs = ", ".join(f'"{v}"' for v in (n.termination_vars or []))
            lines.append(f"  terminationSpec := .finiteCondition [{vs}]")
        elif tk == "llmControlledExit":
            lines.append(f'  terminationSpec := .llmControlledExit ⟨{n.termination_exit_node}⟩ "{n.termination_sentinel}"')
        elif tk == "externalTermination":
            lines.append(f'  terminationSpec := .externalTermination "{n.termination_mechanism}"')
        elif tk == "allowUnbounded":
            lines.append(f'  terminationSpec := .allowUnbounded "{n.termination_justification}"')
        if n.exit_postcond:
            xp = ", ".join(p.to_lean() for p in n.exit_postcond)
            lines.append(f"  exitPostconditions := [{xp}]")
        if is_fe:
            lines.append(f'  iterationVar := "{n.iteration_var}"')
        if n.loop_executes_at_least_once:
            lines.append(f"  executesAtLeastOnce := true")
        lines.append(f"}}")
        lines.append(f"def {prefix}_semNode{n.id} : SemanticWorkflowNode := {prefix}_loopNode{n.id}.toSemanticWorkflowNode")

    else:
        lines.append(f"def {prefix}_semNode{n.id} : SemanticWorkflowNode := {{")
        lines.append(f"  baseNode := {prefix}_node{n.id}")
        lines.append(f"  precondVariables := [{pre_s}]")
        lines.append(f"  postcondVariables := [{post_s}]")
        lines.append(f"}}")

    lines.append("")
    return lines


def _gen_semantic(ir: WorkflowIR, prefix: str, registry_name: str) -> list[str]:
    lines = []
    thm = ir.name.replace("-", "_")

    # Parameter node
    lines.append(f"def {prefix}_paramNode : SemanticWorkflowNode := {{")
    lines.append(f"  baseNode := {{ id := ⟨20041122⟩, name := some \"parameters\", stepType := .setVariable, reads := [], writes := [], llmInstruction := none }}")
    lines.append(f"  precondVariables := []")
    pp = ",\n    ".join(p.to_lean() for p in ir.param_postcond)
    lines.append(f"  postcondVariables := [\n    {pp}\n  ]")
    lines.append(f"}}")
    lines.append("")

    # Semantic node definitions are now generated inline with workflow nodes
    # (see generate_lean's node loop which calls _gen_semantic_node)

    # Graph
    sn = ", ".join(f"{prefix}_semNode{n.id}" for n in ir.nodes)
    ln = ", ".join(f"{prefix}_loopNode{n.id}" for n in ir.nodes if n.is_loop)
    cn = ", ".join(f"{prefix}_condNode{n.id}" for n in ir.nodes if n.is_conditional)
    lines.append(f"def {prefix}SemanticGraph : SemanticWorkflowGraph := {{")
    lines.append(f"  baseGraph := {prefix}Graph")
    lines.append(f"  paramNode := {prefix}_paramNode")
    lines.append(f"  semanticNodes := [{sn}]")
    lines.append(f"  loopNodes := [{ln}]")
    lines.append(f"  conditionalNodes := [{cn}]")
    lines.append(f"  specInvariant := by decide")
    lines.append(f"}}")
    lines.append("")

    # ---- Semantic state space diagnostic ----
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 6a: SEMANTIC STATE SPACE AFTER EACH NODE")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    sep = "=" * 60
    lines.append("#eval do")
    lines.append(f"  let semNodes := {prefix}SemanticGraph.semanticNodes")
    lines.append(f"  let paramPost := {prefix}SemanticGraph.paramNode.postcondVariables")
    lines.append(f'  IO.println "\\n{sep}"')
    lines.append(f'  IO.println "SEMANTIC STATE SPACE TRACE"')
    lines.append(f'  IO.println "{sep}"')
    lines.append('  IO.println "\\n--- Initial State (from parameters) ---"')
    lines.append('  for p in paramPost do')
    lines.append('    IO.println s!"  ✓ {p}"')
    lines.append('  let mut state : List VariablePredicateRequirement := paramPost')
    lines.append('  for node in semNodes do')
    lines.append('    let name := node.baseNode.name.getD "(unnamed)"')
    lines.append('    let nodeId := node.baseNode.id')
    lines.append('    IO.println s!"\\n--- After Node {nodeId}: \\"{name}\\" ---"')
    lines.append('    -- Check preconditions against current state')
    lines.append('    IO.println "  Preconditions:"')
    lines.append('    for p in node.precondVariables do')
    lines.append('      let satisfied := state.any (fun s => s.satisfies p)')
    lines.append('      let mark := if satisfied then "✓" else "✗"')
    lines.append('      IO.println s!"    {mark} requires: {p}"')
    lines.append('    -- Show new facts established')
    lines.append('    IO.println "  Postconditions (new facts):"')
    lines.append('    for p in node.postcondVariables do')
    lines.append('      IO.println s!"    + establishes: {p}"')
    lines.append('    -- Update cumulative state: add new postconditions')
    lines.append('    for p in node.postcondVariables do')
    lines.append('      unless state.any (fun s => s == p) do')
    lines.append('        state := state ++ [p]')
    lines.append('    IO.println s!"  Cumulative State ({state.length} predicates):"')
    lines.append('    for p in state do')
    lines.append('      IO.println s!"    {p}"')
    lines.append(f'  IO.println s!"\\n{sep}"')
    lines.append('  IO.println s!"Final state: {state.length} predicates established"')
    lines.append(f'  IO.println "{sep}"')
    lines.append("")

    # ---- Verification ----
    lines.append("/-")
    lines.append("=" * 72)
    lines.append("STEP 6b: SEMANTIC VERIFICATION")
    lines.append("=" * 72)
    lines.append("-/")
    lines.append("")
    lines.append(f"#eval! do")
    lines.append(f"  let result := {prefix}SemanticGraph.verify {registry_name}")
    lines.append(f"  IO.println (describeGraphVerificationResult result)")
    lines.append("")
    if ir.expected_semantically_sound:
        lines.append(f"theorem {thm}_semantically_sound :")
        lines.append(f"    {prefix}SemanticGraph.isSemanticallySoundBool {registry_name} = true := by")
        lines.append(f"  native_decide")
    else:
        lines.append(f"theorem {thm}_NOT_semantically_sound :")
        lines.append(f"    {prefix}SemanticGraph.isSemanticallySoundBool {registry_name} = false := by")
        lines.append(f"  native_decide")
    lines.append("")
    return lines


# ============================================================================
# 3.5 LAYER 3 IR + CODE-GEN
# ============================================================================

# A Layer 3 ("Dynamic Verification") file is self-contained: it INLINES the
# full Layer 1+2 content (node defs, workflow graph, semantic graph, goal
# spec) and adds Layer 3 data on top — a DynamicVerificationGraph, a
# StepIdMap, a NodeExecutionState, a List PerPredicateLLMInjection, and two
# System.FilePath literals pointing at the SWE-bench report.json and the
# agent event log. No `import VerificationExamples.*` is needed because all
# Layer 2 definitions exist in the same file.
#

_VALID_EXECUTION_STATUSES = {
    "completed", "failed", "skipped", "pending", "inProgress",
}



def _escape_lean_string(s: str) -> str:
    """Escape a Python string for inclusion in a Lean string literal."""
    return (s.replace('\\', '\\\\')
             .replace('"', '\\"')
             .replace('\n', '\\n'))


def _format_lean_float(x: float) -> str:
    """Emit a Lean-friendly float literal matching the hand-written form
    (e.g. 0.85 stays '0.85', 1.0 stays '1.0')."""
    if float(x).is_integer():
        return f"{float(x):.1f}"
    s = f"{float(x):.6f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


@dataclass
class LLMInjectionIR:
    """One PerPredicateLLMInjection entry — pre-computed LLM judgement
    for a (step, variable) pair, injected so the Lean verifier never
    calls an LLM itself."""
    step_name: str
    var_name: str
    holds: bool
    confidence: float = 1.0
    llm_explanation: str = ""

    def to_lean(self) -> str:
        expl = _escape_lean_string(self.llm_explanation)
        conf_str = _format_lean_float(self.confidence)
        holds_str = "true" if self.holds else "false"
        return (
            f'{{ stepName := "{self.step_name}", varName := "{self.var_name}"\n'
            f'      judgement := makeLLMJudgementResult\n'
            f'        (holds := {holds_str}) (confidence := {conf_str})\n'
            f'        (llmExplanation := "{expl}") }}'
        )

    def to_dict(self) -> dict:
        return {
            "step_name": self.step_name,
            "var_name": self.var_name,
            "holds": self.holds,
            "confidence": self.confidence,
            "llm_explanation": self.llm_explanation,
        }

    @staticmethod
    def from_dict(d: dict) -> "LLMInjectionIR":
        return LLMInjectionIR(
            step_name=d["step_name"],
            var_name=d["var_name"],
            holds=bool(d["holds"]),
            confidence=float(d.get("confidence", 1.0)),
            llm_explanation=d.get("llm_explanation", ""),
        )


@dataclass
class DynNodeSpecIR:
    """One DynamicNodeSpec — pairs a Layer 2 semantic node with runtime
    execution data (trajectory step id, step name, execution status)."""
    sem_node_ref: str              # e.g. "passed_workflow_1_v2_semNode0"
    trajectory_step_id: str        # e.g. "1"
    trajectory_step_name: str      # e.g. "explore_repository"
    execution_status: str = "completed"

    def to_dict(self) -> dict:
        return {
            "sem_node_ref": self.sem_node_ref,
            "trajectory_step_id": self.trajectory_step_id,
            "trajectory_step_name": self.trajectory_step_name,
            "execution_status": self.execution_status,
        }

    @staticmethod
    def from_dict(d: dict) -> "DynNodeSpecIR":
        status = d.get("execution_status", "completed")
        if status not in _VALID_EXECUTION_STATUSES:
            raise ValueError(
                f"Unknown execution_status {status!r}; "
                f"expected one of {sorted(_VALID_EXECUTION_STATUSES)}"
            )
        return DynNodeSpecIR(
            sem_node_ref=d["sem_node_ref"],
            trajectory_step_id=d["trajectory_step_id"],
            trajectory_step_name=d["trajectory_step_name"],
            execution_status=status,
        )


@dataclass
class Layer3IR:
    """Root IR for a self-contained Layer 3 verification file.

    The full Layer 1+2 workflow is embedded as `workflow: WorkflowIR`; codegen
    emits that content inline and then appends the Layer 3 definitions. No
    `import VerificationExamples.*` is needed because the Layer 2 content
    lives in the same file.

    `prefix` is the Layer 2 def-name prefix (e.g. "passed_workflow_1_v2") — it's
    used both by the inlined Layer 2 codegen and for referencing generated
    names like `{prefix}SemanticGraph`, `{prefix}_nodeId{i}`, `{prefix}_semNode{i}`
    from the Layer 3 definitions.

    `suffix` is the suffix appended to Layer 3 def names (reportPath{suffix},
    stepIdMap{suffix}, …). Use "" for unsuffixed (matches the
    `passed_workflow_1_per_step_move_analysis_generated.lean` style); use e.g.
    "_11333" for the django example style.
    """
    workflow: WorkflowIR
    prefix: str
    suffix: str
    report_path: str
    event_log_path: str
    step_id_map: list                       # list[(string_id, layer2_node_id)]
    exec_state: list                        # list[(var_name, raw_string)]
    dyn_nodes: list                         # list[DynNodeSpecIR]
    llm_injections: list                    # list[LLMInjectionIR]
    # Cosmetic — visible only in the file's #eval! output, not in lean_query JSON:
    banner_title: Optional[str] = None
    banner_subtitle: Optional[str] = None
    header_comment: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "ir_kind": "layer3",
            "workflow": self.workflow.to_dict(),
            "prefix": self.prefix,
            "suffix": self.suffix,
            "report_path": self.report_path,
            "event_log_path": self.event_log_path,
            "step_id_map": [[s, nid] for (s, nid) in self.step_id_map],
            "exec_state": [[v, raw] for (v, raw) in self.exec_state],
            "dyn_nodes": [d.to_dict() for d in self.dyn_nodes],
            "llm_injections": [i.to_dict() for i in self.llm_injections],
        }
        if self.banner_title is not None:
            d["banner_title"] = self.banner_title
        if self.banner_subtitle is not None:
            d["banner_subtitle"] = self.banner_subtitle
        if self.header_comment is not None:
            d["header_comment"] = self.header_comment
        return d

    @staticmethod
    def from_dict(d: dict) -> "Layer3IR":
        if d.get("ir_kind") not in (None, "layer3"):
            raise ValueError(f"Expected ir_kind='layer3', got {d.get('ir_kind')!r}")
        return Layer3IR(
            workflow=WorkflowIR.from_dict(d["workflow"]),
            prefix=d["prefix"],
            suffix=d.get("suffix", ""),
            report_path=d["report_path"],
            event_log_path=d["event_log_path"],
            step_id_map=[(s, int(nid)) for (s, nid) in d["step_id_map"]],
            exec_state=[(v, raw) for (v, raw) in d["exec_state"]],
            dyn_nodes=[DynNodeSpecIR.from_dict(x) for x in d["dyn_nodes"]],
            llm_injections=[LLMInjectionIR.from_dict(x) for x in d["llm_injections"]],
            banner_title=d.get("banner_title"),
            banner_subtitle=d.get("banner_subtitle"),
            header_comment=d.get("header_comment"),
        )

    def save_json(self, path: str, indent: int = 2) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent, ensure_ascii=False)

    @staticmethod
    def load_json(path: str) -> "Layer3IR":
        with open(path, "r", encoding="utf-8") as f:
            return Layer3IR.from_dict(json.load(f))




# ============================================================================
# 4. MAIN
# ============================================================================

if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser(
        description="Generate Lean4 verification code from parsed_task.json or IR JSON."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--json_path", help="Path to parsed_task.json (Layer 1 parse)")
    source.add_argument("--from_ir",
        help="Path to a saved IR JSON. Auto-detects Layer 1/2 (WorkflowIR) vs "
             "Layer 3 (Layer3IR) based on an 'ir_kind' field in the JSON.")
    parser.add_argument("--prefix", default="writer", help="Lean definition name prefix")
    parser.add_argument("--output", help="Output path for generated .lean file")
    parser.add_argument("--save_ir", help="Save the IR as JSON (useful after parse)")
    parser.add_argument("--env_file", action="append", default=[],
                        help="Load env vars from file(s) before parsing (can be repeated)")
    parser.add_argument(
        "--submodule_map", default="{}",
        help=(
            'JSON mapping from submodule name to Lean integration info. '
            'E.g.: \'{"extract_single_citation": {"lean_import": "TestVerifications...", '
            '"lean_prefix": "extractCitation"}}\''
        ),
    )
    args = parser.parse_args()

    if not args.output and not args.save_ir:
        parser.error("At least one of --output or --save_ir is required")

    # Load env files first so ${VAR} references can be resolved
    for ef in args.env_file:
        print(f"Loading env: {ef}")
        _load_env_file(ef)

    if args.from_ir:
        print(f"Loading IR: {args.from_ir}")
        with open(args.from_ir, "r", encoding="utf-8") as _f:
            _raw = json.load(_f)
        if _raw.get("ir_kind") == "layer3":
            # Layer-3 codegen now lives exclusively in the dynamic layer; this
            # CLI handles only Layer 1/2 (WorkflowIR). Generate Layer 3 with the
            # codegen instead (which also reads the legacy `ir_kind: "layer3"` shape).
            print("ERROR: Layer-3 (ir_kind='layer3') codegen has moved to the "
                  "dynamic layer. Run:\n"
                  "  python leanagent/codegen/agent_evolve/ir_to_lean.py "
                  "--ir <layer3_ir.json> --out <out.lean>", file=sys.stderr)
            sys.exit(2)
        ir = WorkflowIR.from_dict(_raw)
    else:
        print(f"Parsing: {args.json_path}")
        ir = parse_task_json(args.json_path)

    # Merge --submodule_map into ir.submodule_map
    if args.submodule_map and args.submodule_map.strip() not in ("{}", ""):
        try:
            raw_map = json.loads(args.submodule_map)
        except json.JSONDecodeError as e:
            print(f"ERROR: --submodule_map is not valid JSON: {e}", file=sys.stderr)
            sys.exit(1)
        if raw_map:
            if ir.submodule_map is None:
                ir.submodule_map = {}
            for sub_name, sub_info in raw_map.items():
                if sub_name in ir.submodule_map:
                    ir.submodule_map[sub_name].lean_import = sub_info.get("lean_import", "")
                    ir.submodule_map[sub_name].lean_prefix = sub_info.get("lean_prefix", "")
                else:
                    ir.submodule_map[sub_name] = SubmoduleRef(
                        name=sub_name, kind=sub_info.get("kind", "call"),
                        lean_import=sub_info.get("lean_import", ""),
                        lean_prefix=sub_info.get("lean_prefix", ""),
                        output_var=sub_info.get("output_var"),
                        input_var=sub_info.get("input_var"),
                    )
        print(f"  Submodule map: {list(ir.submodule_map.keys()) if ir.submodule_map else []}")

    print(f"  {len(ir.nodes)} nodes, {len(ir.edges)} edges")
    print(f"  Semantic ready: {ir.semantic_ready}")
    for n in ir.nodes:
        tag = "DET" if not n.needs_spec else ("READY" if n.semantic_ready else "TODO")
        print(f"    Node {n.id}: {n.step_type:16s} [{tag}] \"{n.name}\"")

    if args.save_ir:
        ir.save_json(args.save_ir)
        print(f"\nSaved IR: {args.save_ir}")

    if args.output:
        lean_code = generate_lean(ir, args.prefix)
        with open(args.output, "w") as f:
            f.write(lean_code)
        print(f"\nGenerated: {args.output} ({lean_code.count(chr(10))} lines)")
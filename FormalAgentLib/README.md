# FormalAgentLib

The Lean 4 library at the core of Lean4Agent — the formal model and verifier for agent
workflows and trajectories.

- Lean library: **`AgentVerifier`** (namespace `AgenticKernel`); depends on **Mathlib `v4.20.0`**.
- Build: `lake exe cache get && lake build`.

## Layout

- `AgentVerifier/` — the library modules:
  - **core types** — `YamlStepType.lean`, `WorkflowGraphBaiscs.lean`, `BaseTypes.lean`, `JsonSchema.lean`
  - **Layer 1** (static structure & types) — `WorkflowTypeCheck.lean`, `WorkflowProperties.lean`, `WorkflowGraphUtilies.lean`
  - **Layer 2** (static semantics) — `StaticSemanticLayer/`
  - **Layer 3** (dynamic / trajectory) — `DynamicVerification/` (namespace `AgenticKernel.Dyn`)
  - **JSON entry points** — `VerificationJsonOutput.lean`, `StaticSemanticLayer/UnifiedVerification.lean`
- `AgentVerifier.lean` — the library umbrella.

> The Lean modules live under the `AgentVerifier` namespace. The lakefile also declares a
> `VerificationExamples` lib target, which is not required to build the core library.

import AgentVerifier.DynamicVerification.Basics.ExecutionTrace
import AgentVerifier.DynamicVerification.Basics.DynamicVariablePredicate
import AgentVerifier.DynamicVerification.Basics.DynamicInformationFlow
import AgentVerifier.DynamicVerification.Basics.DynamicGraphPredicate
import AgentVerifier.DynamicVerification.DynamicVerificationGraph
import AgentVerifier.DynamicVerification.DynamicUnifiedReport
import AgentVerifier.DynamicVerification.DynamicVerificationIO
import AgentVerifier.DynamicVerification.PerStepView
import AgentVerifier.DynamicVerification.ElaipBench.PredicateChecks
import AgentVerifier.DynamicVerification.ElaipBench.ElaipBench
import AgentVerifier.DynamicVerification.VerificationJsonOutput

/-!
# Dynamic Verification (umbrella)

The rebuilt Layer-3 dynamic verification, mirroring Layer-2's three-component
design. Everything lives under `namespace AgenticKernel.Dyn` so it coexists
with the (untouched) original Layer-3 in `namespace AgenticKernel`.

## Uniform section spine (tracks the whole workflow)

  §0  Basics/ExecutionTrace          — typed trace model + queries
  §1  Basics/DynamicVariablePredicate — Channel ① variable predicates + bridge
  §2  Basics/DynamicInformationFlow   — Channel ② information flow + bridge (NEW)
  §3  Basics/DynamicGraphPredicate    — Channel ③ graph-level predicates + bridge
  §4  DynamicVerificationGraph        — the runtime graph (places the 3 channels) + soundness proofs
  §5  DynamicUnifiedReport            — the unified 3-channel fold + coverage
  §6  DynamicVerificationIO           — IO / external-Python (checker.py) boundary
  §7  PerStepView                     — per-step 3-method view + re-roll (+ SWEBench glue)
  §8  ElaipBench/PredicateChecks      — ELAIP decidable JSON checks
  §9  ElaipBench/ElaipBench           — ELAIP benchmark glue (rewired to the report)
  §10 VerificationJsonOutput        — JSON face of the unified report
      DynamicVerification           — this umbrella

## Three channels × three methods

The three **channels** (variable / information / graph) are each verified by any
of three **methods** (Lean symbolic / external-Python via `checker.py` / LLM
judge). The LLM method has two query modes: **injection** (verdicts baked in as
data; `native_decide`-friendly, §1–§5) and **online** (the Python/agent harness
computes verdicts and injects them; the live external-tool path is §6). No new
axioms beyond the three established trust axioms re-homed in §4.
-/

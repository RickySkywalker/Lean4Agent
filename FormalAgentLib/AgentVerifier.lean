-- This module serves as the root of the `AgentVerifier` library.
-- Import modules here that should be built as part of the library.
import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.VerificationJsonOutput
-- Layer-3 (dynamic / trajectory) — the dynamic layer (`namespace AgenticKernel.Dyn`)
import AgentVerifier.DynamicVerification.DynamicVerification

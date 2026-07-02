"""Authoring helpers that build IR JSON for *_layer2_v2.lean reference files.

Each module under this package constructs a WorkflowIR that mirrors the
corresponding hand-authored Lean file and writes it to
FormalAgentLib/VerificationExamples/layer2_v2_ir/{stem}.ir.json.

The IR JSON is the canonical fixture consumed by TaskPlanToLean. These
scripts are check-in maintenance helpers — regenerate the JSON by running
`python -m demo.lean_verifier.authoring.layer2_v2.<stem>` (or just invoking
the file directly).
"""

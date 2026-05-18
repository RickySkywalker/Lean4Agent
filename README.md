# Lean4Agent

This is the official repository for *Lean4Agent: Formal Modeling and Verification for Agent Workflow and Trajectory*. The Lean repository and experiment codes will be available soon.

## Introduction

We introduce **Lean4Agent**, to the best of our knowledge, the first framework that uses Lean4 to model and verify agent behavior. **Lean4Agent** introduces **FormalAgentLib**, an extensible Lean4 library for formally modeling and verifying agent workflows’ semantic consistency under explicit assumptions, and enabling localization of execution-time failures revealed by trajectories. Building on **FormalAgentLib**, we further develop **LeanEvolve**, which applies the results in **FormalAgentLib** to revise workflows to enhance its capability. Extensive experiments on a hard problem subset of SWE-Bench-Verified and a subset of ELAIP-Bench across 5 leading LLMs indicate that the verification-passing workflows outperform the failing ones by an average of **11.94%**, and **LeanEvolve** further improves SWE performance by **7.47%** on average. Furthermore, **Lean4Agent** establishes a foundation for a new field of using expressive dependent-type FL to formally model and verify agent behavior.

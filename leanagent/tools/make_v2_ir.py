#!/usr/bin/env python3
"""
make_v2_ir.py — Build a v2 Layer-2 IR JSON (for TaskPlanToLean_v2) by merging:

  * the STRUCTURAL data from the existing layer2_v2_ir JSON
    (parameters, nodes' reads/writes/instruction/precond/postcond, edges, goalSpec), and
  * the GRAPH + INFORMATION node-fields parsed from the ground-truth `*_layer2_new.lean`
    (graphContributions / graphVerifications / graphImplicitRetries,
     infoRequires / producesVariableInfo / producesContextInfo, param info,
     and the expected hoare/info soundness from the theorems).

The result is fed to TaskPlanToLean_v2 to regenerate the new-format Lean, giving a
round-trip test (*_layer2_new.lean → v2 IR → TaskPlanToLean_v2 → .lean) against the
ground-truth examples.

Usage:
  python3 make_v2_ir.py <existing_ir.json> <plan_layer2_new.lean> <out_v2_ir.json>
"""

import json
import re
import sys

# reuse the brace-matching / comment-stripping parser from the porter
from port_to_new_layer2 import (strip_line_comments, parse_struct_fields,
                                 find_def_block, match_delim, split_top_level)


def _list_items(text):
    """`[a, b, c]` (or with surrounding ws) → ['a','b','c'] (top-level split)."""
    text = text.strip()
    lb = text.find('[')
    if lb < 0:
        return []
    rb = match_delim(text, lb, '[', ']')
    inner = text[lb + 1:rb]
    return [x.strip() for x in split_top_level(inner, ',') if x.strip()]


def parse_info_atoms(text):
    """`[info "a", info "b"]` → ['a','b']."""
    out = []
    for it in _list_items(text):
        m = re.search(r'info\s+"([^"]+)"', it)
        if m:
            out.append(m.group(1))
    return out


def parse_var_info(text):
    """`[varInfo "v" ["a","b"], varInfo "w" ["c"]]` → [{'var_name':'v','atoms':['a','b']},...]."""
    out = []
    for it in _list_items(text):
        m = re.search(r'varInfo\s+"([^"]+)"\s*(\[.*\])\s*$', it, re.S)
        if not m:
            continue
        atoms = [a.strip().strip('"') for a in _list_items(m.group(2))]
        out.append({"var_name": m.group(1), "atoms": atoms})
    return out


def parse_sg_refs(text):
    """`[fix_implemented, repository_explored]` → ['fix_implemented', ...] (bare idents)."""
    return [it.strip() for it in _list_items(text)]


def node_fields_from_new(src, prefix, node_id):
    """Parse the graph/info record fields of semNode<node_id> (or its loop/cond def)."""
    for pat in (rf'{re.escape(prefix)}_semNode{node_id}(?=\s*:)',
                rf'{re.escape(prefix)}_loopNode{node_id}(?=\s*:)',
                rf'{re.escape(prefix)}_condNode{node_id}(?=\s*:)'):
        blk = find_def_block(src, pat)
        if not blk:
            continue
        fields = dict(parse_struct_fields(src[blk[2] + 1:blk[3]]))
        if any(k in fields for k in ("graphContributions", "graphVerifications",
                                     "graphImplicitRetries", "infoRequires",
                                     "producesVariableInfo", "producesContextInfo")):
            return fields
    return {}


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 1
    ir_path, new_lean_path, out_path = argv[1], argv[2], argv[3]

    ir = json.loads(open(ir_path, encoding="utf-8").read())
    src = strip_line_comments(open(new_lean_path, encoding="utf-8").read())

    mg = re.search(r'def\s+(\S+?)SemanticGraph\s*:\s*SemanticWorkflowGraph', src)
    prefix = mg.group(1)

    # Per-node graph + info fields from the ground-truth new file.
    for n in ir["nodes"]:
        f = node_fields_from_new(src, prefix, n["id"])
        # graph-level (overwrite from ground truth — authoritative incl. retries)
        if "graphContributions" in f:
            n["sub_goal_contributions"] = [{"sub_goal_name": s} for s in parse_sg_refs(f["graphContributions"])]
        if "graphVerifications" in f:
            n["sub_goal_verifications"] = [{"sub_goal_name": s} for s in parse_sg_refs(f["graphVerifications"])]
        if "graphImplicitRetries" in f:
            n["implicit_retries"] = [{"sub_goal_name": s} for s in parse_sg_refs(f["graphImplicitRetries"])]
        # information flow (new fields)
        if "infoRequires" in f:
            n["info_requires"] = parse_info_atoms(f["infoRequires"])
        if "producesVariableInfo" in f:
            n["produces_variable_info"] = parse_var_info(f["producesVariableInfo"])
        if "producesContextInfo" in f:
            n["produces_context_info"] = parse_info_atoms(f["producesContextInfo"])
        # drop the deprecated step_tag / old aspect entries so they aren't re-emitted
        n.pop("step_tag", None)

    # Param-node info.
    pblk = find_def_block(src, re.escape(prefix) + r'_paramNode')
    if pblk:
        pf = dict(parse_struct_fields(src[pblk[2] + 1:pblk[3]]))
        if "producesVariableInfo" in pf:
            ir["param_produces_variable_info"] = parse_var_info(pf["producesVariableInfo"])

    # Expected soundness from the theorems.
    mh = re.search(r'\.hoareSound\s*=\s*(true|false)', src)
    mi = re.search(r'\.infoSound\s*=\s*(true|false)', src)
    if mh:
        ir["expected_semantically_sound"] = (mh.group(1) == "true")
    if mi:
        ir["expected_info_sound"] = (mi.group(1) == "true")

    ir["prefix"] = prefix
    open(out_path, "w", encoding="utf-8").write(json.dumps(ir, indent=2, ensure_ascii=False) + "\n")
    print(f"OK: v2 IR -> {out_path} (prefix={prefix!r}, {len(ir['nodes'])} nodes, "
          f"hoare={ir.get('expected_semantically_sound')}, info={ir.get('expected_info_sound')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

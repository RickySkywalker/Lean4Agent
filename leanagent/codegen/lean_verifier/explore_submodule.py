"""
Recursive YAML Plan Submodule Discovery & Topological Sort

Recursively walks a YAML agent plan tree, discovers ALL modules
(including submodules of submodules), deduplicates, and returns
a topologically-sorted list (leaves first, root last).
"""

import argparse
import json
import os
import pprint
import sys

import yaml


def resolve(ref, base_dir, staging_root, home_dir=None):
    """Resolve a module reference to an absolute path.

    Resolution order:
        1. Absolute path → use as-is
        2. Relative to home_dir (project root) – most YAML module paths
           are specified relative to the project root, e.g.
           ``demo/ai_scientists/writer/modules/search_citations.yaml``
        3. Relative to the current YAML file's own directory
        4. Relative to the staging root (mirrors project structure)
        5. Basename match in plans/ directory under staging_root
    """
    if os.path.isabs(ref):
        return ref

    # Try 1: relative to the project home directory (highest priority
    #         because module paths in YAML plans are usually written
    #         relative to the project root).
    if home_dir:
        candidate_home = os.path.normpath(os.path.join(home_dir, ref))
        if os.path.exists(candidate_home):
            return candidate_home

    # Try 2: relative to the YAML file's own directory
    candidate = os.path.normpath(os.path.join(base_dir, ref))
    if os.path.exists(candidate):
        return candidate

    # Try 3: relative to the staging root
    candidate2 = os.path.normpath(os.path.join(staging_root, ref))
    if os.path.exists(candidate2):
        return candidate2

    # Try 4: basename match in plans/ directory
    plans_dir = os.path.join(staging_root, "plans")
    basename = os.path.basename(ref)
    candidate3 = os.path.join(plans_dir, basename)
    if os.path.exists(candidate3):
        return candidate3

    # Fall back – report as missing later
    if home_dir:
        return candidate_home
    return candidate


def walk(steps, base_dir, staging_root, home_dir=None):
    """Walk workflow steps and collect all module references."""
    refs = []
    if not isinstance(steps, list):
        return refs
    for s in steps:
        if not isinstance(s, dict):
            continue
        if "call" in s:
            c = s["call"]
            if isinstance(c, dict) and "module" in c:
                refs.append({
                    "path": resolve(c["module"], base_dir, staging_root, home_dir),
                    "type": "call",
                    "save_as": c.get("save_as", ""),
                    "params_var": ""
                })
        if "parallel" in s:
            p = s["parallel"]
            if isinstance(p, dict) and "module" in p:
                refs.append({
                    "path": resolve(p["module"], base_dir, staging_root, home_dir),
                    "type": "parallel",
                    "save_as": p.get("save_results_as", ""),
                    "params_var": p.get("parameters_list", "")
                })
            elif isinstance(p, list):
                refs.extend(walk(p, base_dir, staging_root, home_dir))
        if "for_each" in s:
            fe = s["for_each"]
            if isinstance(fe, dict) and "steps" in fe:
                refs.extend(walk(fe["steps"], base_dir, staging_root, home_dir))
        for branch in ("then", "else"):
            if branch in s and isinstance(s[branch], list):
                refs.extend(walk(s[branch], base_dir, staging_root, home_dir))
        if "while" in s:
            w = s["while"]
            if isinstance(w, dict) and "steps" in w:
                refs.extend(walk(w["steps"], base_dir, staging_root, home_dir))
    return refs


def discover(yp, registry, staging_root, home_dir=None):
    """Recursively discover all modules starting from a YAML plan."""
    norm = os.path.normpath(yp)
    if norm in registry:
        return
    if not os.path.exists(yp):
        print(f"WARNING: {yp} not found", file=sys.stderr)
        return
    with open(yp) as f:
        plan = yaml.safe_load(f)

    base_dir = os.path.dirname(yp)
    name = os.path.splitext(os.path.basename(yp))[0]

    # Collect refs from workflow steps
    refs = walk(plan.get("workflow", []), base_dir, staging_root, home_dir) if plan else []

    # Also collect refs from top-level "submodules" declarations
    if plan and "submodules" in plan and isinstance(plan["submodules"], list):
        for sub in plan["submodules"]:
            if isinstance(sub, dict) and "path" in sub:
                refs.append({
                    "path": resolve(sub["path"], base_dir, staging_root, home_dir),
                    "type": "submodule",
                    "save_as": sub.get("name", ""),
                    "params_var": ""
                })

    registry[norm] = {
        "yaml_path": yp,
        "module_name": name,
        "children": [os.path.normpath(r["path"]) for r in refs],
        "child_details": refs
    }
    for r in refs:
        discover(r["path"], registry, staging_root, home_dir)


def topo_sort(root_yaml, registry):
    """Topological sort: leaves first, root last."""
    order = []
    seen = set()

    def dfs(n):
        if n in seen:
            return
        seen.add(n)
        for c in registry.get(n, {}).get("children", []):
            if c in registry:
                dfs(c)
        order.append(n)

    dfs(os.path.normpath(root_yaml))
    for n in registry:
        dfs(n)
    return order


def main():
    parser = argparse.ArgumentParser(
        description="Recursively discover submodules in a YAML agent plan "
                    "and output a topologically-sorted list (leaves first)."
    )
    parser.add_argument(
        "--yaml_plan_path",
        help="Path to the root YAML plan file"
    )
    parser.add_argument(
        "--home-dir",
        default=None,
        help="Project home directory for resolving module paths. "
             "Module references in YAML plans (e.g. "
             "'demo/ai_scientists/writer/modules/search_citations.yaml') "
             "are resolved relative to this directory. "
             "Defaults to the current working directory."
    )
    parser.add_argument(
        "-a", "--already-verified",
        default="[]",
        help='JSON array of already-verified module specs (default: "[]")'
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of Python pprint format"
    )

    args = parser.parse_args()

    root_yaml = args.yaml_plan_path
    staging_root = os.path.dirname(root_yaml)

    # Determine project home directory for path resolution.
    # Module paths in YAML plans are typically relative to the project root
    # (e.g. "demo/ai_scientists/writer/modules/search_citations.yaml"),
    # so we need to know where the project root is.
    home_dir = args.home_dir
    if home_dir is None:
        home_dir = os.getcwd()
    home_dir = os.path.abspath(home_dir)

    print(f"Home dir (project root): {home_dir}", file=sys.stderr)
    print(f"Staging root: {staging_root}", file=sys.stderr)

    # Parse already-verified modules
    try:
        already_verified = json.loads(args.already_verified)
    except json.JSONDecodeError:
        print(f"ERROR: --already-verified is not valid JSON: {args.already_verified}",
              file=sys.stderr)
        sys.exit(1)

    already_names = {m["module_name"] for m in already_verified} if already_verified else set()

    # Discover all modules
    registry = {}
    discover(root_yaml, registry, staging_root, home_dir)

    print(f"Discovered {len(registry)} module(s)", file=sys.stderr)

    # Topological sort
    order = topo_sort(root_yaml, registry)

    root_norm = os.path.normpath(root_yaml)
    if root_norm not in registry:
        print(f"ERROR: Root YAML '{root_yaml}' was not discovered "
              f"(file missing or unreadable).", file=sys.stderr)
        print(f"  Resolved path: {os.path.abspath(root_yaml)}", file=sys.stderr)
        if home_dir:
            print(f"  Home dir: {home_dir}", file=sys.stderr)
        sys.exit(1)

    result = []
    for n in order:
        if n not in registry:
            continue
        e = registry[n]
        if e["module_name"] in already_names:
            continue
        # Deduplicated child names, preserving order
        seen_children = set()
        deduped_children = []
        for c in e["children"]:
            if c in registry:
                cname = registry[c]["module_name"]
                if cname not in seen_children:
                    seen_children.add(cname)
                    deduped_children.append(cname)
        result.append({
            "yaml_path":     e["yaml_path"],
            "module_name":   e["module_name"],
            "is_root":       (n == root_norm),
            "child_names":   deduped_children,
        })

    # Output
    if args.json:
        output_str = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        # Python repr format (True/False/None) so that
        # basic.py's eval() can parse it into a real Python list.
        output_str = pprint.pformat(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Output written to: {args.output}", file=sys.stderr)
    else:
        print(output_str)


if __name__ == "__main__":
    main()

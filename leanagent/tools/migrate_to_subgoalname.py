#!/usr/bin/env python3
"""
migrate_to_subgoalname.py  —  Solution 1, point #3 (typed sub-goal identity).

Rewrites a Layer-2 / Layer-3 verification example so that every sub-goal name is
referenced through a shared, typed `SubGoalName` constant instead of a bare
`String` literal. After the `SubGoalName` newtype change in
`GraphLevelPredicates.lean`, a sub-goal name that is hand-typed in two places
(the node markers and the `GoalSpecification`) is no longer matched by silent
string equality: each plan declares its sub-goal names ONCE as constants and
references those constants in both the markers and the goalSpec, so a typo in
either place is now an "unknown identifier" compile error.

What it does, per file:
  1. Collects every sub-goal name from the markers
     (`markSubGoalContribution` / `markSubGoalVerification` / `markImplicitRetry`,
      second argument) and from `GoalSpecification` (`name := "..."`, the bare
      form — node names use `name := some "..."` and are left untouched).
  2. Emits a per-file namespace `<stem>.SG` of `SubGoalName` constants
     (one `def <ident> : SubGoalName := ⟨"<name>"⟩` per distinct name), inserted
     right after `namespace AgenticKernel`, followed by `open <stem>.SG`.
  3. Rewrites the marker second argument and the goalSpec `name :=` to reference
     the constant identifier (bare, thanks to the `open`).

The namespace is derived from the file stem (unique per file) so constants never
collide across the `VerificationExamples` glob library.

Usage:
    python3 migrate_to_subgoalname.py FILE [FILE ...]
    python3 migrate_to_subgoalname.py --check FILE   # report only, no write
"""

import re
import sys
import keyword as _kw

# Lean keywords we must not emit as bare identifiers (sub-goal names are
# snake_case evidence labels, so collisions are unlikely, but be safe).
LEAN_KEYWORDS = {
    "end", "match", "fun", "do", "let", "if", "then", "else", "with", "from",
    "by", "have", "show", "this", "namespace", "open", "section", "def",
    "theorem", "structure", "inductive", "class", "instance", "where", "deriving",
}

MARKER_RE = re.compile(
    r'(markSubGoalContribution|markSubGoalVerification|markImplicitRetry)'
    r'(\s+\S+\s+)'      # the NodeId argument (single token)
    r'"([^"]+)"'        # the sub-goal name string literal
)

# Bare `name := "..."` is a SubGoalSpec field; `name := some "..."` (node name)
# does NOT match because the quote does not immediately follow `:= `.
GOALSPEC_NAME_RE = re.compile(r'name := "([^"]+)"')


def sanitize_ident(name: str) -> str:
    """Turn a sub-goal name into a valid, non-keyword Lean identifier."""
    ident = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if not ident or not re.match(r'[A-Za-z_]', ident[0]):
        ident = "sg_" + ident
    if ident in LEAN_KEYWORDS or _kw.iskeyword(ident):
        ident = ident + "_"
    return ident


def file_stem_namespace(path: str) -> str:
    base = path.rsplit('/', 1)[-1]
    if base.endswith('.lean'):
        base = base[:-5]
    seg = sanitize_ident(base)
    return f"{seg}.SG"


def collect_subgoal_names(src: str):
    """Return an ordered, de-duplicated list of sub-goal names used in the file."""
    names = []
    seen = set()

    def add(n):
        if n not in seen:
            seen.add(n)
            names.append(n)

    for m in MARKER_RE.finditer(src):
        add(m.group(3))
    for m in GOALSPEC_NAME_RE.finditer(src):
        add(m.group(1))
    return names


def migrate_source(src: str, ns: str):
    names = collect_subgoal_names(src)
    if not names:
        return src, [], {}

    # name -> identifier (stable; warn on collision after sanitisation)
    name_to_ident = {}
    used_idents = {}
    for n in names:
        ident = sanitize_ident(n)
        if ident in used_idents and used_idents[ident] != n:
            # Disambiguate a sanitisation collision deterministically.
            suffix = 2
            while f"{ident}_{suffix}" in used_idents:
                suffix += 1
            ident = f"{ident}_{suffix}"
        used_idents[ident] = n
        name_to_ident[n] = ident

    # Build the constant block.
    lines = [f"namespace {ns}"]
    for n in names:
        lines.append(f'  def {name_to_ident[n]} : SubGoalName := ⟨"{n}"⟩')
    lines.append(f"end {ns}")
    lines.append(f"open {ns}")
    block = "\n".join(lines)

    # Insert right after the first `namespace AgenticKernel` line.
    ns_decl = re.search(r'^namespace AgenticKernel\s*$', src, flags=re.MULTILINE)
    if not ns_decl:
        raise RuntimeError("could not find `namespace AgenticKernel` declaration")
    insert_at = ns_decl.end()
    header = (
        "\n\n/- FIX #3: typed sub-goal identities. Each sub-goal name is declared "
        "once below as a\n   `SubGoalName` constant and referenced (not re-typed) "
        "in the node markers and the\n   `GoalSpecification`, so a typo is a "
        "compile error instead of a silent NONE. -/\n"
    )
    src = src[:insert_at] + header + block + "\n" + src[insert_at:]

    # Rewrite marker second arguments.
    def marker_sub(m):
        ident = name_to_ident[m.group(3)]
        return f"{m.group(1)}{m.group(2)}{ident}"
    src = MARKER_RE.sub(marker_sub, src)

    # Rewrite goalSpec `name := "..."`.
    def goalspec_sub(m):
        return f"name := {name_to_ident[m.group(1)]}"
    src = GOALSPEC_NAME_RE.sub(goalspec_sub, src)

    return src, names, name_to_ident


def main(argv):
    check_only = False
    files = []
    for a in argv[1:]:
        if a == "--check":
            check_only = True
        else:
            files.append(a)
    if not files:
        print(__doc__)
        return 1

    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        ns = file_stem_namespace(path)
        new_src, names, mapping = migrate_source(src, ns)
        if not names:
            print(f"[skip] {path}: no sub-goal names found")
            continue
        print(f"[ok]   {path}: {len(names)} sub-goals -> namespace {ns}")
        for n in names:
            print(f"          {n!r} -> {mapping[n]}")
        if not check_only:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

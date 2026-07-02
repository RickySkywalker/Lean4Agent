#!/usr/bin/env python3
"""
port_to_new_layer2.py  —  Solution 2 back-support / forward-port transformer.

Converts a Layer-2 / Layer-3 example written in the OLD (pre-Solution-2) idiom
into the NEW idiom, so old research files run on the restructured system:

OLD idiom                                  NEW idiom
─────────                                  ─────────
graph markers in `postcondVariables`   →   dedicated node fields
  (`markSubGoalContribution` etc.)           `graphContributions` /
                                             `graphVerifications` /
                                             `graphImplicitRetries`
separate `<p>_infoSpec` overlay        →   per-node `infoRequires` /
                                             `producesVariableInfo` /
                                             `producesContextInfo`
separate `<p>_goalSpec`                →   the graph's embedded `goalSpec` field
STEP 6½/7 analyzeInformationFlow +     →   one `verifyWorkflowReport` call
  analyzeGoalCoverage evals

The whole file is wrapped in a per-file namespace `AgenticKernel.<out-stem>` so
the ported defs never clash with the original in the `VerificationExamples` glob
(WQA symbols resolve via the enclosing `AgenticKernel`). `--` line comments are
stripped (string- and block-comment-aware) because the old files carry inline
comments inside the very lists/structures we rewrite; `/- … -/` section blocks
are preserved.

The new library is deliberately back-compatible (graph-attribute extraction
reads the UNION of new fields and legacy markers), so an *un-ported* old file
already compiles; this transformer produces the clean, fully forward-ported
`*_new.lean`.

Usage:
    python3 port_to_new_layer2.py SRC.lean OUT.lean
    python3 port_to_new_layer2.py --check SRC.lean
"""

import re
import sys
import os


# ── lexing helpers ──────────────────────────────────────────────────────────

def strip_line_comments(src: str) -> str:
    """Remove `--`…EOL comments, respecting string literals and `/- … -/`
    block comments (blocks are copied verbatim)."""
    out, i, n, in_str, esc = [], 0, len(src), False, False
    while i < n:
        c = src[i]
        if in_str:
            out.append(c)
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
            i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '-':
            depth, j = 0, i
            while j < n:
                if src[j] == '/' and j + 1 < n and src[j + 1] == '-':
                    depth += 1; j += 2; continue
                if src[j] == '-' and j + 1 < n and src[j + 1] == '/':
                    depth -= 1; j += 2
                    if depth == 0: break
                    continue
                j += 1
            out.append(src[i:j]); i = j; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if c == '-' and i + 1 < n and src[i + 1] == '-':
            while i < n and src[i] != '\n':
                i += 1
            continue
        out.append(c); i += 1
    return ''.join(out)


def match_delim(s: str, open_idx: int, opn: str, cls: str) -> int:
    depth, i, n = 0, open_idx, len(s)
    while i < n:
        if s[i] == opn: depth += 1
        elif s[i] == cls:
            depth -= 1
            if depth == 0: return i
        i += 1
    raise ValueError(f"unbalanced {opn}{cls}")


def split_top_level(s: str, sep: str = ',') -> list:
    out, depth, cur = [], 0, []
    for c in s:
        if c in '([{': depth += 1
        elif c in ')]}': depth -= 1
        if c == sep and depth == 0:
            out.append(''.join(cur)); cur = []
        else:
            cur.append(c)
    if ''.join(cur).strip():
        out.append(''.join(cur))
    return out


def parse_struct_fields(body: str):
    """Parse `{ a := v1  b := v2, c := v3 }` body → ordered [(name, value)].
    Handles both newline- and comma-separated fields (Lean allows either)."""
    positions, depth, i, n = [], 0, 0, len(body)
    while i < n:
        c = body[i]
        if c in '([{': depth += 1; i += 1; continue
        if c in ')]}': depth -= 1; i += 1; continue
        if depth == 0:
            prev = body[i - 1] if i > 0 else ' '
            if not (prev.isalnum() or prev == '_' or prev == '.'):
                m = re.match(r'([A-Za-z_]\w*)\s*:=', body[i:])
                if m:
                    positions.append((i, m.group(1), i + m.end()))
                    i += m.end(); continue
        i += 1
    fields = []
    for k, (_, name, vstart) in enumerate(positions):
        vend = positions[k + 1][0] if k + 1 < len(positions) else n
        val = body[vstart:vend].strip().rstrip(',').strip()
        fields.append((name, val))
    return fields


def find_def_block(src: str, name_regex: str):
    """Find `def <name> … := { <body> }`. Returns
    (full_start, full_end, brace_open_idx, brace_close_idx, name)."""
    m = re.search(rf'def\s+({name_regex})\b[^=]*:=\s*', src)
    if not m: return None
    brace = src.find('{', m.end())
    if brace < 0: return None
    end = match_delim(src, brace, '{', '}')
    return (m.start(), end + 1, brace, end, m.group(1))


def sanitize_ident(name: str) -> str:
    ident = re.sub(r'[^A-Za-z0-9_]', '_', name)
    if not ident or not re.match(r'[A-Za-z_]', ident[0]):
        ident = "f_" + ident
    return ident


# ── infoSpec ────────────────────────────────────────────────────────────────

def parse_infospec(src: str, prefix: str):
    """{node_num -> {field: text}} from `<prefix>_infoSpec`."""
    blk = find_def_block(src, re.escape(prefix) + r'_infoSpec')
    if not blk: return {}
    body = src[blk[2] + 1:blk[3]]
    lb = body.find('[')
    if lb < 0: return {}
    rb = match_delim(body, lb, '[', ']')
    entries = body[lb + 1:rb]
    result, i = {}, 0
    while i < len(entries):
        if entries[i] == '{':
            j = match_delim(entries, i, '{', '}')
            fields = dict(parse_struct_fields(entries[i + 1:j]))
            nid_val = fields.get('nodeId', '')
            keep = {k: v for k, v in fields.items()
                    if k in ('requires', 'producesVariableInfo', 'producesContextInfo')}
            mm = re.search(r'nodeId(\d+)', nid_val)
            if mm:
                result[int(mm.group(1))] = keep
            elif 'paramNode' in nid_val or '20041122' in nid_val:
                # The parameter node's info (e.g. a param variable bearing an
                # information atom) — goes onto the `paramNode` def, not a semNode.
                result['param'] = keep
            i = j + 1
        else:
            i += 1
    return result


# ── semNode rewrite ─────────────────────────────────────────────────────────

def transform_semnode(src: str, prefix: str, num: int, info: dict) -> str:
    blk = find_def_block(src, re.escape(prefix) + rf'_semNode{num}(?=\s*:)')
    if not blk: return src
    _, _, bstart, bend, _ = blk
    fields = parse_struct_fields(src[bstart + 1:bend])

    contribs, verifs, retries = [], [], []
    new_fields = []
    for name, val in fields:
        if name == 'postcondVariables':
            lb = val.find('['); rb = match_delim(val, lb, '[', ']')
            elems = [e.strip() for e in split_top_level(val[lb + 1:rb], ',') if e.strip()]
            kept = []
            for e in elems:
                mk = re.match(r'(markSubGoalContribution|markSubGoalVerification|markImplicitRetry)\s+\S+\s+(\S+)', e)
                if mk:
                    fn, sg = mk.group(1), mk.group(2)
                    (contribs if fn.endswith("Contribution") else
                     verifs if fn.endswith("Verification") else retries).append(sg)
                else:
                    kept.append(e)
            new_fields.append(('postcondVariables', "[" + ", ".join(kept) + "]"))
        else:
            new_fields.append((name, val))

    inf = info.get(num, {})
    if inf.get('requires'):
        new_fields.append(('infoRequires', inf['requires']))
    if inf.get('producesVariableInfo'):
        new_fields.append(('producesVariableInfo', inf['producesVariableInfo']))
    if inf.get('producesContextInfo'):
        new_fields.append(('producesContextInfo', inf['producesContextInfo']))
    if contribs:
        new_fields.append(('graphContributions', "[" + ", ".join(contribs) + "]"))
    if verifs:
        new_fields.append(('graphVerifications', "[" + ", ".join(verifs) + "]"))
    if retries:
        new_fields.append(('graphImplicitRetries', "[" + ", ".join(dict.fromkeys(retries)) + "]"))

    body = "\n" + "\n".join(f"  {k} := {v}" for k, v in new_fields) + "\n"
    return src[:bstart + 1] + body + src[bend:]


def inject_param_info(src: str, prefix: str, info: dict) -> str:
    """Add the parameter node's information fields to the `<prefix>_paramNode`
    def (its `producesVariableInfo` must survive porting — steps read it)."""
    if not info:
        return src
    blk = find_def_block(src, re.escape(prefix) + r'_paramNode')
    if not blk:
        return src
    extra = []
    if info.get('requires'):
        extra.append(f"  infoRequires := {info['requires']}")
    if info.get('producesVariableInfo'):
        extra.append(f"  producesVariableInfo := {info['producesVariableInfo']}")
    if info.get('producesContextInfo'):
        extra.append(f"  producesContextInfo := {info['producesContextInfo']}")
    if not extra:
        return src
    ins = blk[3]  # the def's closing brace
    return src[:ins] + "\n".join(extra) + "\n" + src[ins:]


# ── eval / theorem stripping ────────────────────────────────────────────────

# Any `#eval`/`#eval!` block mentioning one of these is a per-channel Layer-2
# verification eval that the single `verifyWorkflowReport` now subsumes.
VERIF_EVAL_TRIGGERS = (
    "analyzeGoalCoverage", "analyzeInformationFlow", "isInformationFlowSoundBool",
    "formatGoalCoverageReport", "formatInformationFlowReport",
    "describeGraphVerificationResult", "SEMANTIC STATE SPACE", ".verify emptyRegistry",
)
# Theorems proving a single Layer-2 channel — ported to the unified API.
VERIF_THEOREM_TRIGGERS = ("isSemanticallySoundBool", "isInformationFlowSoundBool")
PROOF_TERMINATORS = ("native_decide", "decide", "rfl", "sorry", "exact", "trivial")


def _capture_bool(src: str, fn: str):
    m = re.search(rf'{re.escape(fn)}[^=]*=\s*(true|false)', src)
    return m.group(1) if m else None


def end_of_block_comment(s: str, start: int) -> int:
    depth, j, n = 0, start, len(s)
    while j < n:
        if s[j] == '/' and j + 1 < n and s[j + 1] == '-':
            depth += 1; j += 2; continue
        if s[j] == '-' and j + 1 < n and s[j + 1] == '/':
            depth -= 1; j += 2
            if depth == 0: return j
            continue
        j += 1
    return n


def strip_step67_headers(src: str) -> str:
    """Drop `/- … -/` section-divider comments whose body starts a line with
    `STEP 6`/`STEP 7` (the old per-channel Layer-2 section banners: 6, 6a, 6b,
    6½, 7). Long prose blocks that merely mention 'STEP 6½' mid-line are kept."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src[i] == '/' and i + 1 < n and src[i + 1] == '-':
            j = end_of_block_comment(src, i)
            body = src[i:j]
            if re.search(r'(?m)^\s*STEP\s*6|^\s*STEP\s*7', body):
                i = j
                if i < n and src[i] == '\n':
                    i += 1
                continue
            out.append(body); i = j; continue
        out.append(src[i]); i += 1
    return ''.join(out)


def consolidate_layer2_verif(src: str) -> str:
    """Remove the per-channel Layer-2 verification `#eval`/`#eval!` blocks and the
    single-channel soundness theorems (Hoare/info). Layer-1 structural evals and
    theorems, and any Layer-3 (`#eval!` over a dynamic graph), are preserved."""
    lines = src.split('\n')
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        s = ln.lstrip()
        if s.startswith("theorem"):
            j, blk = i, []
            while j < len(lines):
                blk.append(lines[j])
                if any(t in lines[j] for t in PROOF_TERMINATORS):
                    j += 1; break
                j += 1
            if any(t in "\n".join(blk) for t in VERIF_THEOREM_TRIGGERS):
                i = j; continue
            out.extend(blk); i = j; continue
        if s.startswith("#eval"):
            j, blk = i + 1, [ln]
            while j < len(lines) and (lines[j][:1] in (' ', '\t') or lines[j].strip() == ""):
                blk.append(lines[j]); j += 1
            if any(t in "\n".join(blk) for t in VERIF_EVAL_TRIGGERS):
                i = j; continue
            out.extend(blk); i = j; continue
        out.append(ln); i += 1
    return "\n".join(out)


# ── driver ──────────────────────────────────────────────────────────────────

def main(argv):
    check = "--check" in argv
    args = [a for a in argv[1:] if a != "--check"]
    if not args:
        print(__doc__); return 1
    src_path = args[0]
    out_path = args[1] if len(args) > 1 else None

    with open(src_path, encoding="utf-8") as f:
        src = strip_line_comments(f.read())

    mg = re.search(r'def\s+(\S+?)SemanticGraph\s*:\s*SemanticWorkflowGraph', src)
    if not mg:
        print(f"ERROR: no `<prefix>SemanticGraph` in {src_path}", file=sys.stderr); return 2
    prefix = mg.group(1)

    info = parse_infospec(src, prefix)
    nums = [int(n) for n in dict.fromkeys(re.findall(rf'def\s+{re.escape(prefix)}_semNode(\d+)\b', src))]
    print(f"[{os.path.basename(src_path)}] prefix={prefix!r} semNodes={nums} "
          f"infoSpec={sorted(str(k) for k in info)}")
    if check:
        for n in nums:
            print(f"   semNode{n}: {info.get(n, {})}")
        return 0

    for n in sorted(nums, reverse=True):
        src = transform_semnode(src, prefix, n, info)

    # Parameter-node information (e.g. a param variable that bears an info atom)
    # goes onto the paramNode def so `InformationFlowSpec.fromGraph` surfaces it.
    src = inject_param_info(src, prefix, info.get('param', {}))

    blk = find_def_block(src, re.escape(prefix) + r'_infoSpec')
    if blk:
        src = src[:blk[0]] + src[blk[1]:]

    gblk = find_def_block(src, re.escape(prefix) + r'_goalSpec')
    sgblk = find_def_block(src, re.escape(prefix) + r'SemanticGraph')
    if gblk and sgblk and gblk[0] > sgblk[0]:
        goal_text = src[gblk[0]:gblk[1]]
        src = src[:gblk[0]] + src[gblk[1]:]
        sgblk = find_def_block(src, re.escape(prefix) + r'SemanticGraph')
        src = src[:sgblk[0]] + goal_text + "\n\n" + src[sgblk[0]:]
    sgblk = find_def_block(src, re.escape(prefix) + r'SemanticGraph')
    if sgblk and "goalSpec :=" not in src[sgblk[2]:sgblk[3]]:
        src = src[:sgblk[3]] + f"  goalSpec := {prefix}_goalSpec\n" + src[sgblk[3]:]

    # Capture the old per-channel verdicts BEFORE stripping, to port them to the
    # unified theorems (preserving each plan's expected truth value).
    sem_val = _capture_bool(src, "isSemanticallySoundBool") or "true"
    info_val = _capture_bool(src, "isInformationFlowSoundBool")

    # Consolidate: drop the per-channel Layer-2 evals/theorems and their STEP 6/7
    # section banners — the single verifyWorkflowReport subsumes them.
    src = strip_step67_headers(src)
    src = consolidate_layer2_verif(src)

    unified_lines = [
        "/- ===================== UNIFIED LAYER-2 VERIFICATION ===================== -/",
        "/- One report — variable soundness + information flow + goal coverage. -/",
        f'#eval IO.println ({prefix}SemanticGraph.verifyWorkflowReport (label := "{prefix}"))',
        "",
        f"theorem {prefix}_hoare_sound : ({prefix}SemanticGraph.verifyWorkflow).hoareSound = {sem_val} := by native_decide",
    ]
    if info_val is not None:
        unified_lines.append(
            f"theorem {prefix}_info_sound : ({prefix}SemanticGraph.verifyWorkflow).infoSound = {info_val} := by native_decide")
    unified = "\n" + "\n".join(unified_lines) + "\n"

    # Insert the unified section right after the SemanticGraph def (Layer-2 area,
    # ahead of any Layer-3 STEP 8), falling back to before `end`.
    sgblk = find_def_block(src, re.escape(prefix) + r'SemanticGraph')
    if sgblk:
        src = src[:sgblk[1]] + "\n" + unified + src[sgblk[1]:]
    else:
        src = re.sub(r'\nend AgenticKernel\b', unified + "\nend AgenticKernel", src, count=1)

    out_stem = sanitize_ident(os.path.splitext(os.path.basename(out_path))[0]) if out_path else prefix + "_new"
    src = src.replace("namespace AgenticKernel\n", f"namespace AgenticKernel.{out_stem}\n", 1)
    src = re.sub(r'\nend AgenticKernel\b', f"\nend AgenticKernel.{out_stem}", src, count=1)

    # Drop now-dangling "(see STEP 6…)" parentheticals — those per-channel
    # sections no longer exist (subsumed by the unified report).
    src = re.sub(r'\s*\(see STEP[^)]*\)', '', src)

    # Collapse runs of blank lines left behind by stripped `--` comments.
    src = re.sub(r'\n[ \t]*\n([ \t]*\n)+', '\n\n', src)

    header = ("/- AUTO-PORTED to the Solution-2 Layer-2 idiom by tools/port_to_new_layer2.py.\n"
              "   Graph contributions/verifications/retries and information flow now live on\n"
              "   the semantic nodes; the goal spec is embedded in the graph; one\n"
              "   `verifyWorkflowReport` replaces the old per-channel evals. Inline `--`\n"
              f"   annotations were dropped in porting — see the original {os.path.basename(src_path)}. -/\n\n")
    src = header + src

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"   -> wrote {out_path}")
    else:
        sys.stdout.write(src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

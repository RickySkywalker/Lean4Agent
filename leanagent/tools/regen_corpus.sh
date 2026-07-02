#!/bin/bash
# Regenerate the full VerificationExamples .lean corpus to the NEW engine type model.
# Strategy: reset each file from OLD (pristine original), then apply the validated step-type
# migration (textual step<->task swap + deleted-type->task). Files using a deleted type with a
# non-TString write are flagged for the IR path (migrate_ir_to_new_engine.py) and skipped here.
set +e
NEW=Verifier
OLD=Verifier
TOOL=$NEW/tools/migrate_lean_steptype.py
cd $NEW

mapfile -t FILES < <(grep -rl "stepType :=" VerificationExamples --include=*.lean 2>/dev/null)
echo "corpus files with stepType: ${#FILES[@]}"

# 1. reset each from OLD working tree (originals), then migrate
reset=0; migrated=0
for f in "${FILES[@]}"; do
  if [ -f "$OLD/$f" ]; then cp "$OLD/$f" "$NEW/$f"; reset=$((reset+1)); fi
done
echo "reset $reset files from OLD"

# 2. apply step-type migration to all, EXACTLY ONCE (a second pass would double-swap = no-op).
#    First a --dry-run only to surface the deleted-type+non-TString-write warnings, then the real pass.
python3 "$TOOL" --dry-run "${FILES[@]}" 2>&1 | grep -iE "WARNING|flagged|migrate.*deleted" | head -20
python3 "$TOOL" "${FILES[@]}" >/dev/null 2>&1
echo "migration applied (single pass)"

# 3. summary of step-type distribution post-migration
echo "=== post-migration step-type histogram (corpus) ==="
grep -rhoE "stepType := \.[a-zA-Z]+" VerificationExamples --include=*.lean 2>/dev/null | sort | uniq -c | sort -rn | head
echo "=== remaining DELETED constructors in corpus (want 0): ==="
grep -rlE "stepType := \.(discover|synthesize|validate|save|evaluate)\b" VerificationExamples --include=*.lean 2>/dev/null | sed "s#$NEW/##" || echo "  (none)"

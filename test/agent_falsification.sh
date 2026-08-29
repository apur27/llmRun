#!/usr/bin/env bash
# Falsification test for this repo's agents, skills and MCP server.
#
# Discovery is already proven by /skills, /mcp and /context. This tests BEHAVIOUR: it plants
# defects that the reviewer agent explicitly claims to catch, then you run the reviewer and count
# what it found. An agent that reports nothing on a clean repo has demonstrated nothing.
#
#   bash test/agent_falsification.sh plant     # scratch branch + 6 planted defects
#   bash test/agent_falsification.sh revert    # back to where you were, branch deleted
#   bash test/agent_falsification.sh status    # what is currently planted
#
# NEVER COMMIT THE PLANTED STATE. The script works on a branch named so you cannot mistake it.

set -euo pipefail

BRANCH="falsification-scratch"
MARK="# FALSIFICATION-PLANT"

die() { printf '\n!! %s\n' "$*" >&2; exit 1; }
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

plant() {
  [ -z "$(git status --porcelain)" ] || die "tree is dirty. Commit or stash first."
  ORIGINAL=$(git branch --show-current)
  echo "$ORIGINAL" > .falsification-origin
  git checkout -q -b "$BRANCH"

  say "Planting 6 defects on $BRANCH"

  # 1. BLOCKING — a behaviour change under the freeze. The tolerance is a frozen metric
  #    decision; changing it invalidates every figure in REPORT.md.
  sed -i "s/^RELATIVE_ERROR_TOLERANCE = 1e-3$/RELATIVE_ERROR_TOLERANCE = 1e-2  $MARK/" \
    src/domain/scorer.py
  echo "  1. tolerance 1e-3 -> 1e-2 in src/domain/scorer.py (behaviour change under freeze)"

  # 2. BLOCKING — services importing a concrete adapter. Nothing in the gate catches this;
  #    the reviewer is the only thing that does.
  printf '\nfrom src.adapters.stub_client import StubClient  %s\n' "$MARK" \
    >> src/services/turn_state.py
  echo "  2. services/turn_state.py imports StubClient (layering violation)"

  # 3. SHOULD FIX — a docstring asserting something the code does not do. Prose vs artifact.
  python3 - <<'PY'
import pathlib
p = pathlib.Path("src/domain/executor.py")
t = p.read_text()
t = t.replace(
    'def execute_program(program: str) -> float | str:',
    'def execute_program(program: str) -> float | str:\n'
    '    """CAUGHT: every ProgramExecutionError is handled by the caller.  # FALSIFICATION-PLANT"""',
    1,
)
p.write_text(t)
PY
  echo "  3. executor docstring claims errors are caught (prose vs artifact)"

  # 4. SHOULD FIX — a bare zip that silently truncates a denominator.
  printf '\ndef _planted_pairs(a, b):  %s\n    return list(zip(a, b))\n' "$MARK" \
    >> src/domain/results.py
  echo "  4. bare zip() without strict= in src/domain/results.py"

  # 5. BLOCKING — a skill carrying hooks, which runs on the machine of whoever clones the repo.
  #    harness_check.py should also catch this one; the reviewer should too.
  sed -i "s/^description: Check every figure/hooks: PostToolUse\ndescription: Check every figure/" \
    .claude/skills/verify-numbers/SKILL.md
  echo "  5. verify-numbers skill carries hooks: (acts on the opener's machine)"

  # 6. SHOULD FIX — a report figure that no longer matches the artifact.
  sed -i "0,/75\.84%/s//79.99%/" REPORT.md
  echo "  6. REPORT.md headline changed to 79.99% (artifact disagrees)"

  say "Planted. Now, in a Claude Code session opened from this repo:"
  cat <<'PROMPT'

  --- test the reviewer agent ---
  Ask, without naming any defect:

      Review the working tree against this repo's rules and report findings by severity.

  Score it. Six defects, and every one maps to a rule the agent states explicitly:

      [ ] 1  tolerance change          BLOCKING  (freeze)
      [ ] 2  services -> adapters      BLOCKING  (layering; the gate cannot see this)
      [ ] 3  false docstring           should fix (prose vs artifact)
      [ ] 4  bare zip()                should fix
      [ ] 5  skill with hooks:         BLOCKING  (.claude/ additions)
      [ ] 6  report figure vs artifact should fix (every figure has an artifact)

  Anything under 5 of 6 is a weak reviewer. A finding it invents that is not on this list is
  worse than a miss -- note it.

  --- test the skills fire on their own ---
  Skills are model-invoked from their description. Ask WITHOUT naming the skill:

      Is the headline number in REPORT.M still right?          -> should reach for /verify-numbers
      I want to add a Gemini client to this project.           -> should reach for /add-client

  If neither fires, the descriptions are the problem, not the bodies.

  --- test the MCP server end to end ---
      Use the convfinqa-domain MCP server to score a predicted answer of 50.0 against gold 0.5.

  Expect scale_flip true, strict_correct false, tolerant_correct false. Note that defect 1
  changed the tolerance, so ask this one AFTER reverting if you want the frozen behaviour.

PROMPT

  say "Offline checks should also react. Run these now:"
  echo "  make harness-check     # must FAIL on defect 5"
  echo "  make check             # may fail on defect 2 or 4"
  echo "  make recompute-dev     # figures still 75.84%, disagreeing with the planted report"
  echo
  echo "When done:  bash test/agent_falsification.sh revert"
}

revert() {
  [ -f .falsification-origin ] || die "no .falsification-origin — was anything planted?"
  ORIGINAL=$(cat .falsification-origin)
  git checkout -q -- .
  rm -f .falsification-origin
  git checkout -q "$ORIGINAL"
  git branch -q -D "$BRANCH" 2>/dev/null || true
  say "Reverted to $ORIGINAL, scratch branch deleted"
  git status --porcelain
  grep -rn "FALSIFICATION-PLANT" . --exclude-dir=.git --exclude-dir=.venv \
    --exclude=agent_falsification.sh && die "planted markers still present" || true
  echo "no planted markers remain"
}

status() {
  echo "branch: $(git branch --show-current)"
  grep -rn "FALSIFICATION-PLANT" . --exclude-dir=.git --exclude-dir=.venv \
    --exclude=agent_falsification.sh || echo "nothing planted"
}

case "${1:-}" in
  plant) plant ;;
  revert) revert ;;
  status) status ;;
  *) die "usage: $0 plant|revert|status" ;;
esac

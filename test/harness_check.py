#!/usr/bin/env python3
"""Verify this repo's Claude Code scaffolding -- everything that is checkable offline.

Written against `.claude/standards/harness/claude-code.md` as verified 2026-08-17 against
https://code.claude.com/docs/en/memory and /skills, and the MCP page fetched 2026-08-29.

WHAT THIS CANNOT DO
-------------------
It cannot prove an instruction file was actually *loaded*. Only `/context` inside a live session
lists what Claude Code read, and nothing offline substitutes for it. Every failure mode below is
one that produces no error at all -- a skill in a directory that is never scanned, an import that
silently resolves nowhere, a `description` truncated past the point where it still triggers. That
is the whole reason this file exists: the silent ones are the ones a test has to catch.

    make harness-check      # this file
    /context                # in a session -- the only proof instruction files loaded
    /mcp                    # in a session -- server status and tool discovery
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# From the harness reference, all documented limits:
CLAUDE_MD_TARGET_LINES = 200  # "target under 200 lines"; guidance, not enforced by the harness
SKILL_BODY_MAX_LINES = 500  # "body should stay under 500 lines"
LISTING_TRUNCATION = 1536  # description + when_to_use truncated at 1,536 chars in the listing
MAX_IMPORT_DEPTH = 4  # "maximum depth four hops"

# A project skill's allowed-tools applies even in an untrusted folder, and a hooks: field
# registers hooks for the session. Both act on the machine of whoever clones this repo.
REVIEW_BLOCKING_FIELDS = ("hooks", "allowed-tools", "disallowed-tools")

failures: list[str] = []
warnings: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def note(msg: str) -> None:
    notes.append(msg)


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-ish frontmatter without a yaml dependency. Flat key: value only."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    block, body = text[4:end], text[end + 4 :]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if line.strip() and not line.startswith((" ", "\t")) and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, body


def check_instruction_file() -> None:
    """CLAUDE.md must exist at a location Claude Code actually reads."""
    candidates = [ROOT / "CLAUDE.md", ROOT / ".claude" / "CLAUDE.md"]
    found = [p for p in candidates if p.exists()]
    if not found:
        fail("no CLAUDE.md at ./CLAUDE.md or ./.claude/CLAUDE.md — agents open this repo blind")
        return
    if len(found) == 2:
        # Discovery is walk-up-and-concatenate, not nearest-wins: both would load.
        warn("both ./CLAUDE.md and ./.claude/CLAUDE.md exist — both load, concatenated")

    path = found[0]
    lines = path.read_text().splitlines()
    note(f"{path.relative_to(ROOT)}: {len(lines)} lines")
    if len(lines) > CLAUDE_MD_TARGET_LINES:
        warn(
            f"{path.relative_to(ROOT)} is {len(lines)} lines, over the documented "
            f"{CLAUDE_MD_TARGET_LINES}-line target. Nothing truncates it; the cost is context "
            "budget and adherence."
        )
    check_imports(path, depth=0, seen=set())

    if (ROOT / "AGENTS.md").exists():
        first = next((ln for ln in lines if ln.strip()), "")
        if "@AGENTS.md" not in path.read_text():
            warn(
                "AGENTS.md exists but CLAUDE.md does not import it. Claude Code does not read "
                "AGENTS.md natively — the two files will drift. Bridge with a first-line "
                f"@AGENTS.md import. (first line is {first!r})"
            )


def check_imports(path: Path, depth: int, seen: set[Path]) -> None:
    """Follow @path imports. Depth cap 4; outside-repo imports show an approval dialog once."""
    if depth > MAX_IMPORT_DEPTH:
        fail(f"{path.relative_to(ROOT)}: import chain deeper than {MAX_IMPORT_DEPTH} hops")
        return
    if path in seen:
        return
    seen.add(path)

    text = path.read_text()
    # Import parsing skips code spans and fenced blocks, so strip those before matching.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)

    for match in re.finditer(r"(?:^|\s)@([\w./~-]+)", text):
        target = match.group(1)
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            fail(
                f"{path.relative_to(ROOT)}: imports {target!r} from outside the repo. That shows "
                "a one-time approval dialog to whoever opens this repo, and declining disables "
                "it permanently and silently."
            )
            continue
        if not resolved.exists():
            fail(f"{path.relative_to(ROOT)}: imports {target!r}, which does not exist")
            continue
        check_imports(resolved, depth + 1, seen)


def check_skills() -> None:
    """Skills live at .claude/skills/<name>/SKILL.md; the DIRECTORY name is the command."""
    skills_dir = ROOT / ".claude" / "skills"
    if not skills_dir.is_dir():
        note("no .claude/skills/")
        return

    found = 0
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            warn(f".claude/skills/{child.name} is not a directory — it will not be discovered")
            continue
        skill = child / "SKILL.md"
        if not skill.exists():
            fail(f".claude/skills/{child.name}/ has no SKILL.md — silently not a skill")
            continue
        found += 1
        fields, body = split_frontmatter(skill.read_text())

        if not fields.get("description"):
            warn(f"/{child.name}: no description — the model has nothing to trigger on")

        # The command name comes from the directory. A mismatched `name` is a display label
        # only, which makes it a quiet trap for anyone reading the frontmatter.
        declared = fields.get("name")
        if declared and declared != child.name:
            warn(
                f"/{child.name}: frontmatter name is {declared!r} but the command comes from the "
                f"directory, so this is /{child.name}. The name field is a display label here."
            )

        listing = len(fields.get("description", "")) + len(fields.get("when_to_use", ""))
        if listing > LISTING_TRUNCATION:
            warn(
                f"/{child.name}: description + when_to_use is {listing} chars, truncated at "
                f"{LISTING_TRUNCATION} in the listing"
            )

        body_lines = len(body.splitlines())
        if body_lines > SKILL_BODY_MAX_LINES:
            warn(
                f"/{child.name}: body is {body_lines} lines, over the {SKILL_BODY_MAX_LINES} "
                "guidance. Once invoked it stays in context for the rest of the session."
            )

        for field in REVIEW_BLOCKING_FIELDS:
            if field in fields:
                fail(
                    f"/{child.name}: carries {field!r}. A project skill's tool permissions apply "
                    "even in a folder the opener never trusted, and a hooks field registers hooks "
                    "for the session — this acts on the machine of whoever clones the repo. "
                    "Remove it, or have a human explicitly approve it."
                )

    note(f"{found} skill(s): {', '.join(p.name for p in sorted(skills_dir.iterdir()) if p.is_dir())}")


def check_agents() -> None:
    """Subagents need parseable frontmatter to be discovered at all."""
    agents_dir = ROOT / ".claude" / "agents"
    if not agents_dir.is_dir():
        note("no .claude/agents/")
        return
    for path in sorted(agents_dir.glob("*.md")):
        fields, _ = split_frontmatter(path.read_text())
        for required in ("name", "description"):
            if not fields.get(required):
                fail(f".claude/agents/{path.name}: no {required} in frontmatter")
        if "hooks" in fields:
            fail(f".claude/agents/{path.name}: carries a hooks field — runs on the opener's machine")
    note(f"{len(list(agents_dir.glob('*.md')))} agent(s)")


def check_mcp() -> None:
    """Project MCP config is .mcp.json at the repo root, under mcpServers. Committed, approved once."""
    path = ROOT / ".mcp.json"
    if not path.exists():
        note("no .mcp.json")
        return
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f".mcp.json does not parse: {exc}")
        return

    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        fail(".mcp.json has no non-empty 'mcpServers' object — nothing will load")
        return

    secret = re.compile(r"(sk-|ghp_|Bearer\s+[A-Za-z0-9])", re.I)
    for name, spec in servers.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            fail(f".mcp.json: server name {name!r} — only letters, numbers, hyphens, underscores")

        blob = json.dumps(spec)
        if secret.search(blob):
            fail(f".mcp.json: server {name!r} looks like it contains a literal credential")

        url = spec.get("url")
        if url:
            warn(
                f".mcp.json: server {name!r} is remote ({url}). Anyone approving this repo's MCP "
                "config is trusting that endpoint. A server that fetches external content can "
                "carry prompt injection into the session."
            )

        # ${VAR} in a project-scoped entry needs a default, or it expands to nothing.
        for var in re.findall(r"\$\{([^}]*)\}", blob):
            if ":-" not in var:
                fail(
                    f".mcp.json: server {name!r} uses ${{{var}}} with no default. In a "
                    "project-scoped entry that expands empty — use ${" + var + ":-.} or similar."
                )

        command = spec.get("command")
        if command and not url:
            args = " ".join(str(a) for a in spec.get("args", []))
            local = [
                a
                for a in spec.get("args", [])
                if isinstance(a, str) and a.endswith(".py") and not (ROOT / a).exists()
            ]
            for missing in local:
                fail(f".mcp.json: server {name!r} points at {missing}, which does not exist")
            note(f".mcp.json: {name} = stdio, {command} {args}")

    note("project MCP config prompts for approval on first load — that dialog is a feature")


def check_mcp_server_runs() -> None:
    """The stdio server must at least import and pass its own selftest."""
    server = ROOT / "mcp_server" / "scorer_server.py"
    if not server.exists():
        return
    proc = subprocess.run(
        [sys.executable, str(server), "--selftest"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        fail(f"mcp_server selftest failed (exit {proc.returncode}):\n{proc.stdout}{proc.stderr}")
    else:
        note("mcp_server selftest passed")


def main() -> int:
    check_instruction_file()
    check_skills()
    check_agents()
    check_mcp()
    check_mcp_server_runs()

    for n in notes:
        print(f"     {n}")
    for w in warnings:
        print(f"warn {w}")
    for f in failures:
        print(f"FAIL {f}", file=sys.stderr)

    print(
        f"\n{len(notes)} note(s), {len(warnings)} warning(s), {len(failures)} failure(s)\n"
        "\nThis proves nothing about what Claude Code actually LOADED. Run /context in a session\n"
        "for that, and /mcp for server status. Both are cheap; neither has an offline substitute."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

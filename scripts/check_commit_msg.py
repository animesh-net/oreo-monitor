"""Reject commit messages that break the conventions in CLAUDE.md.

Usage: check_commit_msg.py FILE   (a FILE of "-" reads the message from stdin)
"""

import re
import sys
from pathlib import Path

MAX_LENGTH = 72
SCISSORS = "# ------------------------ >8 ------------------------"
# Lines that are never allowed in a commit message or a pull request description: any
# co-author or agent trailer, an agent's session link, or "generated/requested by" an agent.
AGENTS = r"claude|anthropic|copilot|openai|chatgpt|gpt|gemini|codex|cursor|\bai\b|llm|agent"
FORBIDDEN_LINE = re.compile(
    r"^\W*(co-authored-by|co-committed-by|claude-session|generated-by|requested-by|assisted-by)\s*:"
    r"|claude\.ai/code"
    r"|(generated|requested|created|written|authored)\s+(by|with|using)\b.*(" + AGENTS + ")",
    re.IGNORECASE,
)
# Deliberately vague, so the check does not advertise what it looks for.
NOT_ALLOWED = "message contains a line that is not allowed"


def problems(message: str) -> list[str]:
    message = message.split(SCISSORS)[0]
    lines = [line for line in message.splitlines() if not line.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or not lines[0].strip():
        return ["message is empty"]

    subject = lines[0]
    found = []
    if not subject[0].isupper():
        found.append("subject must start with a capital letter")
    if len(subject) > MAX_LENGTH:
        found.append(f"subject is {len(subject)} characters, the limit is {MAX_LENGTH}")
    if re.match(r"wip\b", subject, re.IGNORECASE):
        found.append("never commit WIP")
    if len(lines) > 1:
        found.append("message must be a single line with no body")
    if any(FORBIDDEN_LINE.search(line) for line in lines):
        found.append(NOT_ALLOWED)
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    message = sys.stdin.read() if argv[0] == "-" else Path(argv[0]).read_text()
    found = problems(message)
    if found:
        subject = message.strip().splitlines()[0] if message.strip() else ""
        print(f"Commit message rejected: {subject!r}", file=sys.stderr)
        for problem in found:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

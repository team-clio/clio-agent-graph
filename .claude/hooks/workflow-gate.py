#!/usr/bin/env python3
"""workflow-rule 적용 여부를 묻기 전에는 파일 변경과 커밋을 막는 PreToolUse hook.

현재 브랜치가 .claude/workflow-mode.json 에 기록돼 있으면 통과시키고,
없으면 deny 하면서 "먼저 사용자에게 물어라"를 돌려준다.
자세한 규칙은 mydocs/workflow-rules.md 를 참고한다.
"""

import json
import os
import re
import subprocess
import sys

STATE_REL = os.path.join(".claude", "workflow-mode.json")

# Bash 로 우회되는 쓰기 경로. 커밋은 항상 막고, 대표적인 in-place 편집도 함께 막는다.
BASH_WRITE_PATTERNS = [
    r"\bgit\s+commit\b",
    r"\bsed\s+(-[a-zA-Z]*\s+)*-i\b|\bsed\s+-i\b",
    r"\bperl\s+(-\w+\s+)*-i",
    r"\btee\b",
    r">>?\s*\S",
]

DENY_MESSAGE = (
    "workflow-rule 적용 여부가 아직 정해지지 않았다 (브랜치: {branch}).\n"
    "파일을 바꾸기 전에 사용자에게 먼저 물어야 한다.\n\n"
    "1. AskUserQuestion 으로 이 작업에 mydocs/workflow-rules.md 절차를 적용할지 묻는다.\n"
    "   판단 기준은 그 문서의 '적용 기준' 표를 따르고, 추천값도 함께 제시한다.\n"
    '2. 답을 {state} 에 기록한다: {{"{branch}": "on" 또는 "off"}}\n'
    "3. 그 뒤에 작업을 계속한다. 같은 브랜치에서는 다시 묻지 않는다."
)


def allow():
    """결정을 내리지 않고 통과시킨다(정상 권한 흐름)."""
    sys.exit(0)


def deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    state_path = os.path.join(project, STATE_REL)

    if tool in ("Edit", "Write", "NotebookEdit"):
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        # 상태 파일 자체를 쓰는 것은 막지 않는다. 막으면 답을 기록할 방법이 없다.
        if target and os.path.abspath(target) == os.path.abspath(state_path):
            allow()
    elif tool == "Bash":
        command = tool_input.get("command", "")
        if STATE_REL in command or "workflow-mode.json" in command:
            allow()
        if not any(re.search(p, command) for p in BASH_WRITE_PATTERNS):
            allow()
    else:
        allow()

    branch = subprocess.run(
        ["git", "-C", project, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    if branch.returncode != 0:
        allow()  # git 저장소가 아니면 막지 않는다
    name = branch.stdout.strip()

    state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                state = loaded
        except (json.JSONDecodeError, OSError):
            state = {}

    if name in state:
        allow()

    deny(DENY_MESSAGE.format(branch=name, state=STATE_REL))


if __name__ == "__main__":
    main()

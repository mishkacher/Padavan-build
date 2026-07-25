from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

WORKFLOW_ROOT = Path(".github/workflows")
POLICY_WORKFLOW = Path(".github/workflows/docker-runner-policy.yml")
WORKFLOW_PATTERNS = ("*.yml", "*.yaml")

JOB_RE = re.compile(r"^  (?P<job>[A-Za-z0-9_.-]+):(?:\s*(?:#.*)?)$")
RUNS_ON_RE = re.compile(r"^    runs-on:\s*(?P<value>.*?)(?:\s+#.*)?$")
JOB_LEVEL_DOCKER_RE = re.compile(r"^    (?:container|services):(?:\s|$)")
USES_RE = re.compile(r"^\s+(?:-\s+)?uses:\s*(?P<value>.+?)\s*(?:#.*)?$")
RUN_RE = re.compile(r"^(?P<indent>\s+)(?:-\s+)?run:\s*(?P<value>.*)$")

DOCKER_COMMAND_RE = re.compile(
    r"""(?ix)
    (?:^|[\s;&|()])
    (?:sudo\s+)?
    docker(?:\s|$)
    |
    (?:^|[\s;&|()])
    docker-compose(?:\s|$)
    |
    \bDOCKER_(?:BUILDKIT|HOST|TLS_VERIFY|CERT_PATH|CONTEXT)\b
    |
    \b(?:make|just|task)\s+[^\n#]*(?:docker|container)
    |
    (?:^|[\s;&|()])
    (?:\./)?[\w./-]*docker[\w./-]*\.(?:sh|py)(?:\s|$)
    """
)
DOCKER_LABEL_RE = re.compile(
    r"(?i)(?:^|[\s,\[\]{}'\"-])docker(?:$|[\s,\[\]{}'\"-])"
)


@dataclass(frozen=True)
class JobBlock:
    name: str
    lines: list[str]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _workflow_files(root: Path) -> list[Path]:
    workflow_root = root / WORKFLOW_ROOT
    return sorted(
        path
        for pattern in WORKFLOW_PATTERNS
        for path in workflow_root.glob(pattern)
        if path.is_file() and path.relative_to(root) != POLICY_WORKFLOW
    )


def _job_blocks(text: str) -> list[JobBlock]:
    lines = text.splitlines()
    jobs_index: int | None = None
    for index, line in enumerate(lines):
        if line == "jobs:":
            jobs_index = index
            break
    if jobs_index is None:
        return []

    blocks: list[JobBlock] = []
    current_name: str | None = None
    current_lines: list[str] = []

    for line in lines[jobs_index + 1 :]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and _indent(line) == 0:
            break

        match = JOB_RE.match(line)
        if match:
            if current_name is not None:
                blocks.append(JobBlock(current_name, current_lines))
            current_name = match.group("job")
            current_lines = [line]
            continue

        if current_name is not None:
            current_lines.append(line)

    if current_name is not None:
        blocks.append(JobBlock(current_name, current_lines))
    return blocks


def _runs_on_selector(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = RUNS_ON_RE.match(line)
        if not match:
            continue

        value = match.group("value").strip()
        selector_lines = [value] if value else []
        base_indent = _indent(line)
        for continuation in lines[index + 1 :]:
            stripped = continuation.strip()
            if not stripped:
                continue
            if _indent(continuation) <= base_indent:
                break
            selector_lines.append(stripped)
        return " ".join(selector_lines).strip()
    return None


def _docker_evidence(lines: list[str]) -> str | None:
    for line in lines:
        if JOB_LEVEL_DOCKER_RE.match(line):
            return line.strip()

        uses_match = USES_RE.match(line)
        if uses_match:
            value = uses_match.group("value").strip().strip("\"'")
            normalized = value.lower()
            if normalized.startswith("docker/") or normalized.startswith("docker://"):
                return f"uses: {value}"

    for index, line in enumerate(lines):
        run_match = RUN_RE.match(line)
        if not run_match:
            continue

        inline_value = run_match.group("value").strip()
        command_lines: list[str] = []
        if inline_value not in {"", "|", ">", "|-", ">-", "|+", ">+"}:
            command_lines.append(inline_value)

        run_indent = len(run_match.group("indent"))
        for continuation in lines[index + 1 :]:
            stripped = continuation.strip()
            if stripped and _indent(continuation) <= run_indent:
                break
            if stripped:
                command_lines.append(stripped)

        command = "\n".join(command_lines)
        if DOCKER_COMMAND_RE.search(command):
            compact = " ".join(command.split())
            return f"run: {compact[:160]}"

    return None


def audit(root: Path) -> list[str]:
    errors: list[str] = []
    for path in _workflow_files(root):
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(root)

        for job in _job_blocks(text):
            evidence = _docker_evidence(job.lines)
            if evidence is None:
                continue

            selector = _runs_on_selector(job.lines)
            if selector is None:
                errors.append(
                    f"{relative_path}:{job.name}: Docker workload detected ({evidence}), "
                    "but the job has no runs-on selector"
                )
                continue

            if DOCKER_LABEL_RE.search(selector) is None:
                errors.append(
                    f"{relative_path}:{job.name}: Docker workload detected ({evidence}), "
                    f"but runs-on is {selector!r}; add the docker label, normally "
                    "runs-on: [self-hosted, docker]"
                )
    return errors


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    errors = audit(root)
    if errors:
        print("Docker runner routing violations:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Docker runner routing policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(".github/workflows")
SELF = Path(".github/workflows/docker-runner-policy.yml")
ORDER = ("docker", "postgresql", "redis")
RUNS_ON = re.compile(r"^    runs-on:\s*(.*?)(?:\s+#.*)?$", re.M)
LABEL = {name: re.compile(rf"(?i)(?:^|[\s,\[\]{{}}'\"-]){name}(?:$|[\s,\[\]{{}}'\"-])") for name in ORDER}
DOCKER = re.compile(r"""(?ixm)
^[ ]{4}(?:container|services):(?:\s|$)|
^\s+(?:-\s+)?uses:\s*['"]?(?:docker/|docker://)|
(?:^|[\s;&|()])(?:sudo\s+)?docker(?:-compose)?(?:\s|$)|
\bDOCKER_(?:BUILDKIT|HOST|TLS_VERIFY|CERT_PATH|CONTEXT)\b
""")
POSTGRES = re.compile(r"""(?ixm)
^\s+(?:postgres|postgresql):(?:\s|$)|
^\s+image:\s*['"]?postgres(?:ql)?(?::|@|\s|['"]|$)|
postgres(?:ql)?://|
\b(?:POSTGRES_[A-Z0-9_]+|PG(?:HOST|PORT|USER|PASSWORD|DATABASE|SSLMODE))\b|
(?:^|[\s;&|()])(?:sudo\s+)?(?:psql|pg_isready|pg_dump|pg_dumpall|pg_restore|postgres|initdb|createdb|dropdb)(?:\s|$)|
(?:docker(?:\s+compose)?|docker-compose|make|just|task)[^\n#]*(?:postgres|postgresql)
""")
REDIS = re.compile(r"""(?ixm)
^\s+redis:\s*(?:\s|$)|
^\s+image:\s*['"]?redis(?::|@|\s|['"]|$)|
redis(?:s)?://|
\bREDIS_[A-Z0-9_]+\b|
(?:^|[\s;&|()])(?:sudo\s+)?redis-(?:cli|server|benchmark|sentinel)(?:\s|$)|
(?:docker(?:\s+compose)?|docker-compose|make|just|task)[^\n#]*\bredis\b
""")
DETECTORS = {"docker": DOCKER, "postgresql": POSTGRES, "redis": REDIS}


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def jobs(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    try:
        start = lines.index("jobs:") + 1
    except ValueError:
        return []
    result: list[tuple[str, str]] = []
    name: str | None = None
    block: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and indent(line) == 0:
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_.-]+):(?:\s*#.*)?", line)
        if match:
            if name is not None:
                result.append((name, "\n".join(block)))
            name, block = match.group(1), [line]
        elif name is not None:
            block.append(line)
    if name is not None:
        result.append((name, "\n".join(block)))
    return result


def selector(block: str) -> str | None:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = RUNS_ON.match(line)
        if not match:
            continue
        parts = [match.group(1).strip()] if match.group(1).strip() else []
        base = indent(line)
        for extra in lines[index + 1:]:
            if extra.strip() and indent(extra) <= base:
                break
            if extra.strip():
                parts.append(extra.strip())
        return " ".join(parts)
    return None


def audit(repo: Path) -> list[str]:
    errors: list[str] = []
    for pattern in ("*.yml", "*.yaml"):
        for path in sorted((repo / ROOT).glob(pattern)):
            if not path.is_file() or path.relative_to(repo) == SELF:
                continue
            for job_name, block in jobs(path.read_text(encoding="utf-8")):
                required = [name for name in ORDER if DETECTORS[name].search(block)]
                if not required:
                    continue
                current = selector(block)
                expected = f"[{', '.join(('self-hosted', *required))}]"
                if current is None:
                    errors.append(f"{path.relative_to(repo)}:{job_name}: missing runs-on; use {expected}")
                    continue
                missing = [name for name in required if not LABEL[name].search(current)]
                if missing:
                    errors.append(f"{path.relative_to(repo)}:{job_name}: runs-on {current!r} misses {', '.join(missing)}; normally use {expected}")
    return errors


def main() -> int:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    errors = audit(repo)
    if errors:
        print("Dependency runner routing violations:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Dependency runner routing policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

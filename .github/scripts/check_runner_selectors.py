#!/usr/bin/env python3
from __future__ import annotations
import re
import sys
from pathlib import Path
ALLOWED={"[self-hosted, fast]","[self-hosted, docker]","[self-hosted, backtester]","[self-hosted, macOS, ARM64]"}
RUNS_ON=re.compile(r"^\s+runs-on:\s*(?P<value>.*?)\s*(?:#.*)?$")
errors=[]
for path in sorted(Path('.github/workflows').glob('*.y*ml')):
    for number,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        match=RUNS_ON.match(line)
        if match and match.group('value') not in ALLOWED:
            errors.append(f"{path}:{number}: forbidden runs-on selector {match.group('value')!r}")
if errors:
    print('Only four exact self-hosted runner selectors are allowed:',file=sys.stderr)
    for error in errors: print(f'- {error}',file=sys.stderr)
    raise SystemExit(1)
print('Runner selector policy passed.')

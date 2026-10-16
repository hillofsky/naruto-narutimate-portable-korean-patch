#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys
here = Path(__file__).resolve().parent
cmd = [sys.executable, str(here/"build_sub51n_titlehomepolish.py"),
       "--root", r"PROJECT_ROOT",
       "--assets", str(here/"analysis/sub/sub51n_titlehomepolish/build_assets")]
p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
log = here/"sub51n_python_output.log"
log.write_text(p.stdout, encoding="utf-8")
print(p.stdout, end="")
sys.exit(p.returncode)

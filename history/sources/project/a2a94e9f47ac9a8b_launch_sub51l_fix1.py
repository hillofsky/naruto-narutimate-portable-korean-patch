#!/usr/bin/env python3
# Captures stdout+stderr from the real builder so failure ZIP always has the exact Python error.
from pathlib import Path
import subprocess,sys
here=Path(__file__).resolve().parent
cmd=[sys.executable,str(here/"build_sub51l_fix1_consolidated_ui.py"),
     "--root",r"PROJECT_ROOT","--assets",str(here/"assets")]
p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors="replace")
log=here/"sub51l_fix1_python_output.log"
log.write_text(p.stdout,encoding="utf-8")
print(p.stdout,end="")
sys.exit(p.returncode)

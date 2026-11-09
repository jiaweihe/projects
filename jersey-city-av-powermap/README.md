# Jersey City Autonomous Mobility Power Map

**Read [POWERMAP.md](POWERMAP.md).** The data lives in `stakeholders.json`; every claim has a source URL.

    python build.py                 # regenerate POWERMAP.md
    python -m pytest -q             # validate (add LIVE=1 to check links)

The run log and known gaps are in [ITERATIONS.md](ITERATIONS.md).

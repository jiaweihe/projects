#!/bin/bash
cd /home/user/projects/roam-transit-os
echo "== tests+coverage"; timeout 900 python3 -m pytest -q -p no:cacheprovider --cov=roam --cov-report=term 2>&1 | grep -E "passed|failed|^TOTAL"
echo "== ruff"; ruff check roam tests -q --statistics 2>&1 | tail -15; echo "ruff total: $(ruff check roam tests --output-format concise -q 2>/dev/null | wc -l)"
echo "== mypy"; mypy roam --ignore-missing-imports --no-error-summary 2>&1 | grep -c "error:"
echo "== LOC"; find roam -name '*.py' | xargs cat | grep -cvE '^\s*(#|$)'
echo "== bench"
python3 - <<'PY'
import time
from datetime import date
from roam.platform import Platform
from roam.sim.runner import simulate_day
from roam.sim.demand import DemandSpec
t=time.perf_counter(); p=Platform(today=date(2026,11,16))
for n in ["mercer_county_nj","austin_tx","miami_dade_fl"]: p.provision(f"tenants/{n}.yaml")
t1=time.perf_counter()
simulate_day(p,date(2026,11,17),{"mercer_county_nj":DemandSpec(60,40),"austin_tx":DemandSpec(0,60,20),"miami_dade_fl":DemandSpec(80,0,20)},seed=7)
t2=time.perf_counter()
from roam.config.schema import load_config
from roam.proposal.generator import ProposalInput, generate_proposal
cfg,g=load_config("tenants/mercer_county_nj.yaml")
generate_proposal(ProposalInput(name="M",state="NJ",boundary=g["mercer_para"],population=387340,microtransit_boundary=g["mercer_micro"],depot=tuple(cfg.depot),sample_cap=70))
t3=time.perf_counter()
print(f"provision3={t1-t:.2f}s sim3tenants={t2-t1:.2f}s proposal_mercer={t3-t2:.2f}s")
PY
echo "== build"; s=$(date +%s.%N); pip wheel -q --no-deps -w /tmp/claude-0/-home-user-projects/a68cce91-279d-5b77-8a10-2c76c5a1f94b/scratchpad/whl . >/dev/null 2>&1; echo "build=$(echo "$(date +%s.%N)-$s"|bc)s"

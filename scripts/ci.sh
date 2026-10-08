#!/bin/sh
# Run synchronously from a clean checkout; every failed stage stops the run.
set -eu
cd "$(dirname "$0")/.."
MODE=${1:---quick}
case "$MODE" in --quick|--replay|--full) ;; *) echo 'Usage: sh scripts/ci.sh [--quick|--replay|--full]' >&2; exit 2;; esac
export PYTHONPATH="$(pwd)/src:$(pwd)/vendor/python-fluent${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p results
python scripts/verify_vendor.py
python scripts/verify_inputs.py
python -m pytest -q -p no:cacheprovider
python scripts/make_controls.py
python scripts/pilot.py > results/pilot-summary.json
python scripts/extraction_baseline.py > results/extraction-stdout.json
python scripts/evaluate.py > results/control-stdout.json
python scripts/flow_validation.py > results/flow-validation-stdout.json
python scripts/jupyter_boundary.py > results/jupyter-stdout.json
python scripts/fluent_evaluate.py > results/fluent-stdout.json
python scripts/openhangar_boundary.py > results/openhangar-stdout.json
python scripts/xrpl_boundary.py > results/xrpldashboard-stdout.json
python scripts/azm_build_boundary.py > results/azm-build-stdout.json
python scripts/project_audit_evaluate.py > results/project-audit-stdout.json
python scripts/holdout_evaluate.py > results/holdout-stdout.json
python scripts/babel_cli_evaluate.py > results/babel-cli-stdout.json
python scripts/project_scaling.py > results/project-scaling-stdout.json
python scripts/bedrock_boundary.py > results/bedrock-stdout.json
if [ "$MODE" = --full ]; then
    python scripts/partition_evaluate.py > results/validation-stdout.json
    python scripts/partition_confirm.py > results/confirmation-stdout.json
    python scripts/cost_evaluate.py > results/costs-stdout.json
fi
python scripts/weblate_evaluate.py > results/weblate-core-stdout.json
python scripts/localhero_evaluate.py > results/localhero-core-stdout.json
python scripts/public_fix_screen.py > results/public-fix-screen-stdout.json
python scripts/statistical_analysis.py > results/statistical-analysis-stdout.json
python scripts/reference_audit.py > results/reference-audit-stdout.json
python scripts/availability.py > results/availability-stdout.json
python scripts/coverage_report.py > results/branch-coverage-stdout.json
python scripts/selector_reference.py > results/selector-reference-stdout.json
python scripts/report.py > results/report-stdout.json
python scripts/verify_inputs.py
python scripts/audit_results.py
if [ "$MODE" = --replay ]; then
    python scripts/native_replay.py
fi
printf '\nMsgBranch local %s replay completed. Timings are not golden outputs.\n' "$MODE"

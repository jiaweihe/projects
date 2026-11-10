import json

from roam.cli import main

from .conftest import SQUARE, TENANTS


def test_validate_and_golive_exit_codes(tmp_path, capsys):
    assert main(["validate", str(TENANTS / "mercer_county_nj.yaml")]) == 0
    capsys.readouterr()
    assert main(["golive", str(TENANTS / "mercer_county_nj.yaml"), "--out", str(tmp_path)]) == 1  # MOVES blocker
    report = json.loads(capsys.readouterr().out.split("\nNOT LIVE")[0])
    assert report["errors"] == [] and any("MOVES" in b for b in report["golive_blockers"])
    assert main(["golive", str(TENANTS / "austin_tx.yaml"), "--simulation-only", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "austin_tx" / "gtfs_flex.zip").exists()


def test_simulate_prints_kpis_and_seat_stats(capsys):
    rc = main(
        ["simulate", str(TENANTS / "austin_tx.yaml"), "--paratransit", "0", "--microtransit", "15", "--av", "5", "--date", "2026-11-17"]
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["service_date"] == "2026-11-17"
    assert out["kpis"]["austin_tx"]["trips_completed"] > 0 and out["ops_seat"]["tenants"] == 1


def test_simulate_skips_weekends_to_a_service_day(capsys):
    main(["simulate", str(TENANTS / "austin_tx.yaml"), "--paratransit", "0", "--microtransit", "5", "--av", "0", "--date", "2026-11-21"])
    assert json.loads(capsys.readouterr().out)["service_date"] == "2026-11-23"  # Saturday -> Monday


def test_propose_from_boundary_file(tmp_path, capsys):
    b = tmp_path / "town.geojson"
    b.write_text(json.dumps({"type": "Feature", "geometry": SQUARE, "properties": {}}))
    rc = main(["propose", "--boundary", str(b), "--name", "Small Town", "--state", "PA", "--population", "20000", "--out", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and set(out["costs"]) == {"phase_1", "phase_2", "phase_3"}
    assert (tmp_path / "small_town_proposal.pdf").read_bytes()[:4] == b"%PDF"


def test_propose_refuses_excluded_city_cleanly(tmp_path, capsys):
    b = tmp_path / "jc.geojson"
    b.write_text(json.dumps(SQUARE))
    assert main(["propose", "--boundary", str(b), "--name", "Jersey City", "--state", "NJ", "--out", str(tmp_path)]) == 2
    assert "does not propose in Jersey City" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.pdf"))


def test_every_roam_command_in_the_readme_parses():
    """Docs drift guard: commands shown in README must exist with those flags."""
    import shlex

    from roam.cli import build_parser

    from .conftest import ROOT

    readme = (ROOT / "README.md").read_text()
    cmds = [ln.split("#")[0].strip() for ln in readme.splitlines() if ln.strip().startswith("roam ")]
    assert len(cmds) >= 5
    parser = build_parser()
    for cmd in cmds:
        parser.parse_args(shlex.split(cmd)[1:])  # SystemExit on unknown command/flag fails the test

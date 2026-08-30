"""Tests for docker-entrypoint.sh.

The entrypoint runs as root inside the container and drops to PUID:PGID. It is
the only thing standing between a correct deployment and either (a) a container
that cannot write its own database, or (b) a recursive chown over the whole
media library on every single restart.

The script is exercised against shims for the container-only commands (gosu,
chown, getent, useradd, groupadd, id), each of which logs its arguments, so the
assertions are about what the script actually invoked.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
ENTRYPOINT = os.path.join(ROOT, "docker-entrypoint.sh")

SHIMS = {
    # Pretend we are root, so the script does not take the "already non-root" exit.
    "id": '#!/bin/sh\n[ "$1" = "-u" ] && echo 0 || echo "uid=0(root)"\n',
    "chown": '#!/bin/sh\necho "chown $*" >> "$SHIM_LOG"\n',
    "gosu": '#!/bin/sh\necho "gosu $*" >> "$SHIM_LOG"\n',
    "getent": '#!/bin/sh\necho "getent $*" >> "$SHIM_LOG"\nexit 1\n',
    "useradd": '#!/bin/sh\necho "useradd $*" >> "$SHIM_LOG"\n',
    "groupadd": '#!/bin/sh\necho "groupadd $*" >> "$SHIM_LOG"\n',
    # Stands in for gunicorn: proves the entrypoint actually handed off.
    "the-real-command": '#!/bin/sh\necho "ran $*" >> "$SHIM_LOG"\n',
}


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in SHIMS.items():
        f = bin_dir / name
        f.write_text(body)
        f.chmod(0o755)
    data = tmp_path / "data"
    (data / "media").mkdir(parents=True)
    (data / "plex-media").mkdir(parents=True)
    (data / "requests.db").write_text("")
    log = tmp_path / "shim.log"
    log.write_text("")
    return {
        "tmp": tmp_path,
        "data": data,
        "log": log,
        "environ": {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SHIM_LOG": str(log),
            "DB_PATH": str(data / "requests.db"),
            "MEDIA_PATH": str(data / "media"),
            "SPORE_MEDIA_PATH": str(data / "plex-media"),
        },
    }


def _run(env, **overrides):
    e = dict(env["environ"])
    e.update(overrides)
    proc = subprocess.run(
        ["sh", ENTRYPOINT, "the-real-command", "--flag"],
        env=e, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return env["log"].read_text(), proc.stdout + proc.stderr


def test_default_runs_as_root_and_changes_nothing(env):
    """PUID unset must behave exactly as the image did before this existed."""
    log, _ = _run(env)
    assert "chown" not in log
    assert "gosu" not in log
    assert "ran --flag" in log, "the app must still start"


def test_puid_zero_explicitly_is_also_a_no_op(env):
    log, _ = _run(env, PUID="0", PGID="0")
    assert "chown" not in log


def test_first_run_chowns_recursively_and_drops_privileges(env):
    log, _ = _run(env, PUID="1000", PGID="1000")
    assert "chown -R 1000:1000" in log
    assert log.strip().endswith("gosu 1000:1000 the-real-command --flag")


def test_second_run_does_not_walk_the_library_again(env):
    """The expensive pass must happen once, not on every restart."""
    _run(env, PUID="1000", PGID="1000")
    env["log"].write_text("")
    log, _ = _run(env, PUID="1000", PGID="1000")

    assert "chown -R" not in log, "recursive chown repeated on restart"
    assert "chown 1000:1000" in log, "mount roots still need a cheap re-check"
    assert "gosu 1000:1000" in log


def test_changing_puid_triggers_a_fresh_recursive_chown(env):
    """Otherwise half the tree keeps the old owner, silently."""
    _run(env, PUID="1000", PGID="1000")
    env["log"].write_text("")
    log, _ = _run(env, PUID="1001", PGID="1001")

    assert "chown -R 1001:1001" in log


def test_force_chown_repeats_the_recursive_pass(env):
    _run(env, PUID="1000", PGID="1000")
    env["log"].write_text("")
    log, _ = _run(env, PUID="1000", PGID="1000", FORCE_CHOWN="1")

    assert "chown -R 1000:1000" in log


def test_all_three_data_directories_are_covered(env):
    log, _ = _run(env, PUID="1000", PGID="1000")
    for d in ("media", "plex-media"):
        assert str(env["data"] / d) in log
    assert str(env["data"]) in log


def test_a_failed_chown_is_not_recorded_as_done(env, tmp_path):
    """If ownership could not be fixed, the next start must try again rather
    than trust a marker and boot into a database it cannot write."""
    failing = tmp_path / "bin" / "chown"
    failing.write_text('#!/bin/sh\necho "chown $*" >> "$SHIM_LOG"\nexit 1\n')
    failing.chmod(0o755)

    log, out = _run(env, PUID="1000", PGID="1000")
    assert "WARNING" in out

    env["log"].write_text("")
    log2, _ = _run(env, PUID="1000", PGID="1000")
    assert "chown -R" in log2, "must retry after a failed ownership pass"

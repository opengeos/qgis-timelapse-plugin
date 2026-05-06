"""Tests for ``timelapse_core.initialize_ee`` error surfacing.

Issue #49: when initialization fails the plugin used to raise the
generic message "Please authenticate first" with no detail. These tests
pin the new contract: the failure cause is recorded into
``get_last_init_error()`` and ``ee.Authenticate()`` is *not* invoked
silently from inside ``initialize_ee``.
"""

import os
import types

import pytest

from timelapse.core import timelapse_core


@pytest.fixture(autouse=True)
def _reset_core_state(monkeypatch):
    """Wipe the module-level cache so tests do not leak into each other."""
    monkeypatch.setattr(timelapse_core, "_ee_initialized", False)
    monkeypatch.setattr(timelapse_core, "_last_init_error", None)
    # Clear EE_PROJECT_ID so tests don't pick up the dev environment value.
    monkeypatch.delenv("EE_PROJECT_ID", raising=False)


def _install_fake_ee(monkeypatch, *, initialize, authenticate=None):
    """Install a fake ``ee`` module on ``timelapse_core`` for the test.

    Args:
        monkeypatch: pytest's ``monkeypatch`` fixture.
        initialize: Callable substituted for ``ee.Initialize``.
        authenticate: Callable substituted for ``ee.Authenticate``. Defaults
            to one that fails the test if invoked, so we can assert it is
            never called from inside ``initialize_ee``.
    """
    if authenticate is None:

        def authenticate(*args, **kwargs):
            raise AssertionError(
                "initialize_ee must not call ee.Authenticate(); "
                "auth is the Settings dock's job"
            )

    fake_ee = types.SimpleNamespace(
        Initialize=initialize,
        Authenticate=authenticate,
    )
    monkeypatch.setattr(timelapse_core, "ee", fake_ee)


def test_missing_dep_sets_descriptive_error(monkeypatch):
    """When ``ee`` is None the error names earthengine-api, not auth."""
    monkeypatch.setattr(timelapse_core, "ee", None)

    assert timelapse_core.initialize_ee(project="proj") is False

    err = timelapse_core.get_last_init_error()
    assert err is not None
    assert "earthengine-api" in err
    assert "Settings" in err and "Dependencies" in err


def test_initialize_failure_captures_real_exception(monkeypatch, tmp_path):
    """The exception from ``ee.Initialize`` is preserved verbatim."""
    # Avoid hitting a real ~/.config/earthengine/credentials on the test box.
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda p: str(tmp_path / "no-such-credentials") if "earthengine" in p else p,
    )

    def boom(**kwargs):
        raise RuntimeError("project does not have Earth Engine API enabled")

    _install_fake_ee(monkeypatch, initialize=boom)

    assert timelapse_core.initialize_ee(project="my-proj") is False

    err = timelapse_core.get_last_init_error()
    assert err is not None
    # The real exception text must be in the surfaced message; the user
    # cannot diagnose without it.
    assert "project does not have Earth Engine API enabled" in err
    assert "my-proj" in err
    # It should also point them at the Settings dock.
    assert "Settings" in err and "Earth Engine" in err


def test_initialize_does_not_call_authenticate_on_failure(monkeypatch, tmp_path):
    """Regression: ``ee.Authenticate()`` must never run from a worker thread.

    The fake ``ee.Authenticate`` raises if called, and the fake ``ee.Initialize``
    raises so the old fallback path would have triggered.
    """
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda p: str(tmp_path / "no-such-credentials") if "earthengine" in p else p,
    )

    def init_boom(**kwargs):
        raise RuntimeError("init failed")

    # _install_fake_ee installs an Authenticate that fails the test if hit.
    _install_fake_ee(monkeypatch, initialize=init_boom)

    # Should return False without invoking ee.Authenticate()
    # (the AssertionError from authenticate would propagate out otherwise).
    assert timelapse_core.initialize_ee(project="my-proj") is False


def test_successful_init_clears_error(monkeypatch, tmp_path):
    """A successful init resets ``get_last_init_error`` to None."""
    # Pre-populate an error string to prove it gets cleared.
    monkeypatch.setattr(timelapse_core, "_last_init_error", "stale error")
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda p: str(tmp_path / "no-such-credentials") if "earthengine" in p else p,
    )

    def ok(**kwargs):
        return None

    _install_fake_ee(monkeypatch, initialize=ok)

    assert timelapse_core.initialize_ee(project="my-proj") is True
    assert timelapse_core.get_last_init_error() is None
    assert timelapse_core.is_ee_initialized() is True


def test_mark_ee_initialized_helper(monkeypatch):
    """The Settings dock helper toggles the flag and clears the error."""
    monkeypatch.setattr(timelapse_core, "_last_init_error", "stale error")
    monkeypatch.setattr(timelapse_core, "_ee_initialized", False)

    timelapse_core.mark_ee_initialized(True)

    assert timelapse_core.is_ee_initialized() is True
    assert timelapse_core.get_last_init_error() is None

    timelapse_core.mark_ee_initialized(False)

    assert timelapse_core.is_ee_initialized() is False

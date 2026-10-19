import base64
from unittest import mock

import pytest

from exorad.utils import version_control
from exorad.utils.version_control import VersionControl, VersionError

CHANGELOG = "\n".join(
    [
        "# Changelog",
        "",
        "## [Unreleased]",
        "- nothing yet",
        "",
        "## [9.9.9] - 2099-01-01",
        "### Added",
        "- a shiny new thing",
        "",
        "## [2.0.0] - 2020-01-01",
        "- old",
    ]
)


def _fake_response(status=200, body=CHANGELOG):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = {
        "content": base64.b64encode(body.encode("ascii")).decode("ascii")
    }
    return resp


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setattr(VersionControl, "_check_internet", lambda self: True)


class TestGetContent:
    def test_success_populates_lines(self, online, monkeypatch):
        monkeypatch.setattr(
            version_control.requests, "get", lambda url: _fake_response()
        )
        vc = VersionControl(current_version="2.0.0")
        content = vc.get_content("https://github.com/ExObsSim/ExoRad2.0")
        assert vc.status_code is True
        assert any("[9.9.9]" in line for line in content)

    def test_failure_returns_none(self, online, monkeypatch):
        monkeypatch.setattr(
            version_control.requests, "get", lambda url: _fake_response(status=404)
        )
        vc = VersionControl(current_version="2.0.0")
        assert vc.get_content("https://github.com/x/y") is None
        assert vc.status_code is False


class TestGetMessage:
    def test_reports_newer_version(self, online):
        vc = VersionControl.__new__(VersionControl)
        vc.set_log_name()
        vc.current_version = "2.0.0"
        vc.content = CHANGELOG.splitlines()
        message, new_ver = vc.get_message()
        assert new_ver == "9.9.9"
        assert "shiny new thing" in message

    def test_up_to_date_is_silent(self):
        vc = VersionControl.__new__(VersionControl)
        vc.set_log_name()
        vc.current_version = "9.9.9"
        vc.content = CHANGELOG.splitlines()
        message, _new_ver = vc.get_message()
        assert message == ""


class TestInit:
    def test_force_raises_when_outdated(self, online, monkeypatch):
        monkeypatch.setattr(
            version_control.requests, "get", lambda url: _fake_response()
        )
        with pytest.raises(VersionError):
            VersionControl(current_version="2.0.0", force=True)

    def test_no_error_when_current(self, online, monkeypatch):
        monkeypatch.setattr(
            version_control.requests, "get", lambda url: _fake_response()
        )
        VersionControl(current_version="9.9.9", force=True)

    def test_offline_is_a_noop(self, monkeypatch):
        monkeypatch.setattr(VersionControl, "_check_internet", lambda self: False)
        VersionControl(current_version="0.0.1", force=True)


class TestCheckInternet:
    def test_returns_false_on_socket_error(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("unreachable")

        monkeypatch.setattr(version_control.socket, "socket", boom)
        vc = VersionControl.__new__(VersionControl)
        vc.set_log_name()
        assert vc._check_internet() is False

"""
Tests for the broader file-search MCP server. Uses pytest's real
`tmp_path` (an actual temp directory, real filesystem operations — no
point mocking pathlib for this) with AUTHORIZED_PATHS monkeypatched to
point at it, so tests never depend on the real user's actual Desktop/
Documents contents and can't accidentally touch anything outside the
sandboxed temp dir.
"""

from unittest.mock import MagicMock

import pytest

from conftest import load_server_module

files_server = load_server_module("files_server_module", "mcp_servers/files/server.py")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    (tmp_path / "resume.pdf").write_text("fake pdf content")
    (tmp_path / "notes.txt").write_text("fake notes")
    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "resume.pdf").write_text("a second resume, nested")
    (sub / "photo.png").write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(files_server, "AUTHORIZED_PATHS", [tmp_path.resolve()])
    return tmp_path


class TestListDirectory:
    def test_lists_top_level_entries_not_recursive(self, sandbox):
        result = files_server.list_directory(str(sandbox))
        names = {e["name"] for e in result}
        assert names == {"resume.pdf", "notes.txt", "subfolder"}

    def test_defaults_to_the_first_authorized_path(self, sandbox):
        result = files_server.list_directory()
        assert any(e["name"] == "resume.pdf" for e in result)

    def test_rejects_a_path_outside_authorized_locations(self, sandbox, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside")
        with pytest.raises(ValueError, match="outside ORION's authorized locations"):
            files_server.list_directory(str(outside))

    def test_marks_directories_correctly_and_omits_their_size(self, sandbox):
        result = files_server.list_directory(str(sandbox))
        subfolder = next(e for e in result if e["name"] == "subfolder")
        assert subfolder["is_dir"] is True
        assert subfolder["size_bytes"] is None


class TestSearchFiles:
    def test_finds_matches_recursively_by_default(self, sandbox):
        result = files_server.search_files("resume")
        names = [e["path"] for e in result]
        assert len(names) == 2  # top-level and nested resume.pdf

    def test_case_insensitive_substring_match(self, sandbox):
        result = files_server.search_files("RESUME")
        assert len(result) == 2

    def test_can_be_scoped_to_a_specific_directory(self, sandbox):
        result = files_server.search_files("resume", directory=str(sandbox / "subfolder"))
        assert len(result) == 1
        assert "subfolder" in result[0]["path"]

    def test_no_matches_returns_empty_list(self, sandbox):
        assert files_server.search_files("nonexistent-xyz") == []


class TestFindFile:
    def test_exact_name_match_across_all_authorized_locations(self, sandbox):
        result = files_server.find_file("photo.png")
        assert len(result) == 1
        assert result[0]["name"] == "photo.png"

    def test_does_not_match_partial_names(self, sandbox):
        assert files_server.find_file("resume") == []  # "resume" != "resume.pdf" exactly


class TestGetFileMetadata:
    def test_returns_real_size_and_modified_time(self, sandbox):
        result = files_server.get_file_metadata(str(sandbox / "notes.txt"))
        assert result["is_dir"] is False
        assert result["size_bytes"] == len("fake notes")
        assert "modified" in result

    def test_missing_file_raises_a_clear_error(self, sandbox):
        with pytest.raises(ValueError, match="does not exist"):
            files_server.get_file_metadata(str(sandbox / "nope.txt"))


class TestOpenFile:
    def test_calls_os_startfile_on_windows(self, sandbox, monkeypatch):
        monkeypatch.setattr(files_server.sys, "platform", "win32")
        called = {}
        monkeypatch.setattr(files_server.os, "startfile", lambda p: called.setdefault("path", p), raising=False)

        result = files_server.open_file(str(sandbox / "notes.txt"))

        assert "notes.txt" in called["path"]
        assert "Opened" in result

    def test_rejects_a_path_outside_authorized_locations(self, sandbox, tmp_path_factory):
        outside_file = tmp_path_factory.mktemp("outside") / "secret.txt"
        outside_file.write_text("x")
        with pytest.raises(ValueError, match="outside ORION's authorized locations"):
            files_server.open_file(str(outside_file))

    def test_missing_file_raises_before_attempting_to_open(self, sandbox, monkeypatch):
        fake_startfile = MagicMock()
        monkeypatch.setattr(files_server.os, "startfile", fake_startfile, raising=False)
        with pytest.raises(ValueError, match="does not exist"):
            files_server.open_file(str(sandbox / "ghost.txt"))
        fake_startfile.assert_not_called()

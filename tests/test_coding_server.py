"""
Tests for the coding-tools MCP server. No external API — the sandbox
itself is under test, pointed at a temp directory instead of the real
./workspace so these tests don't touch (or depend on) actual project
files.
"""

import pytest

from conftest import load_server_module

coding_server = load_server_module("coding_server_module", "mcp_servers/coding/server.py")


@pytest.fixture(autouse=True)
def temp_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(coding_server, "WORKSPACE_ROOT", tmp_path)
    return tmp_path


class TestSandboxing:
    def test_resolve_allows_paths_inside_workspace(self, temp_workspace):
        target = coding_server._resolve("subdir/file.txt")
        assert temp_workspace in target.parents

    def test_resolve_rejects_path_traversal(self, temp_workspace):
        with pytest.raises(ValueError, match="outside"):
            coding_server._resolve("../../etc/passwd")

    def test_resolve_rejects_absolute_escape(self, temp_workspace):
        with pytest.raises(ValueError, match="outside"):
            coding_server._resolve("../sibling_dir/file.txt")


class TestFileOperations:
    def test_write_then_read_roundtrip(self):
        coding_server.write_file("hello.txt", "hello world")
        assert coding_server.code_read_file("hello.txt") == "hello world"

    def test_write_creates_parent_dirs(self, temp_workspace):
        coding_server.write_file("nested/dir/file.txt", "content")
        assert (temp_workspace / "nested" / "dir" / "file.txt").exists()

    def test_read_nonexistent_file_raises(self):
        with pytest.raises(ValueError, match="not a file"):
            coding_server.code_read_file("does_not_exist.txt")

    def test_list_files_excludes_git(self, temp_workspace):
        (temp_workspace / "visible.txt").write_text("x")
        (temp_workspace / ".git").mkdir()
        listing = coding_server.code_list_files()
        assert "visible.txt" in listing
        assert ".git" not in listing


class TestEditFile:
    def test_replaces_unique_match(self):
        coding_server.write_file("code.py", "def add(a, b):\n    return a - b\n")
        coding_server.edit_file("code.py", "return a - b", "return a + b")
        assert "return a + b" in coding_server.code_read_file("code.py")

    def test_no_match_raises(self):
        coding_server.write_file("code.py", "def add(a, b):\n    return a + b\n")
        with pytest.raises(ValueError, match="not found"):
            coding_server.edit_file("code.py", "nonexistent string", "replacement")

    def test_ambiguous_match_raises(self):
        coding_server.write_file("code.py", "x = 1\nx = 1\n")
        with pytest.raises(ValueError, match="not unique"):
            coding_server.edit_file("code.py", "x = 1", "x = 2")


class TestSearchCode:
    def test_finds_matches_across_files(self):
        coding_server.write_file("a.py", "def foo():\n    pass\n")
        coding_server.write_file("b.py", "def bar():\n    foo()\n")
        matches = coding_server.search_code("foo")
        files_matched = {m["file"] for m in matches}
        assert "a.py" in files_matched
        assert "b.py" in files_matched


class TestRunCommand:
    def test_runs_and_captures_output(self):
        result = coding_server.run_command("python -c \"print('hello from test')\"")
        assert result["returncode"] == 0
        assert "hello from test" in result["stdout"]

    def test_nonexistent_command_reports_error_not_crash(self):
        result = coding_server._run(["definitely_not_a_real_command_xyz"])
        assert result["returncode"] != 0
        assert result["stderr"]

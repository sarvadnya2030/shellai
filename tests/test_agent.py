"""Tests for the tool-use agent."""

import pytest
from shellai.agent import detect_agentic
from shellai.tools import execute_tool, TOOL_SCHEMAS


class TestDetectAgentic:
    def test_write_and_compile(self):
        assert detect_agentic("write me a C program and compile it") is True

    def test_create_and_run(self):
        assert detect_agentic("create a python script and run it") is True

    def test_build_and_deploy(self):
        assert detect_agentic("build the docker image and deploy it") is True

    def test_chain_phrase(self):
        assert detect_agentic("install nginx and then start it") is True

    def test_simple_not_detected(self):
        assert detect_agentic("show disk usage") is False

    def test_single_verb_not_detected(self):
        assert detect_agentic("list all open ports") is False


class TestToolSchemas:
    def test_all_tools_have_required_fields(self):
        for tool in TOOL_SCHEMAS:
            assert tool["type"] == "function"
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_tool_names(self):
        names = {t["function"]["name"] for t in TOOL_SCHEMAS}
        assert names == {"run_command", "write_file", "read_file",
                         "list_directory", "search_files"}


class TestExecuteTool:
    def test_run_command_success(self):
        result = execute_tool("run_command", {"command": "echo hello"})
        assert result["exit_code"] == 0
        assert result["stdout"] == "hello"

    def test_run_command_failure(self):
        result = execute_tool("run_command", {"command": "ls /nonexistent_path_xyz"})
        assert result["exit_code"] != 0
        assert result["stderr"]

    def test_write_and_read_file(self, tmp_path):
        import os; os.chdir(tmp_path)
        path = str(tmp_path / "test.txt")
        write_result = execute_tool("write_file", {"path": path, "content": "hello\nworld\n"})
        assert write_result["ok"] is True
        assert write_result["bytes"] == 12

        read_result = execute_tool("read_file", {"path": path})
        assert read_result["content"] == "hello\nworld\n"
        assert read_result["lines"] == 3

    def test_read_nonexistent_file(self):
        result = execute_tool("read_file", {"path": "/nonexistent/file.txt"})
        assert "error" in result

    def test_list_directory(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = execute_tool("list_directory", {"path": str(tmp_path)})
        assert result["count"] == 2
        names = [e["name"] for e in result["entries"]]
        assert "a.txt" in names

    def test_search_files(self, tmp_path):
        (tmp_path / "foo.py").write_text("")
        (tmp_path / "bar.py").write_text("")
        (tmp_path / "baz.txt").write_text("")
        result = execute_tool("search_files", {"pattern": "*.py", "path": str(tmp_path)})
        assert result["count"] == 2

    def test_unknown_tool_returns_error(self):
        result = execute_tool("nonexistent_tool", {})
        assert "error" in result

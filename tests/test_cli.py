"""Tests for LLM output parsing."""

import pytest
from shellai.utils import clean_llm_command as _clean_llm_command, looks_like_command as _looks_like_command


class TestCleanLLMCommand:
    def test_plain_command(self):
        assert _clean_llm_command("ls -lah") == "ls -lah"

    def test_strips_backticks(self):
        assert _clean_llm_command("`ls -lah`") == "ls -lah"

    def test_strips_markdown_fence(self):
        assert _clean_llm_command("```bash\nls -lah\n```") == "ls -lah"

    def test_strips_dollar_sign(self):
        assert _clean_llm_command("$ ls -lah") == "ls -lah"

    def test_takes_first_line(self):
        assert _clean_llm_command("ls -lah\n# lists files") == "ls -lah"

    def test_empty_input(self):
        assert _clean_llm_command("") == ""

    def test_strips_whitespace(self):
        assert _clean_llm_command("  find . -name '*.py'  ") == "find . -name '*.py'"


class TestLooksLikeCommand:
    def test_ls(self):
        assert _looks_like_command("ls -lah") is True

    def test_find(self):
        assert _looks_like_command("find . -type f -size +1G") is True

    def test_empty(self):
        assert _looks_like_command("") is False

    def test_sentence(self):
        # A plain sentence should not look like a command
        assert _looks_like_command("Here is the command you requested:") is False

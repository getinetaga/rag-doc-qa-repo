"""Unit tests for configuration loading behavior."""

import importlib

from app import config


def test_load_dotenv_reads_values_from_current_working_directory(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=test-key\nLLM_PROVIDER=huggingface\nPGVECTOR_TABLE_NAME=custom_table\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PGVECTOR_TABLE_NAME", raising=False)

    importlib.reload(config)

    assert config.OPENAI_API_KEY == "test-key"
    assert config.LLM_PROVIDER == "huggingface"
    assert config.PGVECTOR_TABLE_NAME == "custom_table"


def test_load_dotenv_does_not_override_existing_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "existing-key")

    importlib.reload(config)

    assert config.OPENAI_API_KEY == "existing-key"
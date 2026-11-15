"""Verify explicit Part 5 settings with disposable configuration only."""

import pytest

from api import academic_config
from api.academic_config import AcademicConfigError, load_academic_settings


def test_explicit_file_and_process_precedence(tmp_path):
    pytest.importorskip("dotenv", reason="explicit .env loading uses the optional rag extra")
    env_file = tmp_path / ".env"
    env_file.write_text(
        'OPENAI_API_KEY="file-dummy-key"\n'
        "OPENAI_MODEL=file-model\n"
        "P5_ENGINE_BASE_URL=http://localhost:8010/parte5/\n",
        encoding="utf-8-sig",
    )
    from_file = load_academic_settings(env_file=env_file, environ={}, port=8010)
    assert from_file.api_key == "file-dummy-key"
    assert from_file.model == "file-model"
    assert from_file.engine_base_url == "http://localhost:8010/parte5"

    from_process = load_academic_settings(
        env_file=env_file,
        environ={"OPENAI_API_KEY": "process-dummy-key", "OPENAI_MODEL": "process-model"},
        port=8010,
    )
    assert from_process.api_key == "process-dummy-key"
    assert from_process.model == "process-model"
    assert "process-dummy-key" not in repr(from_process)

    cleared = load_academic_settings(
        env_file=env_file, environ={"OPENAI_API_KEY": " "}, port=8010,
    )
    assert cleared.api_key is None


def test_absent_file_and_key_use_listener_defaults(tmp_path):
    settings = load_academic_settings(env_file=tmp_path / ".env", environ={}, port=8010)
    assert settings.api_key is None
    assert settings.model == "gpt-6-luna"
    assert settings.engine_base_url == "http://127.0.0.1:8010/parte5"


@pytest.mark.parametrize("base_url", [
    "http://example.test:8000/parte5",
    "http://127.0.0.1:8001/parte5",
    "http://127.0.0.1:8000/parte3",
    "http://dummy-secret@127.0.0.1:8000/parte5",
    "http://127.0.0.1:8000/parte5?token=dummy-secret",
    "http://127.0.0.1:8000/parte5#dummy-secret",
    "http://127.0.0.1:invalid/parte5",
])
def test_engine_base_stays_on_the_academic_listener(tmp_path, base_url):
    with pytest.raises(AcademicConfigError, match="local unified listener") as failure:
        load_academic_settings(
            env_file=tmp_path / ".env", environ={"P5_ENGINE_BASE_URL": base_url},
        )
    assert "dummy-secret" not in str(failure.value)


@pytest.mark.parametrize(("key", "status"), [(None, "MISSING"), ("dummy-key", "CONFIGURED")])
def test_presence_check_reports_only_status(tmp_path, monkeypatch, capsys, key, status):
    settings = load_academic_settings(
        env_file=tmp_path / ".env", environ={} if key is None else {"OPENAI_API_KEY": key},
    )
    monkeypatch.setattr(academic_config, "load_academic_settings", lambda: settings)
    assert academic_config.main() == 0
    assert capsys.readouterr() == (f"{status}\n", "")

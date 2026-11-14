"""Load Part 5 backend settings explicitly from the project env file."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_MODEL = "gpt-6-luna"


class AcademicConfigError(ValueError):
    """An invalid setting or a missing optional configuration dependency."""


@dataclass(frozen=True, slots=True)
class AcademicSettings:
    api_key: str | None = field(repr=False)
    model: str
    engine_base_url: str


def load_academic_settings(
    *, env_file: Path = DEFAULT_ENV_FILE, environ: Mapping[str, str] | None = None,
    port: int = 8000,
) -> AcademicSettings:
    """Read a known file and honor process values without changing the environment."""
    environment = os.environ if environ is None else environ
    file_values: Mapping[str, str | None] = {}
    if env_file.exists():
        try:
            from dotenv import dotenv_values
        except ImportError:
            raise AcademicConfigError('Install the optional "rag" dependencies to read .env.') from None
        try:
            file_values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
        except (OSError, UnicodeError):
            raise AcademicConfigError("Could not read the academic backend configuration file.") from None

    def setting(name: str, default: str = "") -> str:
        return environment.get(name, file_values.get(name) or default).strip()

    model = setting("OPENAI_MODEL", DEFAULT_MODEL)
    if not model:
        raise AcademicConfigError("OPENAI_MODEL must name the configured answer model.")

    engine_base_url = setting("P5_ENGINE_BASE_URL", f"http://127.0.0.1:{port}/parte5")
    try:
        base = urlsplit(engine_base_url)
        valid = (
            base.scheme == "http"
            and base.hostname in {"127.0.0.1", "localhost", "::1"}
            and base.port == port
            and base.path in {"/parte5", "/parte5/"}
            and base.username is None
            and base.password is None
            and "?" not in engine_base_url
            and "#" not in engine_base_url
            and not any(character.isspace() for character in engine_base_url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise AcademicConfigError("P5_ENGINE_BASE_URL must point to the local unified listener at /parte5.")

    return AcademicSettings(setting("OPENAI_API_KEY") or None, model, engine_base_url.rstrip("/"))


def main() -> int:
    """Report configuration presence without displaying a credential."""
    try:
        settings = load_academic_settings()
    except AcademicConfigError as error:
        print(error, file=sys.stderr)
        return 2
    print("CONFIGURED" if settings.api_key else "MISSING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

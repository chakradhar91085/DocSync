"""Runtime settings, loaded from environment variables (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".java", ".kt", ".rb",
    ".rs", ".php", ".cs", ".swift", ".scala", ".vue", ".svelte",
}

# Files that change the project's shape: touching them makes a change "structural".
MANIFEST_FILES = {
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Gemfile", "docker-compose.yml", "Dockerfile",
}

IGNORED_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", "out", "coverage", "vendor",
    "__pycache__", ".venv", "venv", "env", ".mypy_cache", ".pytest_cache",
    "migrations", ".github", ".docsync", "docs_out",
}

IGNORED_SUFFIXES = (".min.js", ".d.ts", ".lock", ".map")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass
class Settings:
    # LLM
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    fallback_model: str = "openrouter/free"
    temperature: float = 0.1
    requests_per_second: float = 0.5
    max_concurrency: int = 3

    # GitHub
    github_token: str = ""
    repo: str = ""
    ref: str = "main"
    github_mcp_url: str = "https://api.githubcopilot.com/mcp/"

    # Notion
    notion_token: str = ""
    notion_root_page_id: str = ""

    # Slack (optional): post a summary after each run
    slack_bot_token: str = ""
    slack_channel_id: str = ""

    # Pipeline
    max_files: int = 150
    max_file_chars: int = 12_000
    state_path: str = ".docsync/state.json"
    extensions: set[str] = field(default_factory=lambda: set(SOURCE_EXTENSIONS))

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_bot_token and self.slack_channel_id)

    @property
    def owner_and_name(self) -> tuple[str, str]:
        if "/" not in self.repo:
            raise ValueError("DOCSYNC_REPO must look like 'owner/name'")
        owner, name = self.repo.split("/", 1)
        return owner, name

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            llm_base_url=os.getenv("LLM_BASE_URL", cls.llm_base_url),
            llm_api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY", ""),
            model=os.getenv("DOCSYNC_MODEL", cls.model),
            fallback_model=os.getenv("DOCSYNC_FALLBACK_MODEL", cls.fallback_model),
            temperature=_float("DOCSYNC_TEMPERATURE", cls.temperature),
            requests_per_second=_float("DOCSYNC_REQUESTS_PER_SECOND", cls.requests_per_second),
            max_concurrency=_int("DOCSYNC_MAX_CONCURRENCY", cls.max_concurrency),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            repo=os.getenv("DOCSYNC_REPO", ""),
            ref=os.getenv("DOCSYNC_REF", cls.ref),
            github_mcp_url=os.getenv("GITHUB_MCP_URL", cls.github_mcp_url),
            notion_token=os.getenv("NOTION_TOKEN", ""),
            notion_root_page_id=os.getenv("NOTION_ROOT_PAGE_ID", ""),
            slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_channel_id=os.getenv("SLACK_CHANNEL_ID", ""),
            max_files=_int("DOCSYNC_MAX_FILES", cls.max_files),
            max_file_chars=_int("DOCSYNC_MAX_FILE_CHARS", cls.max_file_chars),
            state_path=os.getenv("DOCSYNC_STATE_PATH", cls.state_path),
        )


def is_source_file(path: str, extensions: set[str]) -> bool:
    parts = path.split("/")
    if any(p in IGNORED_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    if name.endswith(IGNORED_SUFFIXES):
        return False
    return any(name.endswith(ext) for ext in extensions)


def is_manifest_file(path: str) -> bool:
    return path.split("/")[-1] in MANIFEST_FILES

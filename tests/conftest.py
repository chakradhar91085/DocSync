import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


class FakeLLM:
    """Answers each chain's prompt with plausible JSON, based on the [task:...] marker."""

    def __init__(self):
        self.calls = Counter()
        self.runnable = RunnableLambda(self._respond)

    def _respond(self, messages):
        text = messages[-1].content
        task = re.search(r"\[task:(\w+)\]", text).group(1)
        self.calls[task] += 1
        path = (re.search(r"File: (\S+)", text) or [None, ""])[1]
        if task == "file_summary":
            names = re.findall(r"^(?:def|class|async def) (\w+)", text, re.M)
            data = {
                "path": path, "purpose": f"Handles {path}.",
                "key_symbols": [{"name": n, "kind": "function", "description": f"Does {n}."} for n in names]
                + [{"name": "imaginary_helper", "kind": "function", "description": "Not real."}],
                "internal_dependencies": ["core"] if "from core" in text else [], "external_libraries": [],
            }
        elif task == "module_doc":
            module = re.search(r"module `([^`]+)`", text).group(1)
            data = {"name": module, "overview": f"The {module} module.", "responsibilities": ["stuff"],
                    "key_files": [], "how_it_fits": "It fits."}
        elif task == "api_extract":
            routes = re.findall(r'@app\.(get|post)\("([^"]+)"\)', text)
            data = {"endpoints": [{"method": m, "path": p, "summary": f"{m} {p}"} for m, p in routes]
                    + [{"method": "GET", "path": "/ghost", "summary": "hallucinated"}]}
        elif task == "change_classify":
            data = {"kind": "minor", "reason": "small change"}
        elif task == "architecture":
            data = {"summary": "A small app.", "components": [{"name": "api", "responsibility": "HTTP"}],
                    "data_flow": ["request", "response"], "tech_stack": ["Python"], "mermaid": "not a diagram"}
        elif task == "changelog":
            data = {"title": "Added health check", "summary": "A new endpoint.", "changes": ["health"], "impact": "ops"}
        return AIMessage(content=f"<think>reasoning...</think>\n```json\n{json.dumps(data)}\n```")


@pytest.fixture
def fake_llm():
    return FakeLLM()


def git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def sample_repo(tmp_path):
    repo = tmp_path / "shop"
    (repo / "api").mkdir(parents=True)
    (repo / "core").mkdir()
    (repo / "api" / "routes.py").write_text(
        'from core.db import get_user\n\n@app.get("/users/{user_id}")\ndef read_user(user_id):\n    return get_user(user_id)\n'
    )
    (repo / "core" / "db.py").write_text("def get_user(user_id):\n    return {'id': user_id}\n")
    (repo / "README.md").write_text("# shop\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return repo

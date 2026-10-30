"""Prompt templates for the six chains."""

from langchain_core.prompts import ChatPromptTemplate

SYSTEM = (
    "You are DocSync, a senior engineer writing internal documentation. "
    "Be accurate and concise. Only describe what is actually in the provided code; "
    "never invent functions, endpoints or files. "
    "Always answer with a single JSON object and nothing else."
)

FILE_SUMMARY = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "[task:file_summary]\nSummarise this source file.\n\n"
     "Return JSON with keys: path (string), purpose (string, 2-3 sentences), "
     "key_symbols (list of {{name, kind, description}}; kind is one of function, class, method, "
     "constant, component, type, other; use exact identifiers from the code, max 12), "
     "internal_dependencies (list of repo-internal imports), external_libraries (list of strings).\n"
     "{feedback}\n"
     "File: {path}\n```\n{content}\n```"),
])

MODULE_DOC = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "[task:module_doc]\nWrite the documentation page for the module `{module}` "
     "using these per-file summaries.\n\n"
     "Return JSON with keys: name (string), overview (string, one paragraph), "
     "responsibilities (list of strings), key_files (list of {{path, role}}), "
     "how_it_fits (string: how it interacts with other modules).\n\n"
     "File summaries:\n{summaries}"),
])

API_EXTRACT = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "[task:api_extract]\nList every HTTP endpoint declared in this file. "
     "If the framework derives the route from the file path (e.g. Next.js app/api/**/route.ts), "
     "the route is: {route_hint}\n\n"
     "Return JSON: {{\"endpoints\": [{{method, path, summary, params: [{{name, location, type, required, "
     "description}}], response}}]}}. location is one of path, query, body, header, form. "
     "Return {{\"endpoints\": []}} if there are none.\n\n"
     "File: {path}\n```\n{content}\n```"),
])

CHANGE_CLASSIFY = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "[task:change_classify]\nDecide whether this merge changes the system ARCHITECTURE.\n"
     "structural = new/removed module or service, new external dependency, changed data flow "
     "between modules, new storage or integration.\n"
     "minor = bug fixes, refactors inside a module, docs, tests, small features.\n\n"
     "Return JSON: {{\"kind\": \"minor\" | \"structural\", \"reason\": string}}.\n\n"
     "Commit messages:\n{messages}\n\nChanged files:\n{files}\n\nDiff excerpt:\n{diff}"),
])

ARCHITECTURE = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "[task:architecture]\nWrite the architecture overview of the repository `{repo}` "
     "from these module docs.\n\n"
     "Return JSON with keys: summary (string, 1-2 paragraphs), components (list of "
     "{{name, responsibility}}), data_flow (ordered list of steps for a typical request or job), "
     "tech_stack (list of strings), mermaid (string: a Mermaid 'flowchart TD' diagram whose nodes "
     "are the components; no markdown fences).\n\n"
     "Modules:\n{modules}\n\nManifest files:\n{manifests}"),
])

CHANGELOG = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human",
     "[task:changelog]\nWrite a plain-English changelog entry for this merge, readable by "
     "non-engineers.\n\n"
     "Return JSON with keys: title (string, max 10 words), summary (string, 1-2 sentences), "
     "changes (list of strings), impact (string: who/what is affected).\n\n"
     "Commit messages:\n{messages}\n\nChanged files:\n{files}\n\nDiff excerpt:\n{diff}"),
])

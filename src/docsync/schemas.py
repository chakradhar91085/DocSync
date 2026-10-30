"""Structured outputs of each chain. The LLM fills these; code renders them to Markdown."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Symbol(BaseModel):
    name: str = Field(description="Exact identifier as written in the code")
    kind: Literal["function", "class", "method", "constant", "component", "type", "other"] = "function"
    description: str = Field(description="One sentence on what it does")


class FileSummary(BaseModel):
    """Chain 1 output: one source file."""

    path: str
    purpose: str = Field(description="2-3 sentences: why this file exists")
    key_symbols: list[Symbol] = Field(default_factory=list)
    internal_dependencies: list[str] = Field(
        default_factory=list, description="Other files/modules in this repo it imports"
    )
    external_libraries: list[str] = Field(default_factory=list)


class KeyFile(BaseModel):
    path: str
    role: str


class ModuleDoc(BaseModel):
    """Chain 2 output: one folder/module."""

    name: str
    overview: str
    responsibilities: list[str] = Field(default_factory=list)
    key_files: list[KeyFile] = Field(default_factory=list)
    how_it_fits: str = Field(description="How this module interacts with the rest of the system")


class Param(BaseModel):
    name: str
    location: Literal["path", "query", "body", "header", "form"] = "query"
    type: str = "string"
    required: bool = False
    description: str = ""


class Endpoint(BaseModel):
    method: str = Field(description="HTTP method in upper case")
    path: str = Field(description="Route path exactly as declared in code")
    summary: str
    params: list[Param] = Field(default_factory=list)
    response: str = Field(default="", description="What a successful response contains")
    source_file: str = ""


class EndpointList(BaseModel):
    """Chain 3 output: endpoints declared in one route file."""

    endpoints: list[Endpoint] = Field(default_factory=list)


class ChangeClass(BaseModel):
    """Chain 4 output: does this merge change the architecture?"""

    kind: Literal["minor", "structural"]
    reason: str


class Component(BaseModel):
    name: str
    responsibility: str


class ArchitectureDoc(BaseModel):
    """Chain 5 output."""

    summary: str
    components: list[Component] = Field(default_factory=list)
    data_flow: list[str] = Field(default_factory=list, description="Ordered steps of a typical request")
    tech_stack: list[str] = Field(default_factory=list)
    mermaid: str = Field(default="", description="Mermaid 'flowchart TD' diagram of components")


class ChangelogEntry(BaseModel):
    """Chain 6 output."""

    title: str
    summary: str
    changes: list[str] = Field(default_factory=list)
    impact: str = ""

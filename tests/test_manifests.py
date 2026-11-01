#!/usr/bin/env python3
"""Контракт манифестов плагина rosstat-mcp.

Запуск из корня репозитория::

    python3 -m unittest discover -s tests -v

Только стандартная библиотека; сеть не нужна.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NAME = "rosstat-mcp"
VERSION = "0.4.0"
LONG = (
    "Read-only MCP connection to Rosstat/CBR data marts (v_* views, point-in-time layer) "
    "on the clickhouse-import-rosstat staging server, plus the rosstat-sql skill for writing "
    "efficient ClickHouse queries against them."
)
SHORT = "Read-only MCP to Rosstat/CBR data marts + SQL skill"

MCP_NAME = "rosstat-staging"
MCP_URL = "https://mcp.selfinvesting.ru:8443/mcp"
TOKEN_ENV = "ROSSTAT_MCP_TOKEN"
BEARER = "Bearer ${" + TOKEN_ENV + "}"
REPO_GIT = "https://github.com/kmlebedev/rosstat-mcp.git"

PLUGIN_MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".cursor-plugin/plugin.json",
    "kimi.plugin.json",
    "qwen-extension.json",
)
MARKETPLACES = (
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
    ".cursor-plugin/marketplace.json",
)
MCP_CONFIGS = (".codex-plugin/mcp.json", ".cursor-plugin/mcp.json")
TRACKED_FILES = {
    *PLUGIN_MANIFESTS,
    *MARKETPLACES,
    *MCP_CONFIGS,
    "README.md",
    "LICENSE",
    ".gitignore",
    "tests/test_manifests.py",
    ".github/workflows/check.yml",
    "skills/rosstat-sql/SKILL.md",
}
MAX_BYTES = 65536

SKILL_REL = "skills/rosstat-sql/SKILL.md"
SKILL_MAX_BYTES = 6144
SKILL_DESCRIPTION_MAX = 300
SQL_BLOCK = re.compile(r"```sql\n(.*?)```", re.S)
SQL_SOURCE = re.compile(r"(?i)\b(?:from|join)\s+([A-Za-z_][\w.]*)")
LITERAL_SECRET = re.compile(r"(?i)(bearer\s+(?!\$\{)\S+|password\s*=)")

COMPONENT_KEYS = ("agents", "commands", "hooks")
# Claude Code, Cursor и Qwen подхватывают skills/ сами; явное поле — только где без него не найдут.
SKILLS_DECLARED = {".codex-plugin/plugin.json", "kimi.plugin.json"}
SKILLS_PATH = "./skills/"
FORBIDDEN_KEY = re.compile(r"(?i)(api[_-]?key|token|password|secret|bearer|cookie|credential)")
TOKEN_REF_KEYS = {"bearerTokenEnvVar", "bearer_token_env_var"}
# Описание плагинной переменной Cursor: только метаданные, без значения.
TOKEN_VARIABLE_KEYS = {"type", "title", "description"}


def secret_problems(rel: str, value: object, path: str = "") -> list[str]:
    """Нарушения правила «токен только ссылкой на ROSSTAT_MCP_TOKEN»."""
    problems: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}" if path else key
            if key in TOKEN_REF_KEYS:
                if child != TOKEN_ENV:
                    problems.append(f"{rel}: {here} must name {TOKEN_ENV}")
            elif key == "headers":
                if child != {"Authorization": BEARER}:
                    problems.append(f"{rel}: {here} must be exactly Authorization: {BEARER}")
            elif key == TOKEN_ENV:
                allowed = rel == ".cursor-plugin/plugin.json" and here == f"variables.properties.{TOKEN_ENV}"
                if not allowed or not isinstance(child, dict) or not set(child) <= TOKEN_VARIABLE_KEYS:
                    problems.append(f"{rel}: {here} may only describe the Cursor variable")
            elif FORBIDDEN_KEY.search(key):
                problems.append(f"{rel}: forbidden key {here!r}")
            else:
                problems.extend(secret_problems(rel, child, here))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            problems.extend(secret_problems(rel, child, f"{path}.{i}"))
    elif isinstance(value, str):
        if re.match(r"(?i)(bearer|token|basic)\s", value):
            problems.append(f"{rel}: {path} holds a literal credential")
        if value.startswith(("http://", "https://")) and "?" in value:
            problems.append(f"{rel}: {path} URL must not carry a query string")
    return problems


def skill_tables(sql: str) -> set[str]:
    """Имена таблиц после FROM/JOIN; табличная функция даёт своё имя без аргументов."""
    return set(SQL_SOURCE.findall(sql))


def frontmatter(text: str) -> dict[str, str]:
    parts = text.split("---\n", 2)
    if len(parts) < 3 or parts[0]:
        raise AssertionError("SKILL.md must start with a --- frontmatter block")
    fields = {}
    for line in parts[1].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def load(rel: str) -> dict:
    data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError(f"{rel}: top-level JSON must be an object")
    return data


def get(data: object, path: str) -> object:
    for part in path.split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]  # type: ignore[index]
    return data


class ManifestTest(unittest.TestCase):
    def test_names_versions_descriptions(self) -> None:
        expected = {
            ".claude-plugin/plugin.json": {"name": NAME, "version": VERSION, "description": LONG},
            ".codex-plugin/plugin.json": {
                "name": NAME,
                "version": VERSION,
                "description": LONG,
                "interface.longDescription": LONG,
                "interface.shortDescription": SHORT,
            },
            ".cursor-plugin/plugin.json": {"name": NAME, "version": VERSION, "description": LONG},
            "kimi.plugin.json": {
                "name": NAME,
                "version": VERSION,
                "description": LONG,
                "interface.longDescription": LONG,
                "interface.shortDescription": SHORT,
            },
            "qwen-extension.json": {"name": NAME, "version": VERSION, "description": LONG},
            ".claude-plugin/marketplace.json": {
                "name": NAME,
                "version": VERSION,
                "description": SHORT,
                "plugins.0.name": NAME,
                "plugins.0.description": LONG,
            },
            ".cursor-plugin/marketplace.json": {
                "name": NAME,
                "metadata.version": VERSION,
                "metadata.description": SHORT,
                "plugins.0.name": NAME,
                "plugins.0.description": LONG,
            },
            ".agents/plugins/marketplace.json": {"name": NAME, "plugins.0.name": NAME},
        }
        for rel, fields in expected.items():
            data = load(rel)
            for path, want in fields.items():
                with self.subTest(file=rel, field=path):
                    self.assertEqual(get(data, path), want)
        for rel in MARKETPLACES:
            with self.subTest(file=rel):
                self.assertEqual(len(load(rel)["plugins"]), 1)

    def test_components(self) -> None:
        for rel in PLUGIN_MANIFESTS:
            data = load(rel)
            for key in COMPONENT_KEYS:
                with self.subTest(file=rel, key=key):
                    self.assertNotIn(key, data)
            with self.subTest(file=rel, key="skills"):
                if rel in SKILLS_DECLARED:
                    self.assertEqual(data.get("skills"), SKILLS_PATH)
                else:
                    self.assertNotIn("skills", data)

    def test_mcp_server_contract(self) -> None:
        for rel in PLUGIN_MANIFESTS:
            with self.subTest(file=rel):
                raw = load(rel).get("mcpServers")
                self.assertIsNotNone(raw, f"{rel}: mcpServers is missing")
                if isinstance(raw, str):
                    target = (ROOT / raw).resolve()
                    self.assertTrue(target.is_relative_to(ROOT), f"{rel}: {raw} escapes the repository")
                    self.assertTrue(target.is_file(), f"{rel}: {raw} does not exist")
                    servers = json.loads(target.read_text(encoding="utf-8"))["mcpServers"]
                else:
                    servers = raw
                self.assertNotIn("clickhouse", servers)
                self.assertEqual(set(servers), {MCP_NAME})
                server = servers[MCP_NAME]
                self.assertEqual(server.get("url") or server.get("httpUrl"), MCP_URL)
                auth = (
                    server.get("headers", {}).get("Authorization") == BEARER
                    or server.get("bearerTokenEnvVar") == TOKEN_ENV
                    or server.get("bearer_token_env_var") == TOKEN_ENV
                )
                self.assertTrue(auth, f"{rel}: token must come from {TOKEN_ENV}")

        variables = load(".cursor-plugin/plugin.json")["variables"]
        self.assertIn(TOKEN_ENV, variables["properties"])
        self.assertIn(TOKEN_ENV, variables["required"])

    def test_no_secrets(self) -> None:
        for path in sorted(ROOT.rglob("*.json")):
            if ".git" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            data = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(file=rel):
                self.assertEqual(secret_problems(rel, data), [])

    def test_secret_guard_rejects_literal_tokens(self) -> None:
        def mutated(rel: str, path: str, value: object) -> dict:
            data = load(rel)
            parts = path.split(".")
            node = data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            return data

        cases = {
            "variable default": (".cursor-plugin/plugin.json", "variables.properties.ROSSTAT_MCP_TOKEN.default", "FAKEVALUE123"),
            "env value": ("qwen-extension.json", "mcpServers.rosstat-staging.env", {TOKEN_ENV: "FAKEVALUE123"}),
            "extra header": ("qwen-extension.json", "mcpServers.rosstat-staging.headers.X-Auth", "bearer FAKEVALUE123"),
            "token scheme": (".claude-plugin/plugin.json", "mcpServers.rosstat-staging.headers.Authorization", "Token abc"),
            "query token": ("kimi.plugin.json", "mcpServers.rosstat-staging.url", MCP_URL + "?token=abc"),
            "credential key": ("kimi.plugin.json", "mcpServers.rosstat-staging.credential", "abc"),
        }
        for name, (rel, path, value) in cases.items():
            with self.subTest(case=name):
                self.assertTrue(secret_problems(rel, mutated(rel, path, value)), f"{name} not detected")

    def test_marketplace_sources(self) -> None:
        self.assertEqual(load(".claude-plugin/marketplace.json")["plugins"][0]["source"], "./")
        self.assertEqual(load(".cursor-plugin/marketplace.json")["plugins"][0]["source"], ".")
        self.assertEqual(
            load(".agents/plugins/marketplace.json")["plugins"][0]["source"],
            {"source": "url", "url": REPO_GIT, "ref": "main"},
        )

    def test_skill(self) -> None:
        skills = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
        self.assertEqual(skills, ["rosstat-sql"])
        path = ROOT / SKILL_REL
        self.assertLessEqual(path.stat().st_size, SKILL_MAX_BYTES)
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        self.assertEqual(meta.get("name"), "rosstat-sql")
        self.assertTrue(0 < len(meta.get("description", "")) <= SKILL_DESCRIPTION_MAX)
        self.assertIn("Russian", text)
        self.assertEqual(LITERAL_SECRET.findall(text), [])
        blocks = SQL_BLOCK.findall(text)
        self.assertTrue(blocks, "skill must carry SQL templates")
        for sql in blocks:
            for table in skill_tables(sql):
                with self.subTest(table=table):
                    self.assertTrue(table.startswith(("v_", "system.")), f"{table} is not a v_* view")

    def test_skill_tables_parser(self) -> None:
        sql = "SELECT 1 FROM v_a JOIN system.columns c ON 1 WHERE x IN (SELECT y FROM v_point_in_time_asof(as_of='2024-01-01'))"
        self.assertEqual(skill_tables(sql), {"v_a", "system.columns", "v_point_in_time_asof"})
        self.assertEqual(skill_tables("SELECT 1 FROM macro_series"), {"macro_series"})

    def test_tracked_files_allowlist(self) -> None:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout
        tracked = set(out.split())
        self.assertEqual(tracked, TRACKED_FILES)
        size = sum((ROOT / rel).stat().st_size for rel in tracked)
        self.assertLessEqual(size, MAX_BYTES)


if __name__ == "__main__":
    unittest.main()

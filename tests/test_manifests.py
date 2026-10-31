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
VERSION = "0.3.0"
LONG = (
    "Read-only MCP connection to Rosstat/CBR data marts (v_* views, point-in-time layer) "
    "on the clickhouse-import-rosstat staging server."
)
SHORT = "Read-only MCP to Rosstat/CBR data marts"

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
}
MAX_BYTES = 65536

COMPONENT_KEYS = ("skills", "agents", "commands", "hooks")
FORBIDDEN_KEY = re.compile(r"(?i)(api[_-]?key|token|password|secret)")
TOKEN_REF_KEYS = {"bearerTokenEnvVar", "bearer_token_env_var", TOKEN_ENV}


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

    def test_no_component_fields(self) -> None:
        for rel in PLUGIN_MANIFESTS:
            data = load(rel)
            for key in COMPONENT_KEYS:
                with self.subTest(file=rel, key=key):
                    self.assertNotIn(key, data)

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
            self._walk(rel, json.loads(path.read_text(encoding="utf-8")))

    def _walk(self, rel: str, value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in TOKEN_REF_KEYS:
                    if key != TOKEN_ENV:
                        self.assertEqual(child, TOKEN_ENV, f"{rel}: {key} must name {TOKEN_ENV}")
                    continue
                self.assertIsNone(FORBIDDEN_KEY.search(key), f"{rel}: forbidden key {key!r}")
                self._walk(rel, child)
        elif isinstance(value, list):
            for child in value:
                self._walk(rel, child)
        elif isinstance(value, str) and value.startswith("Bearer "):
            self.assertEqual(value, BEARER, f"{rel}: literal bearer value")

    def test_marketplace_sources(self) -> None:
        self.assertEqual(load(".claude-plugin/marketplace.json")["plugins"][0]["source"], "./")
        self.assertEqual(load(".cursor-plugin/marketplace.json")["plugins"][0]["source"], ".")
        self.assertEqual(
            load(".agents/plugins/marketplace.json")["plugins"][0]["source"],
            {"source": "url", "url": REPO_GIT, "ref": "main"},
        )

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

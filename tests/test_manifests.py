#!/usr/bin/env python3
"""Контракт манифестов плагина rosstat-mcp.

Запуск из корня репозитория::

    python3 -m unittest discover -s tests -v

Только стандартная библиотека; сеть не нужна. Структурная проверка
YAML-патча DeepSeek Harness выполняется при установленном PyYAML (его ставит CI).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:  # PyYAML нужен только для структурной проверки bundle-патча DSH; CI его ставит.
    import yaml
except ImportError:  # pragma: no cover - локальный запуск без dev-зависимостей
    yaml = None

ROOT = Path(__file__).resolve().parent.parent

NAME = "rosstat-mcp"
VERSION = "0.5.0"
LONG = (
    "Read-only MCP connection to Rosstat/CBR data marts (v_* views, point-in-time layer) "
    "on the clickhouse-import-rosstat staging server, plus the rosstat-sql skill for writing "
    "efficient ClickHouse queries against them."
)
SHORT = "Read-only MCP to Rosstat/CBR data marts + SQL skill"

MCP_NAME = "rosstat-staging"
MCP_URL = "https://mcp.selfinvesting.ru:8443/mcp"
AUTH_VALUE = "oauth"
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

# Bundle для DeepSeek Harness: npm-пакет в корне репозитория, который DSH
# ставит как зависимость профиля (`github:kmlebedev/rosstat-mcp`). Патч
# добавляет MCP-строку и host-плагин, регистрирующий скил rosstat-sql.
# DSH 0.2.x не умеет MCP OAuth, поэтому строка авторизуется bearer-токеном
# из ROSSTAT_MCP_TOKEN (как манифесты 0.4.x), а не через OAuth.
DSH_PACKAGE = "package.json"
DSH_PATCH = "cordis.patch.yml"
DSH_PLUGIN = "index.js"
DSH_ICON = "icon.svg"
DSH_LOCALES = ("locale/en.json", "locale/ru.json")
DSH_FILES = (DSH_PACKAGE, DSH_PATCH, DSH_PLUGIN, DSH_ICON, *DSH_LOCALES)
DSH_TOKEN_ENV = "ROSSTAT_MCP_TOKEN"
DSH_HEADER = "`Bearer ${process.env." + DSH_TOKEN_ENV + "}`"
DSH_ROW_IDS = {"mcp-rosstat-staging", "skill-rosstat-sql"}

TRACKED_FILES = {
    *PLUGIN_MANIFESTS,
    *MARKETPLACES,
    *MCP_CONFIGS,
    *DSH_FILES,
    "README.md",
    "LICENSE",
    ".gitignore",
    "mkdocs.yml",
    "tests/test_manifests.py",
    ".github/workflows/check.yml",
    ".github/workflows/pages.yml",
    "skills/rosstat-sql/SKILL.md",
    "skills/rosstat-sql/references/templates.md",
    "skills/rosstat-sql/references/point-in-time.md",
    "wiki/rosstat-mcp.md",
}
# Клиентские манифесты и скил занимают ~60 КБ; bundle DSH добавляет host half,
# локали и иконку, поэтому бюджет расширен до 80 КБ.
MAX_BYTES = 81920

SKILL_REL = "skills/rosstat-sql/SKILL.md"
SKILL_REFS = ("skills/rosstat-sql/references/templates.md", "skills/rosstat-sql/references/point-in-time.md")
SKILL_MAX_BYTES = 6144
# SKILL.md грузится при каждом срабатывании; references — только по ссылке, но и их держим компактными.
SKILL_TOTAL_MAX_BYTES = 10240
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
# OAuth не требует ни статических заголовков, ни плагинных переменных.
BLOCKED_KEYS = {"headers", "variables"}


def secret_problems(rel: str, value: object, path: str = "") -> list[str]:
    """Нарушения правила «только OAuth, без токенов и статических headers»."""
    problems: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}" if path else key
            if key in TOKEN_REF_KEYS:
                problems.append(f"{rel}: {here} is a legacy token reference; use auth: oauth")
            elif key in BLOCKED_KEYS:
                problems.append(f"{rel}: {here} is not allowed; OAuth needs no headers/variables")
            elif key == "auth":
                if child != AUTH_VALUE:
                    problems.append(f"{rel}: {here} must be {AUTH_VALUE!r}")
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


def skill_text() -> str:
    return "\n".join((ROOT / rel).read_text(encoding="utf-8") for rel in (SKILL_REL, *SKILL_REFS))


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
                self.assertNotIn("headers", server)
                self.assertNotIn("bearerTokenEnvVar", server)
                self.assertNotIn("bearer_token_env_var", server)
                if rel == "kimi.plugin.json":
                    self.assertEqual(server.get("auth"), AUTH_VALUE)
                else:
                    self.assertNotIn("auth", server)

        self.assertNotIn("variables", load(".cursor-plugin/plugin.json"))

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
            "bearer env var": ("kimi.plugin.json", "mcpServers.rosstat-staging.bearerTokenEnvVar", "ROSSTAT_MCP_TOKEN"),
            "header": ("qwen-extension.json", "mcpServers.rosstat-staging.headers", {"Authorization": "Bearer FAKE"}),
            "env token": ("qwen-extension.json", "mcpServers.rosstat-staging.env", {"ROSSTAT_MCP_TOKEN": "FAKE"}),
            "query token": ("kimi.plugin.json", "mcpServers.rosstat-staging.url", MCP_URL + "?token=abc"),
            "credential key": ("kimi.plugin.json", "mcpServers.rosstat-staging.credential", "abc"),
            "auth basic": ("kimi.plugin.json", "mcpServers.rosstat-staging.auth", "basic"),
            "cursor variables": (".cursor-plugin/plugin.json", "variables", {"type": "object"}),
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
        files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "skills").rglob("*") if p.is_file())
        self.assertEqual(files, sorted((SKILL_REL, *SKILL_REFS)))
        path = ROOT / SKILL_REL
        self.assertLessEqual(path.stat().st_size, SKILL_MAX_BYTES)
        self.assertLessEqual(sum((ROOT / rel).stat().st_size for rel in files), SKILL_TOTAL_MAX_BYTES)
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        self.assertEqual(meta.get("name"), "rosstat-sql")
        self.assertTrue(0 < len(meta.get("description", "")) <= SKILL_DESCRIPTION_MAX)
        self.assertIn("Russian", text)
        for ref in SKILL_REFS:
            with self.subTest(link=ref):
                self.assertIn(f"]({ref.removeprefix('skills/rosstat-sql/')})", text, "SKILL.md must link every reference")
        whole = skill_text()
        self.assertEqual(LITERAL_SECRET.findall(whole), [])
        blocks = SQL_BLOCK.findall(whole)
        self.assertTrue(blocks, "skill must carry SQL templates")
        for sql in blocks:
            for table in skill_tables(sql):
                with self.subTest(table=table):
                    self.assertTrue(table.startswith(("v_", "system.")), f"{table} is not a v_* view")

    def test_skill_rules_from_review(self) -> None:
        text = skill_text()
        core = (ROOT / SKILL_REL).read_text(encoding="utf-8")
        self.assertIn("create_table_query", core, "source -> view lookup must be in the core workflow")
        body = [l for l in core.split("---\n", 2)[2].splitlines() if l.strip() and not l.startswith("#")]
        self.assertIn("Answer the user in Russian", body[0])
        self.assertNotRegex(text, r"toStartOfWeek\(\w+\)", "weeks must start on Monday")
        self.assertNotIn("any(value)", text, "dedupe must be deterministic")
        self.assertNotRegex(text, r"\d\.\d{4,}", "no literal data values the agent could quote")
        self.assertIn("toDateTime(", text, "DateTime literals need an explicit zone")
        yoy = next(b for b in SQL_BLOCK.findall(text) if "log(" in b)
        self.assertIn("PARTITION BY series", yoy)
        self.assertIn("dateDiff('month'", yoy, "y/y window must prove 12 consecutive months")

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


class DshBundleTest(unittest.TestCase):
    """Контракт bundle для DeepSeek Harness: корневой npm-пакет и его cordis.patch.yml."""

    def test_bundle_manifest(self) -> None:
        data = load(DSH_PACKAGE)
        self.assertEqual(data["name"], NAME)
        self.assertEqual(data["version"], VERSION)
        self.assertEqual(data["description"], SHORT)
        self.assertEqual(data["type"], "module")
        self.assertEqual(data["main"], DSH_PLUGIN)
        self.assertEqual(
            data["exports"],
            {
                ".": f"./{DSH_PLUGIN}",
                "./locale/*.json": "./locale/*.json",
                "./icon": f"./{DSH_ICON}",
            },
        )
        self.assertEqual(data["dsh"], {"bundle": {"patch": f"./{DSH_PATCH}"}})
        self.assertEqual(data["license"], "MIT")
        self.assertEqual(data.get("icon"), None)
        self.assertTrue({DSH_PLUGIN, DSH_PATCH, DSH_ICON, "locale/*.json", "skills"} <= set(data["files"]))
        self.assertNotIn("dependencies", data)
        self.assertNotIn("peerDependencies", data)
        for rel in DSH_FILES:
            with self.subTest(file=rel):
                self.assertTrue((ROOT / rel).is_file(), f"{rel} is missing")

    def test_patch_points_at_the_mcp_server(self) -> None:
        text = (ROOT / DSH_PATCH).read_text(encoding="utf-8")
        self.assertIn("@deepseek-ai/dsh-mcp-client", text)
        self.assertIn(f"serverName: {MCP_NAME}", text)
        self.assertIn(MCP_URL, text)
        self.assertIn(f"process.env.{DSH_TOKEN_ENV}", text)
        self.assertIn("failOnStartupError: true", text)
        self.assertIn(f"name: '{NAME}'", text)
        self.assertEqual(LITERAL_SECRET.findall(text), [], "patch must not carry a literal credential")

    @unittest.skipIf(yaml is None, "PyYAML is not installed; the CI job installs it")
    def test_patch_structure(self) -> None:
        class Loader(yaml.SafeLoader):
            pass

        Loader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node))
        patch = yaml.load((ROOT / DSH_PATCH).read_text(encoding="utf-8"), Loader=Loader)
        self.assertIsInstance(patch, list)
        self.assertEqual(len(patch), 1)
        self.assertEqual(set(patch[0]), {"insert"})
        rows = {row["id"]: row for row in patch[0]["insert"]}
        self.assertEqual(set(rows), DSH_ROW_IDS)

        mcp = rows["mcp-rosstat-staging"]
        self.assertEqual(mcp["name"], "@deepseek-ai/dsh-mcp-client")
        config = mcp["config"]
        self.assertEqual(config["serverName"], MCP_NAME)
        self.assertEqual(config["transport"], "streamable-http")
        self.assertEqual(config["url"], MCP_URL)
        self.assertIs(config["failOnStartupError"], True)
        self.assertEqual(config["headers"], {"Authorization": DSH_HEADER})

        skill = rows["skill-rosstat-sql"]
        self.assertEqual(skill["name"], NAME)
        self.assertNotIn("config", skill)

    def test_locales_and_icon(self) -> None:
        for rel in DSH_LOCALES:
            with self.subTest(file=rel):
                meta = load(rel)["meta"]
                self.assertTrue(meta["title"].strip())
                self.assertTrue(meta["description"].strip())
                self.assertLessEqual(len(meta["description"]), 300)
        icon = ROOT / DSH_ICON
        self.assertLessEqual(icon.stat().st_size, 256 * 1024)
        root = ET.fromstring(icon.read_text(encoding="utf-8"))
        self.assertTrue(root.tag.endswith("svg"))
        self.assertTrue(root.get("viewBox"))

    def test_host_plugin_registers_skill(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for the DeepSeek Harness host half")
        description = frontmatter((ROOT / SKILL_REL).read_text(encoding="utf-8"))["description"]
        script = (
            """
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const root = __ROOT__;
const mod = await import(pathToFileURL(root + "/" + __PLUGIN__).href);
assert.deepEqual(mod.inject, ["skills"]);
let provider;
const ctx = { skills: { registerProvider(create) { provider = create({ signal: new AbortController().signal, invalidate() {} }); } } };
mod.apply(ctx);
const candidates = await provider.list({ cwd: root });
assert.equal(candidates.length, 1);
const candidate = candidates[0];
assert.equal(candidate.name, "rosstat-sql");
assert.equal(candidate.description, __DESCRIPTION__);
assert.equal(candidate.provider, "rosstat-mcp");
assert.equal(candidate.source, "bundled");
assert.equal(candidate.rank, 600);
const definition = await provider.get(candidate);
assert.equal(definition.name, candidate.name);
assert.equal(definition.description, candidate.description);
assert.ok(definition.content.startsWith("# Answering with Rosstat/CBR data"));
assert.ok(definition.content.includes("references/templates.md"));
assert.ok(definition.resourceBase.path.endsWith("skills/rosstat-sql"));
"""
        )
        script = (
            script.replace("__ROOT__", json.dumps(str(ROOT)))
            .replace("__PLUGIN__", json.dumps(DSH_PLUGIN))
            .replace("__DESCRIPTION__", json.dumps(description))
        )
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()

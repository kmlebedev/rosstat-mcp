/**
 * DeepSeek Harness host half of the rosstat-mcp bundle.
 *
 * The bundle patch (`cordis.patch.yml`) connects the remote MCP server; this
 * module adds the repository's `rosstat-sql` skill to the Harness skill
 * registry, so the same instructions that ship to the other clients are
 * available to a Harness agent as soon as the bundle loads.
 */

import { readFile } from "node:fs/promises";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

/** Provider name; also the package name the bundle patch refers to. */
const PROVIDER_NAME = "rosstat-mcp";
/** Directory name under `skills/`; the frontmatter supplies the public name. */
const SKILL_NAME = "rosstat-sql";
/** Rank of packaged skill providers: a lower rank wins a duplicate name. */
const BUNDLED_RANK = 600;

const SKILL_BODY_URL = new URL(`./skills/${SKILL_NAME}/SKILL.md`, import.meta.url);
const SKILL_FILE = fileURLToPath(SKILL_BODY_URL);
const SKILL_DIRECTORY = dirname(SKILL_FILE);
const RESOURCE_BASE = { kind: "directory", path: SKILL_DIRECTORY };
const INVOCATION = { modelInvocable: true, userInvocable: true };
const SOURCE = "bundled";
const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;

let loaded;

/** Read and parse the skill once; a failed read is retried on the next call. */
function loadSkill() {
  loaded ??= readFile(SKILL_BODY_URL, "utf8").then(parseSkill, (error) => {
    loaded = undefined;
    throw error;
  });
  return loaded;
}

/** Parse the flat `name`/`description` frontmatter used by the shared SKILL.md. */
function parseSkill(raw) {
  const match = FRONTMATTER.exec(raw);
  if (match === null) {
    throw new TypeError(`${PROVIDER_NAME}: skills/${SKILL_NAME}/SKILL.md has no YAML frontmatter`);
  }
  const fields = {};
  for (const line of match[1].split(/\r?\n/)) {
    const separator = line.indexOf(":");
    if (separator > 0) fields[line.slice(0, separator).trim()] = unquote(line.slice(separator + 1).trim());
  }
  const name = fields.name;
  const description = fields.description;
  if (!name || !description) {
    throw new TypeError(`${PROVIDER_NAME}: skills/${SKILL_NAME}/SKILL.md frontmatter requires name and description`);
  }
  return { name, description, content: raw.slice(match[0].length).trim() };
}

/** Strip one pair of surrounding quotes from a frontmatter value. */
function unquote(value) {
  if (value.length < 2) return value;
  const quote = value[0];
  return (quote === '"' || quote === "'") && value.endsWith(quote) ? value.slice(1, -1) : value;
}

/** Discovery record for the skill catalog. */
function candidateOf(skill) {
  return {
    name: skill.name,
    description: skill.description,
    invocation: INVOCATION,
    provider: PROVIDER_NAME,
    source: SOURCE,
    rank: BUNDLED_RANK,
    locator: SKILL_BODY_URL,
    path: SKILL_FILE,
    resourceBase: RESOURCE_BASE,
  };
}

/** Loaded skill, resolved against the directory that holds its references. */
function definitionOf(skill) {
  return {
    name: skill.name,
    description: skill.description,
    invocation: INVOCATION,
    provider: PROVIDER_NAME,
    source: SOURCE,
    resourceBase: RESOURCE_BASE,
    path: SKILL_FILE,
    content: skill.content,
  };
}

const provider = {
  name: PROVIDER_NAME,
  async list() {
    return [candidateOf(await loadSkill())];
  },
  async get() {
    return definitionOf(await loadSkill());
  },
};

/** Service required to register the bundled provider. */
export const inject = ["skills"];

/** Register the bundled `rosstat-sql` provider on `ctx.skills`. */
export function apply(ctx) {
  ctx.skills.registerProvider(() => provider);
}

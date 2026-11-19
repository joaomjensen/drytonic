"""Templates written by ``tonic init`` for the supported coding agents.

The generated files are code/configuration, not prose instructions: the agent
cannot edit its own gates without going through the same guard as any other
file.
"""

from typing import Any

OPENCODE_PLUGIN = r'''import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WRITE_TOOLS = new Set(["edit", "write", "patch", "multiedit"]);
const SUPPORTED_EXTENSIONS = new Set([".py", ".ts", ".tsx", ".js", ".jsx"]);
const PLUGIN_ROOT = fileURLToPath(new URL("../../", import.meta.url));

// callID correlates tool.execute.before (guard) with tool.execute.after (check).
const edits = new Map();

function resolveTonicBin(root) {
  // Prefer the project binary at .venv/bin/tonic; fall back to `tonic` on PATH.
  const local = path.join(root, ".venv", "bin", "tonic");
  if (fs.existsSync(local)) return local;
  return "tonic"; // fallback: tonic available on PATH
}

function runTonic(root, args) {
  try {
    return spawnSync(resolveTonicBin(root), args, { encoding: "utf-8" });
  } catch {
    return { status: null }; // gate stays out of the way when tonic is not installed
  }
}

function extractFilePath(input, output) {
  return (
    output?.args?.filePath ??
    output?.args?.path ??
    input?.args?.filePath ??
    input?.args?.path ??
    ""
  );
}

function callID(input, output) {
  return input?.callID ?? output?.callID ?? null;
}

function isSupported(absPath) {
  return SUPPORTED_EXTENSIONS.has(path.extname(absPath).toLowerCase());
}

export default {
  id: "drytonic",
  setup: async (ctx) => {
    const root = typeof ctx?.directory === "string" ? ctx.directory : PLUGIN_ROOT;

    return {
      "tool.execute.before": async (input, output) => {
        if (!WRITE_TOOLS.has(input?.tool)) return;
        const rawPath = extractFilePath(input, output);
        if (!rawPath) return;

        const absPath = path.resolve(root, rawPath);
        const id = callID(input, output);
        const record = { absPath, blocked: false };
        if (id !== null) edits.set(id, record);

        // The decision belongs to the Python CLI; the plugin only interprets it.
        const res = runTonic(root, ["guard", absPath]);
        if (!res || res.status !== 2) return;

        const diagnostic = `${res.stderr ?? ""}${res.stdout ?? ""}`;
        const isGovernance = diagnostic.includes("GUARD:governance");
        const isExistingTest =
          diagnostic.includes("GUARD:test") && fs.existsSync(absPath);

        // Governance is blocked even for new files; new tests may be created.
        if (isGovernance || isExistingTest) {
          record.blocked = true;
          throw new Error(
            `[DRYTONIC GUARD] Edição bloqueada em '${rawPath}'.\n${diagnostic.trim()}`
          );
        }
      },

      "tool.execute.after": async (input, output) => {
        if (!WRITE_TOOLS.has(input?.tool) || !output) return;

        const id = callID(input, output);
        const record = id !== null ? edits.get(id) : null;
        if (id !== null) edits.delete(id);
        if (record?.blocked) return;

        const rawPath = extractFilePath(input, output);
        const absPath =
          record?.absPath ?? (rawPath ? path.resolve(root, rawPath) : "");
        if (!absPath || !isSupported(absPath) || !fs.existsSync(absPath)) return;

        const res = runTonic(root, ["check", absPath]);
        if (!res) return;

        if (res.status === 0) {
          output.output = `${output.output ?? ""}\n[drytonic] OK: ${path.basename(absPath)} verificado sem violações.`;
        } else {
          const diagnostic = (res.stderr || res.stdout || "").trim();
          output.output = `${output.output ?? ""}\n\n[DRYTONIC GATE BLOQUEOU O ARQUIVO - CORRIJA IMEDIATAMENTE]\n${diagnostic}`;
        }
      },
    };
  },
};
'''


def render_opencode_plugin() -> str:
    """Return the ``.opencode/plugins/drytonic.js`` source."""
    return OPENCODE_PLUGIN


def render_claude_settings() -> dict[str, Any]:
    """Return the ``.claude/settings.json`` payload for Claude Code hooks."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'tonic guard "$CLAUDE_FILE_PATHS"',
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'tonic check "$CLAUDE_FILE_PATHS"',
                        }
                    ],
                }
            ],
        }
    }

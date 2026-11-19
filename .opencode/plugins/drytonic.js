import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WRITE_TOOLS = new Set(["edit", "write", "patch", "multiedit"]);
const PLUGIN_ROOT = fileURLToPath(new URL("../../", import.meta.url));

function extractFilePath(input, output) {
  return (
    output?.args?.filePath ??
    output?.args?.path ??
    input?.args?.filePath ??
    input?.args?.path ??
    ""
  );
}

export default {
  id: "drytonic",
  setup: async (ctx) => {
    const root = typeof ctx?.directory === "string" ? ctx.directory : PLUGIN_ROOT;
    const tonicBin = path.join(root, ".venv", "bin", "tonic");

    return {
      "tool.execute.before": async (input, output) => {
        if (!WRITE_TOOLS.has(input?.tool)) return;
        const rawPath = extractFilePath(input, output);
        if (!rawPath) return;

        const absPath = path.resolve(root, rawPath);
        if (!fs.existsSync(tonicBin)) return;

        // A decisão é do CLI Python; o plugin apenas interpreta o resultado.
        const res = spawnSync(tonicBin, ["guard", absPath], {
          encoding: "utf-8",
        });
        if (res.status !== 2) return;

        const diagnostic = `${res.stderr ?? ""}${res.stdout ?? ""}`;
        const isGovernance = diagnostic.includes("GUARD:governance");
        const isExistingTest =
          diagnostic.includes("GUARD:test") && fs.existsSync(absPath);

        // Governança é bloqueada mesmo em arquivos novos; testes novos podem ser criados.
        if (isGovernance || isExistingTest) {
          throw new Error(
            `[DRYTONIC GUARD] Edição bloqueada em '${rawPath}'.\n${diagnostic.trim()}`
          );
        }
      },

      "tool.execute.after": async (input, output) => {
        if (!WRITE_TOOLS.has(input?.tool)) return;
        const rawPath = extractFilePath(input, output);
        if (!rawPath || !rawPath.endsWith(".py")) return;

        const absPath = path.resolve(root, rawPath);
        if (!fs.existsSync(absPath) || !fs.existsSync(tonicBin)) return;

        const res = spawnSync(tonicBin, ["check", absPath], {
          encoding: "utf-8",
        });

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

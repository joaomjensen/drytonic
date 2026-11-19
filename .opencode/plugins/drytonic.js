import fs from "node:fs";
import path from "node:path";

const WRITE_TOOLS = new Set(["edit", "write", "patch", "multiedit"]);

function extractFilePath(input, output) {
  return (
    input?.args?.filePath ??
    input?.args?.path ??
    output?.args?.filePath ??
    output?.args?.path ??
    ""
  );
}

function isProtectedTest(absPath) {
  const base = path.basename(absPath);
  const isTestName =
    (base.startsWith("test_") && base.endsWith(".py")) ||
    base.endsWith("_test.py");
  return isTestName && fs.existsSync(absPath);
}

export const DrytonicPlugin = async ({ $, directory }) => {
  const root = directory || process.cwd();
  const tonicBin = path.join(root, ".venv", "bin", "tonic");

  return {
    "tool.execute.before": async (input, output) => {
      if (!WRITE_TOOLS.has(input?.tool)) return;
      const rawPath = extractFilePath(input, output);
      if (!rawPath) return;

      const absPath = path.resolve(root, rawPath);
      if (isProtectedTest(absPath)) {
        throw new Error(
          `[DRYTONIC SPEC LOCK] Edição bloqueada em '${rawPath}'. Arquivos de teste existentes são contratos imutáveis. Se a especificação estiver incorreta, abra uma disputa com 'tonic dispute'.`
        );
      }
    },

    "tool.execute.after": async (input, output) => {
      if (!WRITE_TOOLS.has(input?.tool)) return;
      const rawPath = extractFilePath(input, output);
      if (!rawPath || !rawPath.endsWith(".py")) return;

      const absPath = path.resolve(root, rawPath);
      if (!fs.existsSync(absPath) || !fs.existsSync(tonicBin)) return;

      const result = await $`${tonicBin} check ${absPath}`.nothrow().quiet();
      if (result.exitCode !== 0) {
        const diagnostic = result.stderr.toString().trim();
        output.output = `${output.output}\n\n[DRYTONIC GATE BLOQUEOU O ARQUIVO - CORRIJA IMEDIATAMENTE]\n${diagnostic}`;
      }
    },
  };
};

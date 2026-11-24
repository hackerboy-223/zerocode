import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { build } from "esbuild";

const root = resolve(import.meta.dirname, "..");
const outDir = mkdtempSync(join(tmpdir(), "zerocode-desktop-tests-"));

try {
  const entry = join(root, "src/lib/settings.test.ts");
  const outFile = join(outDir, "settings.test.mjs");
  await build({
    entryPoints: [entry],
    outfile: outFile,
    bundle: true,
    format: "esm",
    platform: "node",
    external: ["node:*"]
  });
  const result = spawnSync(process.execPath, ["--test", outFile], { stdio: "inherit" });
  process.exitCode = result.status ?? 1;
} finally {
  rmSync(outDir, { recursive: true, force: true });
}

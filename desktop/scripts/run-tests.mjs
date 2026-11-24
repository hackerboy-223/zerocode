import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const outDir = mkdtempSync(join(tmpdir(), "zerocode-desktop-tests-"));
const tscBin = resolve(
  root,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "tsc.cmd" : "tsc"
);

try {
  writeFileSync(join(outDir, "package.json"), JSON.stringify({ type: "module" }));
  const tsconfigPath = join(outDir, "tsconfig.json");
  writeFileSync(
    tsconfigPath,
    JSON.stringify({
      compilerOptions: {
        target: "ES2022",
        module: "NodeNext",
        moduleResolution: "NodeNext",
        strict: true,
        skipLibCheck: true,
        typeRoots: [resolve(root, "node_modules/@types")],
        types: ["node"],
        rootDir: resolve(root, "src"),
        outDir
      },
      files: [resolve(root, "src/lib/settings.test.ts")]
    })
  );
  const compile = spawnSync(tscBin, ["-p", tsconfigPath], {
    stdio: "inherit",
    shell: process.platform === "win32"
  });
  if (compile.status !== 0) {
    process.exitCode = compile.status ?? 1;
  } else {
    const run = spawnSync(
      process.execPath,
      ["--test", join(outDir, "lib/settings.test.js")],
      { stdio: "inherit" }
    );
    process.exitCode = run.status ?? 1;
  }
} finally {
  rmSync(outDir, { recursive: true, force: true });
}

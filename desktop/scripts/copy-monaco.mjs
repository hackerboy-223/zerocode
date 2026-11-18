import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const source = resolve("node_modules/monaco-editor/min/vs");
const target = resolve("public/vs");
if (!existsSync(source)) throw new Error("Monaco Editor n'est pas installé. Exécutez npm install dans desktop/.");
mkdirSync(resolve("public"), { recursive: true });
rmSync(target, { recursive: true, force: true });
cpSync(source, target, { recursive: true });
console.log("Monaco Editor local copié dans desktop/public/vs.");

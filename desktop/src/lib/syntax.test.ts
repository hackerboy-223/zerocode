import test from "node:test";
import assert from "node:assert/strict";
import { tokenizeCode } from "./syntax.js";

test("tokenizeCode highlights TypeScript keywords, types, strings, numbers, and comments", () => {
  const code = 'const count: number = 42; // answer\nclass UserModel { name = "Ada"; }';
  const tokens = tokenizeCode(code, "ts");
  assert.equal(tokens.map((t) => t.text).join(""), code);
  assert.ok(tokens.some((t) => t.kind === "kw" && t.text === "const"));
  assert.ok(tokens.some((t) => t.kind === "num" && t.text === "42"));
  assert.ok(tokens.some((t) => t.kind === "cmt" && t.text === "// answer"));
  assert.ok(tokens.some((t) => t.kind === "type" && t.text === "UserModel"));
  assert.ok(tokens.some((t) => t.kind === "str" && t.text === '"Ada"'));
});

test("tokenizeCode supports Python and Rust comments/keywords", () => {
  const py = 'def run(x):\n    # check\n    return True\n';
  const pyTokens = tokenizeCode(py, "python");
  assert.equal(pyTokens.map((t) => t.text).join(""), py);
  assert.ok(pyTokens.some((t) => t.kind === "kw" && t.text === "def"));
  assert.ok(pyTokens.some((t) => t.kind === "cmt" && t.text === "# check"));

  const rs = "pub fn main() { let v = 10; }";
  const rsTokens = tokenizeCode(rs, "rust");
  assert.ok(rsTokens.some((t) => t.kind === "kw" && t.text === "pub"));
  assert.ok(rsTokens.some((t) => t.kind === "kw" && t.text === "fn"));
});

test("tokenizeCode falls back to plain text for unknown languages or huge inputs", () => {
  const unknown = tokenizeCode("hello world", "plaintext");
  assert.deepEqual(unknown, [{ kind: "plain", text: "hello world" }]);

  const huge = "const x = 1;\n".repeat(2000);
  const capped = tokenizeCode(huge, "ts");
  assert.deepEqual(capped, [{ kind: "plain", text: huge }]);
});

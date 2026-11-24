import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_SETTINGS, sanitizeSettings } from "./settings";

test("sanitizeSettings returns defaults for empty or invalid input", () => {
  assert.deepEqual(sanitizeSettings(null), DEFAULT_SETTINGS);
  assert.deepEqual(sanitizeSettings("invalid"), DEFAULT_SETTINGS);
  assert.deepEqual(sanitizeSettings({}), DEFAULT_SETTINGS);
});

test("sanitizeSettings enforces safe defaultMode and never restores full-stack", () => {
  const result = sanitizeSettings({ defaultMode: "full-stack", theme: "dark", accent: "green" });
  assert.equal(result.defaultMode, "build");
  assert.equal(result.theme, "dark");
  assert.equal(result.accent, "green");

  const plan = sanitizeSettings({ defaultMode: "plan" });
  assert.equal(plan.defaultMode, "plan");
});

test("sanitizeSettings clamps fontSize and filters invalid runtime fields", () => {
  const result = sanitizeSettings({
    fontSize: 99,
    preferredModel: "a".repeat(200),
    runtime: {
      max_steps: 25,
      auto_compact: false,
      allow_outside_cwd: true,
      protect_secrets: false,
      temperature: "hot"
    }
  });
  assert.equal(result.fontSize, DEFAULT_SETTINGS.fontSize);
  assert.equal(result.preferredModel.length, 120);
  assert.deepEqual(result.runtime, { max_steps: 25, auto_compact: false });
});

test("sanitizeSettings accepts valid fontSize, density, sendKey, and think levels", () => {
  const result = sanitizeSettings({
    fontSize: 15,
    density: "compact",
    sendKey: "mod-enter",
    preferredThink: "high",
    autoDelegate: true,
    defaultSubagentRole: "security"
  });
  assert.equal(result.fontSize, 15);
  assert.equal(result.density, "compact");
  assert.equal(result.sendKey, "mod-enter");
  assert.equal(result.preferredThink, "high");
  assert.equal(result.autoDelegate, true);
  assert.equal(result.defaultSubagentRole, "security");
});

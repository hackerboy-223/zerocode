export type TokenKind = "plain" | "kw" | "str" | "cmt" | "num" | "type";

export interface CodeToken {
  kind: TokenKind;
  text: string;
}

const KEYWORDS: Record<string, Set<string>> = {
  js: new Set([
    "async", "await", "break", "case", "catch", "class", "const", "continue", "default",
    "delete", "do", "else", "enum", "export", "extends", "false", "finally", "for", "from",
    "function", "if", "implements", "import", "in", "instanceof", "interface", "let", "new",
    "null", "of", "private", "protected", "public", "readonly", "return", "static", "super",
    "switch", "this", "throw", "true", "try", "type", "typeof", "undefined", "var", "void",
    "while", "yield"
  ]),
  py: new Set([
    "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
    "elif", "else", "except", "False", "finally", "for", "from", "global", "if", "import",
    "in", "is", "lambda", "None", "nonlocal", "not", "or", "pass", "raise", "return",
    "True", "try", "while", "with", "yield"
  ]),
  rs: new Set([
    "as", "async", "await", "break", "const", "continue", "crate", "dyn", "else", "enum",
    "extern", "false", "fn", "for", "if", "impl", "in", "let", "loop", "match", "mod",
    "move", "mut", "pub", "ref", "return", "self", "Self", "static", "struct", "super",
    "trait", "true", "type", "unsafe", "use", "where", "while"
  ]),
  sh: new Set([
    "case", "do", "done", "elif", "else", "esac", "export", "fi", "for", "function", "if",
    "in", "local", "return", "set", "then", "until", "while", "true", "false"
  ]),
  sql: new Set([
    "select", "from", "where", "insert", "into", "values", "update", "set", "delete",
    "create", "table", "drop", "alter", "join", "left", "right", "inner", "outer", "on",
    "group", "by", "order", "limit", "and", "or", "not", "null", "as", "distinct", "in"
  ])
};

function resolveGroup(rawLang: string): "js" | "py" | "rs" | "sh" | "json" | "sql" | "plain" {
  const lang = rawLang.trim().toLowerCase();
  if (["ts", "tsx", "typescript", "js", "jsx", "javascript", "mjs", "cjs", "java", "go", "c", "cpp", "cs"].includes(lang)) return "js";
  if (["py", "python"].includes(lang)) return "py";
  if (["rs", "rust"].includes(lang)) return "rs";
  if (["sh", "bash", "zsh", "shell", "powershell", "ps1", "yaml", "yml", "toml"].includes(lang)) return "sh";
  if (lang === "json") return "json";
  if (lang === "sql") return "sql";
  return "plain";
}

/**
 * Lightweight, zero-dependency syntax tokenizer for chat code blocks.
 * Capped at 16 KB per block so streaming stays instantaneous.
 */
export function tokenizeCode(code: string, rawLang: string): CodeToken[] {
  const group = resolveGroup(rawLang);
  if (group === "plain" || code.length > 16_000) {
    return [{ kind: "plain", text: code }];
  }

  const hashComments = group === "py" || group === "sh";
  const slashComments = group === "js" || group === "rs";
  const dashComments = group === "sql";
  const keywords = group === "json" ? new Set(["true", "false", "null"]) : KEYWORDS[group];

  const tokens: CodeToken[] = [];
  const push = (kind: TokenKind, text: string) => {
    if (!text) return;
    const prev = tokens[tokens.length - 1];
    if (prev && prev.kind === kind) prev.text += text;
    else tokens.push({ kind, text });
  };

  let i = 0;
  const n = code.length;
  while (i < n) {
    const ch = code[i];
    const next = code[i + 1];

    // Comments
    if ((slashComments && ch === "/" && next === "/") || (hashComments && ch === "#") || (dashComments && ch === "-" && next === "-")) {
      const end = code.indexOf("\n", i);
      const stop = end === -1 ? n : end;
      push("cmt", code.slice(i, stop));
      i = stop;
      continue;
    }
    if (slashComments && ch === "/" && next === "*") {
      const end = code.indexOf("*/", i + 2);
      const stop = end === -1 ? n : end + 2;
      push("cmt", code.slice(i, stop));
      i = stop;
      continue;
    }

    // Strings
    if (ch === '"' || ch === "'" || (group === "js" && ch === "`")) {
      const quote = ch;
      let j = i + 1;
      while (j < n && code[j] !== quote) {
        if (code[j] === "\\") j += 2;
        else if (code[j] === "\n" && quote !== "`") break;
        else j++;
      }
      const stop = j < n && code[j] === quote ? j + 1 : j;
      push("str", code.slice(i, stop));
      i = stop;
      continue;
    }

    // Numbers
    if (ch >= "0" && ch <= "9" && (i === 0 || !/[A-Za-z0-9_$]/.test(code[i - 1]))) {
      let j = i + 1;
      while (j < n && /[0-9a-fA-FxXoObB._]/.test(code[j])) j++;
      push("num", code.slice(i, j));
      i = j;
      continue;
    }

    // Identifiers, keywords, and PascalCase types
    if (/[A-Za-z_$]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[A-Za-z0-9_$]/.test(code[j])) j++;
      const word = code.slice(i, j);
      const lookup = group === "sql" ? word.toLowerCase() : word;
      if (keywords.has(lookup)) push("kw", word);
      else if (group !== "sh" && group !== "json" && group !== "sql" && /^[A-Z][A-Za-z0-9_]*$/.test(word)) push("type", word);
      else push("plain", word);
      i = j;
      continue;
    }

    push("plain", ch);
    i++;
  }

  return tokens;
}

import { useMemo } from "react";
import type { ReactNode } from "react";
import { Copy } from "lucide-react";

function renderInlineMarkdown(text: string): ReactNode[] {
  const token = /(`[^`\n]+`|\*\*[^*]+\*\*|__[^_]+__|~~[^~]+~~|\*[^*\n]+\*|_[^_\n]+_|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  return text.split(token).filter(Boolean).map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index} className="inline-code">{part.slice(1, -1)}</code>;
    }
    if ((part.startsWith("**") && part.endsWith("**")) || (part.startsWith("__") && part.endsWith("__"))) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("~~") && part.endsWith("~~")) {
      return <del key={index}>{part.slice(2, -2)}</del>;
    }
    if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_"))) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return part;
  });
}

export function FormattedMessage({ content, onCopy }: { content: string; onCopy: (text: string) => void }) {
  const rendered = useMemo(() => {
    const lines = content.replace(/\r\n/g, "\n").split("\n");
    const nodes: ReactNode[] = [];
    let i = 0;
    let key = 0;
    const isTableDivider = (line: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
    const isBlockStart = (line: string) => /^\s*(```|#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s|\|)/.test(line) || /^\s*([-*_]\s*){3,}$/.test(line);

    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }

      const fence = line.match(/^\s*```([\w+-]*)\s*$/);
      if (fence) {
        const lang = fence[1] || "code";
        const code: string[] = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
        if (i < lines.length) i++;
        const value = code.join("\n");
        nodes.push(
          <div key={key++} className="code-block">
            <div className="code-block-header"><span>{lang}</span><button type="button" className="code-copy-btn" onClick={() => onCopy(value)} title="Copier le code"><Copy size={12} /> Copier</button></div>
            <pre><code>{value}</code></pre>
          </div>
        );
        continue;
      }

      const heading = line.match(/^\s*(#{1,6})\s+(.+)$/);
      if (heading) {
        const level = heading[1].length;
        const Heading = (["h1", "h2", "h3", "h4", "h5", "h6"] as const)[level - 1];
        nodes.push(<Heading key={key++} className="markdown-heading">{renderInlineMarkdown(heading[2])}</Heading>);
        i++;
        continue;
      }

      if (/^\s*([-*_]\s*){3,}$/.test(line)) {
        nodes.push(<hr key={key++} className="markdown-rule" />);
        i++;
        continue;
      }

      if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
        const cells = (value: string) => value.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
        const headers = cells(line);
        i += 2;
        const rows: string[][] = [];
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
        nodes.push(<div key={key++} className="markdown-table-wrap"><table className="markdown-table"><thead><tr>{headers.map((cell, n) => <th key={n}>{renderInlineMarkdown(cell)}</th>)}</tr></thead><tbody>{rows.map((row, n) => <tr key={n}>{headers.map((_, col) => <td key={col}>{renderInlineMarkdown(row[col] || "")}</td>)}</tr>)}</tbody></table></div>);
        continue;
      }

      if (/^\s*>/.test(line)) {
        const quote: string[] = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
        nodes.push(<blockquote key={key++}>{renderInlineMarkdown(quote.join(" "))}</blockquote>);
        continue;
      }

      if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const items: string[] = [];
        const pattern = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        while (i < lines.length && pattern.test(lines[i])) items.push(lines[i++].replace(pattern, ""));
        const List = ordered ? "ol" : "ul";
        nodes.push(<List key={key++} className="markdown-list">{items.map((item, n) => <li key={n}>{renderInlineMarkdown(item)}</li>)}</List>);
        continue;
      }

      const paragraph = [line];
      i++;
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) paragraph.push(lines[i++]);
      nodes.push(<p key={key++} className="markdown-paragraph">{paragraph.map((part, n) => <span key={n}>{n > 0 && <br />}{renderInlineMarkdown(part)}</span>)}</p>);
    }
    return nodes;
  }, [content, onCopy]);

  return <div className="formatted-body">{rendered}</div>;
}

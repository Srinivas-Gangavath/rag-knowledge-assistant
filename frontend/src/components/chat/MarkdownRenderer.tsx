import React, { useState } from "react";

type MarkdownRendererProps = {
  content: string;
  onCitationClick?: (index: number) => void;
  sourcesCount?: number;
};

// Safe link URL validator
function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url, "https://example.com");
    return ["http:", "https:", "mailto:"].includes(parsed.protocol);
  } catch {
    return false;
  }
}

/**
 * Parses inline formatting:
 * - Citation markers: [1], [2], etc.
 * - Bold: **text** or __text__
 * - Italic: *text* or _text_
 * - Inline code: `code`
 * - Links: [text](url)
 */
function renderInlineText(
  text: string,
  onCitationClick?: (index: number) => void,
  sourcesCount?: number,
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  // Regex to match:
  // 1. Citation tokens: \[(\d+)\]
  // 2. Inline code: `([^`]+)`
  // 3. Bold: \*\*([^*]+)\*\*
  // 4. Italic: \*([^*]+)\*
  // 5. Link: \[([^\]]+)\]\(([^)]+)\)
  const pattern = /(\[(\d+)\])|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[([^\]]+)\]\(([^)]+)\))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.substring(lastIndex, match.index));
    }

    const matchedStr = match[0];

    // 1. Citation token [1], [2], etc.
    if (match[1] && match[2]) {
      const citationNum = parseInt(match[2], 10);
      const isValidCitation =
        sourcesCount !== undefined &&
        sourcesCount > 0 &&
        citationNum >= 1 &&
        citationNum <= sourcesCount;
      if (isValidCitation && onCitationClick) {
        nodes.push(
          <button
            key={`cite-${match.index}-${citationNum}`}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onCitationClick(citationNum);
            }}
            aria-label={`View source citation ${citationNum}`}
            className="inline-flex items-center justify-center px-1.5 py-0.2 mx-0.5 text-[10px] font-semibold text-brand-700 bg-brand-50 hover:bg-brand-100 hover:text-brand-900 border border-brand-200 rounded transition-colors focus:outline-none focus:ring-1 focus:ring-brand-500 cursor-pointer"
          >
            {citationNum}
          </button>
        );
      } else {
        nodes.push(matchedStr);
      }
    }
    // 2. Inline code `code`
    else if (matchedStr.startsWith("`") && matchedStr.endsWith("`")) {
      const code = matchedStr.slice(1, -1);
      nodes.push(
        <code
          key={`code-${match.index}`}
          className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-800 border border-slate-200/80"
        >
          {code}
        </code>
      );
    }
    // 3. Bold **text**
    else if (matchedStr.startsWith("**") && matchedStr.endsWith("**")) {
      const boldText = matchedStr.slice(2, -2);
      nodes.push(
        <strong key={`bold-${match.index}`} className="font-semibold text-slate-900">
          {renderInlineText(boldText, onCitationClick, sourcesCount)}
        </strong>
      );
    }
    // 4. Italic *text*
    else if (matchedStr.startsWith("*") && matchedStr.endsWith("*")) {
      const italicText = matchedStr.slice(1, -1);
      nodes.push(
        <em key={`italic-${match.index}`} className="italic text-slate-800">
          {renderInlineText(italicText, onCitationClick, sourcesCount)}
        </em>
      );
    }
    // 5. Link [text](url)
    else if (match[6] && match[7] && match[8]) {
      const linkText = match[7];
      const linkUrl = match[8];
      if (isSafeUrl(linkUrl)) {
        nodes.push(
          <a
            key={`link-${match.index}`}
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 hover:text-brand-700 underline underline-offset-2 transition-colors"
          >
            {linkText}
          </a>
        );
      } else {
        nodes.push(linkText);
      }
    } else {
      nodes.push(matchedStr);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.substring(lastIndex));
  }

  return nodes;
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-slate-200 bg-slate-900 text-slate-100 shadow-xs">
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-950/60 px-3 py-1.5 text-[11px] text-slate-400">
        <span className="font-mono uppercase">{language || "text"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="text-[11px] text-slate-400 hover:text-white transition-colors"
        >
          {copied ? "Copied!" : "Copy code"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 font-mono text-xs leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function MarkdownRenderer({
  content,
  onCitationClick,
  sourcesCount = 0,
}: MarkdownRendererProps) {
  if (!content) return null;

  const lines = content.split(/\r?\n/);
  const elements: React.ReactNode[] = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // 1. Code Block ```
    if (line.trim().startsWith("```")) {
      const language = line.trim().replace(/^```/, "").trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // Skip closing ```
      elements.push(
        <CodeBlock
          key={`code-block-${i}`}
          language={language}
          code={codeLines.join("\n")}
        />
      );
      continue;
    }

    // 2. Headings (#, ##, ###)
    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={`h3-${i}`} className="mt-3.5 mb-1.5 text-xs font-bold text-slate-900">
          {renderInlineText(line.slice(4), onCitationClick, sourcesCount)}
        </h4>
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      elements.push(
        <h3 key={`h2-${i}`} className="mt-4 mb-2 text-sm font-bold text-slate-900">
          {renderInlineText(line.slice(3), onCitationClick, sourcesCount)}
        </h3>
      );
      i++;
      continue;
    }
    if (line.startsWith("# ")) {
      elements.push(
        <h2 key={`h1-${i}`} className="mt-4 mb-2 text-base font-bold text-slate-900">
          {renderInlineText(line.slice(2), onCitationClick, sourcesCount)}
        </h2>
      );
      i++;
      continue;
    }

    // 3. Unordered List (- or *)
    if (/^(\s*[-*])\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^(\s*[-*])\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^(\s*[-*])\s+/, ""));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="my-2 list-disc space-y-1 pl-5 text-xs leading-relaxed text-slate-800">
          {listItems.map((item, idx) => (
            <li key={idx}>{renderInlineText(item, onCitationClick, sourcesCount)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // 4. Ordered List (1., 2.)
    if (/^\s*\d+\.\s+/.test(line)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} className="my-2 list-decimal space-y-1 pl-5 text-xs leading-relaxed text-slate-800">
          {listItems.map((item, idx) => (
            <li key={idx}>{renderInlineText(item, onCitationClick, sourcesCount)}</li>
          ))}
        </ol>
      );
      continue;
    }

    // 5. Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // 6. Normal Paragraph
    const paraLines: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      !lines[i].startsWith("#") &&
      !/^(\s*[-*])\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }

    elements.push(
      <p key={`p-${i}`} className="my-1.5 text-xs leading-relaxed text-slate-800">
        {renderInlineText(paraLines.join(" "), onCitationClick, sourcesCount)}
      </p>
    );
  }

  return <div className="space-y-1">{elements}</div>;
}

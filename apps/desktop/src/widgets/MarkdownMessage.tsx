import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkBreaks from "remark-breaks";
import rehypeKatex from "rehype-katex";
import { Highlight, themes } from "prism-react-renderer";

type MarkdownMessageProps = {
  text: string;
  preview?: boolean;
};

const MATH_COMMAND_RE =
  /\\(?:frac|sum|sqrt|cdot|bar|text|left|right|begin|end|alpha|beta|gamma|delta|theta|lambda|mu|sigma|pi)|[_^]/;

function detectLanguage(className?: string): string | null {
  if (!className) return null;
  const match = /language-([\w-]+)/.exec(className);
  if (!match) return null;
  return match[1] || null;
}

function normalizeCode(value: string) {
  return value.replace(/\n$/, "");
}

function normalizeMathDelimiters(value: string): string {
  if (!value.includes("\\")) return value;
  const chunks = value.split(/(```[\s\S]*?```)/g);
  return chunks
    .map((chunk) => {
      if (chunk.startsWith("```")) return chunk;
      return chunk
        .replace(/\\\[((?:.|\n)*?)\\\]/g, (match, body: string) => {
          const content = body.trim();
          return content ? `\n$$\n${content}\n$$\n` : match;
        })
        .replace(/\\\(((?:.|\n)*?)\\\)/g, (match, body: string) => {
          const content = body.trim();
          return content ? `$${content}$` : match;
        })
        .replace(/\[\s*(\\[\s\S]*?)\s*\]/g, (match, body: string) => {
          const content = body.trim();
          if (!content || !MATH_COMMAND_RE.test(content)) return match;
          return `\n$$\n${content}\n$$\n`;
        });
    })
    .join("");
}

function CodeFence({ code, language }: { code: string; language: string | null }) {
  const [copied, setCopied] = useState(false);
  const normalized = useMemo(() => normalizeCode(code), [code]);
  const languageLabel = language || "text";

  const handleCopy = () => {
    navigator.clipboard?.writeText(normalized).catch(() => null);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <div className="md-code-block">
      <div className="md-code-header">
        <span>{languageLabel}</span>
        <button type="button" className="md-copy-button" onClick={handleCopy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="md-code-scroll">
        <Highlight theme={themes.vsDark} code={normalized} language={languageLabel as never}>
          {({ className, style, tokens, getLineProps, getTokenProps }) => (
            <pre className={className} style={style}>
              {tokens.map((line, lineIndex) => (
                <div key={lineIndex} {...getLineProps({ line })}>
                  {line.map((token, tokenIndex) => (
                    <span key={tokenIndex} {...getTokenProps({ token })} />
                  ))}
                </div>
              ))}
            </pre>
          )}
        </Highlight>
      </div>
    </div>
  );
}

export default function MarkdownMessage({ text, preview = false }: MarkdownMessageProps) {
  const normalized = useMemo(() => normalizeMathDelimiters(text), [text]);
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkBreaks]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
          code: ({ className, children }) => {
            const source = String(children || "");
            const language = detectLanguage(className);
            const inlineCode = !language && !source.includes("\n");
            if (inlineCode) {
              return <code className="md-inline-code">{source}</code>;
            }
            if (preview) {
              return (
                <pre className="md-code-preview">
                  <code>{normalizeCode(source)}</code>
                </pre>
              );
            }
            return <CodeFence code={source} language={language} />;
          },
          table: (props) => (
            <div className="md-table-wrap">
              <table {...props} />
            </div>
          )
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}

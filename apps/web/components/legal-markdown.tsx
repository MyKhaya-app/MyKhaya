import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { Schema } from "hast-util-sanitize";

// rehype-sanitize's defaultSchema already follows GitHub's markdown
// sanitisation (no <script>/<style>/<iframe>, no event-handler or `style`
// attributes, no raw HTML passthrough) — the one thing it still allows that
// a legal document never needs is <img>, so a compromised/malicious admin
// account (or a copy-pasted external document) can't smuggle a tracking
// pixel into content that renders on public, unauthenticated pages.
const LEGAL_MARKDOWN_SCHEMA: Schema = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames ?? []).filter((tag) => tag !== "img"),
};

/**
 * Renders legal-document Markdown identically everywhere it appears — PCC's
 * draft editor preview/current/historical version views, and the consumer
 * public legal pages/in-app Legal & Privacy/legal gate. See
 * mykhaya.legal_schemas on the backend for the equivalent "content is
 * always Markdown, never raw HTML" contract. rehype-sanitize strips
 * anything outside LEGAL_MARKDOWN_SCHEMA (scripts, event handlers, iframes,
 * arbitrary HTML) regardless of what the stored content_markdown contains,
 * so this is safe even against a draft nobody has reviewed yet.
 *
 * `className` selects the prose styling to apply — PCC pages pass
 * "cc-legal-prose" (defined in app/control-centre/pcc.css, PCC-scoped),
 * consumer pages pass "legal-prose" (defined in app/styles.css) — never
 * both, since pcc.css's rules are PCC-root-scoped and invisible outside it.
 */
export function LegalMarkdown({ content, className }: { content: string; className: string }) {
  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, LEGAL_MARKDOWN_SCHEMA]]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

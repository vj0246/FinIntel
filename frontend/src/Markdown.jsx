import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Renders the agent's markdown answers (tables, bold, lists, headings) instead of
// dumping raw '**' and '|' as plain text. remark-gfm adds GitHub tables.
export default function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown>
    </div>
  );
}

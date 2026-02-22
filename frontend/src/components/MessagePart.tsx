import type { Part } from "../types";
import ToolPart from "./ToolPart";
import Markdown from "./Markdown";

type MessagePartProps = {
  part: Part;
};

export default function MessagePart({ part }: MessagePartProps) {
  if (part.type === "tool") {
    return <ToolPart part={part} />;
  }
  const text = part.text || "";
  if (!text) return null;
  return <Markdown content={text} />;
}

import type { Question } from "../types";

type QuestionCardProps = {
  question: Question;
  onReply: (id: string, answers: string[][]) => void;
  onReject: (id: string) => void;
};

export default function QuestionCard({ question, onReply, onReject }: QuestionCardProps) {
  const text = question.questions?.[0]?.question || question.id;

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--accent)]/30 bg-[var(--accent-soft)] p-4 my-2">
      <div className="flex items-center gap-2 mb-2">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6.5" />
          <path d="M6 6a2 2 0 113 1.73c-.5.29-1 .77-1 1.27M8 12h.01" />
        </svg>
        <span className="text-[var(--font-size-sm)] font-[var(--font-weight-semibold)] text-[var(--accent-text)]">
          Question
        </span>
      </div>
      <div className="text-[var(--font-size-sm)] text-[var(--text-base)] mb-3">{text}</div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onReply(question.id, [["Yes"]])}
          className="px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-md)]
            bg-[var(--accent)] text-[var(--text-on-accent)] border-none cursor-pointer
            hover:bg-[var(--accent-hover)] transition-colors"
        >
          Yes
        </button>
        <button
          type="button"
          onClick={() => onReject(question.id)}
          className="px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-md)]
            bg-transparent text-[var(--error-text)] border border-[var(--error)]/30 cursor-pointer
            hover:bg-[var(--error-soft)] transition-colors"
        >
          Reject
        </button>
      </div>
    </div>
  );
}

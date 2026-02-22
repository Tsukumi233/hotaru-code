import { useRef, useCallback } from "react";

type ResizeHandleProps = {
  direction: "horizontal" | "vertical";
  onResize: (delta: number) => void;
};

export default function ResizeHandle({ direction, onResize }: ResizeHandleProps) {
  const dragging = useRef(false);
  const lastPos = useRef(0);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      lastPos.current = direction === "horizontal" ? e.clientX : e.clientY;

      const onMouseMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const pos = direction === "horizontal" ? ev.clientX : ev.clientY;
        const delta = pos - lastPos.current;
        lastPos.current = pos;
        onResize(delta);
      };

      const onMouseUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
      document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";
    },
    [direction, onResize],
  );

  return (
    <div
      onMouseDown={onMouseDown}
      className={`flex-shrink-0 bg-transparent hover:bg-[var(--accent)] transition-colors duration-150 group
        ${
          direction === "horizontal"
            ? "w-1 cursor-col-resize hover:w-1"
            : "h-1 cursor-row-resize hover:h-1"
        }`}
    >
      <div
        className={`${
          direction === "horizontal"
            ? "w-px h-full mx-auto bg-[var(--border-base)] group-hover:bg-[var(--accent)]"
            : "h-px w-full my-auto bg-[var(--border-base)] group-hover:bg-[var(--accent)]"
        }`}
      />
    </div>
  );
}

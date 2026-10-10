import type { CSSProperties } from "react";

/** Sets the `--i` custom property that motion.css staggers entrances by. */
export function stagger(index: number): CSSProperties {
  return { "--i": index } as CSSProperties;
}

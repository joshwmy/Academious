import { useEffect, useRef } from "react";

/**
 * Reveal `.reveal` descendants of the returned ref as they scroll into view.
 *
 * The hidden state only applies once this hook has marked the container with
 * `js-reveal`, so content is never invisible to a reader whose browser lacks
 * IntersectionObserver, or before hydration. Each element is revealed once and
 * then left alone; scrolling back up does not replay the animation.
 */
export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    root.classList.add("js-reveal");
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.15 },
    );
    root.querySelectorAll(".reveal").forEach((element) => observer.observe(element));
    return () => {
      observer.disconnect();
      root.classList.remove("js-reveal");
    };
  }, []);

  return ref;
}

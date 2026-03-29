import { useState, useRef, useEffect, type RefObject } from 'react';

/**
 * Detects scroll direction on a scrollable element and returns whether the
 * top bar should be visible. Hides on scroll down, shows on scroll up.
 */
export function useScrollDirection(scrollRef: RefObject<HTMLElement | null>) {
  const [isVisible, setIsVisible] = useState(true);
  const lastScrollTop = useRef(0);
  const ticking = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const handleScroll = () => {
      if (ticking.current) return;
      ticking.current = true;

      requestAnimationFrame(() => {
        const st = el.scrollTop;
        if (st <= 10) {
          setIsVisible(true);
        } else if (st > lastScrollTop.current + 5) {
          setIsVisible(false);
        } else if (st < lastScrollTop.current - 5) {
          setIsVisible(true);
        }
        lastScrollTop.current = st;
        ticking.current = false;
      });
    };

    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [scrollRef]);

  return isVisible;
}

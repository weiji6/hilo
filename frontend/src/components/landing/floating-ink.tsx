"use client";

import { motion, AnimatePresence } from "motion/react";
import { useEffect, useState, useCallback, useRef } from "react";

interface InkDrop {
  id: number;
  x: number;
  y: number;
  size: number;
  duration: number;
}

/**
 * FloatingInk Component
 * Implements a dual-slot ink bleed background effect to ensure a strict limit
 * of one drop on the left and one on the right, preventing any accidental multiplication.
 */
export function FloatingInk() {
  const [currentDrop, setCurrentDrop] = useState<InkDrop | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const generateDrop = useCallback((side: "left" | "right"): InkDrop => {
    return {
      id: Date.now() + Math.random(),
      // Strictly constrained to their respective sides
      x: side === "left" ? Math.random() * 25 : 75 + Math.random() * 25,
      // Positioned in the upper half
      y: Math.random() * 50,
      size: Math.random() * 200 + 600,
      // Randomized duration for more organic feel (15-25s)
      duration: 15 + Math.random() * 5,
    };
  }, []);

  const triggerNext = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    
    // Clear the current drop to signify the end of the previous one
    setCurrentDrop(null);

    // Wait for a random interval before starting the next one (1s to 4s)
    const delay = Math.random() * 3000 + 1000;
    timeoutRef.current = setTimeout(() => {
      // Randomly pick a side for the next drop
      const side = Math.random() > 0.5 ? "left" : "right";
      setCurrentDrop(generateDrop(side));
    }, delay);
  }, [generateDrop]);

  useEffect(() => {
    // Start the first drop immediately (random side)
    const initialSide = Math.random() > 0.5 ? "left" : "right";
    setCurrentDrop(generateDrop(initialSide));

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [generateDrop]);

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none select-none z-0">
      {/* SVG Filter for Organic Ink Bleeding (墨染) */}
      <svg className="absolute h-0 w-0">
        <defs>
          <filter id="ink-bleed-filter">
            <feTurbulence 
              type="fractalNoise" 
              baseFrequency="0.04" 
              numOctaves="4" 
              result="noise" 
              seed="15"
            />
            <feDisplacementMap 
              in="SourceGraphic" 
              in2="noise" 
              scale="90" 
              xChannelSelector="R" 
              yChannelSelector="G" 
            />
            <feGaussianBlur stdDeviation="15" />
          </filter>
        </defs>
      </svg>

      <div className="relative h-full w-full" style={{ filter: "url(#ink-bleed-filter)" }}>
        <AnimatePresence mode="wait">
          {currentDrop && (
            <motion.div
              key={currentDrop.id}
              className="absolute rounded-full mix-blend-multiply"
              initial={{ 
                left: `${currentDrop.x}%`, 
                top: `${currentDrop.y}%`, 
                scale: 0.1, 
                opacity: 0,
                translateX: "-50%",
                translateY: "-50%"
              }}
              animate={{ 
                scale: [0.1, 1.2], 
                opacity: [0, 0.9, 0.4, 0], 
              }}
              exit={{ opacity: 0 }}
              onAnimationComplete={triggerNext}
              transition={{
                duration: currentDrop.duration,
                ease: "easeOut",
                times: [0, 0.05, 0.4, 1],
              }}
              style={{
                width: currentDrop.size,
                height: currentDrop.size,
                background: "radial-gradient(circle, rgba(126,51,46,0.8) 0%, rgba(126,51,46,0.4) 40%, rgba(126,51,46,0.1) 70%, transparent 100%)"
              }}
            />
          )}
        </AnimatePresence>
      </div>

      {/* Rice paper texture and subtle atmospheric wash */}
      <div className="absolute inset-0 opacity-[0.06] bg-[url('https://www.transparenttextures.com/patterns/natural-paper.png')]" />
      <div className="absolute inset-0 bg-linear-to-b from-primary/[0.02] to-transparent" />
    </div>
  );
}

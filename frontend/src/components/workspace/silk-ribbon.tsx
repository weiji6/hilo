"use client";

import { motion } from "motion/react";

export function SilkRibbon() {
  const waveLayers = [
    {
      id: "wave-surface-1",
      duration: 60,
      opacity: 0.15,
      blur: "blur(40px)",
      path: "M0 40 Q 250 -10, 500 40 T 1000 40 L 1000 120 L 0 120 Z",
      fill: "#7e332e",
    },
    {
      id: "wave-surface-2",
      duration: 45,
      opacity: 0.25,
      blur: "blur(32px)",
      path: "M0 55 Q 250 100, 500 55 T 1000 55 L 1000 120 L 0 120 Z",
      fill: "#7e332e",
    },
    {
      id: "wave-surface-3",
      duration: 30,
      opacity: 0.4,
      blur: "blur(20px)",
      path: "M0 70 Q 250 20, 500 70 T 1000 70 L 1000 120 L 0 120 Z",
      fill: "#7e332e",
    },
    {
      id: "wave-surface-4",
      duration: 20,
      opacity: 0.6,
      blur: "blur(12px)",
      path: "M0 85 Q 500 50, 1000 85 L 1000 120 L 0 120 Z",
      fill: "#7e332e",
    },
    {
      id: "wave-surface-5",
      duration: 12,
      opacity: 0.8,
      blur: "blur(8px)",
      path: "M0 100 Q 250 125, 500 100 T 1000 100 L 1000 120 L 0 120 Z",
      fill: "#7e332e",
    },
  ];

  return (
    <div 
      className="absolute inset-x-0 bottom-0 h-[40vh] overflow-hidden pointer-events-none select-none transition-all duration-1000"
      style={{
        maskImage: "linear-gradient(to top, rgba(0,0,0,1) 0%, rgba(0,0,0,0.8) 40%, rgba(0,0,0,0.4) 70%, rgba(0,0,0,0) 100%)",
        WebkitMaskImage: "linear-gradient(to top, rgba(0,0,0,1) 0%, rgba(0,0,0,0.8) 40%, rgba(0,0,0,0.4) 70%, rgba(0,0,0,0) 100%)",
      }}
    >
      <div className="relative h-full w-full">
        {waveLayers.map((layer) => (
          <motion.div
            key={layer.id}
            animate={{ x: ["-50%", "0%"] }}
            transition={{ duration: layer.duration, repeat: Infinity, ease: "linear" }}
            className="absolute inset-0 flex w-[200%]"
            style={{ filter: layer.blur }}
          >
            {[...Array(2)].map((_, i) => (
              <svg 
                key={i} 
                className="h-full w-full" 
                viewBox="0 0 1000 120" 
                preserveAspectRatio="none"
              >
                <path
                  d={layer.path}
                  fill={layer.fill}
                  opacity={layer.opacity}
                />
              </svg>
            ))}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

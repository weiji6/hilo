"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { motion, type Variants } from "motion/react";

import { Button } from "@/components/ui/button";
import { SilkRibbon } from "@/components/workspace/silk-ribbon";
import { FloatingInk } from "@/components/landing/floating-ink";
import { cn } from "@/lib/utils";

export function Hero({ className }: { className?: string }) {
  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.3,
      },
    },
  };

  const itemVariants: Variants = {
    hidden: { opacity: 0, filter: "blur(10px)", y: 20 },
    visible: {
      opacity: 1,
      filter: "blur(0px)",
      y: 0,
      transition: { duration: 1.2, ease: [0.22, 1, 0.36, 1] as const },
    },
  };

  return (
    <div
      className={cn(
        "relative flex h-screen w-full flex-col items-center justify-center overflow-hidden bg-background",
        className,
      )}
    >
      {/* Background decoration - optional subtle gradient or just clean */}
      <FloatingInk />
      
      {/* Top Decoration to balance weight */}
      <div className="absolute top-24 right-16 z-10 hidden md:block opacity-[0.15] select-none pointer-events-none">
        <div className="flex flex-col items-center gap-6">
          <div className="h-32 w-px bg-primary/40" />
          <span className="font-serif text-sm tracking-[0.5em] text-primary [writing-mode:vertical-rl] whitespace-nowrap translate-x-[2px]">
            知识检索 · 证据溯源
          </span>
        </div>
      </div>

      {/* Main Content Container */}
      <motion.div 
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="container relative z-10 mx-auto flex -translate-y-16 flex-col items-center px-6 text-center"
      >
        <motion.div variants={itemVariants} className="space-y-8">
          <h1 className="font-serif text-6xl font-bold tracking-[0.1em] text-foreground md:text-[5rem]">
            Hilo <br />
            <span className="text-primary opacity-90">让知识成为线索</span>
          </h1>
          
          <div className="mx-auto h-px w-24 bg-primary/30" />
        </motion.div>

        <motion.div variants={itemVariants} className="pt-12">
          <Link href="/workspace">
            <Button
              className={cn(
                "group relative min-w-[220px] overflow-visible rounded-none border border-primary/20",
                "bg-[url('https://www.transparenttextures.com/patterns/natural-paper.png')] bg-white/60",
                "px-10 py-6 font-serif text-xl text-primary backdrop-blur-sm transition-all duration-500",
                "hover:bg-primary/95 hover:text-white hover:border-primary shadow-sm hover:shadow-lg"
              )}
              size="lg"
            >
              <span className="relative z-10 font-bold tracking-[0.3em] pr-[0.3em]">
                开始探索
              </span>
              
              {/* Side Rectangles Decoration - Centered on borders */}
              <div className="absolute -left-[3px] top-1/2 -translate-y-1/2 w-[6px] h-5 bg-primary/60 group-hover:bg-white group-hover:h-7 transition-all duration-300" />
              <div className="absolute -right-[3px] top-1/2 -translate-y-1/2 w-[6px] h-5 bg-primary/60 group-hover:bg-white group-hover:h-7 transition-all duration-300" />

              {/* Inner paper glow on hover */}
              <div className="absolute inset-0 opacity-0 group-hover:opacity-20 shadow-[inset_0_0_20px_rgba(255,255,255,0.8)] transition-opacity" />
            </Button>
          </Link>
        </motion.div>
      </motion.div>

      {/* Unified Silk Ribbon Footer Decoration */}
      <SilkRibbon />
    </div>
  );
}

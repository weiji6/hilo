"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Header() {
  return (
    <motion.header 
      initial={{ y: -100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
      className="fixed top-0 right-0 left-0 z-50 flex h-16 items-center justify-between px-8 md:px-16 bg-white/40 backdrop-blur-md border-b border-primary/5"
    >
      <div className="flex items-center h-full">
        <Link href="/" className="h-full flex items-center">
          {/* Logo container: Rectangular shape with "Red Mud" background */}
          <div className="flex h-10 w-32 items-center justify-center bg-[#9c2c23] shadow-md transition-transform hover:scale-105 active:scale-95 px-4">
            <span className="text-xl font-semibold tracking-widest text-white">Hilo</span>
          </div>
        </Link>
      </div>
      
      <div className="flex items-center">
        <Button 
          asChild 
          variant="ghost" 
          className="rounded-none border border-primary/20 font-serif text-[11px] tracking-[0.2em] text-primary hover:bg-primary hover:text-white transition-all px-6 h-9 shadow-sm"
        >
          <Link href="/auth">登录 / 加入</Link>
        </Button>
      </div>
    </motion.header>
  );
}

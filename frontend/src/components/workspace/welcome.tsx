"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { AgentScenario, AgentTier } from "@/core/settings/local";
import { cn } from "@/lib/utils";

import { motion, type Variants } from "motion/react";

let waved = false;

export function Welcome({
  className,
}: {
  className?: string;
  scenario?: AgentScenario;
  tier?: AgentTier;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();

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
    hidden: { opacity: 0, filter: "blur(10px)", y: 15 },
    visible: {
      opacity: 1,
      filter: "blur(0px)",
      y: 0,
      transition: { duration: 1.5, ease: [0.22, 1, 0.36, 1] as const },
    },
  };

  const strokeVariants: Variants = {
    hidden: { width: 0, opacity: 0 },
    visible: {
      width: 96,
      opacity: 0.2,
      transition: { duration: 1.2, ease: "easeInOut" as const, delay: 0.5 },
    },
  };

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-6 px-8 py-12 text-center relative",
        className,
      )}
    >
      <div className="flex flex-col items-center gap-4">
        <motion.h1 
          variants={itemVariants}
          className="font-serif text-4xl font-bold tracking-[0.15em] text-primary"
        >
          {searchParams.get("mode") === "skill" ? (
            t.welcome.createYourOwnSkill
          ) : (
            t.welcome.greeting
          )}
        </motion.h1>
        <motion.div 
          variants={strokeVariants}
          className="h-px bg-primary" 
        />
      </div>

      <motion.div 
        variants={itemVariants}
        className="max-w-2xl"
      >
        {searchParams.get("mode") === "skill" ? (
          <div className="font-serif text-lg leading-relaxed text-slate-600/90">
            {t.welcome.createYourOwnSkillDescription.includes("\n") ? (
              <pre className="whitespace-pre-wrap font-serif">
                {t.welcome.createYourOwnSkillDescription}
              </pre>
            ) : (
              <p>{t.welcome.createYourOwnSkillDescription}</p>
            )}
          </div>
        ) : (
          <div className="font-serif text-lg leading-relaxed text-slate-600/90">
            {t.welcome.description.includes("\n") ? (
              <pre className="whitespace-pre-wrap font-serif">
                {t.welcome.description}
              </pre>
            ) : (
              <p>{t.welcome.description}</p>
            )}
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

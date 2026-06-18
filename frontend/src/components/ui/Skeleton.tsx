import * as React from "react"
import { cn } from "@/lib/utils"

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "text" | "circular" | "rectangular"
}

function Skeleton({ className, variant = "rectangular", ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse bg-surface-raised",
        variant === "circular"    ? "rounded-full" :
        variant === "text"        ? "h-4 rounded" :
                                    "rounded-md",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }

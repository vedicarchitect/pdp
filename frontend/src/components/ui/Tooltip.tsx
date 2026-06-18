import * as React from "react"
import { cn } from "@/lib/utils"

export interface TooltipProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'content'> {
  content: React.ReactNode;
  children: React.ReactNode;
  placement?: 'top' | 'bottom' | 'left' | 'right';
}

export const Tooltip = ({ content, children, placement = 'top', className, ...props }: TooltipProps) => {
  const placementClasses = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  }

  return (
    <div className={cn("group relative inline-block", className)} {...props}>
      {children}
      <div className={cn(
        "pointer-events-none absolute z-tooltip whitespace-nowrap rounded bg-surface-raised px-2 py-1 text-xs text-text-main opacity-0 transition-opacity group-hover:opacity-100 border border-surface-border",
        placementClasses[placement]
      )}>
        {content}
      </div>
    </div>
  )
}

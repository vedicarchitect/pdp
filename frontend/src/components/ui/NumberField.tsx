import * as React from "react"
import { cn } from "@/lib/utils"

export interface NumberFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean;
}

const NumberField = React.forwardRef<HTMLInputElement, NumberFieldProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <input
        type="number"
        className={cn(
          "flex h-9 w-full rounded-md border bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-text-muted focus-visible:outline-none focus-visible:ring-1 disabled:cursor-not-allowed disabled:opacity-50",
          error ? "border-bearish focus-visible:ring-bearish" : "border-surface-border focus-visible:ring-primary",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
NumberField.displayName = "NumberField"

export { NumberField }

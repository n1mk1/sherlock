// Buttons: pill-shaped. Primary is solid ink, secondary a soft fill, ghost only on hover; the tinted
// variants carry a hue for an area's own action (violet for AI cleaning).
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full text-[14px] font-medium tracking-[-0.005em] " +
    "transition-[background-color,color,opacity,transform] duration-[var(--duration-fast)] ease-[var(--ease)] active:scale-[0.98] " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring " +
    "disabled:opacity-40 disabled:cursor-default disabled:active:scale-100 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:opacity-90",
        secondary: "bg-secondary text-foreground hover:bg-[color-mix(in_srgb,var(--foreground)_9%,transparent)]",
        ghost: "text-foreground hover:bg-secondary",
        destructive: "text-red hover:bg-red-soft",
        violet: "bg-violet-soft text-violet-ink hover:bg-[color-mix(in_srgb,var(--violet)_18%,transparent)]",
        ai: "bg-violet text-primary-foreground hover:opacity-90",
        link: "text-accent underline-offset-4 hover:underline px-0 h-auto active:scale-100",
      },
      size: {
        default: "h-9 px-4",
        sm: "h-8 px-3 text-[13px]",
        icon: "size-8",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        {...props}
      >
        {asChild ? (
          children
        ) : (
          <>
            {loading && <Loader2 className="animate-spin" aria-hidden />}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

/** A round icon-only button for toolbars and headers; the label is its name and tooltip. */
export const IconButton = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }>(
  ({ label, className, children, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        "relative inline-flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors duration-[var(--duration-fast)]",
        "hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring data-[state=open]:bg-secondary data-[state=open]:text-foreground",
        "[&_svg]:size-4 [&_svg]:shrink-0",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  ),
);
IconButton.displayName = "IconButton";

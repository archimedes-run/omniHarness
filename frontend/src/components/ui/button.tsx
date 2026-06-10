import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default: "cursor-pointer bg-black text-white hover:bg-black/90",
        destructive:
          "cursor-pointer bg-destructive text-white hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "cursor-pointer border border-black bg-black text-white shadow-xs hover:bg-black/90 hover:text-white dark:border-black dark:bg-black",
        secondary: "cursor-pointer bg-black text-white hover:bg-black/90",
        ghost:
          "cursor-pointer text-black hover:bg-black hover:text-white dark:text-black dark:hover:bg-black dark:hover:text-white",
        link: "cursor-pointer text-black underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

const submitButtonClasses =
  "border-black bg-black text-white hover:bg-black/90 hover:text-white active:translate-y-px active:scale-[0.985] disabled:border-black disabled:bg-black disabled:text-white";

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";
  const isSubmitButton = props.type === "submit";

  return (
    <Comp
      data-slot="button"
      {...(variant !== undefined && { "data-variant": variant })}
      {...(size !== undefined && { "data-size": size })}
      className={cn(
        buttonVariants({ variant, size }),
        isSubmitButton && submitButtonClasses,
        className,
      )}
      {...props}
    />
  );
}

export { Button, buttonVariants };

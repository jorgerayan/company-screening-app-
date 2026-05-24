import { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type BadgeVariant = "gray" | "green" | "yellow" | "red" | "blue" | "purple";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({
  variant = "gray",
  className,
  children,
  ...props
}: BadgeProps) {
  const variants: Record<BadgeVariant, string> = {
    gray: "bg-gray-100 text-gray-700",
    green: "bg-green-50 text-green-700",
    yellow: "bg-yellow-50 text-yellow-700",
    red: "bg-red-50 text-red-700",
    blue: "bg-blue-50 text-blue-700",
    purple: "bg-purple-50 text-purple-700",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}

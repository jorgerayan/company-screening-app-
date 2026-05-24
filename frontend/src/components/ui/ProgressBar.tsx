import { cn } from "@/lib/utils";

interface ProgressBarProps {
  value: number; // 0–100
  showLabel?: boolean;
  className?: string;
}

export function ProgressBar({
  value,
  showLabel = false,
  className,
}: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value));

  return (
    <div className={cn("w-full", className)}>
      {showLabel && (
        <div className="flex justify-end mb-1">
          <span className="text-xs text-gray-400">{clamped}%</span>
        </div>
      )}
      <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-gray-900 rounded-full transition-all duration-700 ease-in-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

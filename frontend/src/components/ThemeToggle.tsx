import { Moon, Sun } from "lucide-react";
import { cn } from "../lib/cn";
import { useTheme } from "../lib/theme";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label={dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"}
      title={dark ? "Giao diện tối" : "Giao diện sáng"}
      onClick={toggleTheme}
      className={cn(
        "inline-flex h-11 w-[4.75rem] shrink-0 items-center rounded-xl border border-border bg-muted p-1 transition hover:border-accent/30",
        className,
      )}
    >
      <span
        className={cn(
          "flex h-full flex-1 items-center justify-center rounded-lg transition",
          dark ? "text-muted-foreground" : "bg-card text-accent shadow-sm",
        )}
      >
        <Sun className="h-4 w-4" />
      </span>
      <span
        className={cn(
          "flex h-full flex-1 items-center justify-center rounded-lg transition",
          dark ? "bg-card text-accent shadow-sm" : "text-muted-foreground",
        )}
      >
        <Moon className="h-4 w-4" />
      </span>
    </button>
  );
}

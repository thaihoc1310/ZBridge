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
        "relative inline-flex h-9 w-[3.25rem] shrink-0 items-center rounded-full border border-border bg-muted p-0.5 transition hover:border-accent/40",
        className,
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-7 w-7 rounded-full bg-card shadow-sm ring-1 ring-border transition-transform",
          dark ? "translate-x-[1.35rem]" : "translate-x-0",
        )}
      />
      <span className="relative z-10 flex w-full items-center justify-between px-1.5">
        <Sun className={cn("h-3.5 w-3.5", dark ? "text-muted-foreground" : "text-accent")} />
        <Moon className={cn("h-3.5 w-3.5", dark ? "text-accent" : "text-muted-foreground")} />
      </span>
    </button>
  );
}

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./Button";
import { cn } from "../../lib/cn";

type Props = {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
};

export function Modal({ open, onClose, title, description, children, className }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onMouseDown={(event) => event.target === event.currentTarget && onClose()}
        >
          <motion.section
            role="dialog" aria-modal="true" aria-label={title}
            initial={{ opacity: 0, y: 24, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: .98 }}
            transition={{ duration: .22 }}
            className={cn("app-scrollbar max-h-[90vh] w-full max-w-xl overflow-auto rounded-2xl border border-white/40 bg-white p-6 shadow-2xl sm:p-8", className)}
          >
            <div className="mb-6 flex items-start justify-between gap-6">
              <div>
                {title && <h2 className="font-display text-2xl text-foreground">{title}</h2>}
                {description && <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{description}</p>}
              </div>
              <Button variant="ghost" className="-mr-2 -mt-2 h-11 w-11 shrink-0 p-0" onClick={onClose} aria-label="Đóng">
                <X className="h-5 w-5" />
              </Button>
            </div>
            {children}
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

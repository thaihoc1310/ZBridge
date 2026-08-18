import { AnimatePresence, motion } from "framer-motion";
import { LoaderCircle } from "lucide-react";

export function LoadingOverlay({ show, label = "Đang xử lý..." }: { show: boolean; label?: string }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div className="fixed inset-0 z-[70] flex flex-col items-center justify-center bg-slate-950/60 text-white backdrop-blur-md" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="relative mb-5 flex h-20 w-20 items-center justify-center rounded-3xl bg-white/10 shadow-2xl ring-1 ring-white/20">
            <div className="absolute inset-2 animate-spin-slow rounded-full border border-dashed border-blue-300/50" />
            <LoaderCircle className="h-8 w-8 animate-spin text-blue-300" />
          </div>
          <p className="font-medium">{label}</p>
          <p className="mt-1 text-sm text-slate-300">Vui lòng không đóng trang</p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}


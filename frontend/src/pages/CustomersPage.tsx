import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, Filter, RefreshCw, Search, SlidersHorizontal, UsersRound, X } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, queryString } from "../api/client";
import type { Customer, CustomerList, SyncResult } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/Button";
import { DebtConfirmModal, DebtStatusOptions, DebtFileEditorModal, NoteEditorModal, type DebtConfirmation } from "../features/customers/CustomerFields";
import { formatDate, initials } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

type CustomerColumn = "customer" | "debtFile" | "debt" | "lastPaid" | "note";

const COLUMN_WIDTH_STORAGE_KEY = "zbridge:customer-column-widths:v1";
const DEFAULT_COLUMN_WIDTHS: Record<CustomerColumn, number> = {
  customer: 360,
  debtFile: 200,
  debt: 230,
  lastPaid: 170,
  note: 220,
};
const MIN_COLUMN_WIDTHS: Record<CustomerColumn, number> = {
  customer: 220,
  debtFile: 150,
  debt: 220,
  lastPaid: 145,
  note: 160,
};

function initialColumnWidths(): Record<CustomerColumn, number> {
  try {
    const stored = JSON.parse(localStorage.getItem(COLUMN_WIDTH_STORAGE_KEY) ?? "null") as
      | Partial<Record<CustomerColumn, number>>
      | null;
    if (!stored) return DEFAULT_COLUMN_WIDTHS;
    return Object.fromEntries(
      (Object.keys(DEFAULT_COLUMN_WIDTHS) as CustomerColumn[]).map((column) => [
        column,
        Math.max(
          MIN_COLUMN_WIDTHS[column],
          Number(stored[column]) || DEFAULT_COLUMN_WIDTHS[column],
        ),
      ]),
    ) as Record<CustomerColumn, number>;
  } catch {
    return DEFAULT_COLUMN_WIDTHS;
  }
}

export function CustomersPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [debt, setDebt] = useState("");
  // Groups the bot lost access to are hidden by default; they are still
  // reachable through the filter so nobody has to wonder where they went.
  const [availability, setAvailability] = useState("available");
  const [page, setPage] = useState(1);
  const [filterOpen, setFilterOpen] = useState(false);
  const [noteCustomer, setNoteCustomer] = useState<Customer | null>(null);
  const [debtFileCustomer, setDebtFileCustomer] = useState<Customer | null>(null);
  const [debtConfirmation, setDebtConfirmation] = useState<DebtConfirmation | null>(null);
  const [columnWidths, setColumnWidths] = useState(initialColumnWidths);
  const didAutoSync = useRef(false);
  const stopColumnResize = useRef<(() => void) | null>(null);
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const canSync = can(PERMISSIONS.customerSync);
  const canUpdate = can(PERMISSIONS.customerUpdate);
  const customers = useQuery({
    queryKey: ["customers", debouncedSearch, debt, availability, page],
    queryFn: () => api<CustomerList>(`/customers${queryString({ search: debouncedSearch, debt, availability, page, limit: 25 })}`),
    placeholderData: (previousData) => previousData,
  });
  const sync = useMutation({
    mutationFn: () => api<SyncResult>("/customers/sync", { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["customers"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["bot"] });
    },
  });

  useEffect(() => {
    if (!canSync || didAutoSync.current) return;
    didAutoSync.current = true;
    sync.mutate();
    // Auto-sync only once when entering the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canSync]);
  useEffect(() => { const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250); return () => window.clearTimeout(timer); }, [search]);
  useEffect(() => setPage(1), [debouncedSearch, debt, availability]);
  useEffect(() => {
    localStorage.setItem(COLUMN_WIDTH_STORAGE_KEY, JSON.stringify(columnWidths));
  }, [columnWidths]);
  useEffect(() => () => stopColumnResize.current?.(), []);

  const beginColumnResize = (
    column: CustomerColumn,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    stopColumnResize.current?.();
    const startX = event.clientX;
    const startWidth = columnWidths[column];
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const onMove = (moveEvent: PointerEvent) => {
      const width = Math.min(
        720,
        Math.max(MIN_COLUMN_WIDTHS[column], startWidth + moveEvent.clientX - startX),
      );
      setColumnWidths((current) => ({ ...current, [column]: width }));
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      stopColumnResize.current = null;
    };
    stopColumnResize.current = cleanup;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  };
  const tableMinWidth =
    Object.values(columnWidths).reduce((total, width) => total + width, 0) + 48;

  return <div className="mx-auto max-w-[1600px]">
    <PageHeader eyebrow="Customer directory" title="Khách" highlight="hàng" description="Quản lý công nợ, hồ sơ Drive và các tự động hóa theo từng khách hàng Zalo." action={canSync ? <Button variant="secondary" className="h-11 w-11 p-0" aria-label="Đồng bộ khách hàng" title="Đồng bộ khách hàng từ Zalo" disabled={sync.isPending} onClick={() => sync.mutate()}><RefreshCw className={`h-4 w-4 ${sync.isPending ? "animate-spin" : ""}`} /></Button> : undefined} />

    {sync.isError && <div className="mb-5 rounded-xl border border-warning-border bg-warning-bg p-4 text-sm text-warning-fg" role="alert">Không đồng bộ được danh sách từ Zalo: {sync.error instanceof ApiError ? sync.error.message : "lỗi không xác định"}. Danh sách bên dưới là dữ liệu đã lưu gần nhất.</div>}

    <section className="card overflow-visible">
      <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full max-w-xl"><Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><input className="field pl-11" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm theo tên khách hàng hoặc ghi chú..." aria-label="Tìm khách hàng" />{search && <button onClick={() => setSearch("")} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-muted-foreground hover:bg-muted" aria-label="Xóa tìm kiếm"><X className="h-4 w-4" /></button>}</div>
        <div className="relative">
          <Button variant="secondary" onClick={() => setFilterOpen((open) => !open)}><Filter className="h-4 w-4" />Bộ lọc{(debt || availability !== "available") && <span className="h-2 w-2 rounded-full bg-accent" />}</Button>
          {filterOpen && <div className="absolute right-0 top-14 z-20 w-72 rounded-2xl border border-border bg-card p-5 shadow-2xl">
            <div className="flex items-center justify-between"><p className="text-sm font-semibold">Lọc khách hàng</p><SlidersHorizontal className="h-4 w-4 text-accent" /></div>
            <fieldset className="mt-4 space-y-2"><legend className="mb-2 text-xs font-medium text-muted-foreground">Công nợ</legend>{[["", "Tất cả"], ["owed", "Còn nợ"], ["clear", "Đã thanh toán"]].map(([value, label]) => <label key={value} className="flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 text-sm hover:bg-muted"><input type="radio" name="debt" value={value} checked={debt === value} onChange={() => setDebt(value)} className="h-4 w-4 accent-accent" />{label}</label>)}</fieldset>
            <fieldset className="mt-4 space-y-2"><legend className="mb-2 text-xs font-medium text-muted-foreground">Trạng thái nhóm</legend>{[["available", "Khả dụng"], ["unavailable", "Không khả dụng"], ["all", "Tất cả"]].map(([value, label]) => <label key={value} className="flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 text-sm hover:bg-muted"><input type="radio" name="availability" value={value} checked={availability === value} onChange={() => setAvailability(value)} className="h-4 w-4 accent-accent" />{label}</label>)}</fieldset>
            <Button variant="ghost" className="mt-3 w-full" onClick={() => { setDebt(""); setAvailability("available"); setFilterOpen(false); }}>Đặt lại bộ lọc</Button>
          </div>}
        </div>
      </div>

      <div className="app-scrollbar overflow-x-auto">
        <table
          className="w-full table-fixed border-collapse text-left"
          style={{ minWidth: tableMinWidth }}
        >
          <colgroup>
            <col style={{ width: columnWidths.customer }} />
            <col style={{ width: columnWidths.debtFile }} />
            <col style={{ width: columnWidths.debt }} />
            <col style={{ width: columnWidths.lastPaid }} />
            <col style={{ width: columnWidths.note }} />
            <col style={{ width: 48 }} />
          </colgroup>
          <thead><tr className="border-b border-border bg-muted/50 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {([
              ["customer", "Khách hàng", "px-6"],
              ["debtFile", "File công nợ", "px-5"],
              ["debt", "Công nợ", "px-5"],
              ["lastPaid", "Trả nợ gần nhất", "px-5"],
              ["note", "Ghi chú", "px-5"],
            ] as const).map(([column, label, padding]) => (
              <th key={column} className={`relative py-4 font-medium ${padding}`}>
                {label}
                <button
                  type="button"
                  className="group/resize absolute -right-1 top-0 z-10 flex h-full w-3 touch-none cursor-col-resize items-center justify-center"
                  aria-label={`Kéo để đổi độ rộng cột ${label}`}
                  title="Kéo để đổi độ rộng · nhấp đúp để đặt lại"
                  onPointerDown={(event) => beginColumnResize(column, event)}
                  onDoubleClick={() =>
                    setColumnWidths((current) => ({
                      ...current,
                      [column]: DEFAULT_COLUMN_WIDTHS[column],
                    }))
                  }
                >
                  <span className="h-5/6 w-px bg-border transition group-hover/resize:bg-accent" />
                </button>
              </th>
            ))}
            <th />
          </tr></thead>
          <tbody>
            {customers.isLoading && <tr><td colSpan={6} className="px-6 py-14 text-center text-sm text-muted-foreground"><RefreshCw className="mx-auto mb-3 h-5 w-5 animate-spin text-accent" />Đang tải danh sách khách hàng...</td></tr>}
            {customers.data?.items.map((customer) => <tr key={customer.id} className="group border-b border-border transition-colors last:border-0 hover:bg-accent-soft/50">
              <td className="px-6 py-4"><Link to={`/customers/${customer.id}`} className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-accent-soft to-accent/20 text-xs font-bold text-accent">{customer.avatar_url ? <img src={customer.avatar_url} alt="" className="h-full w-full object-cover" /> : initials(customer.name)}</span><span className="truncate font-semibold text-foreground transition group-hover:text-accent">{customer.name}</span></Link></td>
              <td className="px-5 py-4">{customer.debt_file_url ? <a href={customer.debt_file_url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1.5 text-sm font-medium text-accent underline decoration-accent/45 underline-offset-4 transition hover:decoration-accent"><span className="truncate">Mở file công nợ</span><ExternalLink className="h-3.5 w-3.5 shrink-0" /></a> : canUpdate ? <button className="text-sm italic text-muted-foreground/70 transition hover:text-accent" onClick={() => setDebtFileCustomer(customer)}>+ Thêm file công nợ</button> : <span className="text-sm text-muted-foreground/70">—</span>}</td>
              <td className="px-5 py-4"><DebtStatusOptions value={customer.has_debt} disabled={!canUpdate} onChange={(nextValue) => setDebtConfirmation({ customer, nextValue })} /></td>
              <td className="whitespace-nowrap px-5 py-4 text-sm text-muted-foreground">{customer.last_debt_paid_at ? formatDate(customer.last_debt_paid_at) : <span className="sr-only">Chưa có ngày trả nợ</span>}</td>
              <td className="px-5 py-4"><button className={`block max-w-full text-left text-sm transition hover:text-accent ${customer.note ? "text-foreground" : "italic text-muted-foreground/70"}`} onClick={() => setNoteCustomer(customer)}>{customer.note ? customer.note.length > 48 ? "Xem chi tiết" : <span className="block truncate">{customer.note}</span> : "+ Thêm ghi chú"}</button></td>
              <td className="pr-5"><Link to={`/customers/${customer.id}`} aria-label={`Mở ${customer.name}`}><ChevronRight className="h-5 w-5 text-muted-foreground transition group-hover:translate-x-1 group-hover:text-accent" /></Link></td>
            </tr>)}
          </tbody>
        </table>
        {!customers.isLoading && customers.data?.items.length === 0 && <div className="flex flex-col items-center px-6 py-16 text-center"><span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted"><UsersRound className="h-7 w-7 text-muted-foreground" /></span><h3 className="mt-5 font-semibold">Không tìm thấy khách hàng</h3><p className="mt-1 text-sm text-muted-foreground">Thử đổi từ khóa, bộ lọc hoặc đồng bộ lại danh sách.</p></div>}
      </div>
      <footer className="flex flex-col gap-3 border-t border-border px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between"><p className="text-muted-foreground">Hiển thị <strong className="text-foreground">{customers.data?.items.length ?? 0}</strong> / {customers.data?.total ?? 0} khách hàng</p><div className="flex items-center gap-2"><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} aria-label="Trang trước"><ChevronLeft className="h-4 w-4" /></Button><span className="min-w-24 text-center text-xs">Trang {page} / {customers.data?.pages ?? 1}</span><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page >= (customers.data?.pages ?? 1)} onClick={() => setPage((value) => value + 1)} aria-label="Trang sau"><ChevronRight className="h-4 w-4" /></Button></div></footer>
    </section>

    <NoteEditorModal customer={noteCustomer} onClose={() => setNoteCustomer(null)} />
    <DebtFileEditorModal customer={debtFileCustomer} onClose={() => setDebtFileCustomer(null)} />
    <DebtConfirmModal confirmation={debtConfirmation} onClose={() => setDebtConfirmation(null)} />
  </div>;
}

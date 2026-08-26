import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  FileSpreadsheet,
  Folder,
  FolderPlus,
  LogIn,
  LoaderCircle,
  Trash2,
  Unplug,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  DriveConversionItem,
  DriveConversionJob,
  DriveFolder,
  GoogleOAuthStart,
  GoogleOAuthStatus,
} from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

const MAX_XLSX_BYTES = 25 * 1024 * 1024;

export function DriveConverterPanel() {
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleteOriginals, setDeleteOriginals] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("message"),
  );
  const oauth = useQuery({
    queryKey: ["google-oauth-status"],
    queryFn: () => api<GoogleOAuthStatus>("/tools/google/oauth/status"),
  });
  const folders = useQuery({
    queryKey: ["drive-conversion-folders"],
    queryFn: () => api<DriveFolder[]>("/tools/drive/folders"),
    enabled: oauth.data?.connected === true,
  });
  const job = useQuery({
    queryKey: ["drive-conversion-job", jobId],
    queryFn: () => api<DriveConversionJob>(`/tools/drive/jobs/${jobId}`),
    enabled: Boolean(jobId) && oauth.data?.connected === true,
    refetchInterval: (query) =>
      ["SCANNING", "QUEUED", "PROCESSING"].includes(
        query.state.data?.status ?? "",
      )
        ? 2000
        : false,
  });
  useEffect(() => {
    if (job.data?.status !== "READY" || selected.size) return;
    setSelected(
      new Set(
        job.data.items
          .filter(
            (item) =>
              item.can_download &&
              (!deleteOriginals || item.can_trash) &&
              (item.size_bytes == null || item.size_bytes <= MAX_XLSX_BYTES),
          )
          .map((item) => item.id),
      ),
    );
    setExpanded(
      new Set(job.data.items.map((item) => item.relative_path || "/")),
    );
  }, [job.data, deleteOriginals, selected.size]);
  const add = useMutation({
    mutationFn: () =>
      api<DriveFolder>("/tools/drive/folders", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    onSuccess: () => {
      setAddOpen(false);
      setUrl("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["drive-conversion-folders"] });
    },
    onError: (err) =>
      setError(
        err instanceof ApiError ? err.message : "Không kiểm tra được folder.",
      ),
  });
  const connect = useMutation({
    mutationFn: () =>
      api<GoogleOAuthStart>("/tools/google/oauth/start", { method: "POST" }),
    onSuccess: (data) => window.location.assign(data.authorization_url),
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Không bắt đầu được kết nối Google.",
      ),
  });
  const disconnect = useMutation({
    mutationFn: () =>
      api<void>("/tools/google/oauth", { method: "DELETE" }),
    onSuccess: () => {
      setJobId(null);
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["google-oauth-status"] });
      queryClient.removeQueries({ queryKey: ["drive-conversion-folders"] });
    },
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Không ngắt được kết nối Google.",
      ),
  });
  const scan = useMutation({
    mutationFn: (folderId: string) =>
      api<DriveConversionJob>(`/tools/drive/folders/${folderId}/scan`, {
        method: "POST",
      }),
    onSuccess: (data) => {
      setJobId(data.id);
      setSelected(new Set());
      setError(null);
    },
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Không bắt đầu quét được folder.",
      ),
  });
  const start = useMutation({
    mutationFn: (itemIds: string[] = [...selected]) =>
      api<DriveConversionJob>(`/tools/drive/jobs/${jobId}/start`, {
        method: "POST",
        body: JSON.stringify({
          item_ids: itemIds ?? [...selected],
          delete_originals: deleteOriginals,
        }),
      }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({
        queryKey: ["drive-conversion-job", jobId],
      });
    },
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Không bắt đầu chuyển đổi được.",
      ),
  });
  const grouped = useMemo(() => {
    const result = new Map<string, DriveConversionItem[]>();
    for (const item of job.data?.items ?? []) {
      const path = item.relative_path || "/";
      result.set(path, [...(result.get(path) ?? []), item]);
    }
    return [...result.entries()].sort(([a], [b]) => a.localeCompare(b, "vi"));
  }, [job.data?.items]);
  const selectable = (item: DriveConversionItem) =>
    item.can_download &&
    (!deleteOriginals || item.can_trash) &&
    (item.size_bytes == null || item.size_bytes <= MAX_XLSX_BYTES);
  const toggleAll = () =>
    setSelected(
      selected.size
        ? new Set()
        : new Set(
            (job.data?.items ?? []).filter(selectable).map((item) => item.id),
        ),
    );

  if (oauth.isLoading)
    return (
      <Working
        title="Đang kiểm tra Google"
        text="ZBridge đang kiểm tra tài khoản dùng cho công cụ chuyển đổi."
      />
    );
  if (oauth.isError || !oauth.data)
    return <ErrorBox text="Không đọc được trạng thái kết nối Google." />;
  if (!oauth.data.configured)
    return (
      <div className="space-y-4">
        <ErrorBox text="Chưa cấu hình Google OAuth Client ID và Client Secret trên server." />
        <div className="rounded-xl border border-border bg-muted/30 p-4 text-xs text-muted-foreground">
          Authorized redirect URI:{" "}
          <code className="break-all text-foreground">
            {oauth.data.redirect_uri}
          </code>
        </div>
      </div>
    );
  if (!oauth.data.connected)
    return (
      <div className="flex min-h-72 flex-col items-center justify-center text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-soft text-accent">
          <LogIn className="h-6 w-6" />
        </span>
        <h3 className="mt-4 font-display text-2xl">Kết nối Google Drive</h3>
        <p className="mt-2 max-w-lg text-sm text-muted-foreground">
          Đăng nhập tài khoản đang sở hữu hoặc có quyền chỉnh sửa folder. ZBridge
          sẽ xin quyền Drive để tạo Google Sheet và chuyển file XLSX vào Trash.
        </p>
        {error && (
          <div className="mt-4">
            <ErrorBox text={error} />
          </div>
        )}
        <Button
          className="mt-5"
          loading={connect.isPending}
          onClick={() => connect.mutate()}
        >
          <LogIn className="h-4 w-4" />
          Kết nối tài khoản Google
        </Button>
      </div>
    );

  if (!jobId)
    return (
      <div className="space-y-4">
        <div className="flex flex-col gap-3 rounded-xl border border-success-border bg-success-bg p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-medium text-success-fg">
              Google đã kết nối
            </p>
            <p className="mt-1 truncate text-sm font-semibold text-success-fg">
              {oauth.data.email}
            </p>
          </div>
          <Button
            variant="ghost"
            loading={disconnect.isPending}
            onClick={() => {
              if (
                window.confirm(
                  "Ngắt tài khoản Google khỏi công cụ chuyển đổi?",
                )
              )
                disconnect.mutate();
            }}
          >
            <Unplug className="h-4 w-4" />
            Ngắt kết nối
          </Button>
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            Chọn một folder đã lưu hoặc thêm folder mới.
          </p>
          <Button
            onClick={() => {
              setError(null);
              setAddOpen(true);
            }}
          >
            <FolderPlus className="h-4 w-4" />
            Thêm folder
          </Button>
        </div>
        {(error || oauth.data.last_error) && (
          <ErrorBox text={error || oauth.data.last_error || "Lỗi kết nối Google."} />
        )}
        {folders.isLoading ? (
          <Empty text="Đang tải folder..." />
        ) : folders.isError ? (
          <Empty text="Không tải được folder Google Drive." />
        ) : !folders.data?.length ? (
          <Empty text="Chưa có folder nào được lưu." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {folders.data.map((folder) => (
              <button
                key={folder.id}
                type="button"
                className="rounded-xl border border-border bg-card p-4 text-left transition hover:border-accent/40 hover:shadow-card"
                onClick={() => scan.mutate(folder.id)}
                disabled={scan.isPending}
              >
                <span className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-warning-bg text-warning-fg">
                    <Folder className="h-5 w-5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <strong className="block truncate text-sm">
                      {folder.name}
                    </strong>
                    <span className="mt-1 block text-xs text-success-fg">
                      Có quyền xem và tạo file
                    </span>
                  </span>
                  <ChevronDown className="h-4 w-4 -rotate-90 text-muted-foreground" />
                </span>
              </button>
            ))}
          </div>
        )}
        <Modal
          open={addOpen}
          onClose={() => !add.isPending && setAddOpen(false)}
          className="max-w-lg"
          title="Thêm folder Google Drive"
          description="Tài khoản Google đã kết nối phải có quyền xem và tạo file trong folder."
        >
          <div className="space-y-4">
            <input
              className="field"
              placeholder="https://drive.google.com/drive/folders/..."
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                setError(null);
              }}
            />
            {error && <ErrorBox text={error} />}
            <div className="flex justify-end gap-3">
              <Button variant="ghost" onClick={() => setAddOpen(false)}>
                Đóng
              </Button>
              <Button
                loading={add.isPending}
                disabled={!url.trim()}
                onClick={() => add.mutate()}
              >
                Kiểm tra và lưu
              </Button>
            </div>
          </div>
        </Modal>
      </div>
    );

  const data = job.data;
  const retryableFailures =
    data?.items.filter(
      (item) => item.status === "FAILED" && selectable(item),
    ) ?? [];
  if (job.isLoading || data?.status === "SCANNING")
    return (
      <Working
        title="Đang quét folder"
        text="Bot đang duyệt folder cha và toàn bộ folder con để tìm file XLSX."
      />
    );
  if (job.isError || !data)
    return (
      <div className="space-y-4">
        <ErrorBox text="Không tải được lượt quét." />
        <Button variant="ghost" onClick={() => setJobId(null)}>
          Quay lại folder
        </Button>
      </div>
    );
  if (["QUEUED", "PROCESSING"].includes(data.status))
    return (
      <Working
        title="Đang chuyển đổi"
        text={`Đã chuyển ${data.converted_files}/${data.selected_files} file. Có thể đóng panel, job vẫn tiếp tục chạy.`}
      />
    );
  if (data.status === "COMPLETED")
    return (
      <div className="space-y-5">
        <div className="py-3 text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-success-fg" />
          <h3 className="mt-3 font-display text-2xl">Đã hoàn thành</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Thành công {data.converted_files} · lỗi {data.failed_files} · bỏ qua{" "}
            {data.skipped_files}
          </p>
        </div>
        {data.items.filter((item) => item.status === "FAILED").length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-semibold">File không chuyển được</h4>
            {data.items
              .filter((item) => item.status === "FAILED")
              .map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-danger-border bg-danger-bg p-3 text-sm"
                >
                  <strong className="block">{item.source_name}</strong>
                  <p className="mt-1 text-xs text-danger-fg">
                    {item.error_message}
                  </p>
                  <a
                    className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline"
                    href={item.parent_folder_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Mở folder chứa file <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              ))}
          </div>
        )}
        <div className="flex flex-wrap justify-end gap-3">
          <Button variant="ghost" onClick={() => setJobId(null)}>
            Chọn folder khác
          </Button>
          {retryableFailures.length > 0 && (
            <Button
              onClick={() =>
                start.mutate(retryableFailures.map((item) => item.id))
              }
            >
              Thử lại file lỗi
            </Button>
          )}
        </div>
      </div>
    );
  if (data.status === "FAILED")
    return (
      <div className="space-y-4">
        <ErrorBox
          text={data.error_message || "Lượt quét hoặc chuyển đổi gặp lỗi."}
        />
        <Button variant="ghost" onClick={() => setJobId(null)}>
          Quay lại folder
        </Button>
      </div>
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-semibold">{data.folder_name}</h3>
          <p className="text-xs text-muted-foreground">
            Tìm thấy {data.total_files} file XLSX
          </p>
        </div>
        <button
          className="text-xs font-semibold text-accent hover:underline"
          onClick={toggleAll}
        >
          {selected.size ? "Bỏ chọn tất cả" : "Chọn tất cả"}
        </button>
      </div>
      <label className="flex items-start gap-3 rounded-xl border border-warning-border bg-warning-bg p-4">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 accent-accent"
          checked={deleteOriginals}
          onChange={(event) => {
            setDeleteOriginals(event.target.checked);
            setSelected(new Set());
          }}
        />
        <span>
          <strong className="flex items-center gap-2 text-sm">
            <Trash2 className="h-4 w-4" />
            Chuyển XLSX cũ vào thùng rác
          </strong>
          <span className="mt-1 block text-xs text-warning-fg">
            Chỉ thực hiện sau khi Google Sheet mới được tạo thành công. Có thể
            phục hồi từ Trash.
          </span>
        </span>
      </label>
      {error && <ErrorBox text={error} />}
      <div className="app-scrollbar max-h-[30rem] space-y-2 overflow-auto rounded-xl border border-border bg-muted/20 p-2">
        {grouped.map(([path, items]) => {
          const open = expanded.has(path);
          const enabled = items.filter(selectable);
          const allSelected =
            enabled.length > 0 &&
            enabled.every((item) => selected.has(item.id));
          return (
            <div
              key={path}
              className="overflow-hidden rounded-lg border border-border bg-card"
            >
              <div className="flex items-center gap-2 p-3">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-accent"
                  checked={allSelected}
                  onChange={() =>
                    setSelected((current) => {
                      const next = new Set(current);
                      for (const item of enabled) {
                        if (allSelected) next.delete(item.id);
                        else next.add(item.id);
                      }
                      return next;
                    })
                  }
                />
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  onClick={() =>
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (open) next.delete(path);
                      else next.add(path);
                      return next;
                    })
                  }
                >
                  <Folder className="h-4 w-4 text-warning-fg" />
                  <span className="truncate text-sm font-semibold">
                    {path === "/" ? data.folder_name : path}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {items.length}
                  </span>
                  <ChevronDown
                    className={`ml-auto h-4 w-4 transition ${open ? "rotate-180" : ""}`}
                  />
                </button>
              </div>
              {open && (
                <div className="divide-y divide-border border-t border-border">
                  {items.map((item) => (
                    <label
                      key={item.id}
                      className={`flex items-center gap-3 px-4 py-3 ${selectable(item) ? "hover:bg-muted/30" : "opacity-50"}`}
                    >
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-accent"
                        disabled={!selectable(item)}
                        checked={selected.has(item.id)}
                        onChange={() =>
                          setSelected((current) => {
                            const next = new Set(current);
                            if (next.has(item.id)) next.delete(item.id);
                            else next.add(item.id);
                            return next;
                          })
                        }
                      />
                      <FileSpreadsheet className="h-4 w-4 text-success-fg" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">
                          {item.source_name}
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          {formatBytes(item.size_bytes)}
                          {!item.can_download
                            ? " · Không có quyền tải"
                            : deleteOriginals && !item.can_trash
                              ? " · Không có quyền xóa"
                              : item.size_bytes != null &&
                                  item.size_bytes > MAX_XLSX_BYTES
                                ? " · Vượt giới hạn 25 MB"
                              : ""}
                        </span>
                      </span>
                      <a
                        href={item.source_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                        aria-label="Mở file"
                      >
                        <ExternalLink className="h-4 w-4 text-muted-foreground" />
                      </a>
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap justify-between gap-3 border-t border-border pt-5">
        <Button variant="ghost" onClick={() => setJobId(null)}>
          Quay lại
        </Button>
        <Button
          disabled={!selected.size}
          loading={start.isPending}
          onClick={() => start.mutate([...selected])}
        >
          Chuyển {selected.size} file
        </Button>
      </div>
    </div>
  );
}

function Working({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex min-h-72 flex-col items-center justify-center text-center">
      <LoaderCircle className="h-10 w-10 animate-spin text-accent" />
      <h3 className="mt-4 font-display text-xl">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{text}</p>
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-border p-8 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}
function ErrorBox({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-danger-border bg-danger-bg p-3 text-sm text-danger-fg">
      {text}
    </div>
  );
}
function formatBytes(value: number | null) {
  if (value == null) return "Không rõ dung lượng";
  if (value < 1024 * 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

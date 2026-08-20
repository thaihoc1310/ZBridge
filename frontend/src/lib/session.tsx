import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { User } from "../api/types";
import type { PermissionCode } from "./permissions";

const SessionContext = createContext<User | null>(null);

export function SessionProvider({ user, children }: { user: User; children: ReactNode }) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

export function useSession(): User {
  const user = useContext(SessionContext);
  if (!user) throw new Error("useSession phải được dùng bên trong SessionProvider.");
  return user;
}

export function usePermissions() {
  const user = useSession();
  const granted = useMemo(() => new Set<string>(user.role.permissions), [user.role.permissions]);
  return useMemo(
    () => ({
      /** True only when every listed permission is granted. */
      can: (...codes: PermissionCode[]) => codes.every((code) => granted.has(code)),
      canAny: (...codes: PermissionCode[]) => codes.some((code) => granted.has(code)),
    }),
    [granted],
  );
}

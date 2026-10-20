export type AccountScreen =
  | "signin"
  | "register"
  | "verify"
  | "recovery"
  | "reset";

export type AppRoute =
  | { type: "home" }
  | { type: "account"; screen: AccountScreen }
  | { type: "founder-profile" }
  | { type: "public-profile"; accountId: string }
  | { type: "founder-products"; productId?: string }
  | { type: "reviewer-products"; productId?: string }
  | { type: "founder-launches" }
  | { type: "public-launch"; productId: string }
  | { type: "unavailable" };

const unavailable: AppRoute = { type: "unavailable" };
const accountScreens: ReadonlyMap<string, AccountScreen> = new Map([
  ["signin", "signin"],
  ["register", "register"],
  ["verify", "verify"],
  ["recover", "recovery"],
  ["reset", "reset"],
]);

function decodeIdentifier(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const decoded = decodeURIComponent(value);
    return decoded && !decoded.includes("/") ? decoded : null;
  } catch {
    return null;
  }
}

function pathSegments(pathname: string): string[] | null {
  if (!pathname.startsWith("/")) return null;
  const normalized = pathname === "/" ? pathname : pathname.replace(/\/+$/, "");
  if (normalized === "/") return [];
  const segments = normalized.slice(1).split("/");
  return segments.some((segment) => segment.length === 0) ? null : segments;
}

export function classifyRoute(pathname: string): AppRoute {
  const segments = pathSegments(pathname);
  if (!segments) return unavailable;
  if (segments.length === 0) return { type: "home" };

  if (segments.length === 1) {
    const [segment] = segments;
    const screen = accountScreens.get(segment);
    if (screen) return { type: "account", screen };
    if (segment === "profile") return { type: "founder-profile" };
    if (segment === "products") return { type: "founder-products" };
    if (segment === "launches") return { type: "founder-launches" };
  }

  if (segments[0] === "public" && segments.length === 2) {
    const accountId = decodeIdentifier(segments[1]);
    return accountId ? { type: "public-profile", accountId } : unavailable;
  }

  if (segments[0] === "launches" && segments.length === 2) {
    const productId = decodeIdentifier(segments[1]);
    return productId ? { type: "public-launch", productId } : unavailable;
  }

  if (segments[0] === "products") {
    if (segments[1] === "review") {
      if (segments.length === 2) return { type: "reviewer-products" };
      if (segments.length === 3) {
        const productId = decodeIdentifier(segments[2]);
        return productId
          ? { type: "reviewer-products", productId }
          : unavailable;
      }
      return unavailable;
    }
    if (segments.length === 2) {
      const productId = decodeIdentifier(segments[1]);
      return productId ? { type: "founder-products", productId } : unavailable;
    }
  }

  return unavailable;
}

export function navigate(path: string, state: Record<string, unknown> = {}) {
  window.history.pushState(state, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

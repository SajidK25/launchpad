import { useEffect, useState } from "react";

import { useConnectivity } from "./connectivity/useConnectivity";
import { createProductClient } from "./products/client";
import { ProductRoutes } from "./products/ProductScreens";
import { createIdentityClient } from "./identity/client";
import { IdentityRoutes, navigate } from "./identity/Screens";
import { ProfileRoutes } from "./profiles/ProfileScreens";
import { NotificationBell } from "./notifications/NotificationBell";
import { LaunchRoutes } from "./launches/LaunchScreens";

const statusCopy = {
  connected: "Connected",
  loading: "Checking connection",
  unavailable: "Unavailable",
} as const;

const detailCopy = {
  connected: "Launchpad can reach its required local services.",
  loading: "Checking the local API and required services.",
  unavailable: "Launchpad cannot reach the required local services right now.",
} as const;

export function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [identityClient] = useState(() => createIdentityClient());
  const [productClient] = useState(() =>
    createProductClient(undefined, identityClient),
  );
  const connectivity = useConnectivity();
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  useEffect(() => {
    if (window.history.state?.focusProductMain !== true) return;
    document.getElementById("product-main")?.focus();
    window.history.replaceState({}, "", window.location.href);
  }, [path]);

  if (path !== "/") {
    if (path === "/launches")
      return <LaunchRoutes identityClient={identityClient} />;
    if (path === "/products" || path.startsWith("/products/")) {
      return (
        <>
          <NotificationBell identityClient={identityClient} />
          <ProductRoutes
            identityClient={identityClient}
            path={path}
            client={productClient}
          />
        </>
      );
    }
    if (path === "/profile") {
      return (
        <>
          <nav
            aria-label="Founder workspace"
            className="profile-workspace-link"
          >
            <a
              href="/products"
              onClick={(event) => {
                event.preventDefault();
                navigate("/products");
              }}
            >
              Your product drafts
            </a>
          </nav>
          <ProfileRoutes identityClient={identityClient} />
        </>
      );
    }
    if (path.startsWith("/public/"))
      return <ProfileRoutes identityClient={identityClient} />;
    return <IdentityRoutes client={identityClient} />;
  }
  const { refresh, state } = connectivity;

  return (
    <main className="page-shell">
      <section aria-labelledby="page-title" className="connectivity-card">
        <p className="eyebrow">Local development</p>
        <h1 id="page-title">Launchpad</h1>
        <p
          aria-atomic="true"
          aria-live="polite"
          className={`status status-${state}`}
          role="status"
        >
          {statusCopy[state]}
        </p>
        <p className="status-detail">{detailCopy[state]}</p>
        {state === "unavailable" ? (
          <button
            className="retry-button"
            onClick={() => void refresh()}
            type="button"
          >
            Check again
          </button>
        ) : null}
      </section>
    </main>
  );
}

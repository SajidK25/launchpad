import { useEffect, useState } from "react";

import { useConnectivity } from "./connectivity/useConnectivity";
import { createIdentityClient } from "./identity/client";
import { IdentityRoutes } from "./identity/Screens";
import { ProfileRoutes } from "./profiles/ProfileScreens";

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
  const connectivity = useConnectivity();
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  if (path !== "/") {
    if (path === "/profile" || path.startsWith("/public/")) {
      return <ProfileRoutes identityClient={identityClient} />;
    }
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

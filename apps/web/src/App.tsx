import { useEffect, useState, type ReactNode } from "react";
import { createIdentityClient } from "./identity/client";
import { IdentityRoutes } from "./identity/Screens";
import { createProductClient } from "./products/client";
import { ProductRoutes } from "./products/ProductScreens";
import { ProfileRoutes } from "./profiles/ProfileScreens";
import {
  LaunchRoutes,
  PublicLaunchArchive,
  PublicLaunchPage,
} from "./launches/LaunchScreens";
import { AppErrorBoundary } from "./ui/AppErrorBoundary";
import { UnavailableState } from "./ui/Primitives";
import { HomePage } from "./home/HomePage";
import { PublicShell, WorkspaceShell } from "./shell/AppShell";
import { classifyRoute } from "./routing";

export function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [hash, setHash] = useState(window.location.hash);
  const [identityClient] = useState(() => createIdentityClient());
  const [productClient] = useState(() =>
    createProductClient(undefined, identityClient),
  );

  useEffect(() => {
    const update = () => {
      setPath(window.location.pathname);
      setHash(window.location.hash);
    };
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("hashchange", update);
    };
  }, []);

  useEffect(() => {
    const identifier = hash.slice(1);
    if (!identifier) return;
    try {
      document
        .getElementById(decodeURIComponent(identifier))
        ?.scrollIntoView({ block: "start" });
    } catch {
      // Ignore malformed fragments; the route itself remains valid.
    }
  }, [hash, path]);

  useEffect(() => {
    if (window.history.state?.focusProductMain !== true) return;
    document.getElementById("product-main")?.focus();
    window.history.replaceState({}, "", window.location.href);
  }, [path]);

  const route = classifyRoute(path);
  let surface: ReactNode;

  switch (route.type) {
    case "home":
      surface = (
        <PublicShell>
          <HomePage identityClient={identityClient} />
        </PublicShell>
      );
      break;
    case "account":
      surface = (
        <PublicShell>
          <IdentityRoutes client={identityClient} />
        </PublicShell>
      );
      break;
    case "founder-profile":
      surface = (
        <WorkspaceShell identityClient={identityClient}>
          <ProfileRoutes identityClient={identityClient} />
        </WorkspaceShell>
      );
      break;
    case "public-profile":
      surface = (
        <PublicShell>
          <ProfileRoutes identityClient={identityClient} />
        </PublicShell>
      );
      break;
    case "founder-products":
    case "reviewer-products":
      surface = (
        <WorkspaceShell identityClient={identityClient}>
          <ProductRoutes
            identityClient={identityClient}
            path={path}
            client={productClient}
          />
        </WorkspaceShell>
      );
      break;
    case "founder-launches":
      surface = (
        <WorkspaceShell identityClient={identityClient}>
          <LaunchRoutes identityClient={identityClient} />
        </WorkspaceShell>
      );
      break;
    case "public-launch-archive":
      surface = (
        <PublicShell>
          <PublicLaunchArchive
            date={route.date}
            identityClient={identityClient}
          />
        </PublicShell>
      );
      break;
    case "public-launch":
      surface = (
        <PublicShell>
          <PublicLaunchPage
            identityClient={identityClient}
            productId={route.productId}
          />
        </PublicShell>
      );
      break;
    case "unavailable":
      surface = (
        <PublicShell>
          <UnavailableState
            title="This page isn’t available"
            description="Check the address or return to the Launchpad home page."
            action={
              <a className="ui-action ui-action--primary" href="/">
                Go to home
              </a>
            }
          />
        </PublicShell>
      );
      break;
  }

  return <AppErrorBoundary>{surface}</AppErrorBoundary>;
}

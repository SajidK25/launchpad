import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import type { paths } from "@launchpad/contracts";

const readinessPath = "/api/v1/health/ready" satisfies keyof paths;

function App() {
  return (
    <main>
      <h1>Launchpad</h1>
      <p data-readiness-path={readinessPath}>Local development environment</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

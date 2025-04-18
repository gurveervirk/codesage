import { RemixBrowser } from "@remix-run/react";
import { hydrateRoot } from "react-dom/client";
import { CacheProvider } from "@emotion/react";
import createCache from "@emotion/cache";
import { useState } from "react";
import { ClientStyleContext } from "./styleContext";

const cache = createCache({ key: "mui" });

function ClientCacheProvider({ children }: { children: React.ReactNode }) {
  const [, setKey] = useState(0);
  return (
    <ClientStyleContext.Provider value={{ reset: () => setKey((prev) => prev + 1) }}>
      <CacheProvider value={cache}>{children}</CacheProvider>
    </ClientStyleContext.Provider>
  );
}

hydrateRoot(
  document,
  <ClientCacheProvider>
    <RemixBrowser />
  </ClientCacheProvider>
);

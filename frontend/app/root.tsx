import { useState, useEffect, useContext } from "react";
import { Links, Meta, Outlet, Scripts, ScrollRestoration } from "@remix-run/react";
import { CssBaseline } from "@mui/material";
import { CacheProvider } from "@emotion/react";
import createCache from "@emotion/cache";
import { ClientStyleContext, ServerStyleContext } from "./styleContext";
import { ThemeWrapper } from "./theme"; // Import ThemeWrapper here
import "./tailwind.css";

// Create an Emotion cache instance
const createEmotionCache = () => createCache({ key: "mui" });

export function Layout({ children }: { children: React.ReactNode }) {
  const serverStyleData = useContext(ServerStyleContext);
  const clientStyleData = useContext(ClientStyleContext);
  const [cache, setCache] = useState(createEmotionCache());

  // Ensure styles persist after client-side navigation
  useEffect(() => {
    clientStyleData?.reset();
    setCache(createEmotionCache()); // Force Emotion to sync on hydration
  }, []);

  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
        <Meta />
        <Links />
        {/* Server-side styles */}
        {serverStyleData?.map(({ key, ids, css }) => (
          <style key={key} data-emotion={`${key} ${ids.join(" ")}`} dangerouslySetInnerHTML={{ __html: css }} />
        ))}
      </head>
      <body>
        <CacheProvider value={cache}>
          <ThemeWrapper>
            {/* CssBaseline kickstarts an elegant, consistent, and simple baseline to build upon. */}
            <CssBaseline />
            {children}
          </ThemeWrapper>
        </CacheProvider>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return <Outlet />;
}

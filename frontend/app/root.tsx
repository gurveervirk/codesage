import { useState, useEffect, useContext } from "react";
import { Links, Meta, NavLink, Outlet, Scripts, ScrollRestoration } from "@remix-run/react";
import type { LinksFunction, MetaFunction } from "@remix-run/node";
import { Box, CssBaseline, Stack, Typography } from "@mui/material";
import { CacheProvider } from "@emotion/react";
import createCache from "@emotion/cache";
import { ClientStyleContext, ServerStyleContext } from "./styleContext";
import { ThemeWrapper } from "./theme"; // Import ThemeWrapper here
import "./tailwind.css";

// Create an Emotion cache instance
const createEmotionCache = () => createCache({ key: "mui" });

const BLANK_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

export const links: LinksFunction = () => [
  { rel: "icon", href: BLANK_PNG },
  { rel: "apple-touch-icon", href: BLANK_PNG },
  { rel: "preconnect", href: "https://fonts.googleapis.com" },
  { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
  { rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" },
];

export const meta: MetaFunction = () => {
  return [
    { charSet: "utf-8" },
    { name: "viewport", content: "width=device-width,initial-scale=1" },
  ];
};

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
            <CssBaseline />
            <Box sx={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
              <Box
                component="nav"
                sx={{
                  px: 3,
                  py: 1.5,
                  borderBottom: "1px solid",
                  borderColor: "divider",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  bgcolor: "background.default",
                  position: "sticky",
                  top: 0,
                  zIndex: 100,
                }}
              >
                <Typography
                  component={NavLink as React.ElementType}
                  to="/"
                  sx={{
                    fontWeight: 700,
                    fontSize: "1rem",
                    letterSpacing: "-0.01em",
                    color: "text.primary",
                    textDecoration: "none",
                    "&:hover": { opacity: 0.7 },
                  }}
                >
                  deputy
                </Typography>
                <Stack direction="row" spacing={3}>
                  {[
                    { to: "/", label: "search" },
                    { to: "/about", label: "about" },
                  ].map(({ to, label }) => (
                    <NavLink
                      key={to}
                      to={to}
                      end
                      style={({ isActive }) => ({
                        fontSize: "0.875rem",
                        fontWeight: isActive ? 700 : 400,
                        color: "#000",
                        textDecoration: "none",
                        borderBottom: isActive ? "2px solid #000" : "2px solid transparent",
                        paddingBottom: 2,
                      })}
                    >
                      {label}
                    </NavLink>
                  ))}
                </Stack>
              </Box>
              <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "auto" }}>
                {children}
              </Box>
            </Box>
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

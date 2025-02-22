import { useState, useEffect, useContext } from "react";
import { Links, Meta, Outlet, Scripts, ScrollRestoration } from "@remix-run/react";
import { ThemeProvider, CssBaseline, createTheme } from "@mui/material";
import { CacheProvider } from "@emotion/react";
import createCache from "@emotion/cache";
import { ClientStyleContext, ServerStyleContext } from "./styleContext";
import "./tailwind.css";

// Create an Emotion cache instance
const createEmotionCache = () => createCache({ key: "mui", prepend: true });

// Define Material UI theme (Material 3 styles)
const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#6750A4" },
    secondary: { main: "#625B71" },
    background: { default: "#FFFBFE", paper: "#FFFFFF" },
    error: { main: "#B3261E" },
    text: { primary: "#1C1B1F", secondary: "#49454F" },
  },
  typography: {
    fontFamily: "Roboto, sans-serif",
    button: { textTransform: "none", fontWeight: 500 },
  },
  shape: {
    borderRadius: 12, // Material 3 rounded corners
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: "100px", // Full pill-shaped buttons
          padding: "10px 24px",
          fontSize: "1rem",
          boxShadow: "none",
          "&:hover": { backgroundColor: "#5B47A2" },
        },
      },
    },
  },
});

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
        <Meta />
        <Links />
        {/* Server-side styles */}
        {serverStyleData?.map(({ key, ids, css }) => (
          <style key={key} data-emotion={`${key} ${ids.join(" ")}`} dangerouslySetInnerHTML={{ __html: css }} />
        ))}
      </head>
      <body>
        <CacheProvider value={cache}>
          <ThemeProvider theme={theme}>
            <CssBaseline />
            {children}
          </ThemeProvider>
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

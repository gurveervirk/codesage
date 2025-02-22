import { createTheme, ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";

// MD3 Theme Colors
const theme = createTheme({
  palette: {
    mode: "light", // Change to "dark" for dark mode
    primary: {
      main: "#6750A4", // MD3 Primary
    },
    secondary: {
      main: "#625B71", // MD3 Secondary
    },
    background: {
      default: "#FFFBFE", // MD3 Background
      paper: "#FFFFFF",
    },
    error: {
      main: "#B3261E", // MD3 Error color
    },
    text: {
      primary: "#1C1B1F",
      secondary: "#49454F",
    },
  },
  typography: {
    fontFamily: "Roboto, sans-serif",
    h1: { fontSize: "3rem", fontWeight: 400 },
    h2: { fontSize: "2.5rem", fontWeight: 400 },
    h3: { fontSize: "2rem", fontWeight: 400 },
    h4: { fontSize: "1.75rem", fontWeight: 400 },
    h5: { fontSize: "1.5rem", fontWeight: 400 },
    h6: { fontSize: "1.25rem", fontWeight: 500 },
    body1: { fontSize: "1rem", fontWeight: 400 },
    button: { fontSize: "1rem", fontWeight: 500, textTransform: "none" },
  },
  shape: {
    borderRadius: 12, // MD3 Rounded Corners
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: "100px", // MD3 Button Style
          padding: "10px 24px",
          textTransform: "none",
          fontSize: "1rem",
          fontWeight: "500",
          boxShadow: "none",
          "&:hover": {
            backgroundColor: "#5B47A2", // Hover effect
          },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: "16px", // MD3 Card Rounded Corners
          boxShadow: "0px 4px 10px rgba(0,0,0,0.1)", // MD3 Elevation
        },
      },
    },
  },
});

export function ThemeWrapper({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {children}
    </ThemeProvider>
  );
}

import { createTheme, ThemeProvider } from "@mui/material/styles";
import { CssBaseline } from "@mui/material"; // Changed import syntax

// Modern theme with enhanced colors
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#4361ee", // Modern blue
      light: "#6591ee",
      dark: "#2f49c5",
      contrastText: "#ffffff",
    },
    secondary: {
      main: "#3f37c9", // Deep purple
      light: "#6563ff",
      dark: "#2a0f97",
      contrastText: "#ffffff",
    },
    background: {
      default: "#f8f9fd", // Light blue-gray background
      paper: "#ffffff",
    },
    error: {
      main: "#ef476f", // Modern pink-red
      light: "#ff7a9c",
      dark: "#c60042",
    },
    warning: {
      main: "#ffd166", // Warm yellow
      light: "#ffe499",
      dark: "#c8a133",
    },
    info: {
      main: "#118ab2", // Teal blue
      light: "#62bcdb",
      dark: "#006080",
    },
    success: {
      main: "#06d6a0", // Mint green
      light: "#75ffd1",
      dark: "#00a372",
    },
    text: {
      primary: "#2b2d42", // Dark blue-gray
      secondary: "#5c6081",
    },
    divider: "rgba(0, 0, 0, 0.08)",
  },
  typography: {
    fontFamily: "'Inter', 'Roboto', 'Helvetica', 'Arial', sans-serif",
    h1: { fontSize: "3rem", fontWeight: 700, letterSpacing: "-0.02em" },
    h2: { fontSize: "2.5rem", fontWeight: 700, letterSpacing: "-0.01em" },
    h3: { fontSize: "2rem", fontWeight: 600, letterSpacing: "-0.01em" },
    h4: { fontSize: "1.75rem", fontWeight: 600, letterSpacing: "-0.01em" },
    h5: { fontSize: "1.5rem", fontWeight: 600 },
    h6: { fontSize: "1.25rem", fontWeight: 600 },
    body1: { 
      fontSize: "1rem", 
      fontWeight: 400,
      lineHeight: 1.7,
    },
    body2: {
      fontSize: "0.875rem",
      lineHeight: 1.6,
    },
    button: { 
      fontSize: "0.95rem", 
      fontWeight: 500, 
      textTransform: "none",
    },
    caption: {
      fontSize: "0.75rem",
      color: "rgba(0, 0, 0, 0.6)",
    },
  },
  shape: {
    borderRadius: 12,
  },
  shadows: [
    "none",
    "0px 2px 4px rgba(0, 0, 0, 0.03), 0px 1px 2px rgba(0, 0, 0, 0.06)",
    "0px 4px 6px rgba(0, 0, 0, 0.04), 0px 2px 4px rgba(0, 0, 0, 0.06)",
    "0px 6px 8px rgba(0, 0, 0, 0.04), 0px 3px 6px rgba(0, 0, 0, 0.06)",
    "0px 8px 12px rgba(0, 0, 0, 0.05), 0px 4px 8px rgba(0, 0, 0, 0.06)",
    ...Array(20).fill(""),
  ] as any,
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: "8px",
          padding: "8px 20px",
          fontSize: "0.95rem",
          fontWeight: 500,
          boxShadow: "0px 2px 4px rgba(0, 0, 0, 0.05)",
          textTransform: "none",
          transition: "transform 0.2s, box-shadow 0.2s",
          "&:hover": {
            boxShadow: "0px 4px 8px rgba(0, 0, 0, 0.1)",
            transform: "translateY(-1px)",
          },
        },
        containedPrimary: {
          background: "linear-gradient(45deg, #4361ee, #3a86ff)",
        },
        containedSecondary: {
          background: "linear-gradient(45deg, #3f37c9, #4361ee)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: "16px",
          boxShadow: "0px 4px 20px rgba(0, 0, 0, 0.08)",
          transition: "transform 0.3s, box-shadow 0.3s",
          "&:hover": {
            boxShadow: "0px 8px 30px rgba(0, 0, 0, 0.12)",
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: "12px",
        },
        elevation1: {
          boxShadow: "0px 2px 6px rgba(0, 0, 0, 0.05), 0px 1px 3px rgba(0, 0, 0, 0.08)",
        },
        elevation2: {
          boxShadow: "0px 4px 8px rgba(0, 0, 0, 0.06), 0px 2px 4px rgba(0, 0, 0, 0.08)",
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          "& .MuiOutlinedInput-root": {
            borderRadius: "10px",
            "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
              borderColor: "#4361ee",
              borderWidth: "2px",
            },
          },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          borderRight: "none",
          boxShadow: "rgba(0, 0, 0, 0.05) 0px 1px 2px 0px",
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          transition: "transform 0.2s",
          "&:hover": {
            backgroundColor: "rgba(67, 97, 238, 0.08)",
            transform: "scale(1.05)",
          },
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

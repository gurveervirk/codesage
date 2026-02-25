import { createTheme, ThemeProvider } from "@mui/material/styles";
import { CssBaseline } from "@mui/material";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#000000",
      contrastText: "#ffffff",
    },
    secondary: {
      main: "#000000",
      contrastText: "#ffffff",
    },
    background: {
      default: "#fafafa",
      paper: "#ffffff",
    },
    text: {
      primary: "#111111",
      secondary: "#555555",
    },
    divider: "#e0e0e0",
    action: {
      selected: "#f0f0f0",
      hover: "#f5f5f5",
    },
  },
  shape: {
    borderRadius: 2,
  },
  typography: {
    fontFamily: "'Inter', 'Roboto', 'Helvetica', 'Arial', sans-serif",
    button: {
      textTransform: "none",
    },
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 2,
          boxShadow: "none",
        },
        contained: {
          backgroundColor: "#111111",
          color: "#ffffff",
          "&:hover": {
            backgroundColor: "#333333",
            boxShadow: "none",
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 2,
          border: "1px solid #e0e0e0",
          boxShadow: "none",
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          "& .MuiOutlinedInput-root": {
            borderRadius: 2,
            "& fieldset": {
              borderColor: "#d0d0d0",
            },
            "&:hover fieldset": {
              borderColor: "#888888",
            },
            "&.Mui-focused fieldset": {
              borderColor: "#111111",
            },
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

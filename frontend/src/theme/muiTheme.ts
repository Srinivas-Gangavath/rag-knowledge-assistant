import { createTheme } from "@mui/material/styles";

/**
 * MUI theme aligned with enterprise SaaS tokens so Drawer and Tooltip
 * seamlessly match the rest of the application shell.
 */
export const muiTheme = createTheme({
  palette: {
    primary: {
      main: "#4f46e5",
    },
    text: {
      primary: "#0f172a",
      secondary: "#475569",
    },
  },
  typography: {
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, sans-serif",
  },
  shape: {
    borderRadius: 12,
  },
  components: {
    MuiDrawer: {
      styleOverrides: {
        paper: {
          width: 256,
          borderRight: "1px solid #e2e8f0",
          boxShadow: "0 20px 25px -5px rgb(15 23 42 / 0.15)",
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          fontSize: "0.75rem",
          fontWeight: 500,
          backgroundColor: "#0f172a",
          borderRadius: 6,
          padding: "4px 8px",
        },
        arrow: {
          color: "#0f172a",
        },
      },
    },
  },
});

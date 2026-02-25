import type { MetaFunction } from "@remix-run/node";
import { Box, Divider, Stack, Typography } from "@mui/material";

export const meta: MetaFunction = () => [
  { title: "about · deputy" },
  { name: "description", content: "About deputy — Python library definition explorer" },
];

export default function AboutPage() {
  return (
    <Box sx={{ flex: 1, overflow: "auto", p: { xs: 3, md: 5 } }}>
      <Box sx={{ maxWidth: 760 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 0.5 }}>
          What is deputy?
        </Typography>
        <Typography variant="body2" sx={{ lineHeight: 1.8 }}>
          deputy is a tool for exploring and searching various library and dependency definitions. It lets you search for various symbols such as classes, functions, methods,
          modules — by name, fully-qualified name (FQN), or public alias, and inspect its signature,
          docstring, and source code.
        </Typography>

        <Divider sx={{ my: 3 }} />

        <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>
          How to use
        </Typography>

        <Stack spacing={2.5}>
          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
              1. Search for a symbol
            </Typography>
            <Typography variant="body2" sx={{ lineHeight: 1.8 }}>
              Type a symbol name, FQN, or known alias in the Search field. You can use comma-separated
              terms to search for multiple symbols at once (e.g.{" "}
              <Box component="code" sx={{ fontFamily: "Monaco, Menlo, monospace", fontSize: "0.8rem" }}>
                DataFrame, read_csv
              </Box>
              ). Results are ranked by match quality: exact matches appear first, followed by
              suffix matches, symbol matches, and partial matches.
            </Typography>
          </Box>

          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
              2. Filter by version (optional)
            </Typography>
            <Typography variant="body2" sx={{ lineHeight: 1.8 }}>
              Enter a version string in the Version field (e.g.{" "}
              <Box component="code" sx={{ fontFamily: "Monaco, Menlo, monospace", fontSize: "0.8rem" }}>
                2.2.0
              </Box>
              ) to limit both search and definition lookup to that specific library version. Leave it
              empty to search across all available versions.
            </Typography>
          </Box>

          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
              3. Inspect a definition
            </Typography>
            <Typography variant="body2" sx={{ lineHeight: 1.8 }}>
              Click any result in the left panel to load its full definition in the right panel.
              The panel shows the symbol's kind, its file path and line range, its signature,
              its docstring, and its full source code.
            </Typography>
          </Box>

          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
              4. Paginate results
            </Typography>
            <Typography variant="body2" sx={{ lineHeight: 1.8 }}>
              Use the Prev / Next controls at the bottom of the results panel to navigate through
              pages of results (10 results per page).
            </Typography>
          </Box>
        </Stack>

        <Divider sx={{ my: 3 }} />

        <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>
          Symbol kinds
        </Typography>
        <Stack spacing={1}>
          {[
            ["module", "A Python module file."],
            ["class", "A class definition."],
            ["function", "A top-level or module-level function."],
            ["method", "A method defined on a class."],
            ["package", "An importable or distribution package (e.g. numpy, pandas)."],
          ].map(([label, desc]) => (
            <Stack key={label} direction="row" spacing={1.5} alignItems="baseline">
              <Box
                component="code"
                sx={{
                  fontFamily: "Monaco, Menlo, monospace",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  flexShrink: 0,
                  minWidth: 100,
                }}
              >
                {label}
              </Box>
              <Typography variant="body2" color="text.secondary">
                {desc}
              </Typography>
            </Stack>
          ))}
        </Stack>
      </Box>
    </Box>
  );
}

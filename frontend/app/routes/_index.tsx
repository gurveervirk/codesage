import type { MetaFunction } from "@remix-run/node";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import InfoOutlined from "@mui/icons-material/InfoOutlined";
import { useState, useRef } from "react";
import { searchDefinitions, getDefinitions } from "~/utils/api";
import type { SearchResult, Definition } from "~/utils/api";

export const meta: MetaFunction = () => [
  { title: "deputy" },
  { name: "description", content: "Python library definition explorer" },
];

function normalizeSnippet(value: string | null): string {
  if (!value || value.trim().length === 0) return "";
  const unified = value.replace(/\r\n/g, "\n");
  const lines = unified.split("\n");
  while (lines.length > 0 && lines[0].trim() === "") lines.shift();
  while (lines.length > 0 && lines[lines.length - 1].trim() === "") lines.pop();
  if (lines.length === 0) return "";
  const indents = lines
    .filter((l) => l.trim().length > 0)
    .map((l) => (l.match(/^[\t ]*/) ?? [""])[0].length);
  const commonIndent = indents.length > 0 ? Math.min(...indents) : 0;
  return lines
    .map((l) => (l.trim().length === 0 ? "" : l.slice(commonIndent)))
    .join("\n");
}

function CodeBlock({ title, value }: { title: string; value: string | null }) {
  const content = normalizeSnippet(value);
  if (!content) return null;
  return (
    <Box>
      <Typography
        variant="overline"
        sx={{ display: "block", fontWeight: 700, letterSpacing: "0.08em", mb: 0.5, color: "text.secondary", fontSize: "0.7rem" }}
      >
        {title}
      </Typography>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1.5,
          border: "1px solid",
          borderColor: "divider",
          fontFamily: "Monaco, Menlo, Consolas, 'Courier New', monospace",
          fontSize: "0.78rem",
          lineHeight: 1.55,
          overflowX: "auto",
          overflowY: "auto",
          maxHeight: 280,
          bgcolor: "background.paper",
          whiteSpace: "pre",
          wordBreak: "normal",
        }}
      >
        {content}
      </Box>
    </Box>
  );
}

function LabelChip({ label }: { label: string }) {
  const LABEL_MAP: Record<string, string> = {
    DISTRIBUTION_PACKAGE: "package",
    IMPORT_PACKAGE: "namespace",
    MODULE: "module",
    CLASS: "class",
    FUNCTION: "function",
    METHOD: "method",
  };
  const display = LABEL_MAP[label] ?? label.toLowerCase();
  return (
    <Chip
      label={display}
      size="small"
      variant="outlined"
      sx={{
        height: 18,
        fontSize: "0.65rem",
        fontWeight: 600,
        letterSpacing: "0.04em",
        borderRadius: 0,
        borderColor: "text.secondary",
        color: "text.secondary",
        "& .MuiChip-label": { px: 0.75 },
      }}
    />
  );
}

type SourceViewerProps = {
  def: Definition;
  onLoadFull: () => void;
  loadingFull: boolean;
};

function SourceViewer({ def, onLoadFull, loadingFull }: SourceViewerProps) {
  const source = def.full_source ?? def.context_source ?? def.source;
  if (!source || source.trim().length === 0) return null;

  const startLine = def.full_source != null ? 1 : (def.context_start_line ?? 1);
  const entityStart = def.entity_start_line;
  const entityEnd = def.entity_end_line;

  const linesArr = source.split("\n");
  const lastLineNo = startLine + linesArr.length - 1;

  const aboveTrimmed =
    def.full_source == null && def.context_start_line != null && def.entity_start_line != null && def.context_start_line > 1
      ? def.context_start_line - 1
      : 0;

  const gutterWidth = String(lastLineNo).length;

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 0.5 }}>
        <Typography
          variant="overline"
          sx={{ fontWeight: 700, letterSpacing: "0.08em", color: "text.secondary", fontSize: "0.7rem" }}
        >
          Source
        </Typography>
        {def.full_source == null && entityStart != null && (
          <Button
            size="small"
            variant="text"
            onClick={onLoadFull}
            disabled={loadingFull}
            sx={{ fontSize: "0.65rem", minWidth: 0, px: 1, py: 0, textTransform: "none" }}
          >
            {loadingFull ? <CircularProgress size={10} sx={{ mr: 0.5 }} /> : null}
            Show full source
          </Button>
        )}
      </Box>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 0,
          border: "1px solid",
          borderColor: "divider",
          fontFamily: "Monaco, Menlo, Consolas, 'Courier New', monospace",
          fontSize: "0.78rem",
          lineHeight: 1.55,
          overflowX: "auto",
          overflowY: "auto",
          maxHeight: 400,
          bgcolor: "background.paper",
          whiteSpace: "pre",
          wordBreak: "normal",
        }}
      >
        {aboveTrimmed > 0 && (
          <Box component="span" sx={{ display: "block", color: "text.disabled", pl: `${gutterWidth + 2}ch`, py: 0.25, borderBottom: "1px dashed", borderColor: "divider" }}>
            {`⋯ ${aboveTrimmed} line${aboveTrimmed !== 1 ? "s" : ""} above`}
          </Box>
        )}
        {linesArr.map((line, i) => {
          const lineNo = startLine + i;
          const inEntity = entityStart != null && entityEnd != null
            ? lineNo >= entityStart && lineNo <= entityEnd
            : true;
          return (
            <Box
              key={i}
              component="span"
              sx={{
                display: "flex",
                opacity: inEntity ? 1 : 0.4,
              }}
            >
              <Box
                component="span"
                sx={{
                  userSelect: "none",
                  textAlign: "right",
                  minWidth: `${gutterWidth + 1}ch`,
                  pr: "1ch",
                  color: "text.disabled",
                  flexShrink: 0,
                }}
              >
                {lineNo}
              </Box>
              <Box component="span" sx={{ flex: 1 }}>{line}</Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}

const PAGE_SIZE = 10;

export default function SearchPage() {
  const [leftWidth, setLeftWidth] = useState(340);
  const isDragging = useRef(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  const onDividerMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    dragStartX.current = e.clientX;
    dragStartWidth.current = leftWidth;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const next = Math.max(220, Math.min(640, dragStartWidth.current + ev.clientX - dragStartX.current));
      setLeftWidth(next);
    };
    const onUp = () => {
      isDragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const [query, setQuery] = useState("");
  const [version, setVersion] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalResults, setTotalResults] = useState(0);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [searching, setSearching] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFqn, setSelectedFqn] = useState<string | null>(null);
  const [details, setDetails] = useState<Definition[] | null>(null);
  const [overloadTab, setOverloadTab] = useState(0);
  const [loadingFullIdx, setLoadingFullIdx] = useState<number | null>(null);

  const runSearch = async (page = 1) => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setError(null);
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const data = await searchDefinitions(trimmed, version.trim() || undefined, page, PAGE_SIZE);
      setResults(data.definitions);
      setCurrentPage(data.current_page);
      setTotalResults(data.total_results);
      setNextPage(data.next_page);
      setSelectedFqn(null);
      setDetails(null);
    } catch (err) {
      setResults([]);
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  };

  const loadDetails = async (fqn: string) => {
    setSelectedFqn(fqn);
    setLoadingDetails(true);
    setError(null);
    setOverloadTab(0);
    try {
      const data = await getDefinitions([fqn], version.trim() || undefined);
      setDetails(data.definitions.length > 0 ? data.definitions : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load definition");
    } finally {
      setLoadingDetails(false);
    }
  };

  const loadFullSource = async (idx: number) => {
    if (!selectedFqn || !details) return;
    setLoadingFullIdx(idx);
    try {
      const data = await getDefinitions([selectedFqn], version.trim() || undefined, undefined, true);
      if (data.definitions.length > 0) {
        const updated = details.map((d, i) => i === idx ? { ...d, full_source: data.definitions[idx]?.full_source ?? d.full_source } : d);
        setDetails(updated);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load full source");
    } finally {
      setLoadingFullIdx(null);
    }
  };

  return (
    <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <Box sx={{ px: 3, pt: 2.5, pb: 1.5, borderBottom: "1px solid", borderColor: "divider" }}>
        <Typography variant="body2" color="text.secondary">
          Search Python symbols by name, path, or alias — then inspect signatures, docstrings, and source.
        </Typography>
      </Box>
      <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", p: 2.5 }}>
      {error ? (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2, borderRadius: 0 }}>
          {error}
        </Alert>
      ) : null}

      <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "row" }}>
        <Paper
          variant="outlined"
          sx={{ flexShrink: 0, width: leftWidth, display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <Box sx={{ p: 1.5, borderBottom: "1px solid", borderColor: "divider" }}>
            <Stack spacing={1}>
              <TextField
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runSearch(1);
                }}
                fullWidth
                placeholder="symbol, FQN, or alias"
                size="small"
                label="Search"
              />
              <Stack direction="row" spacing={1}>
                <TextField
                  value={version}
                  onChange={(e) => setVersion(e.target.value)}
                  size="small"
                  label="Version"
                  sx={{ flex: 1 }}
                />
                <Button
                  variant="contained"
                  onClick={() => runSearch(1)}
                  disabled={searching}
                  sx={{ flexShrink: 0 }}
                >
                  Go
                </Button>
              </Stack>
            </Stack>
          </Box>

          <Box sx={{ flex: 1, overflow: "auto", px: 1.5, py: 1 }}>
            {searching ? (
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                <CircularProgress size={16} />
                <Typography variant="body2" color="text.secondary">Searching…</Typography>
              </Stack>
            ) : null}

            {!searching && results.length === 0 && totalResults === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                Enter a symbol name, FQN, or alias to search.
              </Typography>
            ) : null}

            {results.length > 0 ? (
              <Stack spacing={0}>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
                  {totalResults} result{totalResults !== 1 ? "s" : ""} — page {currentPage}
                </Typography>
                {results.map((item) => (
                  <Box
                    key={item.fqn}
                    onClick={() => loadDetails(item.fqn)}
                    sx={{
                      p: 1.25,
                      cursor: "pointer",
                      borderBottom: "1px solid",
                      borderColor: "divider",
                      bgcolor: selectedFqn === item.fqn ? "action.selected" : "transparent",
                      "&:hover": { bgcolor: "action.hover" },
                    }}
                  >
                    <Tooltip title={item.aliases.length > 0 ? "Alias" : "Fully Qualified Name"} placement="left" arrow>
                      <Typography
                        variant="body2"
                        sx={{
                          fontFamily: "Monaco, Menlo, Consolas, 'Courier New', monospace",
                          fontSize: "0.8rem",
                          wordBreak: "break-all",
                        }}
                      >
                        {item.aliases.length > 0 ? item.aliases[0] : item.fqn}
                      </Typography>
                    </Tooltip>
                    {item.aliases.length > 0 ? (
                      <Tooltip title="Fully Qualified Name" placement="left" arrow>
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: "block", fontFamily: "Monaco, Menlo, Consolas, 'Courier New', monospace", fontSize: "0.7rem", wordBreak: "break-all" }}
                        >
                          {item.fqn}
                        </Typography>
                      </Tooltip>
                    ) : null}
                    {item.aliases.length > 1 ? (
                      <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 0.5, gap: 0.5 }}>
                        {item.aliases.slice(1).map((a) => (
                          <Tooltip key={a} title="Alias" placement="top" arrow>
                            <Chip
                              label={a}
                              size="small"
                              variant="outlined"
                              sx={{
                                height: 16,
                                fontSize: "0.62rem",
                                fontFamily: "Monaco, Menlo, Consolas, 'Courier New', monospace",
                                borderRadius: 0,
                                borderColor: "divider",
                                color: "text.secondary",
                                "& .MuiChip-label": { px: 0.5 },
                              }}
                            />
                          </Tooltip>
                        ))}
                      </Stack>
                    ) : null}
                    <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 0.5, gap: 0.5 }}>
                      {item.labels.map((lbl) => (
                        <LabelChip key={lbl} label={lbl} />
                      ))}
                    </Stack>
                  </Box>
                ))}
              </Stack>
            ) : null}
          </Box>

          {results.length > 0 ? (
            <Box sx={{ p: 1, borderTop: "1px solid", borderColor: "divider" }}>
              <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="center">
                <Button
                  size="small"
                  disabled={currentPage <= 1 || searching}
                  onClick={() => runSearch(currentPage - 1)}
                >
                  ← Prev
                </Button>
                <Typography variant="caption" color="text.secondary">
                  {currentPage} / {Math.ceil(totalResults / PAGE_SIZE) || 1}
                </Typography>
                <Button
                  size="small"
                  disabled={nextPage === null || searching}
                  onClick={() => runSearch(currentPage + 1)}
                >
                  Next →
                </Button>
              </Stack>
            </Box>
          ) : null}
        </Paper>

        <Box
          onMouseDown={onDividerMouseDown}
          sx={{
            width: 5,
            flexShrink: 0,
            cursor: "col-resize",
            bgcolor: "divider",
            "&:hover": { bgcolor: "text.disabled" },
            transition: "background-color 0.15s",
          }}
        />
        <Paper
          variant="outlined"
          sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}
        >
          <Box
            sx={{
              p: 1.5,
              borderBottom: "1px solid",
              borderColor: "divider",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Stack direction="row" spacing={0.75} alignItems="center">
              <Typography variant="subtitle2" sx={{ fontWeight: 700, letterSpacing: "0.03em" }}>
                Definition
              </Typography>
              <Tooltip title="FQN is the canonical module path. Aliases are shorthand import names." arrow>
                <InfoOutlined sx={{ fontSize: "0.9rem", color: "text.disabled", cursor: "default" }} />
              </Tooltip>
            </Stack>
            {details ? (
              <Button
                size="small"
                variant="text"
                onClick={() => {
                  setDetails(null);
                  setSelectedFqn(null);
                }}
                sx={{ minWidth: 0, px: 1 }}
              >
                Clear
              </Button>
            ) : null}
          </Box>

          <Box sx={{ flex: 1, overflow: "auto", p: 2 }}>
            {loadingDetails ? (
              <Stack direction="row" spacing={1} alignItems="center">
                <CircularProgress size={16} />
                <Typography variant="body2" color="text.secondary">Loading…</Typography>
              </Stack>
            ) : null}

            {!loadingDetails && (!details || details.length === 0) ? (
              <Typography variant="body2" color="text.secondary">
                Click a result to view its signature, docstring, and source code.
              </Typography>
            ) : null}

            {details && !loadingDetails ? (
              <Stack spacing={2}>
                {details.length > 1 ? (
                  <Tabs
                    value={overloadTab}
                    onChange={(_, v) => setOverloadTab(v)}
                    variant="scrollable"
                    scrollButtons="auto"
                    sx={{ borderBottom: "1px solid", borderColor: "divider", minHeight: 32 }}
                    TabIndicatorProps={{ style: { height: 2 } }}
                  >
                    {details.map((_, idx) => (
                      <Tab
                        key={idx}
                        label={`Overload ${idx + 1}`}
                        sx={{ minHeight: 32, py: 0.5, fontSize: "0.72rem", textTransform: "none", fontWeight: 600 }}
                      />
                    ))}
                  </Tabs>
                ) : null}
                {details.map((def, idx) => (
                  <Box key={idx} sx={{ display: details.length > 1 && idx !== overloadTab ? "none" : "block" }}>
                    <Stack spacing={2}>
                      <Box>
                        <Typography
                          variant="body1"
                          sx={{
                            fontFamily: "Monaco, Menlo, Consolas, 'Courier New', monospace",
                            fontWeight: 700,
                            wordBreak: "break-all",
                          }}
                        >
                          {def.name}
                        </Typography>
                        <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 0.75, gap: 0.5 }}>
                          {def.type.map((t) => (
                            <LabelChip key={t} label={t} />
                          ))}
                        </Stack>
                        {def.file_path ? (
                          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75, wordBreak: "break-all" }}>
                            {def.file_path}
                            {def.lines ? ` · lines ${def.lines}` : ""}
                          </Typography>
                        ) : null}
                      </Box>

                      <CodeBlock title="Signature" value={def.signature} />
                      <CodeBlock title="Docstring" value={def.docstring} />
                      <SourceViewer
                        def={def}
                        onLoadFull={() => loadFullSource(idx)}
                        loadingFull={loadingFullIdx === idx}
                      />
                    </Stack>
                  </Box>
                ))}
              </Stack>
            ) : null}
          </Box>
        </Paper>
      </Box>
      </Box>
    </Box>
  );
}

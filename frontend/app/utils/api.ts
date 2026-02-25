const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export type SearchResult = {
  fqn: string;
  labels: string[];
  aliases: string[];
};

export type SearchResponse = {
  definitions: SearchResult[];
  current_page: number;
  total_results: number;
  next_page: number | null;
};

export type Definition = {
  name: string;
  type: string[];
  source: string;
  docstring: string | null;
  signature: string | null;
  file_path: string | null;
  lines: string | null;
  context_source: string | null;
  context_start_line: number | null;
  context_end_line: number | null;
  entity_start_line: number | null;
  entity_end_line: number | null;
  full_source: string | null;
};

export type DefinitionsResponse = {
  definitions: Definition[];
};

export async function searchDefinitions(
  q: string,
  version?: string,
  page = 1,
  pageSize = 10
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, page: String(page), page_size: String(pageSize) });
  if (version) params.set("version", version);
  const res = await fetch(`${API_BASE}/explorer/search?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? "Search failed");
  }
  return res.json();
}

export async function getDefinitions(names: string[], version?: string, contextLines?: number, includeFullSource?: boolean): Promise<DefinitionsResponse> {
  const params = new URLSearchParams({ names: names.join(",") });
  if (version) params.set("version", version);
  if (contextLines !== undefined) params.set("context_lines", String(contextLines));
  if (includeFullSource) params.set("include_full_source", "true");
  const res = await fetch(`${API_BASE}/explorer/definitions?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { detail?: string }).detail ?? "Failed to load definitions");
  }
  return res.json();
}

import { createContext, useContext } from "react";

export const ServerStyleContext = createContext<null | { key: string; ids: string[]; css: string }[]>(null);
export const ClientStyleContext = createContext<{ reset: () => void } | null>(null);

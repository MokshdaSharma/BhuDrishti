// Terra Draw tool definitions — Phase 10
export const TOOLS = ["select","polygon","split","merge","delete"] as const;
export type ToolName = (typeof TOOLS)[number];

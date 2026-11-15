export function contentSecurityPolicy(options?: { frameSrc?: string }): string;
export const FRAME_PATHS: string[];
export const DEMO_FRAME_PATHS: string[];
export function pageFrameSrc(
  host: string | null,
  options?: { demo?: boolean },
): string;

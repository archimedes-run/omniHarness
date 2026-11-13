export type ProtocolDirection =
  | "frame_to_host"
  | "frame_to_host_window"
  | "host_to_frame";

export type ValidationResult =
  | { ok: true; type: string }
  | { ok: false; reason: string };

export function validateProtocolMessage(
  schema: unknown,
  direction: ProtocolDirection,
  message: unknown,
): ValidationResult;

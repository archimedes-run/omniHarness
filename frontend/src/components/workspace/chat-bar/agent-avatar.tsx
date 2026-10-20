import { avatarClasses, avatarInitials } from "@/core/agents";
import { cn } from "@/lib/utils";

/** An agent's avatar: its deterministic colour, always with its initials. */
export function AgentAvatar({
  id,
  name,
  size = 26,
}: {
  id: string;
  name: string;
  size?: number;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold",
        avatarClasses(id),
      )}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}
    >
      {avatarInitials(name)}
    </span>
  );
}

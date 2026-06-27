import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

interface StatusConfig {
  variant: BadgeVariant;
  label: string;
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  draft: { variant: "secondary", label: "Draft" },
  active: { variant: "default", label: "Active" },
  paused: { variant: "secondary", label: "Paused" },
  archived: { variant: "outline", label: "Archived" },
  failed: { variant: "destructive", label: "Failed" },
  waiting_approval: { variant: "outline", label: "Waiting approval" },
  verified: { variant: "default", label: "Verified" },
  queued: { variant: "secondary", label: "Queued" },
  running: { variant: "default", label: "Running" },
  succeeded: { variant: "default", label: "Succeeded" },
  canceled: { variant: "outline", label: "Canceled" },
  expired: { variant: "outline", label: "Expired" },
};

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? {
    variant: "secondary" as BadgeVariant,
    label: status,
  };
  return (
    <Badge variant={config.variant} className={cn(className)}>
      {config.label}
    </Badge>
  );
}

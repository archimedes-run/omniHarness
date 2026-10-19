import { Badge } from "@/components/ui/badge";

/**
 * Content that failed redaction (FR-031, SC-015). The gateway sends a sentence
 * in place of the text and sets `withheld`; this shows it AS a withholding, so
 * it cannot read as "there was nothing there".
 */
export function WithheldNotice({ text }: { text: string }) {
  return (
    <p
      className="text-muted-foreground flex items-center gap-2 text-sm italic"
      data-testid="withheld"
    >
      <Badge variant="outline">Withheld</Badge>
      {text}
    </p>
  );
}

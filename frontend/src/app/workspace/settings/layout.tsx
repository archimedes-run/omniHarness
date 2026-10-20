import { SettingsNav } from "@/components/workspace/settings/settings-nav";

/** Settings (Feature 006 board): a second column with the sections, the
 * section itself centred beside it. */
export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex size-full flex-col md:flex-row">
      <aside className="border-border shrink-0 border-b px-3 pt-6 pb-3 md:w-[220px] md:border-r md:border-b-0">
        <div className="px-2.5 pb-4 text-xl font-semibold">Settings</div>
        <SettingsNav />
      </aside>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

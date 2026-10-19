import { SettingsNav } from "@/components/workspace/settings/settings-nav";

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex size-full flex-col md:flex-row">
      <aside className="border-border shrink-0 border-b p-3 md:w-56 md:border-r md:border-b-0">
        <h1 className="px-3 pb-2 text-lg font-semibold">Settings</h1>
        <SettingsNav />
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { AgentSkillsSection } from "@/components/landing/sections/agent-skills-section";
import { FeaturesSection } from "@/components/landing/sections/features-section";
import { LivePreviewDemoSection } from "@/components/landing/sections/live-preview-demo-section";

export default function LandingPage() {
  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-[#F5F0E8] text-stone-900">
      <Header />
      <main className="flex w-full flex-col">
        <Hero />
        <AgentSkillsSection />
        <LivePreviewDemoSection />
        <FeaturesSection />
      </main>
      <Footer />
    </div>
  );
}

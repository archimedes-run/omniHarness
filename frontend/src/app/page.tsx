import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { AgentSkillsSection } from "@/components/landing/sections/agent-skills-section";
import { ExampleHarnessesSection } from "@/components/landing/sections/example-harnesses-section";
import { FeaturesSection } from "@/components/landing/sections/features-section";
import { FinalCtaSection } from "@/components/landing/sections/final-cta-section";
import { HarnessDefinitionSection } from "@/components/landing/sections/harness-definition-section";
import { LivePreviewDemoSection } from "@/components/landing/sections/live-preview-demo-section";

export default function LandingPage() {
  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-white text-stone-950">
      <Header />
      <main className="flex w-full flex-col">
        <Hero />
        <HarnessDefinitionSection />
        <AgentSkillsSection />
        <FeaturesSection />
        <LivePreviewDemoSection />
        <ExampleHarnessesSection />
        <FinalCtaSection />
      </main>
      <Footer />
    </div>
  );
}

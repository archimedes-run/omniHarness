import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";
import { DaySection } from "@/components/landing/sections/day-section";
import { FinalCtaSection } from "@/components/landing/sections/final-cta-section";
import { ProductSection } from "@/components/landing/sections/product-section";
import { SafetySection } from "@/components/landing/sections/safety-section";

export default function LandingPage() {
  return (
    <div className="bg-background text-foreground min-h-screen w-full overflow-x-clip">
      <Header />
      <main className="flex w-full flex-col">
        <Hero />
        <DaySection />
        <ProductSection />
        <SafetySection />
        <FinalCtaSection />
      </main>
      <Footer />
    </div>
  );
}

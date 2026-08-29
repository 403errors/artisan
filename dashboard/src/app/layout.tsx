import type { Metadata } from "next";
import { Quicksand, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/toast";
import "./globals.css";

const quicksand = Quicksand({
  variable: "--font-quicksand",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Artisan Dashboard",
  description: "Live ticket status across Artisan's three gates.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // Font variables live here, not on <body>: html { @apply font-sans } (globals.css)
    // reads --font-sans -> --font-quicksand, and a CSS variable is only visible to the
    // element that defines it and its descendants — defining it on <body> left <html>
    // unable to see it, so font-family silently fell back to the browser default serif.
    <html lang="en" className={`${quicksand.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster />
      </body>
    </html>
  );
}

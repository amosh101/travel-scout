"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X, Home, User, Bell, LogOut, Plane } from "lucide-react";

interface MobileNavProps {
  userEmail?: string;
  onLogout?: () => void;
}

export default function MobileNav({ userEmail, onLogout }: MobileNavProps) {
  const [isOpen, setIsOpen] = useState(false);
  const pathname = usePathname();

  const isActive = (path: string) => pathname === path;

  const navItems = [
    { href: "/dashboard", label: "Dashboard", icon: Home },
    { href: "/dashboard?tab=interests", label: "Interests", icon: Plane },
    { href: "/dashboard?tab=alerts", label: "Alerts", icon: Bell },
    { href: "/dashboard?tab=profile", label: "Profile", icon: User },
  ];

  return (
    <>
      {/* Mobile Header */}
      <header className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-white border-b border-gray-200">
        <div className="flex items-center justify-between px-4 py-3">
          <Link href="/dashboard" className="flex items-center gap-2">
            <div className="w-8 h-8 bg-navy-600 rounded-lg flex items-center justify-center">
              <Plane className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-lg text-navy-700">Travel Scout</span>
          </Link>

          <button
            onClick={() => setIsOpen(!isOpen)}
            className="p-2 -mr-2 text-gray-600 hover:text-gray-900"
            aria-label="Toggle menu"
          >
            {isOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>

        {/* Mobile Menu Dropdown */}
        {isOpen && (
          <div className="border-t border-gray-100 animate-fade-in">
            <nav className="px-4 py-4 space-y-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href.split("?")[0]);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setIsOpen(false)}
                    className={`flex items-center gap-3 px-3 py-3 rounded-lg transition-colors ${
                      active
                        ? "bg-navy-50 text-navy-700"
                        : "text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    <Icon className={`w-5 h-5 ${active ? "text-navy-600" : "text-gray-400"}`} />
                    <span className="font-medium">{item.label}</span>
                  </Link>
                );
              })}
            </nav>

            {userEmail && (
              <div className="border-t border-gray-100 px-4 py-4">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 bg-navy-100 rounded-full flex items-center justify-center">
                    <User className="w-5 h-5 text-navy-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900 truncate">{userEmail}</p>
                    <p className="text-sm text-gray-500">Logged in</p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    setIsOpen(false);
                    onLogout?.();
                  }}
                  className="flex items-center gap-2 w-full px-3 py-2.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                >
                  <LogOut className="w-5 h-5" />
                  <span>Sign out</span>
                </button>
              </div>
            )}
          </div>
        )}
      </header>

      {/* Spacer for fixed header */}
      <div className="lg:hidden h-14" />

      {/* Bottom Tab Bar for mobile */}
      <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-gray-200">
        <div className="flex items-center justify-around">
          {[
            { href: "/dashboard", label: "Home", icon: Home },
            { href: "/dashboard?tab=interests", label: "Interests", icon: Plane },
            { href: "/dashboard?tab=alerts", label: "Alerts", icon: Bell },
            { href: "/dashboard?tab=profile", label: "Profile", icon: User },
          ].map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href.split("?")[0]);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-col items-center justify-center flex-1 py-2 px-1 ${
                  active ? "text-navy-600" : "text-gray-400"
                }`}
              >
                <div
                  className={`p-1.5 rounded-lg ${active ? "bg-navy-50" : ""}`}
                >
                  <Icon className="w-5 h-5" />
                </div>
                <span className="text-xs mt-0.5">{item.label}</span>
              </Link>
            );
          })}
        </div>
        {/* Safe area padding for iOS */}
        <div className="h-safe-area-inset-bottom bg-white" />
      </nav>
    </>
  );
}

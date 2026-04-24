"use client";

import { Search, Bell, Plane, TrendingDown, Sparkles, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

interface EmptyStateProps {
  type: "interests" | "alerts" | "all";
  onAddInterest?: () => void;
  isScanning?: boolean;
}

export default function EmptyState({ type, onAddInterest, isScanning = false }: EmptyStateProps) {
  const [scanProgress, setScanProgress] = useState(0);
  const [showStats, setShowStats] = useState(false);

  useEffect(() => {
    if (isScanning) {
      const interval = setInterval(() => {
        setScanProgress((prev) => {
          if (prev >= 100) {
            setShowStats(true);
            return 100;
          }
          return prev + 2;
        });
      }, 100);
      return () => clearInterval(interval);
    }
  }, [isScanning]);

  const interestContent = {
    icon: Search,
    title: "No interests yet",
    description: "Add your first travel interest and let our scouts find the best deals for you.",
    action: {
      label: "Add Your First Interest",
      onClick: onAddInterest,
    },
  };

  const alertContent = {
    icon: Bell,
    title: "No alerts yet",
    description: "We'll notify you here when we find flights matching your interests.",
    action: null,
  };

  const allContent = {
    icon: Plane,
    title: "Welcome to Travel Scout",
    description: "Start by adding your first travel interest. Our scouts will monitor flights 24/7.",
    action: {
      label: "Get Started",
      onClick: onAddInterest,
    },
  };

  const content = type === "interests" ? interestContent : type === "alerts" ? alertContent : allContent;
  const Icon = content.icon;

  return (
    <div className="text-center py-12 px-4">
      {/* Scanning animation */}
      {isScanning && (
        <div className="mb-8 p-6 bg-navy-50 rounded-xl border border-navy-100">
          <div className="flex items-center justify-center gap-3 mb-4">
            <Loader2 className="w-6 h-6 text-navy-600 animate-spin" />
            <span className="text-navy-700 font-medium">Scouts are searching...</span>
          </div>
          <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-navy-500 to-accent-500 transition-all duration-300"
              style={{ width: `${scanProgress}%` }}
            />
          </div>
          <p className="text-sm text-gray-500 mt-2">
            {scanProgress < 100
              ? `Scanning ${Math.floor(scanProgress * 4.7)} flights...`
              : "Scan complete!"}
          </p>

          {showStats && (
            <div className="mt-4 pt-4 border-t border-navy-200 grid grid-cols-3 gap-4 animate-fade-in">
              <div className="text-center">
                <div className="text-2xl font-bold text-navy-700">47</div>
                <div className="text-xs text-gray-500">Flights analyzed</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-navy-700">12</div>
                <div className="text-xs text-gray-500">Routes monitored</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-accent-600">3</div>
                <div className="text-xs text-gray-500">Deals found</div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main empty state */}
      <div className="relative inline-flex items-center justify-center w-20 h-20 mb-6">
        <div className="absolute inset-0 bg-navy-100 rounded-full animate-pulse-slow" />
        <div className="absolute inset-2 bg-navy-50 rounded-full" />
        <Icon className="relative w-8 h-8 text-navy-600" />
      </div>

      <h3 className="text-xl font-semibold text-gray-900 mb-2">{content.title}</h3>
      <p className="text-gray-500 max-w-sm mx-auto mb-6">{content.description}</p>

      {content.action && (
        <button
          onClick={content.action.onClick}
          className="inline-flex items-center gap-2 px-6 py-3 bg-navy-600 text-white font-medium rounded-xl hover:bg-navy-700 transition-all btn-premium"
        >
          <Sparkles className="w-4 h-4" />
          {content.action.label}
        </button>
      )}

      {/* Recent deals teaser */}
      {type === "alerts" && (
        <div className="mt-8 p-4 bg-gray-50 rounded-xl">
          <p className="text-sm text-gray-600 font-medium mb-3">Recent deals found for others</p>
          <div className="flex flex-wrap justify-center gap-2">
            {[
              { route: "JNB → CPT", price: "$89", drop: "-32%" },
              { route: "MPM → LIS", price: "$520", drop: "-18%" },
              { route: "LOS → LHR", price: "$380", drop: "-25%" },
            ].map((deal) => (
              <div
                key={deal.route}
                className="flex items-center gap-2 px-3 py-1.5 bg-white rounded-full border border-gray-200 text-sm"
              >
                <span className="font-medium text-gray-700">{deal.route}</span>
                <span className="text-navy-600 font-bold">{deal.price}</span>
                <span className="flex items-center gap-0.5 text-green-600 text-xs">
                  <TrendingDown className="w-3 h-3" />
                  {deal.drop}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

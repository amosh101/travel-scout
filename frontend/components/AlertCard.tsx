"use client";

import { useState } from "react";
import { Plane, ArrowRight, Clock, Bell, Check, X, ExternalLink, TrendingDown, Calendar } from "lucide-react";

export interface Alert {
  id: string;
  origin: string;
  destination: string;
  airline?: string | null;
  price?: number | null;
  currency: string;
  depart_date?: string | null;
  return_date?: string | null;
  found_at: string;
  notified: boolean;
  booking_url?: string | null;
  price_drop?: number | null;
}

interface AlertCardProps {
  alert: Alert;
  onDismiss?: (id: string) => void;
  isExample?: boolean;
}

export default function AlertCard({ alert, onDismiss, isExample = false }: AlertCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const formatPrice = (price: number | null | undefined, currency: string): string => {
    if (!price) return "N/A";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(price);
  };

  const formatDate = (dateStr: string | null | undefined): string => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  };

  const timeAgo = (dateStr: string): string => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

    if (diffInMinutes < 1) return "Just now";
    if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
    if (diffInMinutes < 1440) return `${Math.floor(diffInMinutes / 60)}h ago`;
    return `${Math.floor(diffInMinutes / 1440)}d ago`;
  };

  const handleDismiss = () => {
    setDismissed(true);
    setTimeout(() => onDismiss?.(alert.id), 300);
  };

  if (dismissed) {
    return null;
  }

  return (
    <div
      className={`relative bg-white rounded-xl border overflow-hidden transition-all duration-300 ${
        isHovered ? "shadow-lg scale-[1.02]" : "shadow-sm"
      } ${isExample ? "border-accent-400 bg-gradient-to-br from-white to-accent-50" : "border-gray-200"}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Example badge */}
      {isExample && (
        <div className="absolute top-3 right-3 px-2 py-1 bg-accent-100 text-accent-700 text-xs font-semibold rounded-full">
          Example
        </div>
      )}

      {/* Price drop indicator */}
      {alert.price_drop && alert.price_drop > 0 && (
        <div className="absolute top-0 left-0 bg-green-500 text-white text-xs font-semibold px-3 py-1 rounded-br-lg">
          <div className="flex items-center gap-1">
            <TrendingDown className="w-3 h-3" />
            <span>-{alert.price_drop}%</span>
          </div>
        </div>
      )}

      <div className="p-5">
        {/* Header - Route */}
        <div className="flex items-center gap-4 mb-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-navy-100 rounded-xl flex items-center justify-center">
              <span className="text-navy-700 font-bold text-lg">{alert.origin}</span>
            </div>
            <div className="flex flex-col items-center">
              <ArrowRight className="w-5 h-5 text-gray-400" />
              <Plane className="w-3 h-3 text-gray-300 -mt-1" />
            </div>
            <div className="w-12 h-12 bg-navy-100 rounded-xl flex items-center justify-center">
              <span className="text-navy-700 font-bold text-lg">{alert.destination}</span>
            </div>
          </div>

          <div className="ml-auto text-right">
            <div className="text-2xl font-bold text-navy-700">
              {formatPrice(alert.price, alert.currency)}
            </div>
            <div className="text-xs text-gray-500">per person</div>
          </div>
        </div>

        {/* Flight details */}
        <div className="space-y-2">
          {alert.airline && (
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <span className="font-medium">{alert.airline}</span>
            </div>
          )}

          {(alert.depart_date || alert.return_date) && (
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <Calendar className="w-4 h-4 text-gray-400" />
              <span>
                {alert.depart_date && formatDate(alert.depart_date)}
                {alert.depart_date && alert.return_date && " → "}
                {alert.return_date && formatDate(alert.return_date)}
              </span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-100">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Clock className="w-3 h-3" />
            <span>Found {timeAgo(alert.found_at)}</span>
            {alert.notified && (
              <span className="flex items-center gap-1 text-green-600">
                <Bell className="w-3 h-3" />
                Notified
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {!isExample && onDismiss && (
              <button
                onClick={handleDismiss}
                className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                title="Dismiss alert"
              >
                <X className="w-4 h-4" />
              </button>
            )}
            {alert.booking_url && (
              <a
                href={alert.booking_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 px-3 py-1.5 bg-accent-600 text-white text-sm font-medium rounded-lg hover:bg-accent-700 transition-colors"
              >
                Book
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

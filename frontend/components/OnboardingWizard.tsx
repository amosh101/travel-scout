"use client";

import { useState } from "react";
import { ChevronRight, ChevronLeft, Check, Plane, Calendar, Bell, MapPin, Sparkles } from "lucide-react";
import AirportAutocomplete from "./AirportAutocomplete";
import DatePicker, { DateSelection } from "./DatePicker";

export interface OnboardingData {
  origin: string;
  destination: string;
  dates: DateSelection;
  maxBudget: string;
  notificationChannels: string[];
  telegramChatId: string;
}

interface OnboardingWizardProps {
  onComplete: (data: OnboardingData) => void;
  onSkip?: () => void;
}

export default function OnboardingWizard({ onComplete, onSkip }: OnboardingWizardProps) {
  const [step, setStep] = useState(1);
  const [isAnimating, setIsAnimating] = useState(false);
  const [data, setData] = useState<OnboardingData>({
    origin: "",
    destination: "",
    dates: {
      departureDate: null,
      returnDate: null,
      flexibility: "plusminus3",
    },
    maxBudget: "",
    notificationChannels: ["telegram", "email"],
    telegramChatId: "",
  });

  const totalSteps = 5;

  const handleNext = () => {
    if (step < totalSteps) {
      setIsAnimating(true);
      setTimeout(() => {
        setStep(step + 1);
        setIsAnimating(false);
      }, 300);
    }
  };

  const handlePrev = () => {
    if (step > 1) {
      setIsAnimating(true);
      setTimeout(() => {
        setStep(step - 1);
        setIsAnimating(false);
      }, 300);
    }
  };

  const handleComplete = () => {
    onComplete(data);
  };

  const canProceed = () => {
    switch (step) {
      case 1:
        return data.origin.length >= 2;
      case 2:
        return data.destination.length >= 2;
      case 3:
        return true; // Budget is optional
      case 4:
        return data.notificationChannels.length > 0;
      case 5:
        return true;
      default:
        return false;
    }
  };

  const steps = [
    { icon: MapPin, title: "Where from?", description: "Tell us your home airport" },
    { icon: Plane, title: "Where to?", description: "Choose your destination" },
    { icon: Calendar, title: "When?", description: "Set your travel dates" },
    { icon: Bell, title: "Stay notified", description: "Choose how we alert you" },
    { icon: Sparkles, title: "All set!", description: "Ready to find great deals" },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/90 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-white rounded-2xl shadow-2xl overflow-hidden">
        {/* Header with progress */}
        <div className="bg-gradient-to-r from-navy-600 to-navy-700 p-6 text-white">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-white/20 rounded-lg flex items-center justify-center">
                <Plane className="w-4 h-4" />
              </div>
              <span className="font-bold">Travel Scout</span>
            </div>
            <span className="text-sm text-white/70">Step {step} of {totalSteps}</span>
          </div>

          {/* Progress bar */}
          <div className="w-full h-1.5 bg-white/20 rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-500 transition-all duration-500 ease-out"
              style={{ width: `${(step / totalSteps) * 100}%` }}
            />
          </div>
        </div>

        {/* Content */}
        <div className={`p-6 transition-opacity duration-300 ${isAnimating ? "opacity-0" : "opacity-100"}`}>
          {/* Step indicator */}
          <div className="flex items-center gap-4 mb-6">
            <div className="w-12 h-12 bg-navy-100 rounded-xl flex items-center justify-center">
              {(() => {
                const Icon = steps[step - 1].icon;
                return <Icon className="w-6 h-6 text-navy-600" />;
              })()}
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">{steps[step - 1].title}</h2>
              <p className="text-sm text-gray-500">{steps[step - 1].description}</p>
            </div>
          </div>

          {/* Step content */}
          <div className="space-y-6">
            {step === 1 && (
              <div>
                <AirportAutocomplete
                  value={data.origin}
                  onChange={(origin) => setData({ ...data, origin })}
                  label="Origin Airport"
                  placeholder="Search by city or airport code..."
                  required
                />
                <div className="mt-4 p-4 bg-navy-50 rounded-lg">
                  <p className="text-sm text-navy-700">
                    <strong>Tip:</strong> Enter your home airport. You can add more interests later for different origins.
                  </p>
                </div>
              </div>
            )}

            {step === 2 && (
              <div>
                <div className="mb-4">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Destination Region
                  </label>
                  <input
                    type="text"
                    value={data.destination}
                    onChange={(e) => setData({ ...data, destination: e.target.value })}
                    placeholder="e.g., Europe, Japan, South Africa"
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-navy-600 focus:border-transparent"
                    required
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {["Europe", "Asia", "Africa", "Americas", "Middle East"].map((region) => (
                    <button
                      key={region}
                      type="button"
                      onClick={() => setData({ ...data, destination: region })}
                      className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
                        data.destination === region
                          ? "bg-navy-600 text-white"
                          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                      }`}
                    >
                      {region}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {step === 3 && (
              <div>
                <DatePicker
                  value={data.dates}
                  onChange={(dates) => setData({ ...data, dates })}
                  label="Travel Dates"
                  showReturnDate={true}
                />
                <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkles className="w-4 h-4 text-accent-500" />
                    <span className="font-medium text-gray-900">Smart Tip</span>
                  </div>
                  <p className="text-sm text-gray-600">
                    Being flexible with dates can save you up to 40%. We&apos;ll find the best deals within your flexibility window.
                  </p>
                </div>
                <div className="mt-4">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Max Budget (USD) - Optional
                  </label>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500">$</span>
                    <input
                      type="number"
                      value={data.maxBudget}
                      onChange={(e) => setData({ ...data, maxBudget: e.target.value })}
                      placeholder="e.g., 500"
                      className="w-full pl-8 pr-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-navy-600 focus:border-transparent"
                    />
                  </div>
                </div>
              </div>
            )}

            {step === 4 && (
              <div className="space-y-4">
                <div className="space-y-3">
                  {[
                    {
                      value: "telegram",
                      label: "Telegram",
                      description: "Fast, reliable notifications on your phone",
                    },
                    {
                      value: "email",
                      label: "Email",
                      description: "Daily digest of all matching deals",
                    },
                  ].map((channel) => (
                    <label
                      key={channel.value}
                      className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-all ${
                        data.notificationChannels.includes(channel.value)
                          ? "border-navy-600 bg-navy-50"
                          : "border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={data.notificationChannels.includes(channel.value)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setData({
                              ...data,
                              notificationChannels: [...data.notificationChannels, channel.value],
                            });
                          } else {
                            setData({
                              ...data,
                              notificationChannels: data.notificationChannels.filter(
                                (c) => c !== channel.value
                              ),
                            });
                          }
                        }}
                        className="mt-1"
                      />
                      <div>
                        <p className="font-medium text-gray-900">{channel.label}</p>
                        <p className="text-sm text-gray-500">{channel.description}</p>
                      </div>
                    </label>
                  ))}
                </div>

                {data.notificationChannels.includes("telegram") && (
                  <div className="p-4 bg-blue-50 rounded-lg space-y-3">
                    <p className="font-medium text-blue-900">Set up Telegram notifications:</p>
                    <ol className="text-sm text-blue-800 list-decimal list-inside space-y-2">
                      <li>Message <strong>@BotFather</strong> on Telegram</li>
                      <li>Create a new bot with /newbot</li>
                      <li>Copy your bot token and chat ID</li>
                    </ol>
                    <input
                      type="text"
                      value={data.telegramChatId}
                      onChange={(e) => setData({ ...data, telegramChatId: e.target.value })}
                      placeholder="Your Telegram Chat ID (optional for now)"
                      className="w-full px-3 py-2 border border-blue-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  </div>
                )}
              </div>
            )}

            {step === 5 && (
              <div className="text-center py-4">
                <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Check className="w-10 h-10 text-green-600" />
                </div>
                <h3 className="text-xl font-bold text-gray-900 mb-2">You&apos;re all set!</h3>
                <p className="text-gray-600 mb-6">
                  We&apos;ll start scanning for deals matching your interests. You&apos;ll receive your first alert soon.
                </p>
                <div className="bg-gray-50 rounded-lg p-4 text-left space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">From:</span>
                    <span className="font-medium">{data.origin}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">To:</span>
                    <span className="font-medium">{data.destination}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">Notifications:</span>
                    <span className="font-medium capitalize">{data.notificationChannels.join(", ")}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-gray-200 flex items-center justify-between">
          {step > 1 ? (
            <button
              onClick={handlePrev}
              className="flex items-center gap-1 px-4 py-2 text-gray-600 hover:text-gray-900 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
              Back
            </button>
          ) : (
            <button
              onClick={onSkip}
              className="px-4 py-2 text-gray-500 hover:text-gray-700 transition-colors"
            >
                Skip
            </button>
          )}

          <button
            onClick={step === totalSteps ? handleComplete : handleNext}
            disabled={!canProceed()}
            className="flex items-center gap-1 px-6 py-2.5 bg-navy-600 text-white font-medium rounded-lg hover:bg-navy-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {step === totalSteps ? (
              <>
                Start Scouting
                <Sparkles className="w-4 h-4" />
              </>
            ) : (
              <>
                Next
                <ChevronRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

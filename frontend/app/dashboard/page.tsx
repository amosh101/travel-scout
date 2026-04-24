"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import axios from "axios";
import AirportAutocomplete from "@/components/AirportAutocomplete";
import DatePicker, { DateSelection } from "@/components/DatePicker";
import TelegramSetup from "@/components/TelegramSetup";
import AlertCard, { Alert } from "@/components/AlertCard";
import EmptyState from "@/components/EmptyState";
import MobileNav from "@/components/MobileNav";
import OnboardingWizard, { OnboardingData } from "@/components/OnboardingWizard";
import { 
  Plus, 
  Bell, 
  Settings, 
  LogOut, 
  ChevronDown, 
  ChevronUp,
  Send,
  CheckCircle,
  Plane,
  Trash2,
  User,
  Sparkles,
  RefreshCw
} from "lucide-react";

interface User {
  id: string;
  email: string;
  name: string | null;
  telegram_chat_id: string | null;
}

interface Interest {
  id: string;
  name: string;
  origin_airport: string | null;
  destination_region: string | null;
  event_keywords: string | null;
  max_budget: number | null;
  notification_channels: string[];
  active: boolean;
}

// Component to handle URL params with Suspense
function SearchParamsHandler({ onTabChange }: { onTabChange: (tab: "interests" | "alerts" | "profile") => void }) {
  const searchParams = useSearchParams();
  
  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab === "interests" || tab === "alerts" || tab === "profile") {
      onTabChange(tab);
    }
  }, [searchParams, onTabChange]);
  
  return null;
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);
  const [showProfileSettings, setShowProfileSettings] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [activeTab, setActiveTab] = useState<"interests" | "alerts" | "profile">("interests");
  const [isScanning, setIsScanning] = useState(false);

  // Form state
  const [formName, setFormName] = useState("");
  const [formOrigin, setFormOrigin] = useState("");
  const [formDestination, setFormDestination] = useState("");
  const [formBudget, setFormBudget] = useState("");
  const [formDates, setFormDates] = useState<DateSelection>({
    departureDate: null,
    returnDate: null,
    flexibility: "plusminus3",
  });
  const [formChannels, setFormChannels] = useState<string[]>(["telegram", "email"]);

  // Telegram setup state
  const [telegramChatId, setTelegramChatId] = useState("");
  const [telegramBotToken, setTelegramBotToken] = useState("");
  const [testNotificationStatus, setTestNotificationStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");

  const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001",
  });

  // Add token to requests
  api.interceptors.request.use((config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/login");
      return;
    }

    fetchData();
  }, []);

  // Tab change handler for URL params
  const handleTabChange = useCallback((tab: "interests" | "alerts" | "profile") => {
    setActiveTab(tab);
  }, []);

  const fetchData = async () => {
    try {
      const [userRes, interestsRes, alertsRes] = await Promise.all([
        api.get("/api/auth/me"),
        api.get("/api/interests"),
        api.get("/api/alerts"),
      ]);
      setUser(userRes.data);
      setInterests(interestsRes.data);
      setAlerts(alertsRes.data);
      setTelegramChatId(userRes.data.telegram_chat_id || "");

      // Show onboarding if user has no interests
      if (interestsRes.data.length === 0) {
        setShowOnboarding(true);
        setIsScanning(true);
        setTimeout(() => setIsScanning(false), 5000);
      }
    } catch (err) {
      localStorage.removeItem("token");
      router.push("/login");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    router.push("/");
  };

  const handleAddInterest = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/api/interests", {
        name: formName,
        origin_airport: formOrigin || null,
        destination_region: formDestination || null,
        max_budget: formBudget ? parseFloat(formBudget) : null,
        notification_channels: formChannels,
        date_flexibility: formDates.flexibility,
        preferred_departure_date: formDates.departureDate,
        preferred_return_date: formDates.returnDate,
      });
      setShowAddForm(false);
      resetForm();
      fetchData();
    } catch (err) {
      alert("Failed to add interest");
    }
  };

  const handleOnboardingComplete = async (data: OnboardingData) => {
    try {
      await api.post("/api/interests", {
        name: `${data.origin} to ${data.destination}`,
        origin_airport: data.origin,
        destination_region: data.destination,
        max_budget: data.maxBudget ? parseFloat(data.maxBudget) : null,
        notification_channels: data.notificationChannels,
      });

      if (data.telegramChatId) {
        await updateTelegramChatId(data.telegramChatId);
      }

      setShowOnboarding(false);
      fetchData();
    } catch (err) {
      alert("Failed to create interest");
    }
  };

  const updateTelegramChatId = async (chatId: string) => {
    try {
      await api.put("/api/users/me", { telegram_chat_id: chatId });
      setTelegramChatId(chatId);
    } catch (err) {
      console.error("Failed to update Telegram chat ID");
    }
  };

  const handleToggleInterest = async (id: string, active: boolean) => {
    try {
      await api.put(`/api/interests/${id}`, { active: !active });
      fetchData();
    } catch (err) {
      alert("Failed to update interest");
    }
  };

  const handleDeleteInterest = async (id: string) => {
    if (!confirm("Are you sure you want to delete this interest?")) return;
    try {
      await api.delete(`/api/interests/${id}`);
      fetchData();
    } catch (err) {
      alert("Failed to delete interest");
    }
  };

  const resetForm = () => {
    setFormName("");
    setFormOrigin("");
    setFormDestination("");
    setFormBudget("");
    setFormDates({
      departureDate: null,
      returnDate: null,
      flexibility: "plusminus3",
    });
    setFormChannels(["telegram", "email"]);
  };

  const handleChannelChange = (channel: string) => {
    if (formChannels.includes(channel)) {
      setFormChannels(formChannels.filter((c) => c !== channel));
    } else {
      setFormChannels([...formChannels, channel]);
    }
  };

  const handleSendTestNotification = async () => {
    if (!telegramChatId) {
      alert("Please enter your Telegram chat ID first");
      return;
    }

    setTestNotificationStatus("sending");
    try {
      await api.post("/api/notifications/test", {
        channel: "telegram",
        destination: telegramChatId,
      });
      setTestNotificationStatus("sent");
      setTimeout(() => setTestNotificationStatus("idle"), 3000);
    } catch (err) {
      setTestNotificationStatus("error");
      setTimeout(() => setTestNotificationStatus("idle"), 3000);
    }
  };

  const handleDismissAlert = async (id: string) => {
    try {
      await api.put(`/api/alerts/${id}/dismiss`, { dismissed: true });
      setAlerts(alerts.filter((a) => a.id !== id));
    } catch (err) {
      console.error("Failed to dismiss alert");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-navy-200 border-t-navy-600 rounded-full animate-spin" />
          <p className="text-gray-500 text-sm">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 pb-20 lg:pb-0">
      <Suspense fallback={null}>
        <SearchParamsHandler onTabChange={handleTabChange} />
      </Suspense>
      <MobileNav userEmail={user?.email} onLogout={handleLogout} />

      {/* Desktop Header */}
      <header className="hidden lg:block bg-white shadow-sm sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-navy-600 rounded-xl flex items-center justify-center">
                <Plane className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-navy-700">Travel Scout</h1>
                <p className="text-xs text-gray-500">Find your perfect flight</p>
              </div>
            </div>

            <div className="flex items-center gap-6">
              <nav className="flex gap-1">
                {[
                  { id: "interests", label: "Interests", icon: Plane },
                  { id: "alerts", label: "Alerts", icon: Bell },
                  { id: "profile", label: "Profile", icon: User },
                ].map((tab) => {
                  const Icon = tab.icon;
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id as typeof activeTab)}
                      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                        activeTab === tab.id
                          ? "bg-navy-100 text-navy-700"
                          : "text-gray-600 hover:bg-gray-100"
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                      {tab.label}
                      {tab.id === "alerts" && alerts.length > 0 && (
                        <span className="ml-1 px-2 py-0.5 bg-accent-500 text-white text-xs rounded-full">
                          {alerts.length}
                        </span>
                      )}
                    </button>
                  );
                })}
              </nav>

              <div className="flex items-center gap-3 pl-6 border-l border-gray-200">
                <div className="text-right">
                  <p className="text-sm font-medium text-gray-900">{user?.email}</p>
                </div>
                <button
                  onClick={handleLogout}
                  className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                  title="Sign out"
                >
                  <LogOut className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
        {/* Interests Tab */}
        {activeTab === "interests" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold text-gray-900">Your Interests</h2>
                <p className="text-gray-500 mt-1">
                  {interests.length === 0
                    ? "Add an interest to start tracking flight deals"
                    : `${interests.length} interest${interests.length !== 1 ? "s" : ""} active`}
                </p>
              </div>
              <button
                onClick={() => setShowAddForm(true)}
                className="flex items-center gap-2 px-4 py-2.5 bg-navy-600 text-white font-medium rounded-xl hover:bg-navy-700 transition-colors btn-premium"
              >
                <Plus className="w-5 h-5" />
                Add Interest
              </button>
            </div>

            {/* Add Interest Modal */}
            {showAddForm && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
                <div className="w-full max-w-2xl bg-white rounded-2xl shadow-2xl overflow-hidden animate-slide-up">
                  <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-navy-100 rounded-xl flex items-center justify-center">
                        <Sparkles className="w-5 h-5 text-navy-600" />
                      </div>
                      <div>
                        <h3 className="text-lg font-bold text-gray-900">Add New Interest</h3>
                        <p className="text-sm text-gray-500">Tell us what flights to watch for</p>
                      </div>
                    </div>
                    <button
                      onClick={() => setShowAddForm(false)}
                      className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
                    >
                      ×
                    </button>
                  </div>

                  <form onSubmit={handleAddInterest} className="p-6 space-y-5">
                    <div className="grid md:grid-cols-2 gap-5">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1.5">
                          Interest Name <span className="text-red-500">*</span>
                        </label>
                        <input
                          type="text"
                          value={formName}
                          onChange={(e) => setFormName(e.target.value)}
                          required
                          placeholder="e.g., Summer Europe Trip"
                          className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-navy-600 focus:border-transparent transition-all"
                        />
                      </div>

                      <div>
                        <AirportAutocomplete
                          value={formOrigin}
                          onChange={setFormOrigin}
                          label="Origin Airport"
                          placeholder="Search airports..."
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1.5">
                          Destination Region
                        </label>
                        <input
                          type="text"
                          value={formDestination}
                          onChange={(e) => setFormDestination(e.target.value)}
                          placeholder="e.g., Europe, Japan, South Africa"
                          className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-navy-600 focus:border-transparent transition-all"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1.5">
                          Max Budget (USD)
                        </label>
                        <div className="relative">
                          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500">$</span>
                          <input
                            type="number"
                            value={formBudget}
                            onChange={(e) => setFormBudget(e.target.value)}
                            placeholder="e.g., 500"
                            className="w-full pl-8 pr-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-navy-600 focus:border-transparent transition-all"
                          />
                        </div>
                      </div>
                    </div>

                    <DatePicker
                      value={formDates}
                      onChange={setFormDates}
                      label="Travel Dates (Optional)"
                      showReturnDate={true}
                    />

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Notification Channels
                      </label>
                      <div className="flex flex-wrap gap-3">
                        {["telegram", "email"].map((channel) => (
                          <label
                            key={channel}
                            className={`flex items-center gap-2 px-4 py-2 rounded-xl border cursor-pointer transition-all ${
                              formChannels.includes(channel)
                                ? "border-navy-600 bg-navy-50"
                                : "border-gray-200 hover:border-gray-300"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={formChannels.includes(channel)}
                              onChange={() => handleChannelChange(channel)}
                              className="sr-only"
                            />
                            <div
                              className={`w-4 h-4 rounded border flex items-center justify-center ${
                                formChannels.includes(channel)
                                  ? "bg-navy-600 border-navy-600"
                                  : "border-gray-300"
                              }`}
                            >
                              {formChannels.includes(channel) && (
                                <CheckCircle className="w-3 h-3 text-white" />
                              )}
                            </div>
                            <span className="capitalize font-medium">{channel}</span>
                          </label>
                        ))}
                      </div>
                    </div>

                    <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
                      <button
                        type="button"
                        onClick={() => setShowAddForm(false)}
                        className="px-6 py-2.5 text-gray-600 hover:text-gray-900 font-medium transition-colors"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        className="px-6 py-2.5 bg-navy-600 text-white font-medium rounded-xl hover:bg-navy-700 transition-colors btn-premium"
                      >
                        Save Interest
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {/* Interests List */}
            {interests.length === 0 ? (
              <EmptyState
                type="interests"
                onAddInterest={() => setShowAddForm(true)}
                isScanning={isScanning}
              />
            ) : (
              <div className="grid gap-4">
                {interests.map((interest) => (
                  <div
                    key={interest.id}
                    className={`bg-white rounded-xl border transition-all card-hover ${
                      interest.active ? "border-gray-200" : "border-gray-100 bg-gray-50/50"
                    }`}
                  >
                    <div className="p-5">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-2">
                            <h3 className="font-bold text-gray-900 truncate">{interest.name}</h3>
                            <button
                              onClick={() => handleToggleInterest(interest.id, interest.active)}
                              className={`px-2.5 py-1 text-xs font-semibold rounded-full transition-colors ${
                                interest.active
                                  ? "bg-green-100 text-green-700"
                                  : "bg-gray-100 text-gray-500"
                              }`}
                            >
                              {interest.active ? "Active" : "Paused"}
                            </button>
                          </div>

                          <div className="flex flex-wrap items-center gap-4 text-sm text-gray-600">
                            {interest.origin_airport && (
                              <div className="flex items-center gap-1">
                                <Plane className="w-4 h-4 text-navy-400" />
                                <span className="font-medium">{interest.origin_airport}</span>
                              </div>
                            )}
                            {interest.destination_region && (
                              <>
                                <span className="text-gray-400">→</span>
                                <span>{interest.destination_region}</span>
                              </>
                            )}
                            {interest.max_budget && (
                              <>
                                <span className="text-gray-400">•</span>
                                <span className="text-navy-600 font-medium">
                                  Up to ${interest.max_budget}
                                </span>
                              </>
                            )}
                          </div>

                          <div className="flex flex-wrap gap-2 mt-3">
                            {interest.notification_channels.map((ch) => (
                              <span
                                key={ch}
                                className="inline-flex items-center gap-1 px-2.5 py-1 bg-navy-50 text-navy-700 text-xs font-medium rounded-lg"
                              >
                                <Bell className="w-3 h-3" />
                                {ch}
                              </span>
                            ))}
                          </div>
                        </div>

                        <button
                          onClick={() => handleDeleteInterest(interest.id)}
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                          title="Delete interest"
                        >
                          <Trash2 className="w-5 h-5" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Alerts Tab */}
        {activeTab === "alerts" && (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">Recent Alerts</h2>
              <p className="text-gray-500 mt-1">
                {alerts.length === 0
                  ? "No alerts yet - we'll notify you when we find deals"
                  : `${alerts.length} alert${alerts.length !== 1 ? "s" : ""} found`}
              </p>
            </div>

            {alerts.length === 0 ? (
              <div className="space-y-6">
                <EmptyState type="alerts" />
                
                {/* Example Alert */}
                <div className="pt-6 border-t border-gray-200">
                  <p className="text-sm text-gray-500 mb-4">Here's what an alert will look like:</p>
                  <AlertCard
                    alert={{
                      id: "example",
                      origin: "JNB",
                      destination: "CPT",
                      airline: "South African Airways",
                      price: 89,
                      currency: "USD",
                      depart_date: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split("T")[0],
                      found_at: new Date().toISOString(),
                      notified: true,
                      booking_url: "#",
                      price_drop: 32,
                    }}
                    isExample={true}
                  />
                </div>
              </div>
            ) : (
              <div className="grid gap-4">
                {alerts.map((alert) => (
                  <AlertCard
                    key={alert.id}
                    alert={alert}
                    onDismiss={handleDismissAlert}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Profile Tab */}
        {activeTab === "profile" && (
          <div className="max-w-2xl space-y-6">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">Profile Settings</h2>
              <p className="text-gray-500 mt-1">Manage your account and notification preferences</p>
            </div>

            {/* Account Info */}
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100 bg-gray-50">
                <h3 className="font-semibold text-gray-900">Account Information</h3>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                  <input
                    type="email"
                    value={user?.email || ""}
                    disabled
                    className="w-full px-4 py-2 bg-gray-100 border border-gray-200 rounded-lg text-gray-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    type="text"
                    value={user?.name || ""}
                    disabled
                    className="w-full px-4 py-2 bg-gray-100 border border-gray-200 rounded-lg text-gray-500"
                  />
                </div>
              </div>
            </div>

            {/* Telegram Setup */}
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100 bg-gray-50">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-gray-900">Telegram Notifications</h3>
                  {telegramChatId && testNotificationStatus === "sent" && (
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 bg-green-500 rounded-full" />
                      <span className="text-sm text-green-600">Active</span>
                    </div>
                  )}
                </div>
              </div>
              <div className="p-6">
                <TelegramSetup
                  chatId={telegramChatId}
                  onChatIdChange={setTelegramChatId}
                  onVerify={async () => {
                    try {
                      await api.put("/api/users/me", { telegram_chat_id: telegramChatId });
                      const result = await api.post("/api/notifications/test", {
                        channel: "telegram",
                        destination: telegramChatId,
                      });
                      return true;
                    } catch (err) {
                      return false;
                    }
                  }}
                  testStatus={testNotificationStatus}
                />
              </div>
            </div>

            {/* Danger Zone */}
            <div className="bg-white rounded-xl border border-red-200 overflow-hidden">
              <div className="px-6 py-4 border-b border-red-100 bg-red-50">
                <h3 className="font-semibold text-red-900">Danger Zone</h3>
              </div>
              <div className="p-6">
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 px-4 py-2 text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  Sign Out
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Onboarding Modal */}
      {showOnboarding && (
        <OnboardingWizard
          onComplete={handleOnboardingComplete}
          onSkip={() => setShowOnboarding(false)}
        />
      )}
    </div>
  );
}

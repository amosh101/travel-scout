"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";

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

interface Alert {
  id: string;
  origin: string;
  destination: string;
  airline: string | null;
  price: number | null;
  currency: string;
  depart_date: string | null;
  found_at: string;
  notified: boolean;
}

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);
  const [loading, setLoading] = useState(true);

  // Form state
  const [formName, setFormName] = useState("");
  const [formOrigin, setFormOrigin] = useState("");
  const [formDestination, setFormDestination] = useState("");
  const [formBudget, setFormBudget] = useState("");
  const [formChannels, setFormChannels] = useState<string[]>(["telegram", "email"]);

  const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL,
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
      });
      setShowAddForm(false);
      resetForm();
      fetchData();
    } catch (err) {
      alert("Failed to add interest");
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
    setFormChannels(["telegram", "email"]);
  };

  const handleChannelChange = (channel: string) => {
    if (formChannels.includes(channel)) {
      setFormChannels(formChannels.filter((c) => c !== channel));
    } else {
      setFormChannels([...formChannels, channel]);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-900">Travel Scout</h1>
          <div className="flex items-center gap-4">
            <span className="text-gray-600">{user?.email}</span>
            <button
              onClick={handleLogout}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid lg:grid-cols-3 gap-8">
          {/* Interests Section */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-semibold text-gray-900">
                  Your Interests
                </h2>
                <button
                  onClick={() => setShowAddForm(!showAddForm)}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
                >
                  {showAddForm ? "Cancel" : "+ Add Interest"}
                </button>
              </div>

              {/* Add Interest Form */}
              {showAddForm && (
                <form onSubmit={handleAddInterest} className="mb-6 p-4 bg-gray-50 rounded-lg space-y-4">
                  <div className="grid md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Interest Name
                      </label>
                      <input
                        type="text"
                        value={formName}
                        onChange={(e) => setFormName(e.target.value)}
                        required
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                        placeholder="e.g., Europe Summer Trip"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Origin Airport
                      </label>
                      <input
                        type="text"
                        value={formOrigin}
                        onChange={(e) => setFormOrigin(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                        placeholder="e.g., MPM, JNB"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Destination Region
                      </label>
                      <input
                        type="text"
                        value={formDestination}
                        onChange={(e) => setFormDestination(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                        placeholder="e.g., Europe, UK, USA"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Max Budget (USD)
                      </label>
                      <input
                        type="number"
                        value={formBudget}
                        onChange={(e) => setFormBudget(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                        placeholder="e.g., 500"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Notification Channels
                    </label>
                    <div className="flex gap-4">
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={formChannels.includes("telegram")}
                          onChange={() => handleChannelChange("telegram")}
                          className="mr-2"
                        />
                        Telegram
                      </label>
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          checked={formChannels.includes("email")}
                          onChange={() => handleChannelChange("email")}
                          className="mr-2"
                        />
                        Email
                      </label>
                    </div>
                  </div>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                  >
                    Save Interest
                  </button>
                </form>
              )}

              {/* Interests List */}
              {interests.length === 0 ? (
                <p className="text-gray-500 text-center py-8">
                  No interests yet. Add one to start tracking flight deals.
                </p>
              ) : (
                <div className="space-y-3">
                  {interests.map((interest) => (
                    <div
                      key={interest.id}
                      className={`p-4 border rounded-lg ${
                        interest.active ? "border-gray-200" : "border-gray-100 bg-gray-50"
                      }`}
                    >
                      <div className="flex justify-between items-start">
                        <div>
                          <h3 className="font-medium text-gray-900">
                            {interest.name}
                          </h3>
                          <p className="text-sm text-gray-500 mt-1">
                            {interest.origin_airport || "Any"} →{" "}
                            {interest.destination_region || "Any"}
                            {interest.max_budget && ` (up to $${interest.max_budget})`}
                          </p>
                          <div className="flex gap-2 mt-2">
                            {interest.notification_channels.map((ch) => (
                              <span
                                key={ch}
                                className="text-xs px-2 py-1 bg-gray-100 text-gray-600 rounded"
                              >
                                {ch}
                              </span>
                            ))}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleToggleInterest(interest.id, interest.active)}
                            className={`px-3 py-1 text-sm rounded ${
                              interest.active
                                ? "bg-green-100 text-green-700"
                                : "bg-gray-100 text-gray-500"
                            }`}
                          >
                            {interest.active ? "Active" : "Paused"}
                          </button>
                          <button
                            onClick={() => handleDeleteInterest(interest.id)}
                            className="text-red-500 hover:text-red-700 text-sm"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Alerts & Profile Section */}
          <div className="space-y-6">
            {/* Recent Alerts */}
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">
                Recent Alerts
              </h2>
              {alerts.length === 0 ? (
                <p className="text-gray-500 text-sm">No alerts yet</p>
              ) : (
                <div className="space-y-3">
                  {alerts.slice(0, 5).map((alert) => (
                    <div key={alert.id} className="p-3 bg-blue-50 rounded-lg">
                      <p className="font-medium text-gray-900">
                        {alert.origin} → {alert.destination}
                      </p>
                      <p className="text-sm text-gray-600">
                        {alert.airline} • {alert.currency} {alert.price}
                      </p>
                      <p className="text-xs text-gray-400 mt-1">
                        {new Date(alert.found_at).toLocaleDateString()}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Profile Settings */}
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">
                Profile Settings
              </h2>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Telegram Chat ID
                  </label>
                  <input
                    type="text"
                    defaultValue={user?.telegram_chat_id || ""}
                    placeholder="Get from @userinfobot"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                    disabled
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Configure in settings to receive Telegram alerts
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
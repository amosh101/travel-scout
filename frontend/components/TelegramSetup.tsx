"use client";

import { useState } from "react";
import { Send, CheckCircle, MessageCircle, Bot, User, ArrowRight, ExternalLink, RefreshCw } from "lucide-react";

interface TelegramSetupProps {
  chatId: string;
  onChatIdChange: (chatId: string) => void;
  onVerify: () => Promise<boolean>;
  testStatus: "idle" | "sending" | "sent" | "error";
}

const BOT_FATHER_STEPS = [
  {
    step: 1,
    action: "Open Telegram",
    detail: "Launch the Telegram app on your device",
  },
  {
    step: 2,
    action: "Search @BotFather",
    detail: "Find the official BotFather account (blue checkmark)",
  },
  {
    step: 3,
    action: "Start conversation",
    detail: "Tap 'Start' to begin chatting with BotFather",
  },
  {
    step: 4,
    action: "Create new bot",
    detail: "Send the message: /newbot",
  },
  {
    step: 5,
    action: "Follow instructions",
    detail: "BotFather will ask for a name and username for your bot",
  },
  {
    step: 6,
    action: "Copy your token",
    detail: "Save the bot token (it looks like: 123456789:ABCdefGHIjkl...)",
  },
];

const CHAT_ID_STEPS = [
  {
    step: 1,
    action: "Message @userinfobot",
    detail: "Search for @userinfobot in Telegram",
  },
  {
    step: 2,
    action: "Start conversation",
    detail: "Tap 'Start' - the bot will reply instantly",
  },
  {
    step: 3,
    action: "Copy your Chat ID",
    detail: "The bot will show your numeric ID - copy it here",
  },
];

export default function TelegramSetup({
  chatId,
  onChatIdChange,
  onVerify,
  testStatus,
}: TelegramSetupProps) {
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3>(1);

  const handleVerify = async () => {
    if (!chatId.trim()) return;
    await onVerify();
  };

  return (
    <div className="space-y-6">
      {/* Step indicators */}
      <div className="flex items-center justify-between">
        {[1, 2, 3].map((step) => (
          <div key={step} className="flex items-center">
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center font-semibold transition-colors ${
                currentStep === step
                  ? "bg-navy-600 text-white"
                  : currentStep > step
                  ? "bg-green-500 text-white"
                  : "bg-gray-200 text-gray-500"
              }`}
            >
              {currentStep > step ? (
                <CheckCircle className="w-5 h-5" />
              ) : (
                step
              )}
            </div>
            {step < 3 && (
              <div
                className={`w-16 sm:w-24 h-1 mx-2 transition-colors ${
                  currentStep > step ? "bg-green-500" : "bg-gray-200"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step 1: Create Bot */}
      {currentStep === 1 && (
        <div className="space-y-4">
          <div className="bg-blue-50 rounded-xl p-4 border border-blue-100">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                <Bot className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h3 className="font-semibold text-blue-900">Step 1: Create Your Bot</h3>
                <p className="text-sm text-blue-700">Message @BotFather to create a Telegram bot</p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            {BOT_FATHER_STEPS.map((step) => (
              <div
                key={step.step}
                className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg"
              >
                <span className="w-6 h-6 bg-gray-200 rounded-full flex items-center justify-center text-xs font-medium text-gray-600 flex-shrink-0">
                  {step.step}
                </span>
                <div>
                  <p className="font-medium text-gray-900">{step.action}</p>
                  <p className="text-sm text-gray-500">{step.detail}</p>
                </div>
              </div>
            ))}
          </div>

          <a
            href="https://t.me/BotFather"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 w-full py-3 bg-[#0088cc] text-white rounded-xl font-medium hover:bg-[#0077b3] transition-colors"
          >
            <MessageCircle className="w-5 h-5" />
            Open @BotFather in Telegram
            <ExternalLink className="w-4 h-4" />
          </a>

          <button
            onClick={() => setCurrentStep(2)}
            className="flex items-center justify-center gap-2 w-full py-3 bg-navy-600 text-white rounded-xl font-medium hover:bg-navy-700 transition-colors"
          >
            I&apos;ve created my bot
            <ArrowRight className="w-5 h-5" />
          </button>
        </div>
      )}

      {/* Step 2: Get Chat ID */}
      {currentStep === 2 && (
        <div className="space-y-4">
          <div className="bg-purple-50 rounded-xl p-4 border border-purple-100">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                <User className="w-5 h-5 text-purple-600" />
              </div>
              <div>
                <h3 className="font-semibold text-purple-900">Step 2: Get Your Chat ID</h3>
                <p className="text-sm text-purple-700">Use @userinfobot to find your Telegram ID</p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            {CHAT_ID_STEPS.map((step) => (
              <div
                key={step.step}
                className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg"
              >
                <span className="w-6 h-6 bg-gray-200 rounded-full flex items-center justify-center text-xs font-medium text-gray-600 flex-shrink-0">
                  {step.step}
                </span>
                <div>
                  <p className="font-medium text-gray-900">{step.action}</p>
                  <p className="text-sm text-gray-500">{step.detail}</p>
                </div>
              </div>
            ))}
          </div>

          <a
            href="https://t.me/userinfobot"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 w-full py-3 bg-[#0088cc] text-white rounded-xl font-medium hover:bg-[#0077b3] transition-colors"
          >
            <MessageCircle className="w-5 h-5" />
            Open @userinfobot in Telegram
            <ExternalLink className="w-4 h-4" />
          </a>

          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            <p className="text-sm text-yellow-800">
              <strong>Tip:</strong> The Chat ID is a number like <code className="bg-yellow-100 px-1 rounded">123456789</code>
            </p>
          </div>

          <button
            onClick={() => setCurrentStep(3)}
            className="flex items-center justify-center gap-2 w-full py-3 bg-navy-600 text-white rounded-xl font-medium hover:bg-navy-700 transition-colors"
          >
            I have my Chat ID
            <ArrowRight className="w-5 h-5" />
          </button>

          <button
            onClick={() => setCurrentStep(1)}
            className="flex items-center justify-center gap-2 w-full py-3 text-gray-600 hover:text-gray-900 font-medium transition-colors"
          >
            ← Back to Step 1
          </button>
        </div>
      )}

      {/* Step 3: Verify */}
      {currentStep === 3 && (
        <div className="space-y-4">
          <div className="bg-green-50 rounded-xl p-4 border border-green-100">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                <Send className="w-5 h-5 text-green-600" />
              </div>
              <div>
                <h3 className="font-semibold text-green-900">Step 3: Verify Setup</h3>
                <p className="text-sm text-green-700">Enter your Chat ID and test notifications</p>
              </div>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Your Telegram Chat ID
            </label>
            <input
              type="text"
              value={chatId}
              onChange={(e) => onChatIdChange(e.target.value)}
              placeholder="e.g., 123456789"
              className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-navy-600 focus:border-transparent transition-all"
            />
            <p className="text-xs text-gray-500 mt-1">
              Paste the numeric ID you got from @userinfobot
            </p>
          </div>

          <button
            onClick={handleVerify}
            disabled={!chatId.trim() || testStatus === "sending"}
            className={`flex items-center justify-center gap-2 w-full py-3 rounded-xl font-medium transition-colors ${
              testStatus === "sent"
                ? "bg-green-100 text-green-700"
                : testStatus === "error"
                ? "bg-red-100 text-red-700"
                : chatId.trim()
                ? "bg-navy-600 text-white hover:bg-navy-700"
                : "bg-gray-300 text-gray-500 cursor-not-allowed"
            }`}
          >
            {testStatus === "sending" ? (
              <>
                <RefreshCw className="w-5 h-5 animate-spin" />
                Sending test message...
              </>
            ) : testStatus === "sent" ? (
              <>
                <CheckCircle className="w-5 h-5" />
                Test message sent! Check Telegram
              </>
            ) : testStatus === "error" ? (
              <>
                <RefreshCw className="w-5 h-5" />
                Failed - Try again
              </>
            ) : (
              <>
                <Send className="w-5 h-5" />
                Send Test Message
              </>
            )}
          </button>

          {testStatus === "sent" && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <p className="text-sm text-green-800 font-medium mb-1">
                ✅ Success! Check your Telegram
              </p>
              <p className="text-sm text-green-700">
                You should receive a test message. If you see it, your notifications are set up correctly!
              </p>
            </div>
          )}

          {testStatus === "error" && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-sm text-red-800 font-medium mb-1">
                ❌ Failed to send test message
              </p>
              <p className="text-sm text-red-700">
                Please double-check your Chat ID and make sure you&apos;ve started a conversation with the bot.
              </p>
            </div>
          )}

          <button
            onClick={() => setCurrentStep(2)}
            className="flex items-center justify-center gap-2 w-full py-3 text-gray-600 hover:text-gray-900 font-medium transition-colors"
          >
            ← Back to Step 2
          </button>
        </div>
      )}
    </div>
  );
}

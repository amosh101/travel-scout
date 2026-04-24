"use client";

import { useState, useEffect } from "react";
import { Calendar, ChevronLeft, ChevronRight, Clock } from "lucide-react";

export interface DateSelection {
  departureDate: string | null;
  returnDate: string | null;
  flexibility: "exact" | "plusminus1" | "plusminus3" | "plusminus7" | "weekends";
}

interface DatePickerProps {
  value: DateSelection;
  onChange: (value: DateSelection) => void;
  label?: string;
  showReturnDate?: boolean;
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

const FLEXIBILITY_OPTIONS = [
  { value: "exact", label: "Exact dates", description: "Only flights on these exact dates" },
  { value: "plusminus1", label: "±1 day", description: "Flights within 1 day of your selection" },
  { value: "plusminus3", label: "±3 days", description: "Flights within 3 days of your selection" },
  { value: "plusminus7", label: "±7 days", description: "Flights within 7 days of your selection" },
  { value: "weekends", label: "Weekends only", description: "Friday to Sunday departures" },
];

export default function DatePicker({
  value,
  onChange,
  label = "Travel Dates",
  showReturnDate = true,
}: DatePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [currentMonth, setCurrentMonth] = useState(new Date().getMonth());
  const [currentYear, setCurrentYear] = useState(new Date().getFullYear());
  const [selecting, setSelecting] = useState<"departure" | "return">("departure");

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  };

  const getDaysInMonth = (month: number, year: number): number => {
    return new Date(year, month + 1, 0).getDate();
  };

  const getFirstDayOfMonth = (month: number, year: number): number => {
    return new Date(year, month, 1).getDay();
  };

  const generateCalendar = () => {
    const daysInMonth = getDaysInMonth(currentMonth, currentYear);
    const firstDay = getFirstDayOfMonth(currentMonth, currentYear);
    const days = [];

    // Empty cells for days before the first of the month
    for (let i = 0; i < firstDay; i++) {
      days.push(null);
    }

    // Days of the month
    for (let i = 1; i <= daysInMonth; i++) {
      days.push(i);
    }

    return days;
  };

  const handleDateSelect = (day: number) => {
    const selectedDate = new Date(currentYear, currentMonth, day);
    const dateStr = selectedDate.toISOString().split("T")[0];

    if (selecting === "departure") {
      onChange({
        ...value,
        departureDate: dateStr,
        // Clear return if it's before new departure
        returnDate: value.returnDate && value.returnDate < dateStr ? null : value.returnDate,
      });
      if (showReturnDate) {
        setSelecting("return");
      } else {
        setIsOpen(false);
      }
    } else {
      if (dateStr < (value.departureDate || "")) {
        // If return is before departure, make it the departure
        onChange({
          ...value,
          departureDate: dateStr,
          returnDate: null,
        });
        setSelecting("return");
      } else {
        onChange({
          ...value,
          returnDate: dateStr,
        });
        setIsOpen(false);
      }
    }
  };

  const handlePrevMonth = () => {
    if (currentMonth === 0) {
      setCurrentMonth(11);
      setCurrentYear(currentYear - 1);
    } else {
      setCurrentMonth(currentMonth - 1);
    }
  };

  const handleNextMonth = () => {
    if (currentMonth === 11) {
      setCurrentMonth(0);
      setCurrentYear(currentYear + 1);
    } else {
      setCurrentMonth(currentMonth + 1);
    }
  };

  const isDateDisabled = (day: number): boolean => {
    const date = new Date(currentYear, currentMonth, day);
    date.setHours(0, 0, 0, 0);
    return date < today;
  };

  const isSelected = (day: number): "departure" | "return" | null => {
    const dateStr = new Date(currentYear, currentMonth, day).toISOString().split("T")[0];
    if (dateStr === value.departureDate) return "departure";
    if (dateStr === value.returnDate) return "return";
    return null;
  };

  const isInRange = (day: number): boolean => {
    if (!value.departureDate || !value.returnDate) return false;
    const dateStr = new Date(currentYear, currentMonth, day).toISOString().split("T")[0];
    return dateStr > value.departureDate && dateStr < value.returnDate;
  };

  const displayValue = () => {
    if (!value.departureDate) return "Select dates...";
    let text = formatDate(value.departureDate);
    if (showReturnDate && value.returnDate) {
      text += ` - ${formatDate(value.returnDate)}`;
    } else if (showReturnDate) {
      text += " - Return?";
    }
    return text;
  };

  const calendarDays = generateCalendar();

  return (
    <div className="relative">
      {label && (
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {label}
        </label>
      )}

      {/* Input trigger */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={`w-full flex items-center gap-3 px-4 py-2.5 border rounded-lg transition-all text-left ${
          isOpen
            ? "border-navy-600 ring-2 ring-navy-100"
            : "border-gray-300 hover:border-gray-400"
        }`}
      >
        <Calendar className="h-5 w-5 text-gray-400 flex-shrink-0" />
        <span className={`text-sm ${value.departureDate ? "text-gray-900" : "text-gray-400"}`}>
          {displayValue()}
        </span>
      </button>

      {/* Calendar Popover */}
      {isOpen && (
        <div className="absolute z-50 w-full mt-2 bg-white rounded-xl shadow-xl border border-gray-200 p-4 animate-fade-in">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <button
              type="button"
              onClick={handlePrevMonth}
              className="p-1 hover:bg-gray-100 rounded-full transition-colors"
            >
              <ChevronLeft className="h-5 w-5 text-gray-600" />
            </button>
            <span className="font-semibold text-gray-900">
              {MONTHS[currentMonth]} {currentYear}
            </span>
            <button
              type="button"
              onClick={handleNextMonth}
              className="p-1 hover:bg-gray-100 rounded-full transition-colors"
            >
              <ChevronRight className="h-5 w-5 text-gray-600" />
            </button>
          </div>

          {/* Calendar grid */}
          <div className="mb-4">
            {/* Day headers */}
            <div className="grid grid-cols-7 mb-2">
              {DAYS.map((day) => (
                <div
                  key={day}
                  className="text-center text-xs font-medium text-gray-500 py-1"
                >
                  {day}
                </div>
              ))}
            </div>

            {/* Calendar days */}
            <div className="grid grid-cols-7 gap-1">
              {calendarDays.map((day, index) => (
                <div key={index} className="aspect-square">
                  {day ? (
                    <button
                      type="button"
                      onClick={() => handleDateSelect(day)}
                      disabled={isDateDisabled(day)}
                      className={`w-full h-full rounded-lg text-sm font-medium transition-all ${
                        isDateDisabled(day)
                          ? "text-gray-300 cursor-not-allowed"
                          : isSelected(day) === "departure"
                          ? "bg-navy-600 text-white"
                          : isSelected(day) === "return"
                          ? "bg-navy-600 text-white"
                          : isInRange(day)
                          ? "bg-navy-100 text-navy-800"
                          : "text-gray-700 hover:bg-gray-100"
                      }`}
                    >
                      {day}
                    </button>
                  ) : (
                    <div />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Selection indicator */}
          {showReturnDate && (
            <div className="flex gap-2 mb-4 p-2 bg-gray-50 rounded-lg">
              <button
                type="button"
                onClick={() => setSelecting("departure")}
                className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
                  selecting === "departure"
                    ? "bg-white shadow-sm text-navy-700"
                    : "text-gray-500 hover:text-gray-700"
                }`}
              >
                Departure
                {value.departureDate && (
                  <span className="block text-xs font-normal text-navy-600">
                    {formatDate(value.departureDate)}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => setSelecting("return")}
                className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
                  selecting === "return"
                    ? "bg-white shadow-sm text-navy-700"
                    : "text-gray-500 hover:text-gray-700"
                }`}
              >
                Return
                {value.returnDate ? (
                  <span className="block text-xs font-normal text-navy-600">
                    {formatDate(value.returnDate)}
                  </span>
                ) : (
                  <span className="block text-xs font-normal text-gray-400">
                    Optional
                  </span>
                )}
              </button>
            </div>
          )}

          {/* Flexibility options */}
          <div className="border-t border-gray-200 pt-4">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="h-4 w-4 text-gray-400" />
              <span className="text-sm font-medium text-gray-700">
                Date flexibility
              </span>
            </div>
            <div className="space-y-2">
              {FLEXIBILITY_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() =>
                    onChange({ ...value, flexibility: option.value as DateSelection["flexibility"] })
                  }
                  className={`w-full flex items-center justify-between p-3 rounded-lg border transition-all ${
                    value.flexibility === option.value
                      ? "border-navy-600 bg-navy-50"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="text-left">
                    <p
                      className={`text-sm font-medium ${
                        value.flexibility === option.value
                          ? "text-navy-700"
                          : "text-gray-900"
                      }`}
                    >
                      {option.label}
                    </p>
                    <p className="text-xs text-gray-500">{option.description}</p>
                  </div>
                  {value.flexibility === option.value && (
                    <div className="w-4 h-4 bg-navy-600 rounded-full flex items-center justify-center">
                      <div className="w-2 h-2 bg-white rounded-full" />
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Clear button */}
          {(value.departureDate || value.returnDate) && (
            <button
              type="button"
              onClick={() =>
                onChange({
                  departureDate: null,
                  returnDate: null,
                  flexibility: value.flexibility,
                })
              }
              className="w-full mt-4 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors"
            >
              Clear dates
            </button>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { X, Plane, Search } from "lucide-react";

export interface Airport {
  code: string;
  name: string;
  city: string;
  country: string;
}

interface AirportAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  required?: boolean;
}

// Major airports dataset
const AIRPORTS: Airport[] = [
  { code: "MPM", name: "Maputo International Airport", city: "Maputo", country: "Mozambique" },
  { code: "JNB", name: "O.R. Tambo International", city: "Johannesburg", country: "South Africa" },
  { code: "CPT", name: "Cape Town International", city: "Cape Town", country: "South Africa" },
  { code: "LOS", name: "Murtala Muhammed International", city: "Lagos", country: "Nigeria" },
  { code: "CAI", name: "Cairo International Airport", city: "Cairo", country: "Egypt" },
  { code: "NBO", name: "Jomo Kenyatta International", city: "Nairobi", country: "Kenya" },
  { code: "DAR", name: "Julius Nyerere International", city: "Dar es Salaam", country: "Tanzania" },
  { code: "ADD", name: "Addis Ababa Bole International", city: "Addis Ababa", country: "Ethiopia" },
  { code: "LHR", name: "London Heathrow", city: "London", country: "United Kingdom" },
  { code: "LGW", name: "London Gatwick", city: "London", country: "United Kingdom" },
  { code: "CDG", name: "Charles de Gaulle Airport", city: "Paris", country: "France" },
  { code: "ORY", name: "Orly Airport", city: "Paris", country: "France" },
  { code: "AMS", name: "Amsterdam Airport Schiphol", city: "Amsterdam", country: "Netherlands" },
  { code: "FRA", name: "Frankfurt Airport", city: "Frankfurt", country: "Germany" },
  { code: "MUC", name: "Munich Airport", city: "Munich", country: "Germany" },
  { code: "FCO", name: "Leonardo da Vinci International", city: "Rome", country: "Italy" },
  { code: "MXP", name: "Milan Malpensa Airport", city: "Milan", country: "Italy" },
  { code: "MAD", name: "Adolfo Suárez Madrid–Barajas", city: "Madrid", country: "Spain" },
  { code: "BCN", name: "Barcelona El Prat", city: "Barcelona", country: "Spain" },
  { code: "JFK", name: "John F. Kennedy International", city: "New York", country: "United States" },
  { code: "LGA", name: "LaGuardia Airport", city: "New York", country: "United States" },
  { code: "EWR", name: "Newark Liberty International", city: "Newark", country: "United States" },
  { code: "LAX", name: "Los Angeles International", city: "Los Angeles", country: "United States" },
  { code: "SFO", name: "San Francisco International", city: "San Francisco", country: "United States" },
  { code: "ORD", name: "O'Hare International Airport", city: "Chicago", country: "United States" },
  { code: "MIA", name: "Miami International Airport", city: "Miami", country: "United States" },
  { code: "DXB", name: "Dubai International Airport", city: "Dubai", country: "UAE" },
  { code: "DOH", name: "Hamad International Airport", city: "Doha", country: "Qatar" },
  { code: "SIN", name: "Changi Airport", city: "Singapore", country: "Singapore" },
  { code: "HKG", name: "Hong Kong International", city: "Hong Kong", country: "Hong Kong" },
  { code: "NRT", name: "Narita International Airport", city: "Tokyo", country: "Japan" },
  { code: "HND", name: "Haneda Airport", city: "Tokyo", country: "Japan" },
  { code: "SYD", name: "Sydney Kingsford Smith", city: "Sydney", country: "Australia" },
  { code: "MEL", name: "Melbourne Airport", city: "Melbourne", country: "Australia" },
  { code: "GRU", name: "São Paulo/Guarulhos", city: "São Paulo", country: "Brazil" },
  { code: "GIG", name: "Rio de Janeiro/Galeão", city: "Rio de Janeiro", country: "Brazil" },
  { code: "EZE", name: "Ministro Pistarini", city: "Buenos Aires", country: "Argentina" },
  { code: "CPT", name: "Cape Town International", city: "Cape Town", country: "South Africa" },
  { code: "DUR", name: "King Shaka International", city: "Durban", country: "South Africa" },
  { code: "BEW", name: "Beira Airport", city: "Beira", country: "Mozambique" },
  { code: "POL", name: "Pemba Airport", city: "Pemba", country: "Mozambique" },
  { code: "INH", name: "Inhambane Airport", city: "Inhambane", country: "Mozambique" },
  { code: "VNX", name: "Vilanculos Airport", city: "Vilanculos", country: "Mozambique" },
  { code: "APL", name: "Nampula Airport", city: "Nampula", country: "Mozambique" },
  { code: "TET", name: "Chingozi Airport", city: "Tete", country: "Mozambique" },
  { code: "TNR", name: "Ivato International Airport", city: "Antananarivo", country: "Madagascar" },
  { code: "MRU", name: "Sir Seewoosagur Ramgoolam", city: "Mauritius", country: "Mauritius" },
  { code: "SEZ", name: "Seychelles International", city: "Mahé", country: "Seychelles" },
  { code: "GBE", name: "Sir Seretse Khama International", city: "Gaborone", country: "Botswana" },
  { code: "HRE", name: "Robert Gabriel Mugabe", city: "Harare", country: "Zimbabwe" },
  { code: "LUN", name: "Kenneth Kaunda International", city: "Lusaka", country: "Zambia" },
  { code: "FIH", name: "N'djili International Airport", city: "Kinshasa", country: "DRC" },
  { code: "BKO", name: "Modibo Keita International", city: "Bamako", country: "Mali" },
  { code: "DKR", name: "Blaise Diagne International", city: "Dakar", country: "Senegal" },
  { code: "ABJ", name: "Félix-Houphouët-Boigny", city: "Abidjan", country: "Ivory Coast" },
  { code: "ACC", name: "Kotoka International Airport", city: "Accra", country: "Ghana" },
  { code: "TUN", name: "Tunis-Carthage Airport", city: "Tunis", country: "Tunisia" },
  { code: "CMN", name: "Mohammed V Airport", city: "Casablanca", country: "Morocco" },
  { code: "RAK", name: "Marrakesh Menara Airport", city: "Marrakesh", country: "Morocco" },
  { code: "IST", name: "Istanbul Airport", city: "Istanbul", country: "Turkey" },
  { code: "SAW", name: "Sabiha Gökçen Airport", city: "Istanbul", country: "Turkey" },
  { code: "ATH", name: "Athens International Airport", city: "Athens", country: "Greece" },
  { code: "VIE", name: "Vienna International Airport", city: "Vienna", country: "Austria" },
  { code: "ZRH", name: "Zurich Airport", city: "Zurich", country: "Switzerland" },
  { code: "GVA", name: "Geneva Airport", city: "Geneva", country: "Switzerland" },
  { code: "CPH", name: "Copenhagen Airport", city: "Copenhagen", country: "Denmark" },
  { code: "OSL", name: "Oslo Airport", city: "Oslo", country: "Norway" },
  { code: "ARN", name: "Stockholm Arlanda", city: "Stockholm", country: "Sweden" },
  { code: "HEL", name: "Helsinki Airport", city: "Helsinki", country: "Finland" },
  { code: "PRG", name: "Václav Havel Airport", city: "Prague", country: "Czech Republic" },
  { code: "WAW", name: "Warsaw Chopin Airport", city: "Warsaw", country: "Poland" },
  { code: "BUD", name: "Budapest Ferenc Liszt", city: "Budapest", country: "Hungary" },
  { code: "SOF", name: "Sofia Airport", city: "Sofia", country: "Bulgaria" },
  { code: "OTP", name: "Bucharest Henri Coandă", city: "Bucharest", country: "Romania" },
  { code: "DUB", name: "Dublin Airport", city: "Dublin", country: "Ireland" },
  { code: "LIS", name: "Lisbon Airport", city: "Lisbon", country: "Portugal" },
  { code: "BCN", name: "Barcelona El Prat", city: "Barcelona", country: "Spain" },
  { code: "AGP", name: "Málaga Airport", city: "Málaga", country: "Spain" },
  { code: "PMI", name: "Palma de Mallorca Airport", city: "Palma", country: "Spain" },
  { code: "TFS", name: "Tenerife South Airport", city: "Tenerife", country: "Spain" },
  { code: "LPA", name: "Gran Canaria Airport", city: "Gran Canaria", country: "Spain" },
  { code: "ICN", name: "Incheon International Airport", city: "Seoul", country: "South Korea" },
  { code: "BKK", name: "Suvarnabhumi Airport", city: "Bangkok", country: "Thailand" },
  { code: "KUL", name: "Kuala Lumpur International", city: "Kuala Lumpur", country: "Malaysia" },
  { code: "CGK", name: "Soekarno-Hatta Airport", city: "Jakarta", country: "Indonesia" },
  { code: "MNL", name: "Ninoy Aquino International", city: "Manila", country: "Philippines" },
  { code: "DEL", name: "Indira Gandhi International", city: "New Delhi", country: "India" },
  { code: "BOM", name: "Chhatrapati Shivaji Airport", city: "Mumbai", country: "India" },
  { code: "MAA", name: "Chennai International Airport", city: "Chennai", country: "India" },
  { code: "BLR", name: "Kempegowda International", city: "Bangalore", country: "India" },
  { code: "HYD", name: "Rajiv Gandhi Airport", city: "Hyderabad", country: "India" },
  { code: "CCU", name: "Netaji Subhas Chandra Bose", city: "Kolkata", country: "India" },
  { code: "PVG", name: "Shanghai Pudong", city: "Shanghai", country: "China" },
  { code: "PEK", name: "Beijing Capital International", city: "Beijing", country: "China" },
  { code: "CAN", name: "Guangzhou Baiyun", city: "Guangzhou", country: "China" },
  { code: "TPE", name: "Taiwan Taoyuan", city: "Taipei", country: "Taiwan" },
  { code: "AKL", name: "Auckland Airport", city: "Auckland", country: "New Zealand" },
  { code: "CHC", name: "Christchurch Airport", city: "Christchurch", country: "New Zealand" },
  { code: "CNS", name: "Cairns Airport", city: "Cairns", country: "Australia" },
  { code: "PER", name: "Perth Airport", city: "Perth", country: "Australia" },
  { code: "BNE", name: "Brisbane Airport", city: "Brisbane", country: "Australia" },
  { code: "OOL", name: "Gold Coast Airport", city: "Gold Coast", country: "Australia" },
  { code: "ADL", name: "Adelaide Airport", city: "Adelaide", country: "Australia" },
  { code: "CAN", name: "Cancún International", city: "Cancún", country: "Mexico" },
  { code: "MEX", name: "Mexico City Airport", city: "Mexico City", country: "Mexico" },
  { code: "SJO", name: "Juan Santamaría Airport", city: "San José", country: "Costa Rica" },
  { code: "PTY", name: "Tocumen International", city: "Panama City", country: "Panama" },
  { code: "BOG", name: "El Dorado Airport", city: "Bogotá", country: "Colombia" },
  { code: "UIO", name: "Mariscal Sucre Airport", city: "Quito", country: "Ecuador" },
  { code: "LIM", name: "Jorge Chávez Airport", city: "Lima", country: "Peru" },
  { code: "SCL", name: "Arturo Merino Benítez", city: "Santiago", country: "Chile" },
];

export default function AirportAutocomplete({
  value,
  onChange,
  placeholder = "Search airports...",
  label,
  required = false,
}: AirportAutocompleteProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [selected, setSelected] = useState<Airport | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Filter airports based on query
  const filteredAirports = useCallback(() => {
    if (!query) return [];
    const q = query.toLowerCase();
    return AIRPORTS.filter(
      (airport) =>
        airport.code.toLowerCase().includes(q) ||
        airport.city.toLowerCase().includes(q) ||
        airport.name.toLowerCase().includes(q) ||
        airport.country.toLowerCase().includes(q)
    ).slice(0, 8);
  }, [query]);

  // Set selected airport from value prop
  useEffect(() => {
    if (value) {
      const airport = AIRPORTS.find(
        (a) => a.code.toLowerCase() === value.toLowerCase()
      );
      if (airport) {
        setSelected(airport);
        setQuery(`${airport.code} - ${airport.city}`);
      } else {
        setQuery(value);
      }
    } else {
      setQuery("");
      setSelected(null);
    }
  }, [value]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newQuery = e.target.value;
    setQuery(newQuery);
    setSelected(null);
    setIsOpen(true);
    setHighlightedIndex(0);
    onChange(newQuery);
  };

  const handleSelect = (airport: Airport) => {
    setSelected(airport);
    setQuery(`${airport.code} - ${airport.city}`);
    setIsOpen(false);
    onChange(airport.code);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const options = filteredAirports();

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightedIndex((prev) =>
          prev < options.length - 1 ? prev + 1 : prev
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : 0));
        break;
      case "Enter":
        e.preventDefault();
        if (options[highlightedIndex]) {
          handleSelect(options[highlightedIndex]);
        }
        break;
      case "Escape":
        setIsOpen(false);
        break;
    }
  };

  const clearSelection = () => {
    setQuery("");
    setSelected(null);
    onChange("");
    inputRef.current?.focus();
  };

  const results = filteredAirports();

  return (
    <div className="relative" ref={dropdownRef}>
      {label && (
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {label}
          {required && <span className="text-red-500 ml-1">*</span>}
        </label>
      )}
      <div className="relative">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <Plane className="h-5 w-5 text-gray-400" />
        </div>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => query.length >= 1 && setIsOpen(true)}
          placeholder={placeholder}
          required={required}
          className="w-full pl-10 pr-10 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-navy-600 focus:border-transparent text-sm transition-all"
        />
        {query && (
          <button
            type="button"
            onClick={clearSelection}
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Dropdown */}
      {isOpen && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden animate-fade-in">
          <ul className="max-h-72 overflow-y-auto">
            {results.map((airport, index) => (
              <li
                key={airport.code}
                onClick={() => handleSelect(airport)}
                className={`px-4 py-3 cursor-pointer transition-colors ${
                  index === highlightedIndex
                    ? "bg-navy-50"
                    : "hover:bg-gray-50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 bg-navy-100 rounded-lg flex items-center justify-center flex-shrink-0">
                      <span className="text-navy-700 font-bold text-sm">
                        {airport.code}
                      </span>
                    </div>
                    <div>
                      <p className="font-medium text-gray-900 text-sm">
                        {airport.city}, {airport.country}
                      </p>
                      <p className="text-xs text-gray-500">{airport.name}</p>
                    </div>
                  </div>
                  <Plane className="h-4 w-4 text-gray-300" />
                </div>
              </li>
            ))}
          </ul>
          <div className="px-4 py-2 bg-gray-50 border-t border-gray-200 text-xs text-gray-500">
            <div className="flex items-center gap-1">
              <Search className="h-3 w-3" />
              <span>{results.length} airports found</span>
            </div>
          </div>
        </div>
      )}

      {/* No results */}
      {isOpen && query.length >= 2 && results.length === 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white rounded-lg shadow-lg border border-gray-200 p-4 text-center">
          <p className="text-sm text-gray-500">
            No airports found for &quot;{query}&quot;
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Try searching by IATA code, city, or airport name
          </p>
        </div>
      )}
    </div>
  );
}

// Export airports for use in other components
export { AIRPORTS };

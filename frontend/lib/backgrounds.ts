/**
 * Background theme picker — maps a city/interest/event to a backdrop.
 *
 * Two-pass:
 *   1) Country → theme (curated; geography-aware).
 *   2) Variant a/b/c → deterministic by hash of city name so the same
 *      city always picks the same variant.
 *
 * Themes:
 *   mediterranean, tropical, desert, northern, mountain,
 *   asian_metro, old_world, safari, polar, vineyard,
 *   urban_night, coastal_misty
 *
 * If something is unknown, it falls back to a sensible default
 * (`old_world` for anonymous users).
 */
export const THEME_IDS = [
  "mediterranean",
  "tropical",
  "desert",
  "northern",
  "mountain",
  "asian_metro",
  "old_world",
  "safari",
  "polar",
  "vineyard",
  "urban_night",
  "coastal_misty",
] as const;
export type ThemeId = (typeof THEME_IDS)[number];
export type Variant = "a" | "b" | "c";

// Per-country theme rules. Most-affinities listed first so the FIRST
// match wins. Tunable — anything you don't like, drag to a different
// line.
const COUNTRY_THEMES: Record<string, ThemeId[]> = {
  // Mediterranean
  ES: ["mediterranean", "old_world", "vineyard"],
  PT: ["mediterranean", "old_world"],
  IT: ["mediterranean", "old_world"],
  GR: ["mediterranean", "old_world"],
  FR: ["mediterranean", "old_world", "vineyard"],
  MC: ["mediterranean", "old_world"],
  MT: ["mediterranean", "old_world"],
  CY: ["mediterranean", "old_world"],
  TR: ["mediterranean", "old_world"],
  // Tropical / island
  ID: ["tropical"],
  TH: ["tropical"],
  PH: ["tropical"],
  MV: ["tropical"],
  FJ: ["tropical"],
  WS: ["tropical"],
  TO: ["tropical"],
  VU: ["tropical"],
  SB: ["tropical"],
  PG: ["tropical"],
  BS: ["tropical"],
  CU: ["tropical"],
  JM: ["tropical"],
  DO: ["tropical"],
  HT: ["tropical"],
  LC: ["tropical"],
  VC: ["tropical"],
  AG: ["tropical"],
  GD: ["tropical"],
  BB: ["tropical"],
  TT: ["tropical"],
  KY: ["tropical"],
  TC: ["tropical"],
  VI: ["tropical"],
  PR: ["tropical"],
  BZ: ["tropical"],
  CR: ["tropical"],
  PA: ["tropical"],
  HN: ["tropical"],
  NI: ["tropical"],
  SV: ["tropical"],
  GT: ["tropical"],
  MX: ["tropical", "desert"],  // beach areas vs north
  BR: ["tropical"],            // broad — Amazon + Northeast beaches
  CO: ["tropical", "mountain"],
  VE: ["tropical"],
  GY: ["tropical"],
  SR: ["tropical"],
  GF: ["tropical"],
  // Desert / arid
  SA: ["desert"],
  AE: ["desert"],
  QA: ["desert"],
  BH: ["desert"],
  KW: ["desert"],
  OM: ["desert"],
  YE: ["desert"],
  JO: ["desert"],
  EG: ["desert"],
  LY: ["desert"],
  TN: ["desert", "mediterranean"],
  DZ: ["desert"],
  MA: ["desert", "mediterranean"],
  MR: ["desert"],
  EH: ["desert"],
  SD: ["desert"],
  SS: ["desert"],
  TD: ["desert"],
  NE: ["desert"],
  ML: ["desert"],
  SO: ["desert"],
  DJ: ["desert"],
  ER: ["desert"],
  ET: ["safari", "desert", "mountain"],
  IR: ["desert", "mountain"],
  IQ: ["desert"],
  SY: ["desert"],
  IL: ["desert", "mediterranean"],
  PS: ["desert"],
  LB: ["mediterranean"],
  PK: ["desert", "mountain"],
  AF: ["mountain", "desert"],
  UZ: ["desert"],
  TM: ["desert"],
  AZ: ["desert", "mountain"],
  KZ: ["desert", "mountain"],
  KG: ["mountain", "desert"],
  TJ: ["mountain", "desert"],
  MN: ["mountain", "desert"],
  // Polar / arctic
  IS: ["polar", "northern"],
  GL: ["polar"],
  SJ: ["polar"],
  FO: ["polar", "northern"],
  // Northern
  NO: ["northern", "polar"],
  SE: ["northern", "polar"],
  FI: ["northern", "polar"],
  DK: ["northern"],
  IE: ["northern", "coastal_misty"],
  GB: ["northern", "old_world", "coastal_misty"],
  NL: ["northern", "coastal_misty"],
  BE: ["northern", "old_world"],
  DE: ["northern", "old_world"],
  AT: ["northern", "mountain"],
  CH: ["northern", "mountain"],
  PL: ["northern"],
  CZ: ["northern", "old_world"],
  SK: ["northern"],
  HU: ["northern", "old_world"],
  EE: ["northern"],
  LV: ["northern"],
  LT: ["northern"],
  LU: ["northern", "old_world"],
  LI: ["northern", "mountain"],
  // Mountain / alpine
  NP: ["mountain"],
  BT: ["mountain"],
  AR: ["mountain", "vineyard"],
  CL: ["mountain"],
  BO: ["mountain", "safari"],
  PE: ["mountain", "desert"],
  EC: ["mountain", "tropical"],
  PY: ["safari", "tropical"],
  UY: ["vineyard", "mediterranean"],
  // Safari / savannah
  KE: ["safari", "mountain"],
  TZ: ["safari", "tropical"],
  ZM: ["safari"],
  ZW: ["safari"],
  BW: ["desert", "safari"],
  NA: ["desert", "safari"],
  ZA: ["safari", "vineyard", "coastal_misty"],
  MG: ["tropical", "safari"],
  MZ: ["safari", "tropical", "coastal_misty"],
  MW: ["safari"],
  UG: ["safari", "mountain"],
  RW: ["mountain", "safari"],
  BI: ["mountain", "safari"],
  AO: ["tropical", "safari"],
  CG: ["tropical"],
  CD: ["tropical"],
  GA: ["tropical"],
  GQ: ["tropical"],
  CM: ["tropical"],
  NG: ["tropical"],
  GH: ["tropical"],
  CI: ["tropical"],
  SN: ["tropical"],
  GM: ["tropical"],
  GW: ["tropical"],
  GN: ["tropical"],
  SL: ["tropical"],
  LR: ["tropical"],
  BF: ["safari", "desert"],
  BJ: ["tropical"],
  TG: ["tropical"],
  // Asian metro
  JP: ["asian_metro"],
  KR: ["asian_metro"],
  TW: ["asian_metro", "tropical"],
  HK: ["asian_metro"],
  SG: ["asian_metro", "tropical"],
  MY: ["tropical"],
  CN: ["asian_metro", "mountain"],
  KH: ["tropical"],
  LA: ["tropical", "mountain"],
  VN: ["tropical", "asian_metro"],
  MM: ["tropical", "asian_metro"],
  BD: ["tropical"],
  IN: ["asian_metro", "tropical", "desert"],
  LK: ["tropical"],
  // Old world / misc
  RO: ["old_world"],
  BG: ["old_world"],
  RS: ["old_world"],
  BA: ["old_world"],
  ME: ["old_world"],
  AL: ["old_world"],
  MK: ["old_world"],
  XK: ["old_world"],
  SI: ["old_world"],
  MD: ["old_world"],
  UA: ["old_world"],
  BY: ["northern"],
  RU: ["northern", "polar", "desert"],
  AM: ["mountain", "desert"],
  GE: ["mountain", "northern"],
  // Coastal-misty / Pacific NW
  CA: ["coastal_misty", "northern"],
  US: ["old_world", "mediterranean", "coastal_misty", "urban_night"],
  AU: ["tropical", "desert", "coastal_misty"],
  NZ: ["coastal_misty", "tropical"],
  // Special — urban night (only override for major capitals if you want)
};

// Interest (key) → theme tweaks layered on top of country default.
// Only tested when present, doesn't override country unless stronger.
const INTEREST_THEMES: Record<string, ThemeId> = {
  // Music/nightlife → urban_night
  jazz: "urban_night",
  techno: "urban_night",
  electronic_music: "urban_night",
  nightlife: "urban_night",
  // Surf/beach/sailing → tropical/mediterranean
  surfing: "tropical",
  sailing: "mediterranean",
  kitesurfing: "tropical",
  diving: "tropical",
  // Wine / culinary → vineyard / mediterranean
  wine: "vineyard",
  food_tours: "vineyard",
  culinary: "vineyard",
  // Wildlife → safari
  wildlife: "safari",
  national_parks: "safari",
  safari: "safari",
  // Climbing / alpine → mountain
  climbing: "mountain",
  trekking: "mountain",
  hiking: "mountain",
  skiing: "mountain",
  snowboarding: "mountain",
  // Cycling / running urban → urban_night / old_world
  cycling: "old_world",
  marathon: "old_world",
};

// Pick a variant deterministically from a hashable input.
function hashCode(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function pickTheme(
  country: string | null | undefined,
  city: string | null | undefined,
  interests: string[] | null | undefined,
): ThemeId {
  const c = (country ?? "").toUpperCase();
  const candidates = COUNTRY_THEMES[c];

  // 1) interest override on top of country preference
  if (interests && interests.length > 0) {
    for (const i of interests) {
      const want = INTEREST_THEMES[i];
      if (want) {
        return want;
      }
    }
  }

  // 2) country default (first hit, or fallback to old_world)
  if (candidates && candidates.length > 0) {
    return candidates[0];
  }

  // 3) global fallback
  return "old_world";
}

function pickVariant(city: string | null | undefined, country: string | null | undefined): Variant {
  const seed = `${country ?? "?"}-${city ?? "?"}`;
  const h = hashCode(seed);
  const v = (h % 3) as 0 | 1 | 2;
  return v === 0 ? "a" : v === 1 ? "b" : "c";
}

export type BackgroundPick = {
  theme: ThemeId;
  variant: Variant;
  src: string;        // /backgrounds/mediterranean_a.jpg
  palette: {
    sky: string;
    horizon: string;
    sea: string;
    accent: string;
  };
};

// Per-theme CSS color hints so the page can match text colors.
// These match the dominant tones of each palette; tuned against the
// Python generator.
export const THEME_PALETTE_CSS: Record<ThemeId, BackgroundPick["palette"]> = {
  mediterranean: { sky: "#ffdeb2", horizon: "#e4a882", sea: "#60a2bc", accent: "#fcb864" },
  tropical:      { sky: "#aae0da", horizon: "#58a890", sea: "#348a7c", accent: "#dcf0a8" },
  desert:        { sky: "#f4c89c", horizon: "#dc8054", sea: "#c05838", accent: "#fcc460" },
  northern:      { sky: "#b4c4dc", horizon: "#546e94", sea: "#284066", accent: "#dcc4f0" },
  mountain:      { sky: "#dce0e8", horizon: "#a0b0c8", sea: "#6c7c98", accent: "#e8dcc8" },
  asian_metro:   { sky: "#ecb8c8", horizon: "#7c5094", sea: "#382464", accent: "#fcc458" },
  old_world:     { sky: "#dcd4c8", horizon: "#988474", sea: "#584c48", accent: "#c8a884" },
  safari:        { sky: "#fcdca8", horizon: "#dc9854", sea: "#b49050", accent: "#609058" },
  polar:         { sky: "#e4ecf4", horizon: "#b4c8dc", sea: "#7c9cb4", accent: "#f0f4fa" },
  vineyard:      { sky: "#e4c4a8", horizon: "#a4746c", sea: "#603c48", accent: "#d49060" },
  urban_night:   { sky: "#2c2450", horizon: "#583c7c", sea: "#1c102c", accent: "#fc9c60" },
  coastal_misty: { sky: "#d8dee4", horizon: "#94a4b0", sea: "#546478", accent: "#c8d8e0" },
};

export function pickBackground(opts: {
  city?: string | null;
  country?: string | null;
  interests?: string[] | null;
}): BackgroundPick {
  const theme = pickTheme(opts.country, opts.city, opts.interests);
  const variant = pickVariant(opts.city, opts.country);
  const src = `/backgrounds/${theme}_${variant}.jpg`;
  return { theme, variant, src, palette: THEME_PALETTE_CSS[theme] };
}

// Pick a "browse" theme that's neutral / not tied to a specific city.
// Used on the home page when there's no destination yet.
export function pickDefaultBackground(): BackgroundPick {
  const themes: ThemeId[] = ["mediterranean", "tropical", "mountain", "safari", "old_world"];
  const i = Math.floor(Math.random() * themes.length);
  return {
    theme: themes[i],
    variant: "a",
    src: `/backgrounds/${themes[i]}_a.jpg`,
    palette: THEME_PALETTE_CSS[themes[i]],
  };
}

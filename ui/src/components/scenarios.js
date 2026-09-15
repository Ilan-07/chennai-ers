// Scenario and study-area names, in one place because three panels now print
// them. Two components each holding their own copy is how "Flood, 25-year" and
// "25-year flood" ended up on screen at the same time.

export const SCENARIO_LABEL = {
  dry: "Dry day",
  peak: "Peak hour",
  flood5: "Flood, 5-year",
  flood25: "Flood, 25-year",
  flood100: "Flood, 100-year",
  f2015: "2015 flood",
};

// Study areas, shortest name that still distinguishes them. The full label sits
// underneath; two buttons reading the same thing is how the first version went
// out, so these are declared once and shared with the top bar.
export const SHORT = {
  gcc: "Corporation",
  metro: "Built-up city",
  full: "Full settlement",
};

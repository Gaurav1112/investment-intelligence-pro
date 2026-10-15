import { createContext, useContext, type ReactNode } from "react";
import type { ProfileStatus } from "./types";
import { useApi } from "./useApi";

interface Ctx {
  status: ProfileStatus | null;
  loading: boolean;
  error: unknown;
  reload: () => void;
}
const ProfileContext = createContext<Ctx>({ status: null, loading: true, error: null, reload: () => {} });

export function ProfileProvider({ children }: { children: ReactNode }) {
  const { data, loading, error, reload } = useApi<ProfileStatus>("/api/profile");
  return <ProfileContext.Provider value={{ status: data, loading, error, reload }}>{children}</ProfileContext.Provider>;
}

export const useProfile = () => useContext(ProfileContext);

export const OBJECTIVES: Record<string, { code: string; title: string; blurb: string }> = {
  A_capital_preservation: {
    code: "A",
    title: "Capital preservation",
    blurb: "Get the money back on the date, with the smallest chance of a loss.",
  },
  B_income: { code: "B", title: "Predictable proceeds", blurb: "Know in advance, as closely as possible, what you will receive." },
  C_liquidity: { code: "C", title: "Liquidity / emergency", blurb: "Be able to take the money out quickly and cheaply." },
  D_growth: { code: "D", title: "Risk-adjusted growth", blurb: "Grow the money while keeping losses within a budget you set." },
  E_aggressive_growth: {
    code: "E",
    title: "Aggressive growth",
    blurb: "Seek higher growth and accept large temporary losses, up to a budget you state explicitly.",
  },
};

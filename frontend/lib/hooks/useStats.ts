"use client";

import { useEffect, useState } from "react";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

export interface PlatformStats {
  total_leads: number;
  leads_with_owner: number;
  cities: string[];
  categories: Record<string, number>;
  reported_today: number;
  contacted: number;
  favorited: number;
}

export function useStats() {
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchStats = async () => {
      try {
        const [statsRes, citiesRes] = await Promise.all([
          fetch(`${API_BASE}/api/leads/stats`).then((r) => r.json()),
          fetch(`${API_BASE}/api/leads/cities`).then((r) => r.json()),
        ]);

        if (cancelled) return;

        const categories = statsRes.by_category || {};
        const cityCount = Array.isArray(citiesRes) ? citiesRes.length : 0;

        setStats({
          total_leads: statsRes.total || 0,
          leads_with_owner: statsRes.with_owner || 0,
          cities: Array.isArray(citiesRes) ? citiesRes : [],
          categories,
          reported_today: statsRes.reported_today || 0,
          contacted: statsRes.contacted || 0,
          favorited: statsRes.favorited || 0,
        });
      } catch (err) {
        if (!cancelled) setError("Erro ao carregar estatísticas");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchStats();

    return () => {
      cancelled = true;
    };
  }, []);

  return { stats, loading, error };
}
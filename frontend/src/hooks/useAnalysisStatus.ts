"use client";

import { useState, useEffect, useRef } from "react";
import { getAnalysisStatus } from "@/lib/api";
import type { AnalysisStatusResponse } from "@/types/report";

const POLL_INTERVAL_MS = 5000;
const TERMINAL_STATES = ["completed", "failed"];

export function useAnalysisStatus(analysisId: string | null) {
  const [data, setData] = useState<AnalysisStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!analysisId) return;

    const poll = async () => {
      try {
        const status = await getAnalysisStatus(analysisId);
        setData(status);
        if (TERMINAL_STATES.includes(status.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current);
        }
      } catch (e) {
        setError("Error fetching analysis status");
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    };

    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [analysisId]);

  return { data, error };
}
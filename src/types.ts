export interface RawPost {
  id: string;
  source: string;
  text: string;
  url: string | null;
  score: number;
  created_at: string;
  collected_at: string;
  metadata: Record<string, unknown>;
}

export interface TopicCluster {
  id: string;
  label: string;
  keywords: string[];
  posts: RawPost[];
  velocity: number;          // % change in volume over window
  velocityHistory: number[]; // hourly buckets for sparkline
  novelty: number;           // 0–1, how unique vs other clusters
  volume: number;
  driver: string | null;     // 'person' | 'new_paper' | 'new_repo' | 'product_launch' | 'benchmark'
  isInflection: boolean;
  topAuthors: { name: string; count: number }[];
  dominantSource: string;
  topUrl: string | null;
}

export interface GravitySignal {
  topic: TopicCluster;
  watchedAccounts: { name: string; posts: number }[];
  convergenceStrength: number; // how many watched accounts overlap
  window: string;             // e.g. "72h"
  isCoordinated: boolean;     // heuristic: timing too tight
}

export type TabId = 'heatmap' | 'gravity' | 'inflections';

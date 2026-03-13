export interface Post {
  id: string;
  source: 'hn' | 'reddit' | 'twitter';
  title: string;
  url: string | null;
  score: number;
  comments: number;
  author: string;
  subreddit?: string;
  created_at: string;
  age: string;
}

export type SourceFilter = 'all' | 'hn' | 'reddit' | 'twitter';
export type TimeframeFilter = '1h' | '24h' | '7d';

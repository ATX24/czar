export interface Post {
  id: string;
  source: string;
  title: string;
  url: string | null;
  score: number;
  comments: number;
  author: string;
  subreddit?: string;
  created_at: string;
  age: string;
}

export type SourceFilter = 'all' | 'hn' | 'lobsters' | 'techcrunch' | 'verge' | 'wired' | 'arstechnica' | 'hackernews_best';
export type TimeframeFilter = '1h' | '24h' | '7d';

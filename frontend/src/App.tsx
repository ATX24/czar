import { useState, useEffect, useCallback } from 'react';
import { Heart } from 'lucide-react';
import type { Post, SourceFilter, TimeframeFilter } from './types';
import { supabase } from './supabaseClient';

function formatScore(score: number): string {
  if (score >= 1000) {
    return (score / 1000).toFixed(1) + 'K';
  }
  return score.toLocaleString();
}

function getSourceLabel(source: string): string {
  switch (source) {
    case 'hn': return 'HN';
    case 'reddit': return 'RD';
    case 'twitter': return 'TW';
    default: return source.toUpperCase();
  }
}

function getMetricLabel(source: string): string {
  switch (source) {
    case 'hn': return 'Points';
    case 'reddit': return 'Upvotes';
    case 'twitter': return 'Reposts';
    default: return 'Score';
  }
}

function calculateAge(createdAt: string): string {
  const now = new Date();
  const created = new Date(createdAt);
  const diffMs = now.getTime() - created.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays > 0) return `${diffDays}d ago`;
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  if (diffHours > 0) return `${diffHours}h ago`;
  const diffMins = Math.floor(diffMs / (1000 * 60));
  return `${diffMins}m ago`;
}

function App() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [timeframeFilter, setTimeframeFilter] = useState<TimeframeFilter>('7d');
  const [likedPosts, setLikedPosts] = useState<Set<string>>(new Set());
  const [activeNav, setActiveNav] = useState('monitor');

  const fetchPosts = useCallback(async () => {
    setLoading(true);
    try {
      // Calculate the "since" timestamp
      const now = new Date();
      let since: Date;
      if (timeframeFilter === '1h') {
        since = new Date(now.getTime() - 60 * 60 * 1000);
      } else if (timeframeFilter === '24h') {
        since = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      } else {
        since = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      }

      let query = supabase
        .from('raw_posts')
        .select('*')
        .gte('created_at', since.toISOString())
        .order('score', { ascending: false })
        .limit(100);

      if (sourceFilter !== 'all') {
        query = query.eq('source', sourceFilter);
      }

      const { data, error } = await query;

      if (error) {
        console.error('Supabase error:', error);
        setPosts([]);
        return;
      }

      const mapped: Post[] = (data || []).map((row) => {
        const meta = row.metadata || {};
        // Use actual points from metadata, not the normalized 0-1 score
        const realScore = meta.points ?? meta.score ?? row.score ?? 0;
        return {
          id: row.id,
          source: row.source,
          title: (row.text || 'Untitled').slice(0, 200),
          url: row.url,
          score: realScore,
          comments: meta.descendants ?? meta.num_comments ?? 0,
          author: meta.by ?? meta.author ?? 'unknown',
          subreddit: meta.subreddit ?? undefined,
          created_at: row.created_at,
          age: row.created_at ? calculateAge(row.created_at) : 'unknown',
        };
      });

      mapped.sort((a, b) => b.score - a.score);
      setPosts(mapped);
    } catch (err) {
      console.error('Failed to fetch posts:', err);
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }, [sourceFilter, timeframeFilter]);

  useEffect(() => {
    fetchPosts();
  }, [fetchPosts]);

  const toggleLike = (postId: string) => {
    setLikedPosts(prev => {
      const newSet = new Set(prev);
      if (newSet.has(postId)) {
        newSet.delete(postId);
      } else {
        newSet.add(postId);
      }
      return newSet;
    });
  };

  return (
    <div className="app-container">
      <header>
        <div className="logo-area">
          <span className="logo-icon">✺</span>
          <span>czar</span>
        </div>

        <div className={`status-marker ${loading ? 'loading' : ''}`}></div>

        <nav className="header-nav">
          <a
            className={activeNav === 'monitor' ? 'active' : ''}
            onClick={() => setActiveNav('monitor')}
          >
            Monitor
          </a>
          <a
            className={activeNav === 'archive' ? 'active' : ''}
            onClick={() => setActiveNav('archive')}
          >
            Archive
          </a>
          <a
            className={activeNav === 'sources' ? 'active' : ''}
            onClick={() => setActiveNav('sources')}
          >
            Sources
          </a>
          <a
            className={activeNav === 'settings' ? 'active' : ''}
            onClick={() => setActiveNav('settings')}
          >
            Settings
          </a>
        </nav>
      </header>

      <main>
        <section className="controls-section">
          <div className="control-group">
            <span className="control-label">Source</span>
            <div className="pill-list">
              {(['all', 'hn', 'reddit'] as SourceFilter[]).map((source) => (
                <button
                  key={source}
                  className={`pill ${sourceFilter === source ? 'active' : ''}`}
                  onClick={() => setSourceFilter(source)}
                >
                  {source === 'all' ? 'All' : source === 'hn' ? 'HackerNews' : 'Reddit'}
                </button>
              ))}
            </div>
          </div>

          <div className="control-group">
            <span className="control-label">Timeframe</span>
            <div className="pill-list">
              {(['1h', '24h', '7d'] as TimeframeFilter[]).map((tf) => (
                <button
                  key={tf}
                  className={`pill ${timeframeFilter === tf ? 'active' : ''}`}
                  onClick={() => setTimeframeFilter(tf)}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="feed-list">
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <article key={i} className="feed-item">
                <div className="item-metrics">
                  <span className="metric-main loading-skeleton" style={{ width: 60, height: 20 }}>&nbsp;</span>
                  <span className="metric-sub loading-skeleton" style={{ width: 80, height: 12 }}>&nbsp;</span>
                </div>
                <div className="item-content">
                  <div className="loading-skeleton" style={{ width: '80%', height: 18 }}>&nbsp;</div>
                  <div className="loading-skeleton" style={{ width: '40%', height: 14 }}>&nbsp;</div>
                </div>
              </article>
            ))
          ) : posts.length === 0 ? (
            <div className="empty-state">
              <h3>No posts found</h3>
              <p>Try adjusting your filters or check back later.</p>
            </div>
          ) : (
            posts.map((post) => (
              <article key={post.id} className="feed-item">
                <div className="item-metrics">
                  <span className="metric-main">{formatScore(post.score)}</span>
                  <span className="metric-sub">
                    {getMetricLabel(post.source)} ({getSourceLabel(post.source)})
                  </span>
                </div>
                <div className="item-content">
                  <a
                    href={post.url || '#'}
                    className="item-title"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {post.title}
                  </a>
                  <div className="item-meta">
                    {post.source === 'reddit' && post.subreddit && (
                      <div className="meta-part">
                        <span>Sub:</span> r/{post.subreddit}
                      </div>
                    )}
                    {post.source === 'hn' && (
                      <div className="meta-part">
                        <span>By:</span> {post.author}
                      </div>
                    )}
                    <div className="meta-part">
                      <span>Age:</span> {post.age}
                    </div>
                    {post.comments > 0 && (
                      <div className="meta-part">
                        <span>Cmts:</span> {formatScore(post.comments)}
                      </div>
                    )}
                  </div>
                </div>
                <div className="item-actions">
                  <Heart
                    className={`action-icon ${likedPosts.has(post.id) ? 'liked' : ''}`}
                    size={14}
                    onClick={() => toggleLike(post.id)}
                    fill={likedPosts.has(post.id) ? 'currentColor' : 'none'}
                  />
                  <a
                    href={post.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="action-pill"
                  >
                    Read
                  </a>
                </div>
              </article>
            ))
          )}
        </section>

        <div className="footer-status">
          {loading ? 'Updating Stream...' : `${posts.length} items loaded`}
        </div>
      </main>
    </div>
  );
}

export default App;

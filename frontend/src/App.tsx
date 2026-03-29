import { useState, useEffect, useMemo } from 'react';
import type { RawPost, TabId, TopicCluster, GravitySignal } from './types';
import { supabase } from './supabaseClient';
import { clusterPosts, detectGravity, getHeatmapTopics, getInflections } from './lib/analyze';
import { TopicCard } from './components/TopicCard';

function App() {
  const [posts, setPosts] = useState<RawPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>('heatmap');

  useEffect(() => {
    (async () => {
      setLoading(true);
      const { data, error } = await supabase
        .from('raw_posts')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(500);

      if (error) {
        console.error('Supabase error:', error);
        setPosts([]);
      } else {
        setPosts((data as RawPost[]) || []);
      }
      setLoading(false);
    })();
  }, []);

  const clusters = useMemo(() => clusterPosts(posts), [posts]);
  const heatmap = useMemo(() => getHeatmapTopics(clusters), [clusters]);
  const gravitySignals = useMemo(() => detectGravity(clusters), [clusters]);
  const inflections = useMemo(() => getInflections(clusters), [clusters]);

  const tabs: { id: TabId; label: string; count: number }[] = [
    { id: 'heatmap', label: 'Heatmap', count: heatmap.length },
    { id: 'gravity', label: 'Gravity', count: gravitySignals.length },
    { id: 'inflections', label: 'Inflections', count: inflections.length },
  ];

  return (
    <div className="app-container">
      <header>
        <div className="logo-area">
          <span className="logo-icon">✺</span>
          <span>czar</span>
        </div>
        <div className={`status-marker ${loading ? 'loading' : ''}`} />
      </header>

      <nav className="tab-bar">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
            <span className="tab-count">{tab.count}</span>
          </button>
        ))}
      </nav>

      <main>
        {loading ? (
          <div className="loading-state">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton-card" />
            ))}
          </div>
        ) : (
          <>
            {activeTab === 'heatmap' && (
              <HeatmapView topics={heatmap} />
            )}
            {activeTab === 'gravity' && (
              <GravityView signals={gravitySignals} />
            )}
            {activeTab === 'inflections' && (
              <InflectionsView topics={inflections} />
            )}
          </>
        )}
      </main>

      <div className="footer-status">
        {loading
          ? 'Analyzing stream...'
          : `${posts.length} posts → ${clusters.length} topics`}
      </div>
    </div>
  );
}

function HeatmapView({ topics }: { topics: TopicCluster[] }) {
  if (topics.length === 0) return <EmptyState message="No velocity signals yet. Waiting for data." />;
  return (
    <section className="card-grid">
      {topics.map((t, i) => (
        <TopicCard key={t.id} topic={t} rank={i + 1} />
      ))}
    </section>
  );
}

function GravityView({ signals }: { signals: GravitySignal[] }) {
  if (signals.length === 0) return <EmptyState message="No watched-account convergence detected." />;
  return (
    <section className="card-grid">
      {signals.map(s => (
        <TopicCard
          key={s.topic.id}
          topic={s.topic}
          showGravityInfo={{
            watchedAccounts: s.watchedAccounts,
            isCoordinated: s.isCoordinated,
          }}
        />
      ))}
    </section>
  );
}

function InflectionsView({ topics }: { topics: TopicCluster[] }) {
  if (topics.length === 0) return <EmptyState message="No inflection points detected in this window." />;
  return (
    <section className="card-grid">
      {topics.map(t => (
        <TopicCard key={t.id} topic={t} />
      ))}
    </section>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="empty-state">
      <p>{message}</p>
    </div>
  );
}

export default App;
